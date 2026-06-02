import asyncio
from typing import Awaitable, Callable
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.schemas.audio import AudioConfig, StartSessionMessage
from app.schemas.transcript import TranscriptMessage
from app.services.session_manager import SessionManager


def make_start_message(
    sources: list[str] | None = None,
    user_id: str = "user-test",
) -> StartSessionMessage:
    return StartSessionMessage(
        type="start_session",
        session_id=uuid4(),
        user_id=user_id,
        sources=sources or ["microphone"],
        audio_config=AudioConfig(),
    )


def make_mock_provider():
    provider = MagicMock()
    provider.provider_name = "mock"
    provider.connect = AsyncMock()
    provider.disconnect = AsyncMock()
    provider.send_audio = AsyncMock()
    return provider


@pytest.fixture
def session_manager():
    return SessionManager()


@pytest.fixture
def mock_provider(monkeypatch):
    provider = make_mock_provider()
    monkeypatch.setattr("app.services.session_manager.create_provider", lambda: provider)
    return provider


async def noop_transcript(_: TranscriptMessage) -> None:
    pass


class TestSessionCreation:
    async def test_create_session_opens_provider_per_source(self, session_manager, mock_provider):
        msg = make_start_message(sources=["microphone", "system"])
        await session_manager.create_session(msg, noop_transcript)

        assert mock_provider.connect.call_count == 2
        assert session_manager.active_sessions() == 1

    async def test_duplicate_session_id_ignored(self, session_manager, mock_provider):
        msg = make_start_message()
        await session_manager.create_session(msg, noop_transcript)
        await session_manager.create_session(msg, noop_transcript)

        assert mock_provider.connect.call_count == 1

    async def test_close_session_disconnects_providers(self, session_manager, mock_provider):
        msg = make_start_message(sources=["microphone"])
        await session_manager.create_session(msg, noop_transcript)
        session_id = str(msg.session_id)

        await session_manager.close_session(session_id)

        mock_provider.disconnect.assert_called_once()
        assert session_manager.active_sessions() == 0

    async def test_close_nonexistent_session_is_safe(self, session_manager):
        await session_manager.close_session("does-not-exist")


class TestAudioRouting:
    async def test_audio_routed_to_correct_queue(self, session_manager, mock_provider):
        msg = make_start_message(sources=["microphone"])
        await session_manager.create_session(msg, noop_transcript)
        session_id = str(msg.session_id)

        await session_manager.route_audio(session_id, "microphone", b"\x00" * 100)

        await asyncio.sleep(0.05)
        mock_provider.send_audio.assert_called_once()

    async def test_audio_for_unknown_session_does_not_raise(self, session_manager):
        await session_manager.route_audio("unknown-id", "microphone", b"\x00" * 100)

    async def test_audio_for_unknown_source_does_not_raise(self, session_manager, mock_provider):
        msg = make_start_message(sources=["microphone"])
        await session_manager.create_session(msg, noop_transcript)
        session_id = str(msg.session_id)

        await session_manager.route_audio(session_id, "system", b"\x00" * 100)


class TestConcurrencyIsolation:
    async def test_two_sessions_never_share_providers(self, session_manager, monkeypatch):
        """Verifica que dos sesiones distintas usan instancias de proveedor distintas."""
        providers = []

        def make_provider():
            p = make_mock_provider()
            providers.append(p)
            return p

        monkeypatch.setattr("app.services.session_manager.create_provider", make_provider)

        msg_a = make_start_message(sources=["microphone"], user_id="user-a")
        msg_b = make_start_message(sources=["microphone"], user_id="user-b")

        await asyncio.gather(
            session_manager.create_session(msg_a, noop_transcript),
            session_manager.create_session(msg_b, noop_transcript),
        )

        assert len(providers) == 2
        assert providers[0] is not providers[1]
        assert session_manager.active_sessions() == 2

    async def test_concurrent_audio_routing_no_mixing(self, session_manager, monkeypatch):
        """Envía audio de dos usuarios en paralelo y verifica que cada proveedor
        solo recibió sus propios bytes."""
        received: dict[str, list[bytes]] = {"a": [], "b": []}
        providers_map: dict[str, object] = {}
        call_order: list[str] = []

        def make_provider_for(label: str):
            p = make_mock_provider()

            async def capture_audio(data: bytes) -> None:
                received[label].append(data)

            p.send_audio = capture_audio
            return p

        provider_index = {"i": 0}
        labels = ["a", "b"]

        def make_provider():
            label = labels[provider_index["i"] % 2]
            provider_index["i"] += 1
            return make_provider_for(label)

        monkeypatch.setattr("app.services.session_manager.create_provider", make_provider)

        msg_a = make_start_message(sources=["microphone"], user_id="user-a")
        msg_b = make_start_message(sources=["microphone"], user_id="user-b")

        await session_manager.create_session(msg_a, noop_transcript)
        await session_manager.create_session(msg_b, noop_transcript)

        audio_a = b"\xAA" * 100
        audio_b = b"\xBB" * 100

        await asyncio.gather(
            session_manager.route_audio(str(msg_a.session_id), "microphone", audio_a),
            session_manager.route_audio(str(msg_b.session_id), "microphone", audio_b),
        )

        await asyncio.sleep(0.1)

        assert all(chunk == audio_a for chunk in received["a"]), "Session A got foreign audio"
        assert all(chunk == audio_b for chunk in received["b"]), "Session B got foreign audio"
