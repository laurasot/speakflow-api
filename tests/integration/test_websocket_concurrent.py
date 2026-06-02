import asyncio
import json
from typing import Awaitable, Callable
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from fastapi.websockets import WebSocket

from app.main import app
from app.schemas.audio import AudioConfig, StartSessionMessage
from app.schemas.transcript import TranscriptMessage
from app.services.session_manager import SessionManager


def make_mock_provider():
    provider = MagicMock()
    provider.provider_name = "mock"
    provider.connect = AsyncMock()
    provider.disconnect = AsyncMock()
    provider.send_audio = AsyncMock()
    return provider


@pytest.fixture(autouse=True)
def patch_provider(monkeypatch):
    provider = make_mock_provider()
    monkeypatch.setattr("app.services.session_manager.create_provider", lambda: provider)
    yield provider


@pytest.fixture(autouse=True)
def reset_session_manager():
    """Resetea el singleton entre tests."""
    from app.core.dependencies import get_session_manager
    get_session_manager.cache_clear()
    yield
    get_session_manager.cache_clear()


class TestWebSocketProtocol:
    def test_rejected_without_user_id_header(self):
        from starlette.websockets import WebSocketDisconnect

        client = TestClient(app)
        with pytest.raises(WebSocketDisconnect) as exc_info:
            with client.websocket_connect("/v1/stt/stream"):
                pass
        assert exc_info.value.code == 1008

    def test_session_started_on_valid_start_message(self):
        client = TestClient(app)
        session_id = str(uuid4())

        with client.websocket_connect("/v1/stt/stream", headers={"X-User-Id": "user1"}) as ws:
            ws.send_json({
                "type": "start_session",
                "session_id": session_id,
                "user_id": "user1",
                "sources": ["microphone"],
                "audio_config": {"sample_rate": 16000, "channels": 1, "encoding": "pcm16le"},
            })
            response = ws.receive_json()
            assert response["type"] == "session_started"
            assert response["session_id"] == session_id

    def test_error_on_invalid_json_message(self):
        client = TestClient(app)

        with client.websocket_connect("/v1/stt/stream", headers={"X-User-Id": "user1"}) as ws:
            ws.send_text('{"type": "unknown_type", "garbage": true}')
            response = ws.receive_json()
            assert response["type"] == "error"
            assert response["code"] == "invalid_message"

    def test_stop_session_closes_gracefully(self):
        client = TestClient(app)
        session_id = str(uuid4())

        with client.websocket_connect("/v1/stt/stream", headers={"X-User-Id": "user1"}) as ws:
            ws.send_json({
                "type": "start_session",
                "session_id": session_id,
                "user_id": "user1",
                "sources": ["microphone"],
                "audio_config": {"sample_rate": 16000, "channels": 1, "encoding": "pcm16le"},
            })
            ws.receive_json()  # session_started

            ws.send_json({"type": "stop_session", "session_id": session_id})
            response = ws.receive_json()
            assert response["type"] == "session_ended"
            assert response["session_id"] == session_id


class TestConcurrentUsers:
    async def test_two_users_sessions_are_independent(self):
        """Verifica que dos sesiones concurrentes son completamente independientes."""
        manager = SessionManager()
        received_by_session: dict[str, list[str]] = {}

        providers_created: list[MagicMock] = []

        def make_provider():
            p = make_mock_provider()
            providers_created.append(p)
            return p

        async def on_transcript_a(t: TranscriptMessage) -> None:
            received_by_session.setdefault("a", []).append(t.text)

        async def on_transcript_b(t: TranscriptMessage) -> None:
            received_by_session.setdefault("b", []).append(t.text)

        msg_a = StartSessionMessage(
            type="start_session",
            session_id=uuid4(),
            user_id="user-a",
            sources=["microphone"],
            audio_config=AudioConfig(),
        )
        msg_b = StartSessionMessage(
            type="start_session",
            session_id=uuid4(),
            user_id="user-b",
            sources=["microphone"],
            audio_config=AudioConfig(),
        )

        with pytest.MonkeyPatch().context() as mp:
            mp.setattr("app.services.session_manager.create_provider", make_provider)
            await asyncio.gather(
                manager.create_session(msg_a, on_transcript_a),
                manager.create_session(msg_b, on_transcript_b),
            )

        assert manager.active_sessions() == 2
        assert len(providers_created) == 2
        assert providers_created[0] is not providers_created[1]

        sid_a = str(msg_a.session_id)
        sid_b = str(msg_b.session_id)
        session_a = manager._sessions[sid_a]
        session_b = manager._sessions[sid_b]

        assert session_a.streams["microphone"].provider is not session_b.streams["microphone"].provider

    async def test_close_one_session_does_not_affect_other(self):
        """Cerrar la sesión A no debe tocar la sesión B."""
        manager = SessionManager()
        providers: list[MagicMock] = []

        def make_provider():
            p = make_mock_provider()
            providers.append(p)
            return p

        msg_a = StartSessionMessage(
            type="start_session",
            session_id=uuid4(),
            user_id="user-a",
            sources=["microphone"],
            audio_config=AudioConfig(),
        )
        msg_b = StartSessionMessage(
            type="start_session",
            session_id=uuid4(),
            user_id="user-b",
            sources=["microphone"],
            audio_config=AudioConfig(),
        )

        async def noop(_: TranscriptMessage) -> None:
            pass

        with pytest.MonkeyPatch().context() as mp:
            mp.setattr("app.services.session_manager.create_provider", make_provider)
            await manager.create_session(msg_a, noop)
            await manager.create_session(msg_b, noop)

        await manager.close_session(str(msg_a.session_id))

        assert manager.active_sessions() == 1
        assert str(msg_b.session_id) in manager._sessions
        providers[0].disconnect.assert_called_once()
        providers[1].disconnect.assert_not_called()
