from fastapi import APIRouter
from pydantic import BaseModel

from app.core.dependencies import SessionManagerDep

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: str
    active_sessions: int


@router.get("/health", response_model=HealthResponse)
async def health(session_manager: SessionManagerDep) -> HealthResponse:
    return HealthResponse(
        status="ok",
        active_sessions=session_manager.active_sessions(),
    )
