from __future__ import annotations

import typing
from unittest.mock import patch

from fastapi.testclient import TestClient
from pytest import MonkeyPatch

from backend.app.config import get_settings
from backend.app.main import create_app


def test_log_kiosk_message_success(monkeypatch: MonkeyPatch) -> None:
    # Set settings variables
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://localhost:5432/attendance")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("BIOMETRIC_KEK", "test-kek")
    get_settings.cache_clear()

    # Mock audit middleware db call
    async def fake_append(*args: typing.Any, **kwargs: typing.Any) -> None:
        pass
    monkeypatch.setattr("backend.app.audit.middleware.append_audit_entry", fake_append)

    app = create_app()
    with TestClient(app) as client, patch("backend.app.main.logger") as mock_logger:
        response = client.post(
            "/api/kiosk/logs",
            json={"message": "Test message\nwith injection attempt\r"},
        )
        assert response.status_code == 204
        mock_logger.info.assert_called_once_with("[CLIENT] Test message\\nwith injection attempt\\r")


def test_log_kiosk_message_truncation(monkeypatch: MonkeyPatch) -> None:
    # Set settings variables
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://localhost:5432/attendance")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("BIOMETRIC_KEK", "test-kek")
    get_settings.cache_clear()

    # Mock audit middleware db call
    async def fake_append(*args: typing.Any, **kwargs: typing.Any) -> None:
        pass
    monkeypatch.setattr("backend.app.audit.middleware.append_audit_entry", fake_append)

    app = create_app()
    with TestClient(app) as client, patch("backend.app.main.logger") as mock_logger:
        long_msg = "A" * 600
        response = client.post(
            "/api/kiosk/logs",
            json={"message": long_msg},
        )
        assert response.status_code == 204

        logged_arg = mock_logger.info.call_args[0][0]
        assert len(logged_arg) == 500 + len("[CLIENT] ")
        assert logged_arg == f"[CLIENT] {'A' * 500}"
