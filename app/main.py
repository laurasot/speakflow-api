import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.logging import request_id_var, setup_logging
from app.routers.v1 import health, websocket_stt

setup_logging()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    logger.info("speakflow-api starting", extra={"extra": {"provider": settings.speech_provider}})
    yield
    logger.info("speakflow-api shutting down")


app = FastAPI(
    title="speakflow-api",
    version="0.1.0",
    description="Real-time Speech-to-Text backend with provider abstraction",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def request_tracking(request: Request, call_next):  # type: ignore[no-untyped-def]
    request_id = str(uuid4())
    request_id_var.set(request_id)
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response


app.include_router(health.router, prefix="/v1")
app.include_router(websocket_stt.router, prefix="/v1")
