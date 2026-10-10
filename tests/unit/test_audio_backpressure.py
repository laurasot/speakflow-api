import asyncio
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.schemas.audio import AudioConfig, StartSessionMessage
from app.schemas.transcript import TranscriptMessage
from app.services.session_manager import SessionManager

QUEUE_MAX = 3


async def noop_transcript(_: TranscriptMessage) -> None:
    pass


def make_start_message(sources: list[str]) -> StartSessionMessage:
    return StartSessionMessage(
        type="start_session",
        session_id=uuid4(),
        user_id="user-test",
        sources=sources,
        audio_config=AudioConfig(),
    )


class SlowProvider:
    """Provider whose send_audio blocks until released, simulating a lagging STT."""

    provider_name = "slow"

    def __init__(self) -> None:
        self.sent: list[bytes] = []
        self.release = asyncio.Event()
        self.connect = AsyncMock()
        self.disconnect = AsyncMock()

    async def send_audio(self, pcm_bytes: bytes) -> None:
        await self.release.wait()
        self.sent.append(pcm_bytes)


@pytest.fixture
def providers(monkeypatch):
    created: list[SlowProvider] = []

    def factory() -> SlowProvider:
        provider = SlowProvider()
        created.append(provider)
        return provider

    monkeypatch.setattr("app.services.session_manager.create_provider", factory)
    return created


@pytest.fixture
def manager():
    return SessionManager(queue_max_chunks=QUEUE_MAX)


async def let_consumer_pick_first_chunk() -> None:
    for _ in range(3):
        await asyncio.sleep(0)


async def drain(provider: SlowProvider, expected: int) -> None:
    provider.release.set()
    for _ in range(100):
        if len(provider.sent) >= expected:
            return
        await asyncio.sleep(0.01)


async def test_route_audio_never_blocks_when_provider_lags(manager, providers):
    msg = make_start_message(["microphone"])
    sid = str(msg.session_id)
    await manager.create_session(msg, noop_transcript)

    async def flood() -> None:
        for i in range(QUEUE_MAX * 5):
            await manager.route_audio(sid, "microphone", bytes([i]))

    await asyncio.wait_for(flood(), timeout=1.0)

    await manager.close_session(sid)


async def test_overflow_drops_oldest_and_keeps_newest(manager, providers):
    msg = make_start_message(["microphone"])
    sid = str(msg.session_id)
    await manager.create_session(msg, noop_transcript)
    provider = providers[0]

    await manager.route_audio(sid, "microphone", b"\x00")
    await let_consumer_pick_first_chunk()
    for i in range(1, 7):
        await manager.route_audio(sid, "microphone", bytes([i]))

    await drain(provider, expected=1 + QUEUE_MAX)

    assert provider.sent == [b"\x00", b"\x04", b"\x05", b"\x06"]
    assert manager.dropped_chunks(sid) == 3

    await manager.close_session(sid)


async def test_no_drops_while_under_capacity(manager, providers):
    msg = make_start_message(["microphone"])
    sid = str(msg.session_id)
    await manager.create_session(msg, noop_transcript)
    provider = providers[0]

    await manager.route_audio(sid, "microphone", b"\x00")
    await let_consumer_pick_first_chunk()
    for i in range(1, QUEUE_MAX + 1):
        await manager.route_audio(sid, "microphone", bytes([i]))

    await drain(provider, expected=1 + QUEUE_MAX)

    assert provider.sent == [bytes([i]) for i in range(QUEUE_MAX + 1)]
    assert manager.dropped_chunks(sid) == 0

    await manager.close_session(sid)


async def test_overflow_in_one_source_does_not_affect_the_other(manager, providers):
    msg = make_start_message(["microphone", "system"])
    sid = str(msg.session_id)
    await manager.create_session(msg, noop_transcript)
    mic_provider, sys_provider = providers

    await manager.route_audio(sid, "microphone", b"\x00")
    await let_consumer_pick_first_chunk()
    for i in range(1, 10):
        await manager.route_audio(sid, "microphone", bytes([i]))

    sys_provider.release.set()
    await manager.route_audio(sid, "system", b"\xaa")
    await drain(sys_provider, expected=1)

    assert sys_provider.sent == [b"\xaa"]
    assert manager.dropped_chunks(sid) > 0

    mic_provider.release.set()
    await manager.close_session(sid)


def test_dropped_chunks_is_zero_for_unknown_session():
    assert SessionManager(queue_max_chunks=QUEUE_MAX).dropped_chunks("nope") == 0


def test_default_capacity_comes_from_settings():
    from app.core.config import settings

    assert SessionManager()._queue_max_chunks == settings.audio_queue_max_chunks


def test_rejects_non_positive_capacity():
    with pytest.raises(ValueError):
        SessionManager(queue_max_chunks=0)
