from functools import lru_cache
from typing import Annotated

from fastapi import Depends

from app.core.auth import ApiKeyVerifier, TokenVerifier
from app.core.config import settings
from app.services.session_manager import SessionManager
from app.services.speech_service import SpeechService
from app.services.transcript_processor import TranscriptProcessor, build_transcript_processor


@lru_cache(maxsize=1)
def get_token_verifier() -> TokenVerifier:
    return ApiKeyVerifier(settings.auth_api_key_hashes)


@lru_cache(maxsize=1)
def get_session_manager() -> SessionManager:
    return SessionManager()


@lru_cache(maxsize=1)
def get_speech_service() -> SpeechService:
    processor = build_transcript_processor()
    return SpeechService(processor)


SessionManagerDep = Annotated[SessionManager, Depends(get_session_manager)]
SpeechServiceDep = Annotated[SpeechService, Depends(get_speech_service)]
TokenVerifierDep = Annotated[TokenVerifier, Depends(get_token_verifier)]
