import logging

from app.core.config import settings
from app.providers.stt.base import SpeechProvider

logger = logging.getLogger(__name__)

_REGISTRY: dict[str, type] = {}


def register_provider(name: str):
    """Decorador para registrar un proveedor STT en el registry global."""

    def decorator(cls: type) -> type:
        _REGISTRY[name] = cls
        logger.debug("STT provider registered", extra={"extra": {"provider": name}})
        return cls

    return decorator


def create_provider() -> SpeechProvider:
    """Crea una instancia nueva del proveedor STT configurado en SPEECH_PROVIDER."""
    _load_providers()

    provider_class = _REGISTRY.get(settings.speech_provider)
    if provider_class is None:
        available = list(_REGISTRY.keys())
        raise ValueError(
            f"STT provider '{settings.speech_provider}' desconocido. "
            f"Disponibles: {available}"
        )

    instance = provider_class()
    logger.info("STT provider created", extra={"extra": {"provider": settings.speech_provider}})
    return instance  # type: ignore[return-value]


def _load_providers() -> None:
    """Importa todos los módulos de proveedores para registrarlos."""
    from app.providers.stt.assemblyai import provider as _  # noqa: F401
    from app.providers.stt.aws_transcribe import provider as _  # noqa: F401
    from app.providers.stt.deepgram import provider as _  # noqa: F401
    from app.providers.stt.whisper_local import provider as _  # noqa: F401
