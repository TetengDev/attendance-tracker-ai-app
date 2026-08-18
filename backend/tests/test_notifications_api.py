"""Unit tests for the notification rules, preferences, and unsubscribe REST APIs."""

from __future__ import annotations

import base64
import os
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
from backend.app.db.session import get_session
from backend.app.main import create_app
from backend.app.models.admin import AdminRole, AdminUser
from backend.app.models.notifications import NotificationRule
from backend.app.models.people import ContactChannel, Guardian, PersonGuardian


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

    def __init__(
        self,
        rule: NotificationRule | None = None,
        guardian: Guardian | None = None,
        pg_link: PersonGuardian | None = None,
    ) -> None:
        self.rule = rule
        self.guardian = guardian
        self.pg_link = pg_link
        self.added: list[Any] = []
        self.deleted: list[Any] = []
        self.committed = 0

    async def get(self, model: type, identifier: Any) -> Any | None:
        if model is NotificationRule:
            return self.rule if self.rule and self.rule.id == identifier else None
        if model is Guardian:
            return self.guardian if self.guardian and self.guardian.id == identifier else None
        return None

    async def execute(
        self,
        statement: Any,
        params: Any = None,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        sql = str(statement)
        if "FROM notification_rules" in sql:
            return MockResult([self.rule] if self.rule else [])
        if "FROM guardians" in sql:
            return MockResult([self.guardian] if self.guardian else [])
        if "FROM person_guardians" in sql:
            return MockResult([self.pg_link] if self.pg_link else [])
        return MockResult(None)

    def add(self, instance: Any) -> None:
        self.added.append(instance)

    async def delete(self, instance: Any) -> None:
        self.deleted.append(instance)

    async def commit(self) -> None:
        self.committed += 1

    async def flush(self) -> None:
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
def app_with_notifications(monkeypatch: pytest.MonkeyPatch) -> tuple[FastAPI, FakeSession]:
    # Mock audit logger
    async def fake_audit(*args: Any, **kwargs: Any) -> None:
        pass

    monkeypatch.setattr("backend.app.api.common.audited_mutation", fake_audit)
    monkeypatch.setattr("backend.app.audit.service.append_audit_entry", fake_audit)

    # Skip database operations in AuditMiddleware
    async def fake_append_entry(_entry: object) -> None:
        pass

    monkeypatch.setattr("backend.app.audit.middleware._append_entry", fake_append_entry)

    # Build FastAPI
    app = create_app()
    session = FakeSession()
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[authenticated_admin_user] = lambda: _admin_user()

    return app, session


def test_list_rules(app_with_notifications: tuple[FastAPI, FakeSession]) -> None:
    app, session = app_with_notifications
    rule = NotificationRule(
        id=uuid4(),
        trigger_status="absent",
        delay_minutes=15,
        channel=ContactChannel.SMS,
        template="Absence Alert",
        is_active=True,
    )
    session.rule = rule

    with TestClient(app) as client:
        response = client.get(
            "/api/notifications/rules",
            headers={"x-admin-id": "00000000-0000-0000-0000-0000000000ad"},
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["trigger_status"] == "absent"
        assert data[0]["delay_minutes"] == 15


def test_create_rule(app_with_notifications: tuple[FastAPI, FakeSession]) -> None:
    app, session = app_with_notifications

    with TestClient(app) as client:
        response = client.post(
            "/api/notifications/rules",
            headers={"x-admin-id": "00000000-0000-0000-0000-0000000000ad"},
            json={
                "trigger_status": "late",
                "delay_minutes": 5,
                "channel": "email",
                "template": "Hello {{ person_name }} is late",
                "is_active": True,
            },
        )
        assert response.status_code == 201
        data = response.json()
        assert data["trigger_status"] == "late"
        assert data["channel"] == "email"
        assert len(session.added) == 2
        rules = [r for r in session.added if isinstance(r, NotificationRule)]
        assert len(rules) == 1
        assert rules[0].trigger_status == "late"


def test_update_rule(app_with_notifications: tuple[FastAPI, FakeSession]) -> None:
    app, session = app_with_notifications
    rule = NotificationRule(
        id=uuid4(),
        trigger_status="absent",
        delay_minutes=15,
        channel=ContactChannel.SMS,
        template="Absence Alert",
        is_active=True,
    )
    session.rule = rule

    with TestClient(app) as client:
        response = client.put(
            f"/api/notifications/rules/{rule.id}",
            headers={"x-admin-id": "00000000-0000-0000-0000-0000000000ad"},
            json={
                "delay_minutes": 20,
                "template": "Updated Absence Alert",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["delay_minutes"] == 20
        assert data["template"] == "Updated Absence Alert"
        assert rule.delay_minutes == 20
        assert str(rule.template) == "Updated Absence Alert"


def test_delete_rule(app_with_notifications: tuple[FastAPI, FakeSession]) -> None:
    app, session = app_with_notifications
    rule = NotificationRule(
        id=uuid4(),
        trigger_status="absent",
        delay_minutes=15,
        channel=ContactChannel.SMS,
        template="Absence Alert",
        is_active=True,
    )
    session.rule = rule

    with TestClient(app) as client:
        response = client.delete(
            f"/api/notifications/rules/{rule.id}",
            headers={"x-admin-id": "00000000-0000-0000-0000-0000000000ad"},
        )
        assert response.status_code == 204
        assert len(session.deleted) == 1
        assert session.deleted[0] == rule


def test_get_preferences(app_with_notifications: tuple[FastAPI, FakeSession]) -> None:
    app, session = app_with_notifications
    guardian_id = uuid4()
    guardian = Guardian(
        id=guardian_id,
        display_name="Mr. Bob",
        preferred_channel=ContactChannel.SMS,
        phone="+639000000000",
    )
    pg_link = PersonGuardian(
        person_id=uuid4(),
        guardian_id=guardian_id,
        receives_attendance_alerts=True,
    )
    session.guardian = guardian
    session.pg_link = pg_link

    with TestClient(app) as client:
        response = client.get(
            f"/api/notifications/preferences/{guardian_id}",
            headers={"x-admin-id": "00000000-0000-0000-0000-0000000000ad"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["guardian_id"] == str(guardian_id)
        assert data["preferred_channel"] == "sms"
        assert data["receives_attendance_alerts"] is True


def test_update_preferences(app_with_notifications: tuple[FastAPI, FakeSession]) -> None:
    app, session = app_with_notifications
    guardian_id = uuid4()
    guardian = Guardian(
        id=guardian_id,
        display_name="Mr. Bob",
        preferred_channel=ContactChannel.SMS,
        phone="+639000000000",
    )
    pg_link = PersonGuardian(
        person_id=uuid4(),
        guardian_id=guardian_id,
        receives_attendance_alerts=True,
    )
    session.guardian = guardian
    session.pg_link = pg_link

    with TestClient(app) as client:
        response = client.patch(
            f"/api/notifications/preferences/{guardian_id}",
            headers={"x-admin-id": "00000000-0000-0000-0000-0000000000ad"},
            json={
                "preferred_channel": "email",
                "receives_attendance_alerts": False,
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["preferred_channel"] == "email"
        assert data["receives_attendance_alerts"] is False
        assert guardian.preferred_channel == ContactChannel.EMAIL
        assert pg_link.receives_attendance_alerts is False


def test_public_unsubscribe(app_with_notifications: tuple[FastAPI, FakeSession]) -> None:
    app, session = app_with_notifications
    guardian_id = uuid4()
    guardian = Guardian(
        id=guardian_id,
        display_name="Mr. Bob",
        preferred_channel=ContactChannel.SMS,
        phone="+639000000000",
    )
    pg_link = PersonGuardian(
        person_id=uuid4(),
        guardian_id=guardian_id,
        receives_attendance_alerts=True,
    )
    session.guardian = guardian
    session.pg_link = pg_link

    # Generate token
    from backend.app.notifications.service import generate_unsubscribe_token

    token = generate_unsubscribe_token(guardian_id)

    with TestClient(app) as client:
        response = client.get(f"/api/notifications/unsubscribe?token={token}")
        assert response.status_code == 200
        assert "successfully unsubscribed" in response.text
        assert guardian.preferred_channel == ContactChannel.NONE
        assert pg_link.receives_attendance_alerts is False
