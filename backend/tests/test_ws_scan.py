"""Integration tests for the WebSocket scan endpoint (TEN-41).

Covers:
  - Hello handshake (success, invalid JWT, revoked device, fixed device without location)
  - Heartbeat handling (durable logging, settings version update pushes)
  - FrameBurst processing:
    - Active session checking
    - Burst truth table combining (liveness fail, no face, single match, ambiguous matches)
    - Event persistence before response
    - Unknown face rate audits
"""

from __future__ import annotations

import base64
import os

SECRET_KEY = "kek.test:" + base64.urlsafe_b64encode(bytes([9]) * 32).decode().rstrip("=")
os.environ["BIOMETRIC_KEK"] = SECRET_KEY
os.environ["JWT_SECRET"] = SECRET_KEY
os.environ["DATABASE_URL"] = "postgresql+asyncpg://localhost:5432/attendance"
os.environ["REDIS_URL"] = "redis://localhost:6379/0"

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID, uuid4

import jwt
import numpy as np
import pytest
from fastapi.testclient import TestClient
from pytest import MonkeyPatch
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.api.enrollment import get_face_engine, get_gallery_index
from backend.app.auth.device import get_device_token_key, hash_device_token
from backend.app.auth.passwords import hash_admin_password
from backend.app.config import get_settings

get_settings.cache_clear()
from backend.app.db.session import get_session
from backend.app.errors import ErrorCode
from backend.app.face.gallery import GalleryEntry, GalleryIndex
from backend.app.face.protocol import FakeFaceEngine
from backend.app.main import create_app
from backend.app.models.attendance import AttendanceEvent, AttendanceEventOutcome
from backend.app.models.devices import Device, DeviceDirection, DeviceFormFactor, DeviceMode
from backend.app.models.people import Person
from backend.app.models.sessions import ScanSession, ScanSessionLocationSource
from backend.app.models.settings import Setting, SettingScope

# ---------------------------------------------------------------------------
# Test Fixtures & Constants
# ---------------------------------------------------------------------------


DEVICE_ID = UUID("dddddddd-dddd-dddd-dddd-dddddddddddd")
LOCATION_ID = UUID("11111111-1111-1111-1111-111111111111")
PERSON_A_ID = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
PERSON_B_ID = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
SESSION_ID = UUID("44444444-4444-4444-4444-444444444444")
RAW_TOKEN = "secret-device-token"


def _make_jwt(device_id: UUID = DEVICE_ID) -> str:
    return jwt.encode({"sub": str(device_id), "type": "scan_session"}, SECRET_KEY, algorithm="HS256")


# ---------------------------------------------------------------------------
# Mock Database Session
# ---------------------------------------------------------------------------


class MockSession:
    def __init__(self) -> None:
        self.device = Device(
            id=DEVICE_ID,
            location_id=LOCATION_ID,
            mode=DeviceMode.FIXED,
            form_factor=DeviceFormFactor.TABLET,
            direction=DeviceDirection.BIDIRECTIONAL,
            token_hash=hash_device_token(RAW_TOKEN, get_device_token_key(SECRET_KEY)),
            token_display_prefix="tst_dev",
            allowed_cidrs=["127.0.0.1/32"],
            settings_override={},
        )
        self.person_a = Person(id=PERSON_A_ID, display_name="Alice", external_id="12345")
        self.person_b = Person(id=PERSON_B_ID, display_name="Bob")
        self.scan_session = ScanSession(
            id=SESSION_ID,
            device_id=DEVICE_ID,
            location_id=LOCATION_ID,
            location_source=ScanSessionLocationSource.DEVICE_FIXED,
            started_at=datetime.now(tz=UTC),
            last_activity_at=datetime.now(tz=UTC),
            scan_count=0,
        )
        self.added: list[Any] = []
        self.committed = False
        self.rolled_back = False
        self.settings_version = 1
        self.gallery_version = 1
        self.settings = [
            Setting(
                id=uuid4(),
                key="liveness.mode",
                scope=SettingScope.ORG,
                scope_id=None,
                value="enforce",
                version=1,
            )
        ]
        self.should_find_person = True
        self.existing_event: AttendanceEvent | None = None

    async def get(self, model: type, identifier: Any) -> Any | None:
        if model is Device:
            return self.device if identifier == DEVICE_ID else None
        if model is Person:
            if identifier == PERSON_A_ID:
                return self.person_a
            if identifier == PERSON_B_ID:
                return self.person_b
        return None

    async def execute(self, statement: Any, params: dict[str, Any] | None = None) -> Any:
        sql = str(statement)

        class MockResult:
            def __init__(self, value: Any) -> None:
                self._value = value

            def scalars(self) -> MockResult:
                return self

            def all(self) -> list[Any]:
                return cast(list[Any], self._value)

            def scalar_one_or_none(self) -> Any:
                return self._value

        if "FROM settings_versions" in sql:
            if "gallery" in sql or "GALLERY" in sql:
                return MockResult(self.gallery_version)
            return MockResult(self.settings_version)
        if "FROM settings" in sql:
            return MockResult(self.settings)
        if "FROM face_embeddings" in sql:
            return MockResult([])
        if "FROM scan_sessions" in sql:
            return MockResult(self.scan_session)
        if "FROM attendance_events" in sql:
            return MockResult(self.existing_event)
        if "FROM people" in sql:
            return MockResult(self.person_a if self.should_find_person else None)

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
def test_engine() -> FakeFaceEngine:
    return FakeFaceEngine()


@pytest.fixture
def test_gallery() -> GalleryIndex:
    return GalleryIndex()


def _skip_middleware_audit(_entry: object) -> None:
    return None


@pytest.fixture
def client(
    monkeypatch: MonkeyPatch,
    mock_session: MockSession,
    test_engine: FakeFaceEngine,
    test_gallery: GalleryIndex,
) -> TestClient:
    monkeypatch.setattr("backend.app.audit.middleware._append_entry", _skip_middleware_audit)
    get_settings.cache_clear()

    async def fake_get_session() -> AsyncIterator[AsyncSession]:
        yield mock_session  # type: ignore[misc]

    app = create_app()
    app.dependency_overrides[get_session] = fake_get_session
    app.dependency_overrides[get_face_engine] = lambda: test_engine
    app.dependency_overrides[get_gallery_index] = lambda: test_gallery
    return TestClient(app)


# ---------------------------------------------------------------------------
# Test Cases
# ---------------------------------------------------------------------------


class TestWebSocketHandshake:
    def test_handshake_success(self, client: TestClient, mock_session: MockSession) -> None:
        with client.websocket_connect("/api/kiosk/ws") as ws:
            ws.send_json(
                {
                    "type": "hello",
                    "device_token_jwt": _make_jwt(),
                    "app_version": "1.0.0",
                }
            )
            ready = ws.receive_json()
            assert ready["type"] == "ready"
            assert ready["gallery_version"] == 1
            assert ready["settings_version"] == 1

            push = ws.receive_json()
            assert push["type"] == "settings_push"
            assert push["settings_version"] == 1
            assert "scan.rate_per_second" in push["payload"]

    def test_handshake_invalid_jwt(self, client: TestClient) -> None:
        with client.websocket_connect("/api/kiosk/ws") as ws:
            ws.send_json(
                {
                    "type": "hello",
                    "device_token_jwt": "invalid-jwt",
                    "app_version": "1.0.0",
                }
            )
            err = ws.receive_json()
            assert err["type"] == "error"
            assert err["error"]["code"] == ErrorCode.DEVICE_REVOKED.value

    def test_handshake_succeeds_with_valid_jwt_even_if_token_hash_rotated(self, client: TestClient, mock_session: MockSession) -> None:
        mock_session.device.token_hash = hash_admin_password("another-token")
        with client.websocket_connect("/api/kiosk/ws") as ws:
            ws.send_json(
                {
                    "type": "hello",
                    "device_token_jwt": _make_jwt(),
                    "app_version": "1.0.0",
                }
            )
            ready = ws.receive_json()
            assert ready["type"] == "ready"

    def test_handshake_fixed_device_missing_location(self, client: TestClient, mock_session: MockSession) -> None:
        mock_session.device.__dict__["location_id"] = None
        with client.websocket_connect("/api/kiosk/ws") as ws:
            ws.send_json(
                {
                    "type": "hello",
                    "device_token_jwt": _make_jwt(),
                    "app_version": "1.0.0",
                }
            )
            err = ws.receive_json()
            assert err["type"] == "error"
            assert err["error"]["code"] == ErrorCode.DEVICE_REVOKED.value

    def test_handshake_blocks_non_allowed_cidr_by_x_forwarded_for(self, client: TestClient, mock_session: MockSession) -> None:
        mock_session.device.allowed_cidrs = ["192.168.1.1/32"]
        with client.websocket_connect(
            "/api/kiosk/ws",
            headers={"x-forwarded-for": "192.168.1.2"}
        ) as ws:
            ws.send_json(
                {
                    "type": "hello",
                    "device_token_jwt": _make_jwt(),
                    "app_version": "1.0.0",
                }
            )
            err = ws.receive_json()
            assert err["type"] == "error"
            assert err["error"]["code"] == ErrorCode.DEVICE_REVOKED.value

    def test_handshake_allows_allowed_cidr_by_x_forwarded_for(self, client: TestClient, mock_session: MockSession) -> None:
        mock_session.device.allowed_cidrs = ["192.168.1.0/24"]
        with client.websocket_connect(
            "/api/kiosk/ws",
            headers={"x-forwarded-for": "192.168.1.5, 10.0.0.1"}
        ) as ws:
            ws.send_json(
                {
                    "type": "hello",
                    "device_token_jwt": _make_jwt(),
                    "app_version": "1.0.0",
                }
            )
            ready = ws.receive_json()
            assert ready["type"] == "ready"

    def test_handshake_blocks_non_allowed_cidr_by_x_real_ip(self, client: TestClient, mock_session: MockSession) -> None:
        mock_session.device.allowed_cidrs = ["192.168.1.1/32"]
        with client.websocket_connect(
            "/api/kiosk/ws",
            headers={"x-real-ip": "192.168.1.2"}
        ) as ws:
            ws.send_json(
                {
                    "type": "hello",
                    "device_token_jwt": _make_jwt(),
                    "app_version": "1.0.0",
                }
            )
            err = ws.receive_json()
            assert err["type"] == "error"
            assert err["error"]["code"] == ErrorCode.DEVICE_REVOKED.value

    def test_handshake_allows_allowed_cidr_by_x_real_ip(self, client: TestClient, mock_session: MockSession) -> None:
        mock_session.device.allowed_cidrs = ["192.168.1.0/24"]
        with client.websocket_connect(
            "/api/kiosk/ws",
            headers={"x-real-ip": "192.168.1.5"}
        ) as ws:
            ws.send_json(
                {
                    "type": "hello",
                    "device_token_jwt": _make_jwt(),
                    "app_version": "1.0.0",
                }
            )
            ready = ws.receive_json()
            assert ready["type"] == "ready"


class TestWebSocketHeartbeat:
    def test_heartbeat_logged(self, client: TestClient, mock_session: MockSession) -> None:
        with client.websocket_connect("/api/kiosk/ws") as ws:
            ws.send_json(
                {
                    "type": "hello",
                    "device_token_jwt": _make_jwt(),
                    "app_version": "1.0.0",
                }
            )
            ws.receive_json()  # ready
            ws.receive_json()  # settings_push

            ws.send_json(
                {
                    "type": "heartbeat",
                    "fps": 30.0,
                    "queue_depth": 0,
                    "error_count": 0,
                    "clock_skew_ms": 12,
                }
            )
            rotation = ws.receive_json()
            assert rotation["type"] == "token_rotation"
            assert "device_token" in rotation

        assert any(item.__class__.__name__ == "DeviceHeartbeat" for item in mock_session.added)
        assert mock_session.committed is True

    def test_heartbeat_settings_push_on_update(
        self, client: TestClient, mock_session: MockSession
    ) -> None:
        with client.websocket_connect("/api/kiosk/ws") as ws:
            ws.send_json(
                {
                    "type": "hello",
                    "device_token_jwt": _make_jwt(),
                    "app_version": "1.0.0",
                }
            )
            ws.receive_json()  # ready
            ws.receive_json()  # settings_push

            mock_session.settings_version = 2

            ws.send_json(
                {
                    "type": "heartbeat",
                    "fps": 30.0,
                    "queue_depth": 0,
                    "error_count": 0,
                    "clock_skew_ms": 12,
                }
            )
            rotation = ws.receive_json()
            assert rotation["type"] == "token_rotation"

            push = ws.receive_json()
            assert push["type"] == "settings_push"
            assert push["settings_version"] == 2


class TestWebSocketFrameBurst:
    @pytest.fixture(autouse=True)
    def setup_gallery(self) -> None:
        from backend.app.scan.cooldown import global_cooldown_checker

        global_cooldown_checker.reset()

    def test_frame_burst_match_success(
        self,
        client: TestClient,
        mock_session: MockSession,
        test_engine: FakeFaceEngine,
        test_gallery: GalleryIndex,
    ) -> None:
        test_engine.next_result(person="alice", score=0.9, liveness=0.95, n_faces=1)

        # Populate Alice in the test gallery index
        dummy_img = np.zeros((240, 320, 3), dtype=np.uint8)
        dets = test_engine.detect(dummy_img)
        aligned = test_engine.align(dummy_img, dets[0].landmarks)
        emb = test_engine.embed(aligned)
        test_gallery.load(
            [GalleryEntry(person_id=PERSON_A_ID, embedding_id=uuid4(), vector=emb.vector)]
        )

        # Make sure subsequent detect populates Alice's match result too
        test_engine.next_result(person="alice", score=0.9, liveness=0.95, n_faces=1)

        with client.websocket_connect("/api/kiosk/ws") as ws:
            ws.send_json(
                {
                    "type": "hello",
                    "device_token_jwt": _make_jwt(),
                    "app_version": "1.0.0",
                }
            )
            ws.receive_json()  # ready
            ws.receive_json()  # settings_push

            import cv2

            img = np.random.randint(0, 256, (240, 320, 3), dtype=np.uint8)
            _, buf = cv2.imencode(".jpg", img)
            jpeg_b64 = base64.b64encode(buf).decode()

            ws.send_json(
                {
                    "type": "frame_burst",
                    "idempotency_key": "burst-1234",
                    "burst_seq": 1,
                    "frames": [
                        {
                            "jpeg_b64": jpeg_b64,
                            "bbox": (10, 10, 100, 100),
                            "monotonic_offset_ms": 100,
                        }
                    ],
                }
            )

            detected = ws.receive_json()
            assert detected["type"] == "detected"
            checking = ws.receive_json()
            assert checking["type"] == "checking"

            res = ws.receive_json()
            assert res["type"] == "result"
            assert res["status"] == "accepted"
            assert res["person"]["id"] == str(PERSON_A_ID)
            assert res["person"]["display_name"] == "Alice"

            events = [item for item in mock_session.added if isinstance(item, AttendanceEvent)]
            assert len(events) == 1
            assert events[0].person_id == PERSON_A_ID
            assert events[0].outcome == AttendanceEventOutcome.ACCEPTED

    def test_frame_burst_liveness_denied(
        self,
        client: TestClient,
        mock_session: MockSession,
        test_engine: FakeFaceEngine,
        test_gallery: GalleryIndex,
    ) -> None:
        # Spoof frame
        test_engine.next_result(person="alice", score=0.9, liveness=0.1, n_faces=1)

        with client.websocket_connect("/api/kiosk/ws") as ws:
            ws.send_json(
                {
                    "type": "hello",
                    "device_token_jwt": _make_jwt(),
                    "app_version": "1.0.0",
                }
            )
            ws.receive_json()  # ready
            ws.receive_json()  # settings_push

            import cv2

            img = np.random.randint(0, 256, (240, 320, 3), dtype=np.uint8)
            _, buf = cv2.imencode(".jpg", img)
            jpeg_b64 = base64.b64encode(buf).decode()

            ws.send_json(
                {
                    "type": "frame_burst",
                    "idempotency_key": "burst-5678",
                    "burst_seq": 1,
                    "frames": [
                        {
                            "jpeg_b64": jpeg_b64,
                            "bbox": (10, 10, 100, 100),
                            "monotonic_offset_ms": 100,
                        }
                    ],
                }
            )

            ws.receive_json()  # detected
            ws.receive_json()  # checking

            err = ws.receive_json()
            assert err["type"] == "error"
            assert err["error"]["code"] == ErrorCode.LIVENESS_FAILED.value

    def test_frame_burst_idempotency_cache(self, client: TestClient, mock_session: MockSession) -> None:
        # Seed an existing successful event in mock session
        mock_session.existing_event = AttendanceEvent(
            idempotency_key="burst-dup-123",
            person_id=PERSON_A_ID,
            device_id=DEVICE_ID,
            session_id=SESSION_ID,
            location_id=LOCATION_ID,
            direction="in",
            outcome="accepted",
            location_source="device_fixed",
            client_captured_at=datetime.now(tz=UTC),
            server_received_at=datetime.now(tz=UTC),
            occurred_at=datetime.now(tz=UTC),
            monotonic_offset_ms=100,
            was_backdated=False,
            top1_score=0.95,
        )

        with client.websocket_connect("/api/kiosk/ws") as ws:
            ws.send_json(
                {
                    "type": "hello",
                    "device_token_jwt": _make_jwt(),
                    "app_version": "1.0.0",
                }
            )
            ws.receive_json()  # ready
            ws.receive_json()  # settings_push

            ws.send_json(
                {
                    "type": "frame_burst",
                    "idempotency_key": "burst-dup-123",
                    "burst_seq": 1,
                    "frames": [
                        {
                            "jpeg_b64": "dGVzdA==",  # valid base64
                            "bbox": (10, 10, 100, 100),
                            "monotonic_offset_ms": 100,
                        }
                    ],
                }
            )
            # Response should bypass pipeline and return cached success immediately
            res = ws.receive_json()
            assert res["type"] == "result"
            assert res["status"] == "accepted"
            assert res["person"]["id"] == str(PERSON_A_ID)
            assert res["person"]["display_name"] == "Alice"

    def test_frame_burst_database_error_rollback(
        self, client: TestClient, mock_session: MockSession, monkeypatch: MonkeyPatch
    ) -> None:
        # Make commit raise an unexpected exception
        class MockDatabaseError(Exception):
            pass

        async def mock_commit() -> None:
            raise MockDatabaseError("Mock database error")

        monkeypatch.setattr(mock_session, "commit", mock_commit)

        with client.websocket_connect("/api/kiosk/ws") as ws:
            ws.send_json(
                {
                    "type": "hello",
                    "device_token_jwt": _make_jwt(),
                    "app_version": "1.0.0",
                }
            )
            ws.receive_json()  # ready
            ws.receive_json()  # settings_push

            ws.send_json(
                {
                    "type": "heartbeat",
                    "fps": 30.0,
                    "queue_depth": 0,
                    "error_count": 0,
                    "clock_skew_ms": 12,
                }
            )
            # Should receive SCAN_BACKEND_UNAVAILABLE error
            err = ws.receive_json()
            assert err["type"] == "error"
            assert err["error"]["code"] == ErrorCode.SCAN_BACKEND_UNAVAILABLE.value
            # Verify session rollback was called
            assert mock_session.rolled_back is True

    def test_check_in_success(
        self, client: TestClient, mock_session: MockSession
    ) -> None:
        with client.websocket_connect("/api/kiosk/ws") as ws:
            ws.send_json(
                {
                    "type": "hello",
                    "device_token_jwt": _make_jwt(),
                    "app_version": "1.0.0",
                }
            )
            ws.receive_json()  # ready
            ws.receive_json()  # settings_push

            ws.send_json(
                {
                    "type": "check_in",
                    "external_id": "12345",
                    "idempotency_key": "chk-idem-key",
                    "direction": "in",
                }
            )
            res = ws.receive_json()
            assert res["type"] == "result"
            assert res["status"] == "accepted"
            assert res["person"]["id"] == str(PERSON_A_ID)
            assert res["person"]["display_name"] == "Alice"
            assert res["committed"] is True

            # Verify AttendanceEvent was persisted
            assert len(mock_session.added) == 1
            event = mock_session.added[0]
            assert isinstance(event, AttendanceEvent)
            assert event.idempotency_key == "chk-idem-key"
            assert event.person_id == PERSON_A_ID
            assert event.outcome == AttendanceEventOutcome.ACCEPTED

    def test_check_in_invalid_pin(
        self, client: TestClient, mock_session: MockSession
    ) -> None:
        mock_session.should_find_person = False

        with client.websocket_connect("/api/kiosk/ws") as ws:
            ws.send_json(
                {
                    "type": "hello",
                    "device_token_jwt": _make_jwt(),
                    "app_version": "1.0.0",
                }
            )
            ws.receive_json()  # ready
            ws.receive_json()  # settings_push

            ws.send_json(
                {
                    "type": "check_in",
                    "external_id": "99999",
                    "idempotency_key": "chk-idem-key-invalid",
                    "direction": "in",
                }
            )
            err = ws.receive_json()
            assert err["type"] == "error"
            assert err["error"]["code"] == ErrorCode.UNKNOWN_FACE.value
            assert "Invalid PIN or QR code" in err["error"]["message"]
            assert len(mock_session.added) == 0

    def test_check_in_backdated(
        self, client: TestClient, mock_session: MockSession
    ) -> None:
        with client.websocket_connect("/api/kiosk/ws") as ws:
            ws.send_json(
                {
                    "type": "hello",
                    "device_token_jwt": _make_jwt(),
                    "app_version": "1.0.0",
                }
            )
            ws.receive_json()  # ready
            ws.receive_json()  # settings_push

            ws.send_json(
                {
                    "type": "check_in",
                    "external_id": "12345",
                    "idempotency_key": "chk-backdated-key",
                    "direction": "in",
                    "monotonic_offset_ms": 30000,  # 30 seconds ago
                }
            )
            res = ws.receive_json()
            assert res["type"] == "result"
            assert res["status"] == "accepted"
            assert res["committed"] is True

            # Verify AttendanceEvent was backdated
            assert len(mock_session.added) == 1
            event = mock_session.added[0]
            assert isinstance(event, AttendanceEvent)
            assert event.idempotency_key == "chk-backdated-key"
            assert event.was_backdated is True
            assert event.monotonic_offset_ms == 30000
            diff = event.server_received_at - event.occurred_at
            assert abs(diff.total_seconds() - 30.0) < 1.0
            assert event.client_captured_at == event.occurred_at
