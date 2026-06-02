import logging
from typing import Any

from app.schemas.transcript import TranscriptMessage

logger = logging.getLogger(__name__)


class TranscriptProcessor:
    """
    Normaliza y post-procesa transcripciones finales con LangChain.
    El chain es opcional — si no se configura, devuelve la transcripción sin modificar.
    """

    def __init__(self, chain: Any | None = None) -> None:
        self._chain = chain

    async def process(self, transcript: TranscriptMessage) -> TranscriptMessage:
        """
        Aplica post-procesamiento LangChain solo a transcripciones finales.
        Las parciales se devuelven inmediatamente sin overhead.
        """
        if not transcript.is_final or self._chain is None:
            return transcript

        try:
            result = await self._chain.ainvoke({"text": transcript.text})
            enriched_text = result.get("text", transcript.text) if isinstance(result, dict) else str(result)

            return transcript.model_copy(update={"text": enriched_text})
        except Exception:
            logger.exception(
                "LangChain post-processing failed, returning original transcript",
                extra={"extra": {"session_id": transcript.session_id}},
            )
            return transcript


def build_transcript_processor() -> TranscriptProcessor:
    """
    Construye el TranscriptProcessor.
    Agrega un chain LangChain aquí cuando sea necesario.
    """
    chain = _build_chain()
    return TranscriptProcessor(chain=chain)


def _build_chain() -> Any | None:
    """
    Construye el chain LangChain para post-procesamiento.
    Retorna None si no hay API key configurada.
    """
    try:
        from app.core.config import settings

        if not settings.openai_api_key:
            logger.info("No OPENAI_API_KEY set — LangChain post-processing disabled")
            return None

        from langchain_core.output_parsers import StrOutputParser
        from langchain_core.prompts import ChatPromptTemplate
        from langchain_openai import ChatOpenAI

        prompt = ChatPromptTemplate.from_messages([
            (
                "system",
                "Eres un corrector de transcripciones de audio. "
                "Corrige errores de puntuación y capitalización sin cambiar el contenido. "
                "Responde solo con el texto corregido.",
            ),
            ("human", "{text}"),
        ])

        llm = ChatOpenAI(
            model="gpt-4o-mini",
            temperature=0,
            api_key=settings.openai_api_key,
        )

        return prompt | llm | StrOutputParser()

    except ImportError:
        logger.warning("langchain-openai not installed — LangChain post-processing disabled")
        return None
