from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.core.config import settings
from app.core.dependencies import get_session_manager, get_token_verifier
from app.main import app
from tests.conftest import TEST_API_KEY, TEST_USER_ID

URL = "/v1/stt/stream"


def _start_message(user_id: str = TEST_USER_ID) -> dict:
    return {
        "type": "start_session",
        "session_id": str(uuid4()),
        "user_id": user_id,
        "sources": ["microphone"],
        "audio_config": {"sample_rate": 16000, "channels": 1, "encoding": "pcm16le"},
    }


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    provider = MagicMock()
    provider.provider_name = "mock"
    provider.connect = AsyncMock()
    provider.disconnect = AsyncMock()
    provider.send_audio = AsyncMock()
    monkeypatch.setattr("app.services.session_manager.create_provider", lambda: provider)
    get_session_manager.cache_clear()
    yield
    get_session_manager.cache_clear()


def _assert_rejected(headers: dict[str, str] | None) -> None:
    client = TestClient(app)
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect(URL, headers=headers or {}):
            pass
    assert exc.value.code == 1008


class TestHandshakeAuthentication:
    def test_missing_authorization_is_rejected(self):
        _assert_rejected(None)

    def test_invalid_key_is_rejected(self):
        _assert_rejected({"Authorization": "Bearer not-a-real-key"})

    def test_wrong_scheme_is_rejected(self):
        _assert_rejected({"Authorization": f"Basic {TEST_API_KEY}"})

    def test_legacy_x_user_id_header_alone_no_longer_authenticates(self):
        _assert_rejected({"X-User-Id": TEST_USER_ID})

    def test_a_forged_x_user_id_does_not_override_the_credential(self, auth_headers):
        client = TestClient(app)
        headers = {**auth_headers, "X-User-Id": "someone-else"}
        with client.websocket_connect(URL, headers=headers) as ws:
            ws.send_json(_start_message(user_id="someone-else"))
            response = ws.receive_json()
        assert response["type"] == "error"
        assert response["code"] == "user_mismatch"

    def test_fails_closed_when_no_keys_are_configured(self, monkeypatch, auth_headers):
        monkeypatch.setattr(settings, "auth_api_key_hashes", {})
        get_token_verifier.cache_clear()
        _assert_rejected(auth_headers)

    def test_valid_key_is_accepted(self, auth_headers):
        client = TestClient(app)
        with client.websocket_connect(URL, headers=auth_headers) as ws:
            message = _start_message()
            ws.send_json(message)
            response = ws.receive_json()
        assert response["type"] == "session_started"
        assert response["session_id"] == message["session_id"]


class TestIdentityComesFromTheCredential:
    def test_start_session_with_another_users_id_is_refused(self, auth_headers):
        client = TestClient(app)
        with client.websocket_connect(URL, headers=auth_headers) as ws:
            ws.send_json(_start_message(user_id="victim"))
            response = ws.receive_json()
            assert response["type"] == "error"
            assert response["code"] == "user_mismatch"
            assert get_session_manager().active_sessions() == 0

    def test_connection_stays_usable_after_a_refused_start_session(self, auth_headers):
        client = TestClient(app)
        with client.websocket_connect(URL, headers=auth_headers) as ws:
            ws.send_json(_start_message(user_id="victim"))
            assert ws.receive_json()["code"] == "user_mismatch"

            ws.send_json(_start_message())
            assert ws.receive_json()["type"] == "session_started"
