import logging

from fastapi import APIRouter, Header, WebSocket, WebSocketDisconnect, status
from pydantic import TypeAdapter, ValidationError

from app.core.dependencies import SessionManagerDep
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
    TranscriptMessage,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["stt"])

_incoming_adapter: TypeAdapter[IncomingMessage] = TypeAdapter(IncomingMessage)  # type: ignore[type-arg]


@router.websocket("/stt/stream")
async def stt_stream(
    websocket: WebSocket,
    session_manager: SessionManagerDep,
    x_user_id: str | None = Header(default=None),
) -> None:
    if not x_user_id:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="X-User-Id header required")
        return

    await websocket.accept()
    user_id_var.set(x_user_id)

    session_id: str | None = None

    async def send_transcript(transcript: TranscriptMessage) -> None:
        await websocket.send_json(transcript.model_dump())

    try:
        while True:
            # Cada ciclo puede ser texto (JSON) o binario (PCM)
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
                    session_id = str(parsed.session_id)
                    session_id_var.set(session_id)

                    await session_manager.create_session(parsed, send_transcript)
                    await websocket.send_json(
                        SessionStartedMessage(session_id=session_id).model_dump()
                    )

                elif isinstance(parsed, StopSessionMessage):
                    sid = str(parsed.session_id)
                    await session_manager.close_session(sid)
                    await websocket.send_json(
                        SessionEndedMessage(session_id=sid).model_dump()
                    )
                    break

                elif isinstance(parsed, AudioChunkMetadata):
                    # El siguiente frame es el binario — se lee en el próximo ciclo
                    # Guardamos la metadata temporalmente en el scope local
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
        if session_id:
            await session_manager.close_session(session_id)
