import logging

from langchain_core.language_models import BaseChatModel
from langchain_openai import ChatOpenAI

from app.core.config import settings
from app.providers.llm.factory import register_llm_provider

logger = logging.getLogger(__name__)


@register_llm_provider("openai")
class OpenAIProvider:
    provider_name = "openai"

    @property
    def enabled(self) -> bool:
        return bool(settings.openai_api_key)

    def create_llm(self) -> BaseChatModel:
        if not self.enabled:
            raise RuntimeError("OPENAI_API_KEY not configured")

        logger.info(
            "Creating OpenAI LLM",
            extra={"extra": {"model": settings.suggestion_model}},
        )
        return ChatOpenAI(
            model=settings.suggestion_model or "gpt-4o-mini",
            temperature=0.7,
            api_key=settings.openai_api_key,
        )
