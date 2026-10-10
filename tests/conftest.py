import hashlib

import pytest

from app.core.config import settings
from app.core.dependencies import get_token_verifier

TEST_USER_ID = "user1"
TEST_API_KEY = "test-api-key-user1"


def sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


@pytest.fixture(autouse=True)
def configured_api_keys(monkeypatch):
    """Every test starts with exactly one valid API key; the suite never depends on a local .env."""
    monkeypatch.setattr(settings, "auth_api_key_hashes", {sha256_hex(TEST_API_KEY): TEST_USER_ID})
    get_token_verifier.cache_clear()
    yield
    get_token_verifier.cache_clear()


@pytest.fixture
def auth_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {TEST_API_KEY}"}
