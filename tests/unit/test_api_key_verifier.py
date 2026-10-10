import pytest

from app.core.auth import (
    ApiKeyVerifier,
    AuthenticationError,
    Identity,
    extract_bearer_token,
)
from tests.conftest import sha256_hex


@pytest.fixture
def verifier() -> ApiKeyVerifier:
    return ApiKeyVerifier(
        {
            sha256_hex("key-alice"): "alice",
            sha256_hex("key-bob"): "bob",
        }
    )


class TestApiKeyVerifier:
    def test_valid_key_returns_the_identity_it_is_mapped_to(self, verifier):
        assert verifier.verify("key-alice") == Identity(user_id="alice")
        assert verifier.verify("key-bob") == Identity(user_id="bob")

    @pytest.mark.parametrize("token", ["", "   ", "key-alice ", "KEY-ALICE", "key-mallory"])
    def test_invalid_key_is_rejected(self, verifier, token):
        with pytest.raises(AuthenticationError):
            verifier.verify(token)

    def test_the_stored_hash_is_not_accepted_as_a_key(self, verifier):
        with pytest.raises(AuthenticationError):
            verifier.verify(sha256_hex("key-alice"))

    def test_without_configured_keys_everything_is_rejected(self):
        with pytest.raises(AuthenticationError):
            ApiKeyVerifier({}).verify("anything")

    def test_rejection_does_not_reveal_why(self, verifier):
        with pytest.raises(AuthenticationError) as exc:
            verifier.verify("key-mallory")
        assert "key-mallory" not in str(exc.value)


class TestExtractBearerToken:
    @pytest.mark.parametrize(
        "header, expected",
        [
            ("Bearer abc123", "abc123"),
            ("bearer abc123", "abc123"),
            ("BEARER abc123", "abc123"),
            ("Bearer   abc123  ", "abc123"),
        ],
    )
    def test_valid_headers(self, header, expected):
        assert extract_bearer_token(header) == expected

    @pytest.mark.parametrize("header", [None, "", "Bearer", "Bearer ", "Basic abc123", "abc123"])
    def test_invalid_headers_return_none(self, header):
        assert extract_bearer_token(header) is None
