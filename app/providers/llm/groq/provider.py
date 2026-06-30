import logging

from langchain_core.language_models import BaseChatModel
from langchain_groq import ChatGroq

from app.core.config import settings
from app.providers.llm.factory import register_llm_provider

logger = logging.getLogger(__name__)

_DEFAULT_MODEL = "llama-3.1-8b-instant"


@register_llm_provider("groq")
class GroqProvider:
    provider_name = "groq"

    @property
    def enabled(self) -> bool:
        return bool(settings.groq_api_key)

    def create_llm(self) -> BaseChatModel:
        if not self.enabled:
            raise RuntimeError("GROQ_API_KEY not configured")

        model = settings.suggestion_model or _DEFAULT_MODEL
        logger.info(
            "Creating Groq LLM",
            extra={"extra": {"model": model}},
        )
        return ChatGroq(
            model=model,
            temperature=0.7,
            api_key=settings.groq_api_key,
        )
