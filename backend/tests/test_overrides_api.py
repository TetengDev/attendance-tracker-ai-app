"""Unit tests for the manual attendance overrides REST API router."""

from __future__ import annotations

import base64
import os
from datetime import date
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# Set up test environment variables
os.environ.setdefault(
    "BIOMETRIC_KEK",
    "kek.test:" + base64.urlsafe_b64encode(bytes([9]) * 32).decode().rstrip("="),
)
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://localhost:5432/attendance")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

from backend.app.api.common import authenticated_admin_user
from backend.app.attendance.decision_table import AttendanceStatus
from backend.app.db.session import get_session
from backend.app.main import create_app
from backend.app.models.admin import AdminRole, AdminUser
from backend.app.models.attendance import AttendanceOverride


class MockResult:
    """Mock result query stream returned by session execute."""

    def __init__(self, value: Any) -> None:
        self._value = value

    def scalars(self) -> MockResult:
        return self

    def all(self) -> list[Any]:
        if isinstance(self._value, list):
            return self._value
        return [self._value] if self._value is not None else []

    def scalar_one_or_none(self) -> Any:
        if isinstance(self._value, list):
            return self._value[0] if self._value else None
        return self._value

    def unique(self) -> MockResult:
        return self


class FakeSession:
    """Mock database transaction session."""

    def __init__(self, override: AttendanceOverride | None = None) -> None:
        self.override = override
        self.added: list[Any] = []
        self.deleted: list[Any] = []
        self.committed = 0

    async def execute(
        self,
        statement: Any,
        params: Any = None,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        sql = str(statement)
        if "FROM attendance_overrides" in sql:
            return MockResult(self.override)
        return MockResult(None)

    def add(self, instance: Any) -> None:
        self.added.append(instance)

    async def delete(self, instance: Any) -> None:
        self.deleted.append(instance)

    async def commit(self) -> None:
        self.committed += 1

    async def rollback(self) -> None:
        pass


def _admin_user(role: AdminRole = AdminRole.ADMIN) -> AdminUser:
    return AdminUser(
        id=UUID("00000000-0000-0000-0000-0000000000ad"),
        email="admin@example.test",
        display_name="Admin",
        password_hash="hash",
        role=role,
        is_active=True,
    )


@pytest.fixture
def app_with_override(monkeypatch: pytest.MonkeyPatch) -> tuple[FastAPI, FakeSession]:
    # Mock audit logger
    captured_audits: list[dict[str, Any]] = []

    async def fake_audit(*args: Any, **kwargs: Any) -> None:
        captured_audits.append(kwargs)

    monkeypatch.setattr("backend.app.api.overrides.audited_mutation", fake_audit)

    # Skip database operations in AuditMiddleware
    async def fake_append_entry(_entry: object) -> None:
        pass

    monkeypatch.setattr("backend.app.audit.middleware._append_entry", fake_append_entry)

    # Mock background resolver
    async def fake_resolve(session: Any, person_id: Any, business_date: Any, as_of: Any) -> None:
        pass

    monkeypatch.setattr("backend.app.attendance.resolver.resolve", fake_resolve)

    # Set up dirty flag capture
    dirty_flags: list[tuple[UUID, date]] = []

    class FakeRedisState:
        def set_dirty(self, person_id: UUID, business_date: date) -> None:
            dirty_flags.append((person_id, business_date))

    monkeypatch.setattr("backend.app.attendance.resolver.redis_resolver_state", FakeRedisState())

    # Build FastAPI
    app = create_app()
    session = FakeSession()
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[authenticated_admin_user] = lambda: _admin_user()

    return app, session


def test_create_override_success(app_with_override: tuple[FastAPI, FakeSession]) -> None:
    app, session = app_with_override
    person_id = uuid4()
    shift_id = uuid4()

    with TestClient(app) as client:
        response = client.post(
            "/api/attendance/overrides",
            headers={"x-admin-id": "00000000-0000-0000-0000-0000000000ad"},
            json={
                "person_id": str(person_id),
                "business_date": "2026-08-15",
                "shift_id": str(shift_id),
                "period_label": "day",
                "status": "excused",
                "reason": "Doctor visit",
            },
        )

    assert response.status_code == 201
    data = response.json()
    assert data["status"] == "excused"
    assert data["reason"] == "Doctor visit"
    assert len(session.added) == 1
    assert isinstance(session.added[0], AttendanceOverride)
    assert session.committed == 2  # Once for override save, once for resolved records save


def test_create_override_invalid_reason(app_with_override: tuple[FastAPI, FakeSession]) -> None:
    app, _session = app_with_override
    person_id = uuid4()
    shift_id = uuid4()

    with TestClient(app) as client:
        response = client.post(
            "/api/attendance/overrides",
            headers={"x-admin-id": "00000000-0000-0000-0000-0000000000ad"},
            json={
                "person_id": str(person_id),
                "business_date": "2026-08-15",
                "shift_id": str(shift_id),
                "period_label": "day",
                "status": "excused",
                "reason": "   ",  # Blank spaces reason check
            },
        )

    assert response.status_code == 422


def test_list_overrides(app_with_override: tuple[FastAPI, FakeSession]) -> None:
    app, session = app_with_override
    person_id = uuid4()
    shift_id = uuid4()

    override = AttendanceOverride(
        id=uuid4(),
        person_id=person_id,
        business_date=date(2026, 8, 15),
        shift_id=shift_id,
        period_label="day",
        status=AttendanceStatus.EXCUSED,
        reason="Doctor visit",
        actor_admin_id=UUID("00000000-0000-0000-0000-0000000000ad"),
    )
    session.override = override

    with TestClient(app) as client:
        response = client.get(
            "/api/attendance/overrides",
            headers={"x-admin-id": "00000000-0000-0000-0000-0000000000ad"},
            params={"person_id": str(person_id)},
        )

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["reason"] == "Doctor visit"


def test_delete_override(app_with_override: tuple[FastAPI, FakeSession]) -> None:
    app, session = app_with_override
    person_id = uuid4()
    shift_id = uuid4()
    override_id = uuid4()

    override = AttendanceOverride(
        id=override_id,
        person_id=person_id,
        business_date=date(2026, 8, 15),
        shift_id=shift_id,
        period_label="day",
        status=AttendanceStatus.EXCUSED,
        reason="Doctor visit",
        actor_admin_id=UUID("00000000-0000-0000-0000-0000000000ad"),
    )
    session.override = override

    with TestClient(app) as client:
        response = client.delete(
            f"/api/attendance/overrides/{override_id}",
            headers={"x-admin-id": "00000000-0000-0000-0000-0000000000ad"},
        )

    assert response.status_code == 204
    assert len(session.deleted) == 1
    assert session.deleted[0].id == override_id
    assert session.committed == 2
