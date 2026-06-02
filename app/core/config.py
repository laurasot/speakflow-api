from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # Provider
    speech_provider: Literal["deepgram", "assemblyai", "aws_transcribe", "whisper_local"] = (
        "deepgram"
    )

    # Provider keys
    deepgram_api_key: str = ""
    assemblyai_api_key: str = ""

    # AWS
    aws_region: str = "us-east-1"
    aws_access_key_id: str = ""
    aws_secret_access_key: str = ""

    # LangChain / OpenAI
    openai_api_key: str = ""

    # Timeouts
    provider_connect_timeout: int = Field(default=10, ge=1)
    provider_response_timeout: int = Field(default=30, ge=1)

    # Server
    log_level: str = "INFO"
    cors_origins: list[str] = ["http://localhost:3000"]


settings = Settings()
