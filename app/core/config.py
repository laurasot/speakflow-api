from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # STT provider
    speech_provider: Literal["deepgram", "assemblyai", "aws_transcribe", "whisper_local"] = (
        "deepgram"
    )

    # STT provider keys
    deepgram_api_key: str = ""
    assemblyai_api_key: str = ""

    # AWS
    aws_region: str = "us-east-1"
    aws_access_key_id: str = ""
    aws_secret_access_key: str = ""

    # LLM provider
    llm_provider: Literal["openai", "groq", "anthropic"] = "groq"
    suggestion_model: str = ""  # vacío = usa el default de cada provider

    # LLM provider keys
    openai_api_key: str = ""
    groq_api_key: str = ""
    anthropic_api_key: str = ""

    # Auth: SHA-256 hash of each API key -> user_id it authenticates as. Empty = every connection is rejected.
    auth_api_key_hashes: dict[str, str] = Field(default_factory=dict)

    # Audio backpressure
    audio_queue_max_chunks: int = Field(
        default=120,
        ge=1,
        description="Chunks de audio en cola por fuente antes de descartar los más antiguos (120 ≈ 60 s a 500 ms)",
    )

    # Timeouts
    provider_connect_timeout: int = Field(default=10, ge=1)
    provider_response_timeout: int = Field(default=30, ge=1)

    # Suggestion trigger settings
    suggestion_silence_threshold: float = Field(
        default=6.0, ge=1.0, description="Segundos de silencio antes de disparar sugerencia"
    )
    suggestion_similarity_threshold: float = Field(
        default=0.6, ge=0.0, le=1.0, description="Umbral de similitud para detectar pregunta repetida"
    )
    suggestion_context_size: int = Field(
        default=5, ge=1, le=20, description="Número de turnos de contexto para el LLM"
    )
    suggestion_filler_words: list[str] = Field(
        default=["um", "uh", "mmm", "hmm", "eh", "bueno", "este", "pues", "like", "you know"],
        description="Palabras de relleno que indican duda del usuario",
    )
    enable_semantic_similarity: bool = Field(
        default=False,
        description="Usar embeddings (BAAI/bge-small-en-v1.5) en lugar de difflib para similitud",
    )

    # Server
    log_level: str = "INFO"
    cors_origins: list[str] = ["http://localhost:3000"]


settings = Settings()
