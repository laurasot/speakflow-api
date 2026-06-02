import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Awaitable, Callable, Literal

from app.providers.base import SpeechProvider
from app.providers.factory import create_provider
from app.schemas.audio import AudioConfig, StartSessionMessage
from app.schemas.transcript import TranscriptMessage

logger = logging.getLogger(__name__)


@dataclass
class AudioStream:
    source: Literal["microphone", "system"]
    queue: asyncio.Queue[bytes]
    provider: SpeechProvider
    task: asyncio.Task  # type: ignore[type-arg]


@dataclass
class Session:
    session_id: str
    user_id: str
    audio_config: AudioConfig
    streams: dict[str, AudioStream] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class SessionManager:
    """Gestiona sesiones activas garantizando aislamiento total entre usuarios."""

    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}
        self._lock = asyncio.Lock()

    async def create_session(
        self,
        msg: StartSessionMessage,
        on_transcript: Callable[[TranscriptMessage], Awaitable[None]],
    ) -> None:
        """Crea la sesión y abre una conexión al proveedor por cada fuente solicitada."""
        session_id = str(msg.session_id)

        async with self._lock:
            if session_id in self._sessions:
                logger.warning(
                    "Session already exists, skipping creation",
                    extra={"extra": {"session_id": session_id}},
                )
                return

            session = Session(
                session_id=session_id,
                user_id=msg.user_id,
                audio_config=msg.audio_config,
            )
            self._sessions[session_id] = session

        for source in msg.sources:
            await self._open_stream(session, source, on_transcript)

        logger.info(
            "Session created",
            extra={
                "extra": {
                    "session_id": session_id,
                    "user_id": msg.user_id,
                    "sources": msg.sources,
                }
            },
        )

    async def _open_stream(
        self,
        session: Session,
        source: str,
        on_transcript: Callable[[TranscriptMessage], Awaitable[None]],
    ) -> None:
        """Abre un stream de audio para una fuente específica dentro de una sesión."""
        provider = create_provider()
        queue: asyncio.Queue[bytes] = asyncio.Queue()

        await provider.connect(
            session_id=session.session_id,
            source=source,
            audio_config=session.audio_config,
            on_transcript=on_transcript,
        )

        task = asyncio.create_task(
            self._consume_queue(queue, provider, session.session_id, source),
            name=f"stream-{session.session_id}-{source}",
        )

        session.streams[source] = AudioStream(
            source=source,  # type: ignore[arg-type]
            queue=queue,
            provider=provider,
            task=task,
        )

        logger.info(
            "Stream opened",
            extra={"extra": {"session_id": session.session_id, "source": source}},
        )

    async def _consume_queue(
        self,
        queue: asyncio.Queue[bytes],
        provider: SpeechProvider,
        session_id: str,
        source: str,
    ) -> None:
        """Consume la cola de audio y envía cada chunk al proveedor."""
        while True:
            try:
                pcm_bytes = await queue.get()
                await provider.send_audio(pcm_bytes)
                queue.task_done()
            except asyncio.CancelledError:
                logger.info(
                    "Stream consumer cancelled",
                    extra={"extra": {"session_id": session_id, "source": source}},
                )
                break
            except Exception:
                logger.exception(
                    "Error sending audio to provider",
                    extra={"extra": {"session_id": session_id, "source": source}},
                )

    async def route_audio(
        self,
        session_id: str,
        source: str,
        pcm_bytes: bytes,
    ) -> None:
        """Mete el audio en la cola de la fuente correcta. Sin lock — aislamiento por diseño."""
        session = self._sessions.get(session_id)
        if session is None:
            logger.warning(
                "Audio received for unknown session",
                extra={"extra": {"session_id": session_id}},
            )
            return

        stream = session.streams.get(source)
        if stream is None:
            logger.warning(
                "Audio received for unknown source",
                extra={"extra": {"session_id": session_id, "source": source}},
            )
            return

        await stream.queue.put(pcm_bytes)

    async def close_session(self, session_id: str) -> None:
        """Cancela las tareas, desconecta proveedores y borra la sesión."""
        async with self._lock:
            session = self._sessions.pop(session_id, None)

        if session is None:
            return

        for source, stream in session.streams.items():
            stream.task.cancel()
            try:
                await stream.task
            except asyncio.CancelledError:
                pass
            try:
                await stream.provider.disconnect()
            except Exception:
                logger.exception(
                    "Error disconnecting provider",
                    extra={"extra": {"session_id": session_id, "source": source}},
                )

        logger.info(
            "Session closed",
            extra={"extra": {"session_id": session_id, "user_id": session.user_id}},
        )

    def active_sessions(self) -> int:
        return len(self._sessions)
