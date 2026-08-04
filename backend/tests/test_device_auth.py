"""Unit and integration tests for device pairing, JWT exchange, and WebSocket security."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import jwt
import pytest
from fastapi.testclient import TestClient
from pytest import MonkeyPatch
from sqlalchemy.ext.asyncio import AsyncSession


def get_test_secret_key() -> str:
    """Retrieve the KEK configured in the current app settings."""
    return get_settings().biometric_kek.get_secret_value()


from backend.app.api.enrollment import get_face_engine, get_gallery_index
from backend.app.auth.device import (
    get_device_token_key,
    global_revocation_registry,
    hash_device_token,
    hash_pairing_code,
    issue_device_jwt,
)
from backend.app.config import get_settings
from backend.app.db.session import get_session
from backend.app.errors import ErrorCode
from backend.app.face.gallery import GalleryIndex
from backend.app.face.protocol import FakeFaceEngine
from backend.app.main import create_app
from backend.app.models.devices import Device, DeviceDirection, DeviceFormFactor, DeviceMode
from backend.app.models.settings import Setting, SettingScope

# ── Test Fixtures ────────────────────────────────────────────────────────────

DEVICE_ID = UUID("dddddddd-dddd-dddd-dddd-dddddddddddd")
LOCATION_ID = UUID("11111111-1111-1111-1111-111111111111")
ADMIN_USER_ID = UUID("88888888-8888-8888-8888-888888888888")
RAW_TOKEN = "test-long-lived-device-token-123456"


class MockAuditService:
    def __init__(self) -> None:
        self.entries: list[Any] = []

    async def append_audit_entry(self, session: Any, entry: Any) -> None:
        self.entries.append(entry)


class MockSession:
    def __init__(self) -> None:
        secret_key = get_test_secret_key()
        self.device = Device(
            id=DEVICE_ID,
            location_id=LOCATION_ID,
            mode=DeviceMode.FIXED,
            form_factor=DeviceFormFactor.TABLET,
            direction=DeviceDirection.BIDIRECTIONAL,
            token_hash=hash_device_token(RAW_TOKEN, get_device_token_key(secret_key)),
            token_display_prefix="tst_dev",
            allowed_cidrs=["127.0.0.1/32"],
            settings_override={},
        )
        self.added: list[Any] = []
        self.committed = False
        self.rolled_back = False

    async def get(self, model: type, identifier: Any) -> Any | None:
        if model is Device and identifier == DEVICE_ID:
            return self.device
        return None

    async def execute(self, statement: Any, params: dict[str, Any] | None = None) -> Any:
        sql = str(statement)

        class MockResult:
            def __init__(self, value: Any) -> None:
                self._value = value

            def scalar_one_or_none(self) -> Any:
                return self._value

            def scalars(self) -> MockResult:
                return self

            def all(self) -> list[Any]:
                if isinstance(self._value, list):
                    return self._value
                return [self._value] if self._value is not None else []

        if "FROM devices" in sql:
            # Match by pairing code
            if self.device.pairing_code_hash is not None:
                # Mock the expiry check from SQL
                now = datetime.now(tz=UTC)
                if (
                    self.device.pairing_code_expires_at is not None
                    and self.device.pairing_code_expires_at > now
                ):
                    return MockResult(self.device)
            return MockResult(None)

        if "FROM settings_versions" in sql:
            return MockResult(1)

        if "FROM settings" in sql:
            return MockResult([
                Setting(
                    id=uuid4(),
                    key="liveness.mode",
                    scope=SettingScope.ORG,
                    scope_id=None,
                    value="enforce",
                    version=1,
                )
            ])

        return MockResult(None)

    def add(self, entity: Any) -> None:
        self.added.append(entity)

    async def commit(self) -> None:
        self.committed = True

    async def rollback(self) -> None:
        self.rolled_back = True

    async def flush(self) -> None:
        pass


@pytest.fixture
def mock_session() -> MockSession:
    return MockSession()


@pytest.fixture
def client(
    monkeypatch: MonkeyPatch,
    mock_session: MockSession,
) -> TestClient:
    async def async_none(*a: Any, **k: Any) -> None:
        pass

    # Bypass audit logging dependency
    monkeypatch.setattr("backend.app.api.common.audited_mutation", lambda *a, **k: None)
    monkeypatch.setattr("backend.app.audit.middleware._append_entry", async_none)
    
    # Configure JWT_SECRET to match current BIOMETRIC_KEK
    secret_key = get_test_secret_key()
    monkeypatch.setenv("JWT_SECRET", secret_key)
    get_settings.cache_clear()

    async def fake_get_session() -> AsyncIterator[AsyncSession]:
        yield mock_session  # type: ignore[misc]

    async def fake_admin_user() -> Any:
        class FakeAdmin:
            id = ADMIN_USER_ID
            role = "admin"
            is_active = True
        return FakeAdmin()

    # Import authenticated_admin_user from common to override it
    from backend.app.api.common import authenticated_admin_user

    app = create_app()
    app.dependency_overrides[get_session] = fake_get_session
    app.dependency_overrides[get_face_engine] = lambda: FakeFaceEngine()
    app.dependency_overrides[get_gallery_index] = lambda: GalleryIndex()
    app.dependency_overrides[authenticated_admin_user] = fake_admin_user
    return TestClient(app)


# ── Test Cases ────────────────────────────────────────────────────────────────

class TestDevicePairingFlow:
    def test_generate_pairing_code_success(self, client: TestClient, mock_session: MockSession) -> None:
        response = client.post(
            f"/api/devices/{DEVICE_ID}/pairing-code",
            headers={"x-admin-id": str(ADMIN_USER_ID)},
        )
        assert response.status_code == 201
        data = response.json()
        assert "pairing_code" in data
        assert "expires_at" in data
        assert len(data["pairing_code"]) == 8
        assert mock_session.committed is True

        # Verify it updated the DB device record
        assert mock_session.device.pairing_code_hash == hash_pairing_code(data["pairing_code"])
        assert mock_session.device.pairing_code_expires_at is not None

    def test_pair_device_success(self, client: TestClient, mock_session: MockSession) -> None:
        # 1. Setup pairing code on device
        pairing_code = "ABCDEFGH"
        mock_session.device.pairing_code_hash = hash_pairing_code(pairing_code)
        mock_session.device.pairing_code_expires_at = datetime.now(tz=UTC) + timedelta(minutes=15)

        # 2. Call pair endpoint
        response = client.post("/api/kiosk/pair", json={"pairing_code": pairing_code})
        assert response.status_code == 200
        data = response.json()
        assert data["device_id"] == str(DEVICE_ID)
        assert "device_token" in data
        assert len(data["device_token"]) >= 32

        # 3. Verify single-use: pairing code is cleared
        assert mock_session.device.pairing_code_hash is None
        assert mock_session.device.pairing_code_expires_at is None
        assert mock_session.device.token_display_prefix == data["device_token"][:6]
        assert mock_session.committed is True

    def test_pair_device_invalid_code(self, client: TestClient, mock_session: MockSession) -> None:
        response = client.post("/api/kiosk/pair", json={"pairing_code": "INVALIDD"})
        assert response.status_code == 401, response.json()
        assert response.json()["detail"]["error"]["code"] == ErrorCode.DEVICE_REVOKED.value

    def test_pair_device_expired_code(self, client: TestClient, mock_session: MockSession) -> None:
        pairing_code = "EXPIREDD"
        mock_session.device.pairing_code_hash = hash_pairing_code(pairing_code)
        mock_session.device.pairing_code_expires_at = datetime.now(tz=UTC) - timedelta(seconds=1)

        response = client.post("/api/kiosk/pair", json={"pairing_code": pairing_code})
        assert response.status_code == 401, response.json()
        assert response.json()["detail"]["error"]["code"] == ErrorCode.DEVICE_REVOKED.value


class TestDeviceTokenRefresh:
    def test_refresh_token_success(self, client: TestClient, mock_session: MockSession) -> None:
        response = client.post(
            "/api/kiosk/token",
            json={"device_id": str(DEVICE_ID), "device_token": RAW_TOKEN},
        )
        assert response.status_code == 200, response.json()
        data = response.json()
        assert "device_token_jwt" in data

        # Decode JWT and verify claims
        secret_key = get_test_secret_key()
        claims = jwt.decode(data["device_token_jwt"], secret_key, algorithms=["HS256"])
        assert claims["sub"] == str(DEVICE_ID)
        assert claims["token"] == RAW_TOKEN
        assert claims["type"] == "scan_session"
        assert claims["exp"] > int(datetime.now(tz=UTC).timestamp())

    def test_refresh_token_revoked_device(self, client: TestClient, mock_session: MockSession) -> None:
        global_revocation_registry.revoke(DEVICE_ID)
        try:
            response = client.post(
                "/api/kiosk/token",
                json={"device_id": str(DEVICE_ID), "device_token": RAW_TOKEN},
            )
            assert response.status_code == 401, response.json()
            assert response.json()["detail"]["error"]["code"] == ErrorCode.DEVICE_REVOKED.value
        finally:
            global_revocation_registry.reset()

    def test_refresh_token_invalid_credentials(self, client: TestClient, mock_session: MockSession) -> None:
        response = client.post(
            "/api/kiosk/token",
            json={"device_id": str(DEVICE_ID), "device_token": "wrong-token"},
        )
        assert response.status_code == 401, response.json()
        assert response.json()["detail"]["error"]["code"] == ErrorCode.DEVICE_REVOKED.value


class TestWebSocketSecurity:
    def test_handshake_blocks_non_allowed_cidr(self, client: TestClient, mock_session: MockSession) -> None:
        # Configure allowed CIDRs to block localhost
        mock_session.device.allowed_cidrs = ["192.168.1.1/32"]

        secret_key = get_test_secret_key()
        jwt_token = issue_device_jwt(DEVICE_ID, RAW_TOKEN, secret_key)

        with client.websocket_connect("/api/kiosk/ws") as ws:
            ws.send_json(
                {
                    "type": "hello",
                    "device_token_jwt": jwt_token,
                    "app_version": "1.0.0",
                }
            )
            err = ws.receive_json()
            assert err["type"] == "error"
            assert err["error"]["code"] == ErrorCode.DEVICE_REVOKED.value

    def test_handshake_blocks_revoked_device(self, client: TestClient) -> None:
        global_revocation_registry.revoke(DEVICE_ID)
        secret_key = get_test_secret_key()
        jwt_token = issue_device_jwt(DEVICE_ID, RAW_TOKEN, secret_key)
        try:
            with client.websocket_connect("/api/kiosk/ws") as ws:
                ws.send_json(
                    {
                        "type": "hello",
                        "device_token_jwt": jwt_token,
                        "app_version": "1.0.0",
                    }
                )
                err = ws.receive_json()
                assert err["type"] == "error"
                assert err["error"]["code"] == ErrorCode.DEVICE_REVOKED.value
        finally:
            global_revocation_registry.reset()

    def test_heartbeat_disconnects_revoked_device(self, client: TestClient) -> None:
        secret_key = get_test_secret_key()
        jwt_token = issue_device_jwt(DEVICE_ID, RAW_TOKEN, secret_key)

        with client.websocket_connect("/api/kiosk/ws") as ws:
            ws.send_json(
                {
                    "type": "hello",
                    "device_token_jwt": jwt_token,
                    "app_version": "1.0.0",
                }
            )
            ws.receive_json()  # ready
            ws.receive_json()  # settings_push

            # Revoke device now
            global_revocation_registry.revoke(DEVICE_ID)
            try:
                # Send heartbeat
                ws.send_json(
                    {
                        "type": "heartbeat",
                        "fps": 30.0,
                        "queue_depth": 0,
                        "error_count": 0,
                        "clock_skew_ms": 12,
                    }
                )
                # Should receive error and disconnect
                err = ws.receive_json()
                assert err["type"] == "error"
                assert err["error"]["code"] == ErrorCode.DEVICE_REVOKED.value
            finally:
                global_revocation_registry.reset()
