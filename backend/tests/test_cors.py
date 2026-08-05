from __future__ import annotations

from fastapi.testclient import TestClient
from pytest import MonkeyPatch

from backend.app.config import get_settings
from backend.app.main import create_app


def test_cors_allows_configured_origins(monkeypatch: MonkeyPatch) -> None:
    # Clear cache and set custom allowed origins
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://localhost:5432/attendance")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("BIOMETRIC_KEK", "test-kek")
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "http://allowed.com,https://another-allowed.com")
    get_settings.cache_clear()

    app = create_app()
    with TestClient(app) as client:
        # Check allowed origin
        res = client.get("/health", headers={"Origin": "http://allowed.com"})
        assert res.status_code == 200
        assert res.headers.get("access-control-allow-origin") == "http://allowed.com"
        assert res.headers.get("access-control-allow-credentials") == "true"

        # Check another allowed origin
        res2 = client.get("/health", headers={"Origin": "https://another-allowed.com"})
        assert res2.status_code == 200
        assert res2.headers.get("access-control-allow-origin") == "https://another-allowed.com"

        # Check disallowed origin
        res3 = client.get("/health", headers={"Origin": "http://disallowed.com"})
        assert res3.status_code == 200
        assert "access-control-allow-origin" not in res3.headers


def test_cors_defaults_allow_local_dev_origins(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://localhost:5432/attendance")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("BIOMETRIC_KEK", "test-kek")
    monkeypatch.delenv("CORS_ALLOWED_ORIGINS", raising=False)
    get_settings.cache_clear()

    app = create_app()
    with TestClient(app) as client:
        for origin in [
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "http://localhost:5174",
            "http://127.0.0.1:5174",
        ]:
            res = client.get("/health", headers={"Origin": origin})
            assert res.status_code == 200
            assert res.headers.get("access-control-allow-origin") == origin
