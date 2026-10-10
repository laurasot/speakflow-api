import hashlib

import pytest

from app.core.config import Settings, settings
from app.core.dependencies import get_session_manager, get_speech_service, get_token_verifier
from app.providers.stt import factory
from app.services import embedding_service
from app.services.embedding_service import EmbeddingService

TEST_USER_ID = "user1"
TEST_API_KEY = "test-api-key-user1"

SINGLETONS = (get_token_verifier, get_session_manager, get_speech_service)


def sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


@pytest.fixture(autouse=True)
def hermetic_env(monkeypatch):
    """Resets settings to declared defaults, clears singletons and isolates the provider registry."""
    for name, field in Settings.model_fields.items():
        monkeypatch.setattr(settings, name, field.get_default(call_default_factory=True))
    monkeypatch.setattr(settings, "auth_api_key_hashes", {sha256_hex(TEST_API_KEY): TEST_USER_ID})
    monkeypatch.setattr(settings, "llm_provider", "openai")
    monkeypatch.setattr(settings, "openai_api_key", "")
    monkeypatch.setattr(factory, "_REGISTRY", dict(factory._REGISTRY))
    monkeypatch.setattr(embedding_service, "_embedding_service", None)
    for attr, value in (("_instance", None), ("_model", None), ("_enabled", False), ("_load_attempted", False)):
        monkeypatch.setattr(EmbeddingService, attr, value)
    for singleton in SINGLETONS:
        singleton.cache_clear()
    yield
    for singleton in SINGLETONS:
        singleton.cache_clear()


@pytest.fixture
def auth_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {TEST_API_KEY}"}
