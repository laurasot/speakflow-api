import logging
from typing import Awaitable, Callable

from app.infrastructure.metrics import TranscriptMetrics, metrics_collector
from app.schemas.transcript import TranscriptMessage
from app.services.transcript_processor import TranscriptProcessor

logger = logging.getLogger(__name__)


class SpeechService:
    """
    Orquesta el flujo de una transcripción:
    recibe el evento crudo del proveedor → post-procesa → registra métricas → notifica al cliente.
    """

    def __init__(self, processor: TranscriptProcessor) -> None:
        self._processor = processor

    def build_transcript_callback(
        self,
        send_to_client: Callable[[TranscriptMessage], Awaitable[None]],
    ) -> Callable[[TranscriptMessage], Awaitable[None]]:
        """Devuelve el callback que se pasa al proveedor en connect()."""

        async def on_transcript(transcript: TranscriptMessage) -> None:
            try:
                processed = await self._processor.process(transcript)

                metrics_collector.record(
                    TranscriptMetrics(
                        provider=transcript.provider,
                        session_id=transcript.session_id,
                        source=transcript.source,
                        language=transcript.language,
                        latency_ms=0.0,
                        char_count=len(transcript.text),
                        is_final=transcript.is_final,
                    )
                )

                await send_to_client(processed)
            except Exception:
                logger.exception(
                    "Error in transcript pipeline",
                    extra={"extra": {"session_id": transcript.session_id}},
                )

        return on_transcript
