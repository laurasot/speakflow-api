import logging
import time
from dataclasses import asdict, dataclass

logger = logging.getLogger(__name__)


@dataclass
class TranscriptMetrics:
    provider: str
    session_id: str
    source: str
    language: str
    latency_ms: float
    char_count: int
    is_final: bool
    error: str | None = None


class MetricsCollector:
    """Registra métricas de cada transcripción para comparar proveedores."""

    def record(self, metrics: TranscriptMetrics) -> None:
        logger.info("transcript_metrics", extra={"extra": asdict(metrics)})

    def record_error(self, provider: str, session_id: str, source: str, error: str) -> None:
        logger.error(
            "provider_error",
            extra={
                "extra": {
                    "provider": provider,
                    "session_id": session_id,
                    "source": source,
                    "error": error,
                }
            },
        )

    def record_session_start(self, session_id: str, user_id: str, provider: str) -> None:
        logger.info(
            "session_start",
            extra={"extra": {"session_id": session_id, "user_id": user_id, "provider": provider}},
        )

    def record_session_end(self, session_id: str, duration_seconds: float) -> None:
        logger.info(
            "session_end",
            extra={"extra": {"session_id": session_id, "duration_seconds": duration_seconds}},
        )


class ProviderTimer:
    """Mide la latencia entre el momento en que se envía audio y cuando llega la transcripción."""

    def __init__(self) -> None:
        self._sent_at: float | None = None

    def mark_sent(self) -> None:
        self._sent_at = time.monotonic()

    def latency_ms(self) -> float:
        if self._sent_at is None:
            return 0.0
        return (time.monotonic() - self._sent_at) * 1000


metrics_collector = MetricsCollector()
