import asyncio
import logging
import time
from collections import deque
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import TYPE_CHECKING, Awaitable, Callable, Literal

from app.core.config import settings
from app.schemas.transcript import (
    ConversationTurn,
    SuggestionMessage,
    SuggestionTriggerReason,
    TranscriptMessage,
)
from app.services.suggestion_service import SuggestionService

if TYPE_CHECKING:
    from app.services.session_manager import Session

logger = logging.getLogger(__name__)


@dataclass
class SuggestionState:
    """Estado del trigger de sugerencias por sesión."""

    conversation_context: deque[ConversationTurn] = field(
        default_factory=lambda: deque(maxlen=settings.suggestion_context_size)
    )
    last_system_final_at: float | None = None
    last_system_final_text: str | None = None
    suggestion_timer: asyncio.TimerHandle | None = None
    pending_suggestion: bool = False
    # Razón que activará la sugerencia — se refina en _on_silence_timeout con filler words
    pending_trigger_reason: SuggestionTriggerReason = "silence"
    # A quién estamos esperando respuesta: "microphone" (User) o "system" (Speaker)
    waiting_for: Literal["microphone", "system"] | None = None


class SuggestionTrigger:
    """
    Decide cuándo disparar sugerencias basándose en 5 señales:
    1. Silencio largo del mic después de que el Speaker preguntó
    2. El Speaker repite la pregunta (similitud semántica)
    3. Palabras de relleno del User (um, uh, mmm...)
    4. Pregunta directa del Speaker (termina en ?)
    5. Pregunta directa del User y el Speaker no responde
    """

    def __init__(
        self,
        suggestion_service: SuggestionService,
        send_suggestion: Callable[[SuggestionMessage], Awaitable[None]],
    ) -> None:
        self._service = suggestion_service
        self._send_suggestion = send_suggestion
        self._states: dict[str, SuggestionState] = {}

    def get_or_create_state(self, session_id: str) -> SuggestionState:
        if session_id not in self._states:
            self._states[session_id] = SuggestionState()
        return self._states[session_id]

    def cleanup_session(self, session_id: str) -> None:
        state = self._states.pop(session_id, None)
        if state and state.suggestion_timer:
            state.suggestion_timer.cancel()

    async def evaluate(self, transcript: TranscriptMessage) -> None:
        """Evalúa una transcripción final y decide si disparar sugerencia."""
        if not transcript.is_final:
            return

        if not self._service.enabled:
            return

        state = self.get_or_create_state(transcript.session_id)

        turn = ConversationTurn(
            source=transcript.source,
            text=transcript.text,
            timestamp=transcript.timestamp,
        )
        state.conversation_context.append(turn)

        if transcript.source == "system":
            await self._handle_system_final(transcript, state)
        else:
            await self._handle_mic_final(transcript, state)

    async def _handle_system_final(
        self,
        transcript: TranscriptMessage,
        state: SuggestionState,
    ) -> None:
        """Maneja un final del sistema (Speaker).

        Cancela el timer si estábamos esperando que el Speaker respondiera
        una pregunta del User, luego evalúa si el Speaker preguntó algo.
        """
        now = time.monotonic()

        is_question = self._is_question(transcript.text)
        is_repeat = self._is_repeat(transcript.text, state.last_system_final_text)

        state.last_system_final_at = now
        state.last_system_final_text = transcript.text

        if state.suggestion_timer:
            state.suggestion_timer.cancel()
            state.suggestion_timer = None
            state.pending_suggestion = False
            state.waiting_for = None

        if not is_question:
            logger.debug(
                "Speaker spoke but not a question, skipping",
                extra={"extra": {"session_id": transcript.session_id}},
            )
            return

        silence_threshold = settings.suggestion_silence_threshold
        # repeated_question reduce el umbral (más urgente)
        # filler_words se evalúa al expirar el timer con el contexto del mic acumulado
        reason: SuggestionTriggerReason = "repeated_question" if is_repeat else "silence"
        if is_repeat:
            silence_threshold *= 0.5

        self._start_timer(
            session_id=transcript.session_id,
            state=state,
            question_text=transcript.text,
            question_source="Speaker",
            waiting_for="microphone",
            reason=reason,
            threshold=silence_threshold,
        )

    async def _handle_mic_final(
        self,
        transcript: TranscriptMessage,
        state: SuggestionState,
    ) -> None:
        """Maneja un final del micrófono (User).

        Si estábamos esperando que el User respondiera al Speaker, cancela el timer.
        Si el User hizo una pregunta y el Speaker aún no responde, inicia uno nuevo.
        """
        if state.waiting_for == "microphone" and state.suggestion_timer:
            state.suggestion_timer.cancel()
            state.suggestion_timer = None
            state.pending_suggestion = False
            state.waiting_for = None
            logger.debug(
                "User responded to Speaker, suggestion timer cancelled",
                extra={"extra": {"session_id": transcript.session_id}},
            )

        # Si el User preguntó algo y no hay ya un timer corriendo, iniciamos uno
        # esperando que el Speaker responda
        if self._is_question(transcript.text) and not state.pending_suggestion:
            self._start_timer(
                session_id=transcript.session_id,
                state=state,
                question_text=transcript.text,
                question_source="User",
                waiting_for="system",
                reason="user_question",
                threshold=settings.suggestion_silence_threshold,
            )

    def _start_timer(
        self,
        session_id: str,
        state: SuggestionState,
        question_text: str,
        question_source: Literal["User", "Speaker"],
        waiting_for: Literal["microphone", "system"],
        reason: SuggestionTriggerReason,
        threshold: float,
    ) -> None:
        """Inicia el timer de silencio para una pregunta detectada."""
        state.pending_trigger_reason = reason
        state.waiting_for = waiting_for
        state.pending_suggestion = True

        loop = asyncio.get_running_loop()
        state.suggestion_timer = loop.call_later(
            threshold,
            lambda: asyncio.create_task(
                self._on_silence_timeout(session_id, question_text, question_source)
            ),
        )

        logger.debug(
            "Suggestion timer started",
            extra={
                "extra": {
                    "session_id": session_id,
                    "question_source": question_source,
                    "waiting_for": waiting_for,
                    "threshold_seconds": threshold,
                    "reason": reason,
                }
            },
        )

    async def _on_silence_timeout(
        self,
        session_id: str,
        question_text: str,
        question_source: Literal["User", "Speaker"],
    ) -> None:
        """Se llama cuando el silencio supera el umbral sin respuesta."""
        state = self._states.get(session_id)
        if not state or not state.pending_suggestion:
            return

        state.pending_suggestion = False
        state.waiting_for = None

        silence_seconds = settings.suggestion_silence_threshold
        trigger_reason: SuggestionTriggerReason = state.pending_trigger_reason

        # filler words solo aplican cuando es el User quien debe responder al Speaker
        if trigger_reason == "silence" and question_source == "Speaker":
            if self._has_filler_words(state):
                trigger_reason = "filler_words"

        logger.info(
            "Triggering suggestion",
            extra={
                "extra": {
                    "session_id": session_id,
                    "question_source": question_source,
                    "silence_seconds": silence_seconds,
                    "trigger_reason": trigger_reason,
                }
            },
        )

        suggestion = await self._service.generate(
            session_id=session_id,
            context=list(state.conversation_context),
            question_text=question_text,
            question_source=question_source,
            silence_seconds=silence_seconds,
            trigger_reason=trigger_reason,
        )

        if suggestion:
            await self._send_suggestion(suggestion)

    def _is_question(self, text: str) -> bool:
        """Detecta si el texto es una pregunta."""
        text = text.strip()
        if text.endswith("?"):
            return True

        question_starters = (
            "what", "how", "why", "when", "where", "who", "which",
            "could", "can", "would", "will", "do", "does", "did",
            "is", "are", "was", "were", "have", "has",
            "qué", "cómo", "por qué", "cuándo", "dónde", "quién", "cuál",
            "puedes", "podrías", "puedo", "podría",
        )
        lower = text.lower()
        return any(lower.startswith(q) for q in question_starters)

    def _is_repeat(self, current: str, previous: str | None) -> bool:
        """Detecta si el Speaker repitió una pregunta similar."""
        if not previous:
            return False

        ratio = SequenceMatcher(None, current.lower(), previous.lower()).ratio()
        return ratio >= settings.suggestion_similarity_threshold

    def _has_filler_words(self, state: SuggestionState) -> bool:
        """Revisa si los últimos turnos del mic tienen palabras de relleno."""
        filler_words = set(w.lower() for w in settings.suggestion_filler_words)

        for turn in state.conversation_context:
            if turn.source != "microphone":
                continue
            words = set(turn.text.lower().split())
            if words & filler_words:
                return True

        return False
