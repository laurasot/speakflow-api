import logging

from app.core.config import settings
from app.providers.base import SpeechProvider

logger = logging.getLogger(__name__)

_REGISTRY: dict[str, type] = {}


def register_provider(name: str):
    """Decorador para registrar un proveedor en el registry global."""

    def decorator(cls: type) -> type:
        _REGISTRY[name] = cls
        logger.debug("Provider registered", extra={"extra": {"provider": name}})
        return cls

    return decorator


def create_provider() -> SpeechProvider:
    """Crea una instancia nueva del proveedor configurado en SPEECH_PROVIDER."""
    # Importar los módulos para que los decoradores @register_provider se ejecuten
    _load_providers()

    provider_class = _REGISTRY.get(settings.speech_provider)
    if provider_class is None:
        available = list(_REGISTRY.keys())
        raise ValueError(
            f"Proveedor '{settings.speech_provider}' desconocido. "
            f"Disponibles: {available}"
        )

    instance = provider_class()
    logger.info("Provider created", extra={"extra": {"provider": settings.speech_provider}})
    return instance  # type: ignore[return-value]


def _load_providers() -> None:
    """Importa todos los módulos de proveedores para registrarlos."""
    # Las importaciones aquí son intencionales — activan los decoradores
    from app.providers.assemblyai import provider as _  # noqa: F401
    from app.providers.aws_transcribe import provider as _  # noqa: F401
    from app.providers.deepgram import provider as _  # noqa: F401
    from app.providers.whisper_local import provider as _  # noqa: F401
