from __future__ import annotations

from fastapi.testclient import TestClient
from pydantic import ValidationError
from pytest import MonkeyPatch

from backend.app.api.health import _is_reachable, _target_from_url
from backend.app.config import Settings, get_settings
from backend.app.main import create_app


def test_root_app_import_path_matches_uvicorn_command() -> None:
    from app.main import app

    assert app.title == "Attendance Tracker"


def test_settings_requires_biometric_kek() -> None:
    try:
        Settings(  # type: ignore[call-arg]
            database_url="postgresql+asyncpg://localhost/db",
            redis_url="redis://localhost:6379/0",
        )
    except ValidationError as exc:
        assert "biometric_kek" in str(exc)
    else:
        raise AssertionError("BIOMETRIC_KEK must be required")


def test_health_returns_ok(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://localhost:5432/attendance")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("BIOMETRIC_KEK", "test-kek")
    get_settings.cache_clear()

    with TestClient(create_app()) as client:
        assert client.get("/health").json() == {"status": "ok"}


def test_deep_health_returns_503_when_dependency_unreachable(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://localhost:1/attendance")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:1/0")
    monkeypatch.setenv("BIOMETRIC_KEK", "test-kek")
    get_settings.cache_clear()

    with TestClient(create_app()) as client:
        response = client.get("/health/deep")

        assert response.status_code == 503
        assert response.json()["detail"] == {
            "status": "unhealthy",
            "checks": {"postgres": False, "redis": False},
        }


def test_deep_health_exposes_settings_version(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://localhost:5432/attendance")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("BIOMETRIC_KEK", "test-kek")
    monkeypatch.setattr("backend.app.api.health._is_reachable", lambda _target: True)
    get_settings.cache_clear()

    with TestClient(create_app()) as client:
        response = client.get("/health/deep")

        assert response.status_code == 200
        assert response.json() == {
            "status": "ok",
            "checks": {"postgres": True, "redis": True},
            "settings_version": 1,
            "gallery_version": 1,
            "index_loaded_version": 0,
            "gallery_diverged": True,
        }


def test_health_url_target_parsing_defaults() -> None:
    postgres = _target_from_url("postgres", "postgresql+asyncpg://user:pass@db/attendance")
    redis = _target_from_url("redis", "redis://cache/0")

    assert (postgres.host, postgres.port) == ("db", 5432)
    assert (redis.host, redis.port) == ("cache", 6379)


def test_reachability_returns_false_for_closed_port() -> None:
    assert not _is_reachable(_target_from_url("redis", "redis://localhost:1/0"))
