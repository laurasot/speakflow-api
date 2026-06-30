import logging

from langchain_core.language_models import BaseChatModel

from app.core.config import settings
from app.providers.llm.base import LLMProvider

logger = logging.getLogger(__name__)

_REGISTRY: dict[str, type] = {}


def register_llm_provider(name: str):
    """Decorador para registrar un proveedor LLM en el registry global."""

    def decorator(cls: type) -> type:
        _REGISTRY[name] = cls
        return cls

    return decorator


def create_llm_provider() -> LLMProvider:
    """Crea una instancia del proveedor LLM configurado en LLM_PROVIDER."""
    _load_providers()

    provider_class = _REGISTRY.get(settings.llm_provider)
    if provider_class is None:
        available = list(_REGISTRY.keys())
        raise ValueError(
            f"LLM provider '{settings.llm_provider}' desconocido. "
            f"Disponibles: {available}"
        )

    instance = provider_class()
    logger.info(
        "LLM provider created",
        extra={"extra": {"provider": settings.llm_provider}},
    )
    return instance  # type: ignore[return-value]


def create_llm() -> BaseChatModel:
    """Shortcut: crea el proveedor y devuelve el LLM listo para usar."""
    return create_llm_provider().create_llm()


def _load_providers() -> None:
    """Importa los módulos de proveedores para activar los decoradores."""
    from app.providers.llm.anthropic import provider as _  # noqa: F401
    from app.providers.llm.groq import provider as _  # noqa: F401
    from app.providers.llm.openai import provider as _  # noqa: F401
