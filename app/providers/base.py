from typing import Awaitable, Callable, Protocol, runtime_checkable

from app.schemas.audio import AudioConfig
from app.schemas.transcript import TranscriptMessage


@runtime_checkable
class SpeechProvider(Protocol):
    """Contrato que todos los proveedores de Speech-to-Text deben cumplir."""

    provider_name: str

    async def connect(
        self,
        session_id: str,
        source: str,
        audio_config: AudioConfig,
        on_transcript: Callable[[TranscriptMessage], Awaitable[None]],
    ) -> None:
        """Abre una conexión persistente con el proveedor para esta fuente."""
        ...

    async def disconnect(self) -> None:
        """Cierra la conexión limpiamente y libera recursos."""
        ...

    async def send_audio(self, pcm_bytes: bytes) -> None:
        """Envía un chunk de audio PCM crudo al proveedor."""
        ...
