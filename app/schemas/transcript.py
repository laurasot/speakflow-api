from typing import Annotated, Literal, Union

from pydantic import UUID4, BaseModel, Field


class SessionStartedMessage(BaseModel):
    type: Literal["session_started"] = "session_started"
    session_id: str


class TranscriptMessage(BaseModel):
    type: Literal["transcript"] = "transcript"
    session_id: str
    source: Literal["microphone", "system"]
    text: str
    is_final: bool
    timestamp: int = Field(..., description="Unix timestamp en milisegundos")
    provider: str
    language: str
    start_time: float
    end_time: float


class SessionEndedMessage(BaseModel):
    type: Literal["session_ended"] = "session_ended"
    session_id: str


class ErrorMessage(BaseModel):
    type: Literal["error"] = "error"
    code: str
    message: str
    session_id: str | None = None


OutgoingMessage = Annotated[
    Union[SessionStartedMessage, TranscriptMessage, SessionEndedMessage, ErrorMessage],
    Field(discriminator="type"),
]
