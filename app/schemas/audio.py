from typing import Annotated, Literal, Union

from pydantic import UUID4, BaseModel, Field


class AudioConfig(BaseModel):
    sample_rate: int = Field(default=16000, ge=8000, le=48000)
    channels: int = Field(default=1, ge=1, le=2)
    encoding: Literal["pcm16le"] = "pcm16le"


class StartSessionMessage(BaseModel):
    type: Literal["start_session"]
    session_id: UUID4
    user_id: str
    sources: list[Literal["microphone", "system"]] = Field(..., min_length=1)
    audio_config: AudioConfig = Field(default_factory=AudioConfig)


class AudioChunkMetadata(BaseModel):
    type: Literal["audio_chunk"]
    session_id: UUID4
    source: Literal["microphone", "system"]
    timestamp: int = Field(..., description="Unix timestamp en milisegundos")
    size: int = Field(..., gt=0, description="Tamaño en bytes del frame binario que sigue")


class StopSessionMessage(BaseModel):
    type: Literal["stop_session"]
    session_id: UUID4


IncomingMessage = Annotated[
    Union[StartSessionMessage, AudioChunkMetadata, StopSessionMessage],
    Field(discriminator="type"),
]
