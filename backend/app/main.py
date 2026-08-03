from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from backend.app.api.health import router as health_router
from backend.app.audit.middleware import AuditMiddleware
from backend.app.config import get_settings


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    get_settings()
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="Attendance Tracker", lifespan=lifespan)
    app.add_middleware(AuditMiddleware)
    app.include_router(health_router)
    return app


app = create_app()
