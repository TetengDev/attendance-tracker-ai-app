from __future__ import annotations

import socket
from dataclasses import dataclass
from typing import Annotated
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, status

from backend.app.config import Settings, get_settings
from backend.app.face.gallery import DEFAULT_GALLERY_STATE
from backend.app.settings.resolver import DEFAULT_SETTINGS_STORE, settings_version_for_health

router = APIRouter(tags=["health"])


@dataclass(frozen=True)
class ReachabilityTarget:
    name: str
    host: str
    port: int


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/health/deep")
def deep_health(settings: Annotated[Settings, Depends(get_settings)]) -> dict[str, object]:
    checks = {
        "postgres": _is_reachable(_target_from_url("postgres", settings.database_url)),
        "redis": _is_reachable(_target_from_url("redis", settings.redis_url)),
    }
    if not all(checks.values()):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"status": "unhealthy", "checks": checks},
        )
    return {
        "status": "ok",
        "checks": checks,
        "settings_version": settings_version_for_health(DEFAULT_SETTINGS_STORE),
        **DEFAULT_GALLERY_STATE.health(),
    }


def _target_from_url(name: str, url: str) -> ReachabilityTarget:
    parsed = urlsplit(url)
    if parsed.hostname is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"status": "unhealthy", "checks": {name: False}},
        )
    default_port = 5432 if parsed.scheme.startswith("postgresql") else 6379
    return ReachabilityTarget(name=name, host=parsed.hostname, port=parsed.port or default_port)


def _is_reachable(target: ReachabilityTarget, *, timeout_seconds: float = 0.25) -> bool:
    try:
        with socket.create_connection((target.host, target.port), timeout=timeout_seconds):
            return True
    except OSError:
        return False
