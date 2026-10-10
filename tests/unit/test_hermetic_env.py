import pytest

from app.core.auth import AuthenticationError
from app.core.config import Settings, settings
from app.core.dependencies import get_session_manager, get_speech_service, get_token_verifier
from app.providers.stt import factory
from tests.conftest import TEST_API_KEY, sha256_hex


def test_settings_match_declared_defaults():
    """No Settings field may carry a value read from the machine environment or .env."""
    for name, field in Settings.model_fields.items():
        if name in {"auth_api_key_hashes", "llm_provider"}:
            continue
        assert getattr(settings, name) == field.get_default(call_default_factory=True), name


def test_openai_key_is_empty_even_with_env_value():
    assert settings.openai_api_key == ""
    assert settings.llm_provider == "openai"


def test_a_pollute_verifier_cache(monkeypatch):
    monkeypatch.setattr(settings, "auth_api_key_hashes", {sha256_hex("other-key"): "intruder"})
    assert get_token_verifier() is not None


def test_b_verifier_is_rebuilt_from_test_key():
    verifier = get_token_verifier()
    assert verifier.verify(TEST_API_KEY).user_id == "user1"
    with pytest.raises(AuthenticationError):
        verifier.verify("other-key")


def test_a_pollute_other_singletons():
    get_session_manager()
    get_speech_service()


def test_b_singletons_start_empty():
    assert get_session_manager.cache_info().currsize == 0
    assert get_speech_service.cache_info().currsize == 0


def test_a_leak_registry_entry():
    factory._REGISTRY["__test_provider__"] = object


def test_b_registry_has_no_leaked_entry():
    assert "__test_provider__" not in factory._REGISTRY
