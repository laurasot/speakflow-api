import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Awaitable, Callable, Literal

from app.core.config import settings
from app.providers.stt.base import SpeechProvider
from app.providers.stt.factory import create_provider
from app.schemas.audio import AudioConfig, StartSessionMessage
from app.schemas.transcript import TranscriptMessage

logger = logging.getLogger(__name__)


@dataclass
class AudioStream:
    source: Literal["microphone", "system"]
    queue: asyncio.Queue[bytes]
    provider: SpeechProvider
    task: asyncio.Task  # type: ignore[type-arg]
    dropped_chunks: int = 0


@dataclass
class Session:
    session_id: str
    user_id: str
    audio_config: AudioConfig
    owner: str | None = None
    streams: dict[str, AudioStream] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class SessionManager:
    """Gestiona sesiones activas garantizando aislamiento total entre usuarios."""

    def __init__(self, queue_max_chunks: int | None = None) -> None:
        capacity = settings.audio_queue_max_chunks if queue_max_chunks is None else queue_max_chunks
        if capacity < 1:
            raise ValueError("queue_max_chunks must be >= 1")
        self._queue_max_chunks = capacity
        self._sessions: dict[str, Session] = {}
        self._lock = asyncio.Lock()

    async def create_session(
        self,
        msg: StartSessionMessage,
        on_transcript: Callable[[TranscriptMessage], Awaitable[None]],
        owner: str | None = None,
    ) -> None:
        """Crea la sesión y abre una conexión al proveedor por cada fuente solicitada.

        `owner` identifica la conexión que la creó. Si llega un start_session con un
        session_id ya existente desde otro owner (reconexión del cliente), la sesión
        anterior se reemplaza: sus callbacks apuntan a un socket que ya no existe.
        """
        session_id = str(msg.session_id)

        async with self._lock:
            existing = self._sessions.get(session_id)
            if existing is not None and existing.owner == owner:
                logger.warning(
                    "Session already exists, skipping creation",
                    extra={"extra": {"session_id": session_id}},
                )
                return

            session = Session(
                session_id=session_id,
                user_id=msg.user_id,
                audio_config=msg.audio_config,
                owner=owner,
            )
            self._sessions[session_id] = session

        if existing is not None:
            logger.info(
                "Session taken over by a new connection",
                extra={"extra": {"session_id": session_id}},
            )
            await self._teardown(existing)

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
        queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=self._queue_max_chunks)

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
        """Mete el audio en la cola de la fuente correcta. Sin lock — aislamiento por diseño.

        Nunca bloquea: si el proveedor va atrasado y la cola está llena, descarta el
        chunk más antiguo, para que la latencia no crezca sin tope ni se frene el
        loop de recepción del WebSocket.
        """
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

        if stream.queue.full():
            stream.queue.get_nowait()
            stream.queue.task_done()
            stream.dropped_chunks += 1
            if stream.dropped_chunks == 1 or stream.dropped_chunks % 50 == 0:
                logger.warning(
                    "Audio queue full, dropping oldest chunk",
                    extra={
                        "extra": {
                            "session_id": session_id,
                            "source": source,
                            "dropped_chunks": stream.dropped_chunks,
                        }
                    },
                )
        stream.queue.put_nowait(pcm_bytes)

    def dropped_chunks(self, session_id: str) -> int:
        """Total de chunks descartados por backpressure en todas las fuentes de la sesión."""
        session = self._sessions.get(session_id)
        if session is None:
            return 0
        return sum(stream.dropped_chunks for stream in session.streams.values())

    async def close_session(self, session_id: str, owner: str | None = None) -> bool:
        """Cancela las tareas, desconecta proveedores y borra la sesión.

        Si se indica `owner`, solo cierra la sesión cuando le pertenece: una conexión
        vieja no puede cerrar la sesión que ya tomó una conexión nueva. Devuelve True
        si la sesión se cerró.
        """
        async with self._lock:
            session = self._sessions.get(session_id)
            if session is None or (owner is not None and session.owner != owner):
                return False
            del self._sessions[session_id]

        await self._teardown(session)
        return True

    async def _teardown(self, session: Session) -> None:
        """Detiene los streams de una sesión ya retirada del registro."""
        session_id = session.session_id
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
