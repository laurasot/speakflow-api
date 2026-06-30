import logging

from langchain_anthropic import ChatAnthropic
from langchain_core.language_models import BaseChatModel

from app.core.config import settings
from app.providers.llm.factory import register_llm_provider

logger = logging.getLogger(__name__)

_DEFAULT_MODEL = "claude-haiku-4-5"


@register_llm_provider("anthropic")
class AnthropicProvider:
    provider_name = "anthropic"

    @property
    def enabled(self) -> bool:
        return bool(settings.anthropic_api_key)

    def create_llm(self) -> BaseChatModel:
        if not self.enabled:
            raise RuntimeError("ANTHROPIC_API_KEY not configured")

        model = settings.suggestion_model or _DEFAULT_MODEL
        logger.info(
            "Creating Anthropic LLM",
            extra={"extra": {"model": model}},
        )
        return ChatAnthropic(
            model=model,
            temperature=0.7,
            api_key=settings.anthropic_api_key,
        )
