from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from logging.handlers import BaseRotatingHandler, TimedRotatingFileHandler
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from backend.app.api.consents import router as consents_router
from backend.app.api.device_pairing import router as device_pairing_router
from backend.app.api.devices import router as devices_router
from backend.app.api.dashboard import router as dashboard_router
from backend.app.api.enrollment import router as enrollment_router
from backend.app.api.groups import router as groups_router
from backend.app.api.health import router as health_router
from backend.app.api.locations import router as locations_router
from backend.app.api.people import router as people_router
from backend.app.api.people_merge import router as people_merge_router
from backend.app.api.sessions import router as sessions_router
from backend.app.api.settings import router as settings_router
from backend.app.api.ws_enroll import router as ws_enroll_router
from backend.app.api.ws_scan import router as ws_scan_router
from backend.app.audit.middleware import AuditMiddleware
from backend.app.config import get_settings

logger = logging.getLogger("attendance_tracker")


def setup_file_logging() -> None:
    logs_dir = Path("logs")
    logs_dir.mkdir(exist_ok=True)
    log_file = logs_dir / "app.log"
    file_handler = TimedRotatingFileHandler(
        log_file,
        when="H",
        interval=3,
        backupCount=4,  # Keep 12 hours of logs by default
        encoding="utf-8"
    )
    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s (%(filename)s:%(lineno)d): %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    file_handler.setFormatter(formatter)
    file_handler.setLevel(logging.DEBUG)

    root_logger = logging.getLogger()
    if not any(isinstance(h, TimedRotatingFileHandler) for h in root_logger.handlers):
        # Remove any existing file handlers (useful during hot reloads)
        root_logger.handlers = [h for h in root_logger.handlers if not isinstance(h, BaseRotatingHandler)]
        root_logger.addHandler(file_handler)
        if root_logger.level > logging.DEBUG:
            root_logger.setLevel(logging.DEBUG)
    
    # Ensure our specific app logger is at DEBUG
    logging.getLogger("attendance_tracker").setLevel(logging.DEBUG)
    logging.getLogger("backend").setLevel(logging.DEBUG)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    setup_file_logging()
    get_settings()
    yield


class KioskLogPayload(BaseModel):
    message: str


def create_app() -> FastAPI:
    app = FastAPI(title="Attendance Tracker", lifespan=lifespan)
    settings = get_settings()
    origins = [o.strip() for o in settings.cors_allowed_origins.split(",") if o.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(AuditMiddleware)

    @app.post("/api/kiosk/logs", status_code=204)
    async def log_kiosk_message(payload: KioskLogPayload) -> None:
        # Limit message size and sanitize to prevent log injection
        sanitized = payload.message[:500].replace("\n", "\\n").replace("\r", "\\r")
        logger.info(f"[CLIENT] {sanitized}")

    app.include_router(health_router)
    app.include_router(people_router)
    app.include_router(people_merge_router)
    app.include_router(consents_router)
    app.include_router(enrollment_router)
    app.include_router(ws_enroll_router)
    app.include_router(ws_scan_router)
    app.include_router(sessions_router)
    app.include_router(groups_router)
    app.include_router(locations_router)
    app.include_router(devices_router)
    app.include_router(device_pairing_router)
    app.include_router(dashboard_router)
    app.include_router(settings_router)
    return app


app = create_app()
