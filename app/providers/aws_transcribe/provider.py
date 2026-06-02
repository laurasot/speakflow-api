import asyncio
import json
import logging
import time
from typing import Awaitable, Callable

import boto3

from app.core.config import settings
from app.providers.factory import register_provider
from app.schemas.audio import AudioConfig
from app.schemas.transcript import TranscriptMessage

logger = logging.getLogger(__name__)

_RETRY_DELAYS = [1, 2, 4]


@register_provider("aws_transcribe")
class AWSTranscribeProvider:
    """
    Proveedor AWS Transcribe Streaming.
    Usa el SDK boto3 con la API de transcripción en tiempo real.
    """

    provider_name = "aws_transcribe"

    def __init__(self) -> None:
        self._session_id: str = ""
        self._source: str = ""
        self._audio_config: AudioConfig | None = None
        self._on_transcript: Callable[[TranscriptMessage], Awaitable[None]] | None = None
        self._input_queue: asyncio.Queue[bytes] = asyncio.Queue()
        self._stream_task: asyncio.Task | None = None  # type: ignore[type-arg]
        self._client = None

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
        await self._connect_with_retry()

    async def _connect_with_retry(self) -> None:
        for attempt, delay in enumerate(_RETRY_DELAYS):
            try:
                await self._establish_connection()
                logger.info(
                    "AWS Transcribe connected",
                    extra={"extra": {"session_id": self._session_id, "source": self._source}},
                )
                return
            except Exception as exc:
                logger.warning(
                    "AWS Transcribe connection attempt failed",
                    extra={"extra": {"session_id": self._session_id, "attempt": attempt + 1, "error": str(exc)}},
                )
                if attempt < len(_RETRY_DELAYS) - 1:
                    await asyncio.sleep(delay)

        raise ConnectionError(
            f"AWS Transcribe unavailable after {len(_RETRY_DELAYS)} attempts "
            f"(session={self._session_id})"
        )

    async def _establish_connection(self) -> None:
        assert self._audio_config is not None

        self._client = boto3.client(
            "transcribe-streaming",
            region_name=settings.aws_region,
        )

        self._stream_task = asyncio.create_task(
            self._run_stream(),
            name=f"aws-stream-{self._session_id}-{self._source}",
        )

    async def _run_stream(self) -> None:
        assert self._audio_config is not None and self._client is not None

        async def audio_generator():
            while True:
                chunk = await self._input_queue.get()
                if chunk == b"__STOP__":
                    break
                yield {"AudioEvent": {"AudioChunk": chunk}}

        try:
            response = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: self._client.start_stream_transcription(
                    LanguageCode="es-ES",
                    MediaSampleRateHertz=self._audio_config.sample_rate,
                    MediaEncoding="pcm",
                    AudioStream=audio_generator(),
                ),
            )

            async for event in response["TranscriptResultStream"]:
                if "TranscriptEvent" in event:
                    results = event["TranscriptEvent"]["Transcript"]["Results"]
                    for result in results:
                        if not result["Alternatives"]:
                            continue
                        alt = result["Alternatives"][0]
                        if self._on_transcript:
                            await self._on_transcript(
                                TranscriptMessage(
                                    session_id=self._session_id,
                                    source=self._source,  # type: ignore[arg-type]
                                    text=alt["Transcript"],
                                    is_final=not result["IsPartial"],
                                    timestamp=int(time.time() * 1000),
                                    provider=self.provider_name,
                                    language="es",
                                    start_time=result.get("StartTime", 0.0),
                                    end_time=result.get("EndTime", 0.0),
                                )
                            )
        except Exception:
            logger.exception(
                "Error in AWS Transcribe stream",
                extra={"extra": {"session_id": self._session_id}},
            )

    async def send_audio(self, pcm_bytes: bytes) -> None:
        await self._input_queue.put(pcm_bytes)

    async def disconnect(self) -> None:
        await self._input_queue.put(b"__STOP__")
        if self._stream_task is not None:
            self._stream_task.cancel()
            try:
                await self._stream_task
            except asyncio.CancelledError:
                pass
        logger.info(
            "AWS Transcribe disconnected",
            extra={"extra": {"session_id": self._session_id, "source": self._source}},
        )
