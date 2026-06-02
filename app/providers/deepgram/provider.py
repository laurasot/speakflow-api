import asyncio
import json
import logging
import time
from typing import Any, Awaitable, Callable

import websockets

from app.core.config import settings
from app.providers.factory import register_provider
from app.schemas.audio import AudioConfig
from app.schemas.transcript import TranscriptMessage

logger = logging.getLogger(__name__)

_DEEPGRAM_WS_URL = "wss://api.deepgram.com/v1/listen"
_RETRY_DELAYS = [1, 2, 4]


@register_provider("deepgram")
class DeepgramProvider:
    """
    Proveedor Deepgram usando su API WebSocket de streaming.
    Documentación: https://developers.deepgram.com/reference/streaming
    """

    provider_name = "deepgram"

    def __init__(self) -> None:
        self._ws: Any | None = None
        self._session_id: str = ""
        self._source: str = ""
        self._audio_config: AudioConfig | None = None
        self._on_transcript: Callable[[TranscriptMessage], Awaitable[None]] | None = None
        self._receive_task: asyncio.Task | None = None  # type: ignore[type-arg]

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
                    "Deepgram connected",
                    extra={"extra": {"session_id": self._session_id, "source": self._source}},
                )
                return
            except Exception as exc:
                logger.warning(
                    "Deepgram connection attempt failed",
                    extra={
                        "extra": {
                            "session_id": self._session_id,
                            "attempt": attempt + 1,
                            "error": str(exc),
                        }
                    },
                )
                if attempt < len(_RETRY_DELAYS) - 1:
                    await asyncio.sleep(delay)

        raise ConnectionError(
            f"Deepgram unavailable after {len(_RETRY_DELAYS)} attempts "
            f"(session={self._session_id})"
        )

    async def _establish_connection(self) -> None:
        assert self._audio_config is not None

        url = (
            f"{_DEEPGRAM_WS_URL}"
            f"?model=nova-2"
            f"&language=es"
            f"&encoding=linear16"
            f"&sample_rate={self._audio_config.sample_rate}"
            f"&channels={self._audio_config.channels}"
            f"&interim_results=true"
            f"&smart_format=true"
            f"&utterance_end_ms=1000"
        )
        headers = {"Authorization": f"Token {settings.deepgram_api_key}"}

        timeout = settings.provider_connect_timeout
        self._ws = await asyncio.wait_for(
            websockets.connect(url, additional_headers=headers),  # type: ignore[attr-defined]
            timeout=timeout,
        )

        self._receive_task = asyncio.create_task(
            self._receive_loop(),
            name=f"deepgram-recv-{self._session_id}-{self._source}",
        )

    async def _receive_loop(self) -> None:
        try:
            async for raw_msg in self._ws:
                try:
                    data = json.loads(raw_msg)
                    msg_type = data.get("type")

                    if msg_type == "Results" and self._on_transcript:
                        channel = data.get("channel", {})
                        alts = channel.get("alternatives", [])
                        if not alts:
                            continue
                        alt = alts[0]
                        text = alt.get("transcript", "")
                        if not text:
                            continue

                        words = alt.get("words", [])
                        start = words[0].get("start", 0.0) if words else 0.0
                        end = words[-1].get("end", 0.0) if words else 0.0

                        await self._on_transcript(
                            TranscriptMessage(
                                session_id=self._session_id,
                                source=self._source,  # type: ignore[arg-type]
                                text=text,
                                is_final=data.get("is_final", False),
                                timestamp=int(time.time() * 1000),
                                provider=self.provider_name,
                                language=data.get("channel", {}).get("detected_language", "es"),
                                start_time=start,
                                end_time=end,
                            )
                        )
                except Exception:
                    logger.exception(
                        "Error processing Deepgram message",
                        extra={"extra": {"session_id": self._session_id}},
                    )
        except Exception:
            logger.exception(
                "Deepgram receive loop error",
                extra={"extra": {"session_id": self._session_id}},
            )

    async def send_audio(self, pcm_bytes: bytes) -> None:
        if self._ws is None:
            return
        try:
            await self._ws.send(pcm_bytes)
        except Exception:
            logger.exception(
                "Deepgram send_audio error",
                extra={"extra": {"session_id": self._session_id}},
            )

    async def disconnect(self) -> None:
        if self._receive_task is not None:
            self._receive_task.cancel()
            try:
                await self._receive_task
            except asyncio.CancelledError:
                pass

        if self._ws is not None:
            try:
                # Señal de fin de stream a Deepgram
                await self._ws.send(json.dumps({"type": "CloseStream"}))
                await self._ws.close()
            except Exception:
                logger.exception(
                    "Error closing Deepgram WebSocket",
                    extra={"extra": {"session_id": self._session_id}},
                )
            finally:
                self._ws = None
                logger.info(
                    "Deepgram disconnected",
                    extra={"extra": {"session_id": self._session_id, "source": self._source}},
                )
