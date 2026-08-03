from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from backend.app.api.consents import router as consents_router
from backend.app.api.devices import router as devices_router
from backend.app.api.enrollment import router as enrollment_router
from backend.app.api.groups import router as groups_router
from backend.app.api.health import router as health_router
from backend.app.api.locations import router as locations_router
from backend.app.api.people import router as people_router
from backend.app.api.people_merge import router as people_merge_router
from backend.app.api.sessions import router as sessions_router
from backend.app.api.ws_enroll import router as ws_enroll_router
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
    app.include_router(people_router)
    app.include_router(people_merge_router)
    app.include_router(consents_router)
    app.include_router(enrollment_router)
    app.include_router(ws_enroll_router)
    app.include_router(sessions_router)
    app.include_router(groups_router)
    app.include_router(locations_router)
    app.include_router(devices_router)
    return app


app = create_app()
