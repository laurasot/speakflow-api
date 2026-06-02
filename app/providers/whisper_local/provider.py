import asyncio
import io
import logging
import time
import wave
from typing import Awaitable, Callable

from app.providers.factory import register_provider
from app.schemas.audio import AudioConfig
from app.schemas.transcript import TranscriptMessage

logger = logging.getLogger(__name__)


@register_provider("whisper_local")
class WhisperLocalProvider:
    """
    Proveedor local usando OpenAI Whisper.
    Acumula audio en un buffer y transcribe por lotes cada N segundos.
    Requiere: pip install openai-whisper
    """

    provider_name = "whisper_local"
    BATCH_SECONDS = 5

    def __init__(self) -> None:
        self._session_id: str = ""
        self._source: str = ""
        self._audio_config: AudioConfig | None = None
        self._on_transcript: Callable[[TranscriptMessage], Awaitable[None]] | None = None
        self._buffer: bytearray = bytearray()
        self._batch_task: asyncio.Task | None = None  # type: ignore[type-arg]
        self._running = False
        self._model = None

    async def connect(
        self,
        session_id: str,
        source: str,
        audio_config: AudioConfig,
        on_transcript: Callable[[TranscriptMessage], Awaitable[None]],
    ) -> None:
        self._session_id = session_id
        self._source = source
        self._audio_config = audio_config
        self._on_transcript = on_transcript
        self._running = True
        self._buffer = bytearray()

        await self._load_model()

        self._batch_task = asyncio.create_task(
            self._batch_loop(),
            name=f"whisper-batch-{session_id}-{source}",
        )
        logger.info(
            "Whisper local connected",
            extra={"extra": {"session_id": session_id, "source": source}},
        )

    async def _load_model(self) -> None:
        try:
            import whisper  # type: ignore[import]
            self._model = await asyncio.get_event_loop().run_in_executor(
                None, whisper.load_model, "base"
            )
        except ImportError:
            raise RuntimeError(
                "openai-whisper no está instalado. "
                "Ejecuta: uv add openai-whisper"
            )

    async def _batch_loop(self) -> None:
        while self._running:
            await asyncio.sleep(self.BATCH_SECONDS)
            if self._buffer:
                await self._transcribe_buffer()

    async def _transcribe_buffer(self) -> None:
        assert self._audio_config is not None and self._model is not None

        audio_bytes = bytes(self._buffer)
        self._buffer = bytearray()

        try:
            wav_io = io.BytesIO()
            with wave.open(wav_io, "wb") as wf:
                wf.setnchannels(self._audio_config.channels)
                wf.setsampwidth(2)  # 16-bit = 2 bytes
                wf.setframerate(self._audio_config.sample_rate)
                wf.writeframes(audio_bytes)
            wav_io.seek(0)

            result = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: self._model.transcribe(wav_io, language="es"),
            )

            text = result.get("text", "").strip()
            if text and self._on_transcript:
                await self._on_transcript(
                    TranscriptMessage(
                        session_id=self._session_id,
                        source=self._source,  # type: ignore[arg-type]
                        text=text,
                        is_final=True,
                        timestamp=int(time.time() * 1000),
                        provider=self.provider_name,
                        language=result.get("language", "es"),
                        start_time=0.0,
                        end_time=self.BATCH_SECONDS,
                    )
                )
        except Exception:
            logger.exception(
                "Error transcribing Whisper batch",
                extra={"extra": {"session_id": self._session_id}},
            )

    async def send_audio(self, pcm_bytes: bytes) -> None:
        self._buffer.extend(pcm_bytes)

    async def disconnect(self) -> None:
        self._running = False
        if self._batch_task is not None:
            self._batch_task.cancel()
            try:
                await self._batch_task
            except asyncio.CancelledError:
                pass

        if self._buffer:
            await self._transcribe_buffer()

        logger.info(
            "Whisper local disconnected",
            extra={"extra": {"session_id": self._session_id, "source": self._source}},
        )
