import threading
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.core.dependencies import get_session_manager
from app.main import app

GRACE_SECONDS = 0.5


def _start_message(session_id: str) -> dict:
    return {
        "type": "start_session",
        "session_id": session_id,
        "user_id": "user1",
        "sources": ["microphone"],
        "audio_config": {"sample_rate": 16000, "channels": 1, "encoding": "pcm16le"},
    }


@pytest.fixture
def provider_disconnected():
    """Provider mock whose disconnect() sets an event, so tests can observe a session being closed."""
    event = threading.Event()
    provider = MagicMock()
    provider.provider_name = "mock"
    provider.connect = AsyncMock()
    provider.send_audio = AsyncMock()
    provider.disconnect = AsyncMock(side_effect=lambda: event.set())
    return provider, event


@pytest.fixture(autouse=True)
def isolated_state(monkeypatch, provider_disconnected):
    provider, _ = provider_disconnected
    monkeypatch.setattr("app.services.session_manager.create_provider", lambda: provider)
    get_session_manager.cache_clear()
    yield
    get_session_manager.cache_clear()


def test_closing_stale_connection_does_not_close_session_owned_by_new_connection(
    provider_disconnected, auth_headers
):
    _, disconnected = provider_disconnected
    session_id = str(uuid4())
    headers = auth_headers

    with TestClient(app) as client:
        with client.websocket_connect("/v1/stt/stream", headers=headers) as stale:
            stale.send_json(_start_message(session_id))
            assert stale.receive_json()["type"] == "session_started"

            with client.websocket_connect("/v1/stt/stream", headers=headers) as fresh:
                fresh.send_json(_start_message(session_id))
                assert fresh.receive_json()["type"] == "session_started"
                disconnected.clear()

                stale.close()

                session_was_closed = disconnected.wait(timeout=GRACE_SECONDS)
                assert not session_was_closed, "stale connection closed the session of the new one"
                assert get_session_manager().active_sessions() == 1
