import logging
from uuid import uuid4

from fastapi import APIRouter, Header, WebSocket, WebSocketDisconnect, status
from pydantic import TypeAdapter, ValidationError

from app.core.auth import AuthenticationError, extract_bearer_token
from app.core.dependencies import SessionManagerDep, SpeechServiceDep, TokenVerifierDep
from app.core.logging import session_id_var, user_id_var
from app.schemas.audio import (
    AudioChunkMetadata,
    IncomingMessage,
    StartSessionMessage,
    StopSessionMessage,
)
from app.schemas.transcript import (
    ErrorMessage,
    SessionEndedMessage,
    SessionStartedMessage,
    SuggestionMessage,
    TranscriptMessage,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["stt"])

_incoming_adapter: TypeAdapter[IncomingMessage] = TypeAdapter(IncomingMessage)  # type: ignore[type-arg]


@router.websocket("/stt/stream")
async def stt_stream(
    websocket: WebSocket,
    session_manager: SessionManagerDep,
    speech_service: SpeechServiceDep,
    token_verifier: TokenVerifierDep,
    authorization: str | None = Header(default=None),
) -> None:
    token = extract_bearer_token(authorization)
    try:
        if token is None:
            raise AuthenticationError
        identity = token_verifier.verify(token)
    except AuthenticationError:
        logger.warning("WebSocket rejected: authentication failed")
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Authentication required")
        return

    await websocket.accept()
    user_id_var.set(identity.user_id)

    session_id: str | None = None
    connection_id = str(uuid4())

    async def send_to_client(message: TranscriptMessage | SuggestionMessage) -> None:
        await websocket.send_json(message.model_dump())

    try:
        while True:
            message = await websocket.receive()

            if message["type"] == "websocket.disconnect":
                break

            if "text" in message:
                raw = message["text"]
                try:
                    parsed = _incoming_adapter.validate_json(raw)
                except ValidationError as exc:
                    await websocket.send_json(
                        ErrorMessage(
                            code="invalid_message",
                            message=str(exc),
                            session_id=session_id,
                        ).model_dump()
                    )
                    continue

                if isinstance(parsed, StartSessionMessage):
                    if parsed.user_id != identity.user_id:
                        logger.warning("start_session refused: user_id does not match credential")
                        await websocket.send_json(
                            ErrorMessage(
                                code="user_mismatch",
                                message="user_id does not match the authenticated user.",
                                session_id=str(parsed.session_id),
                            ).model_dump()
                        )
                        continue

                    session_id = str(parsed.session_id)
                    session_id_var.set(session_id)

                    speech_service.cleanup_session(session_id)
                    on_transcript = speech_service.build_transcript_callback(
                        session_id=session_id,
                        send_to_client=send_to_client,
                    )
                    await session_manager.create_session(
                        parsed, on_transcript, owner=connection_id
                    )
                    await websocket.send_json(
                        SessionStartedMessage(session_id=session_id).model_dump()
                    )

                elif isinstance(parsed, StopSessionMessage):
                    sid = str(parsed.session_id)
                    if await session_manager.close_session(sid, owner=connection_id):
                        speech_service.cleanup_session(sid)
                    await websocket.send_json(
                        SessionEndedMessage(session_id=sid).model_dump()
                    )
                    break

                elif isinstance(parsed, AudioChunkMetadata):
                    pending_metadata = parsed
                    binary_message = await websocket.receive()

                    if "bytes" not in binary_message:
                        logger.warning("Expected binary frame after audio_chunk metadata")
                        continue

                    pcm_bytes = binary_message["bytes"]
                    if session_id is None:
                        await websocket.send_json(
                            ErrorMessage(
                                code="no_session",
                                message="No active session. Send start_session first.",
                            ).model_dump()
                        )
                        continue

                    await session_manager.route_audio(
                        session_id=str(pending_metadata.session_id),
                        source=pending_metadata.source,
                        pcm_bytes=pcm_bytes,
                    )

    except WebSocketDisconnect:
        logger.info("WebSocket disconnected", extra={"extra": {"session_id": session_id}})
    except Exception:
        logger.exception("Unexpected error in WebSocket handler")
    finally:
        if session_id and await session_manager.close_session(
            session_id, owner=connection_id
        ):
            speech_service.cleanup_session(session_id)
