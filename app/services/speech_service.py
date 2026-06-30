import logging
from typing import Awaitable, Callable

from app.infrastructure.metrics import TranscriptMetrics, metrics_collector
from app.schemas.transcript import SuggestionMessage, TranscriptMessage
from app.services.suggestion_service import SuggestionService
from app.services.suggestion_trigger import SuggestionTrigger
from app.services.transcript_processor import TranscriptProcessor

logger = logging.getLogger(__name__)


class SpeechService:
    """
    Orquesta el flujo de una transcripción:
    recibe el evento crudo del proveedor → post-procesa → registra métricas → notifica al cliente.
    También integra el sistema de sugerencias para disparar LLM cuando el usuario se traba.
    """

    def __init__(self, processor: TranscriptProcessor) -> None:
        self._processor = processor
        self._suggestion_service = SuggestionService()
        self._triggers: dict[str, SuggestionTrigger] = {}

    def build_transcript_callback(
        self,
        session_id: str,
        send_to_client: Callable[[TranscriptMessage | SuggestionMessage], Awaitable[None]],
    ) -> Callable[[TranscriptMessage], Awaitable[None]]:
        """Devuelve el callback que se pasa al proveedor en connect()."""

        trigger = SuggestionTrigger(
            suggestion_service=self._suggestion_service,
            send_suggestion=send_to_client,
        )
        self._triggers[session_id] = trigger

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

                if transcript.is_final:
                    await trigger.evaluate(transcript)

            except Exception:
                logger.exception(
                    "Error in transcript pipeline",
                    extra={"extra": {"session_id": transcript.session_id}},
                )

        return on_transcript

    def cleanup_session(self, session_id: str) -> None:
        """Limpia el estado de sugerencias al cerrar una sesión."""
        trigger = self._triggers.pop(session_id, None)
        if trigger:
            trigger.cleanup_session(session_id)
