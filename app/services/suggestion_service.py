import logging
import time
from collections.abc import Sequence
from typing import Literal

from langchain_core.output_parsers import StrOutputParser

from app.core.config import settings
from app.prompts.suggestion import suggestion_prompt
from app.providers.llm.factory import create_llm_provider
from app.schemas.transcript import ConversationTurn, SuggestionMessage, SuggestionTriggerReason

logger = logging.getLogger(__name__)


class SuggestionService:
    """Genera sugerencias de respuesta usando LangChain y el LLM configurado."""

    def __init__(self) -> None:
        self._chain = None
        self._provider_name = settings.llm_provider
        self._initialize_chain()

    def _initialize_chain(self) -> None:
        try:
            provider = create_llm_provider()

            if not provider.enabled:
                logger.warning(
                    "LLM provider has no API key — suggestions disabled",
                    extra={"extra": {"provider": self._provider_name}},
                )
                return

            llm = provider.create_llm()
            self._chain = suggestion_prompt | llm | StrOutputParser()

            logger.info(
                "SuggestionService initialized",
                extra={
                    "extra": {
                        "provider": self._provider_name,
                        "model": settings.suggestion_model or "provider_default",
                    }
                },
            )
        except Exception:
            logger.exception(
                "Failed to initialize SuggestionService",
                extra={"extra": {"provider": self._provider_name}},
            )

    @property
    def enabled(self) -> bool:
        return self._chain is not None

    async def generate(
        self,
        session_id: str,
        context: Sequence[ConversationTurn],
        question_text: str,
        question_source: Literal["User", "Speaker"],
        silence_seconds: float,
        trigger_reason: SuggestionTriggerReason = "silence",
    ) -> SuggestionMessage | None:
        """Genera una sugerencia basada en el contexto de la conversación.

        question_source indica quién hizo la pregunta:
        - "Speaker": el Speaker preguntó y el User no respondió → sugerimos respuesta al User
        - "User": el User preguntó y el Speaker no respondió → sugerimos cómo el User puede continuar
        """
        if not self.enabled:
            logger.debug(
                "Suggestions disabled",
                extra={"extra": {"session_id": session_id, "provider": self._provider_name}},
            )
            return None

        try:
            history = self._format_history(context)
            silent_party = "User" if question_source == "Speaker" else "Speaker"

            result = await self._chain.ainvoke({
                "conversation_history": history,
                "question_source": question_source,
                "question_text": question_text,
                "silent_party": silent_party,
                "silence_seconds": int(silence_seconds),
            })

            suggestion_text = result.strip()
            if not suggestion_text:
                return None

            logger.info(
                "Suggestion generated",
                extra={
                    "extra": {
                        "session_id": session_id,
                        "provider": self._provider_name,
                        "question_source": question_source,
                        "based_on": question_text[:50],
                    }
                },
            )

            return SuggestionMessage(
                session_id=session_id,
                source="system",
                suggestion=suggestion_text,
                based_on=question_text,
                trigger_reason=trigger_reason,
                timestamp=int(time.time() * 1000),
            )

        except Exception:
            logger.exception(
                "Error generating suggestion",
                extra={"extra": {"session_id": session_id, "provider": self._provider_name}},
            )
            return None

    def _format_history(self, context: Sequence[ConversationTurn]) -> str:
        if not context:
            return "(No previous conversation)"
        return "\n".join(f"[{turn.role}]: {turn.text}" for turn in context)
