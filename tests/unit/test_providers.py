from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.providers.factory import _REGISTRY, create_provider, register_provider
from app.schemas.audio import AudioConfig
from app.schemas.transcript import TranscriptMessage


class TestProviderRegistry:
    def test_register_provider_adds_to_registry(self):
        @register_provider("__test_provider__")
        class TestProvider:
            provider_name = "__test_provider__"

        assert "__test_provider__" in _REGISTRY
        assert _REGISTRY["__test_provider__"] is TestProvider

    def test_create_provider_raises_on_unknown(self, monkeypatch):
        monkeypatch.setattr("app.providers.factory.settings.speech_provider", "unknown_xyz")
        with pytest.raises(ValueError, match="desconocido"):
            create_provider()


class TestTranscriptMessage:
    def test_transcript_message_serializes_correctly(self):
        msg = TranscriptMessage(
            session_id="session-123",
            source="microphone",
            text="Hola mundo",
            is_final=True,
            timestamp=1717000000000,
            provider="deepgram",
            language="es",
            start_time=0.0,
            end_time=1.5,
        )
        data = msg.model_dump()
        assert data["type"] == "transcript"
        assert data["text"] == "Hola mundo"
        assert data["is_final"] is True

    def test_error_message_session_id_optional(self):
        from app.schemas.transcript import ErrorMessage

        msg = ErrorMessage(code="provider_unavailable", message="Deepgram down")
        assert msg.session_id is None
        assert msg.type == "error"


class TestAudioSchemas:
    def test_start_session_validates_sources(self):
        from app.schemas.audio import StartSessionMessage

        msg = StartSessionMessage(
            type="start_session",
            session_id=uuid4(),
            user_id="user1",
            sources=["microphone", "system"],
            audio_config=AudioConfig(),
        )
        assert len(msg.sources) == 2

    def test_audio_chunk_metadata_requires_positive_size(self):
        from pydantic import ValidationError

        from app.schemas.audio import AudioChunkMetadata

        with pytest.raises(ValidationError):
            AudioChunkMetadata(
                type="audio_chunk",
                session_id=uuid4(),
                source="microphone",
                timestamp=123456,
                size=0,
            )
