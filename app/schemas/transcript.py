from dataclasses import dataclass
from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field

# Por qué se disparó la sugerencia — el frontend usa esto para mostrar contexto al usuario
SuggestionTriggerReason = Literal[
    "silence",           # Speaker habló y el User no respondió a tiempo
    "repeated_question", # Speaker repitió un turno similar
    "filler_words",      # User dijo um/uh/mmm mientras debía responder al Speaker
    "user_question",     # User preguntó y el Speaker no respondió
]


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


class SuggestionMessage(BaseModel):
    type: Literal["suggestion"] = "suggestion"
    session_id: str
    source: Literal["microphone", "system"]
    suggestion: str
    based_on: str = Field(..., description="El texto (del Speaker o del User) que disparó la sugerencia")
    trigger_reason: SuggestionTriggerReason = Field(
        ...,
        description=(
            "Por qué se activó la sugerencia: "
            "'silence' = silencio prolongado, "
            "'repeated_question' = el Speaker repitió la pregunta, "
            "'filler_words' = el User dijo palabras de relleno (um, uh...)"
        ),
    )
    timestamp: int = Field(..., description="Unix timestamp en milisegundos")


@dataclass
class ConversationTurn:
    """Representa un turno de conversación para el contexto del LLM."""

    source: Literal["microphone", "system"]
    text: str
    timestamp: int

    @property
    def role(self) -> str:
        """Devuelve el rol para el prompt del LLM."""
        return "User" if self.source == "microphone" else "Speaker"


OutgoingMessage = Annotated[
    Union[
        SessionStartedMessage,
        TranscriptMessage,
        SessionEndedMessage,
        ErrorMessage,
        SuggestionMessage,
    ],
    Field(discriminator="type"),
]
