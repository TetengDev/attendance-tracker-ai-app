from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import cast
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pytest import MonkeyPatch
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.api.common import RequestActor, authenticated_admin_user
from backend.app.api.groups import get_groups_service
from backend.app.api.people import get_people_service
from backend.app.api.people_merge import get_people_merge_service
from backend.app.api.sessions import get_sessions_service
from backend.app.config import get_settings
from backend.app.db.session import get_session
from backend.app.main import create_app
from backend.app.models.admin import AdminRole, AdminUser
from backend.app.models.people import Group, GroupKind, Person, PersonKind
from backend.app.models.sessions import ScanSession, ScanSessionEndReason, ScanSessionLocationSource
from backend.app.people.merge import PersonMergeSummary


class FakeSession:
    committed = False
    rolled_back = False

    async def commit(self) -> None:
        self.committed = True

    async def rollback(self) -> None:
        self.rolled_back = True


async def fake_session() -> AsyncIterator[AsyncSession]:
    yield FakeSession()  # type: ignore[misc]


async def _skip_middleware_audit(_entry: object) -> None:
    return None


def _admin_user(
    role: AdminRole = AdminRole.ADMIN, *, scope_group_ids: list[UUID] | None = None
) -> AdminUser:
    return AdminUser(
        id=UUID("00000000-0000-0000-0000-0000000000ad"),
        email="admin@example.test",
        display_name="Admin",
        password_hash="hash",
        role=role,
        scope_group_ids=scope_group_ids or [],
        is_active=True,
        totp_secret=b"x" * 32 if role in {AdminRole.OWNER, AdminRole.ADMIN, AdminRole.HR} else None,
    )


def _app(monkeypatch: MonkeyPatch) -> FastAPI:
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://localhost:5432/attendance")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("BIOMETRIC_KEK", "test-kek")
    monkeypatch.setattr("backend.app.audit.middleware._append_entry", _skip_middleware_audit)
    get_settings.cache_clear()
    app = create_app()
    app.dependency_overrides[get_session] = fake_session
    return app


def _authenticated_app(
    monkeypatch: MonkeyPatch,
    admin_user: AdminUser | None = None,
) -> FastAPI:
    app = _app(monkeypatch)
    app.dependency_overrides[authenticated_admin_user] = lambda: admin_user or _admin_user()
    return app


def test_core_crud_routers_are_registered(monkeypatch: MonkeyPatch) -> None:
    with TestClient(_app(monkeypatch)) as client:
        paths = set(client.get("/openapi.json").json()["paths"])

    assert "/api/people" in paths
    assert "/api/people/{survivor_id}/merge" in paths
    assert "/api/sessions" in paths
    assert "/api/sessions/{session_id}/end" in paths
    assert "/api/groups" in paths
    assert "/api/locations" in paths
    assert "/api/devices" in paths


def test_create_group_rejects_unknown_fields_before_service_call(monkeypatch: MonkeyPatch) -> None:
    with TestClient(_authenticated_app(monkeypatch)) as client:
        response = client.post(
            "/api/groups",
            json={"kind": "section", "name": "7-A", "unexpected": True},
        )

    assert response.status_code == 422


def test_crud_requires_authenticated_admin(monkeypatch: MonkeyPatch) -> None:
    with TestClient(_app(monkeypatch)) as client:
        response = client.get("/api/groups")

    assert response.status_code == 401
    assert response.json()["detail"] == "admin authentication required"


def test_group_mutation_appends_audit_entry_and_commits(
    monkeypatch: MonkeyPatch,
) -> None:
    group_id = UUID("00000000-0000-0000-0000-000000000030")
    audit_calls: list[dict[str, object]] = []

    class FakeGroupsService:
        async def create(self, _session: AsyncSession, payload: object) -> Group:
            return Group(id=group_id, kind=GroupKind.SECTION, name="7-A", is_active=True)

    async def fake_audit(
        _session: AsyncSession,
        actor: RequestActor,
        *,
        action: str,
        entity_type: str,
        entity_id: str | None,
        before: dict[str, object] | None,
        after: dict[str, object] | None,
    ) -> None:
        audit_calls.append(
            {
                "actor": actor.admin_id,
                "action": action,
                "entity_type": entity_type,
                "entity_id": entity_id,
                "before": before,
                "after": after,
            }
        )

    monkeypatch.setattr("backend.app.api.groups.audited_mutation", fake_audit)

    app = _app(monkeypatch)
    app.dependency_overrides[get_groups_service] = lambda: FakeGroupsService()
    app.dependency_overrides[authenticated_admin_user] = lambda: _admin_user()
    with TestClient(app) as client:
        response = client.post(
            "/api/groups",
            headers={
                "x-admin-id": "00000000-0000-0000-0000-0000000000ad",
                "x-request-id": "req-test",
            },
            json={"kind": "section", "name": "7-A"},
        )

    assert response.status_code == 201
    assert response.json()["id"] == str(group_id)
    assert audit_calls == [
        {
            "actor": UUID("00000000-0000-0000-0000-0000000000ad"),
            "action": "group.create",
            "entity_type": "group",
            "entity_id": str(group_id),
            "before": None,
            "after": {
                "id": str(group_id),
                "parent_group_id": None,
                "kind": "section",
                "name": "7-A",
                "code": None,
                "is_active": True,
            },
        }
    ]


def test_people_list_passes_supervisor_scope_to_repository_layer(
    monkeypatch: MonkeyPatch,
) -> None:
    group_id = UUID("00000000-0000-0000-0000-000000000777")
    person_id = UUID("00000000-0000-0000-0000-000000000031")
    captured_admin: CapturedAdmin | None = None

    @dataclass
    class CapturedAdmin:
        role: AdminRole
        scope_group_ids: list[UUID]

    class FakePeopleService:
        async def list(
            self,
            _session: AsyncSession,
            admin_user: AdminUser,
            *,
            business_date: object,
            limit: int,
            offset: int,
        ) -> list[Person]:
            nonlocal captured_admin
            captured_admin = CapturedAdmin(
                role=AdminRole(admin_user.role),
                scope_group_ids=admin_user.scope_group_ids,
            )
            return [
                Person(
                    id=person_id,
                    kind=PersonKind.STUDENT,
                    display_name="Maria Santos",
                    locale="en",
                    is_active=True,
                )
            ]

    app = _authenticated_app(
        monkeypatch, _admin_user(AdminRole.SUPERVISOR, scope_group_ids=[group_id])
    )
    app.dependency_overrides[get_people_service] = lambda: FakePeopleService()
    with TestClient(app) as client:
        response = client.get(
            "/api/people?admin_role=admin&scope_group_id=00000000-0000-0000-0000-000000000999",
        )

    assert response.status_code == 200
    assert response.json()[0]["display_name"] == "Maria Santos"
    assert captured_admin == CapturedAdmin(AdminRole.SUPERVISOR, [group_id])


def test_person_merge_endpoint_audits_and_commits(monkeypatch: MonkeyPatch) -> None:
    survivor_id = UUID("00000000-0000-0000-0000-000000000090")
    duplicate_id = UUID("00000000-0000-0000-0000-000000000091")
    audit_calls: list[dict[str, object]] = []

    class FakePeopleMergeService:
        async def merge(
            self,
            _session: AsyncSession,
            *,
            survivor_id: UUID,
            duplicate_id: UUID,
        ) -> PersonMergeSummary:
            return PersonMergeSummary(
                survivor_id=survivor_id,
                duplicate_id=duplicate_id,
                consents_moved=1,
                enrollment_assets_moved=2,
                embeddings_moved=3,
                embeddings_deactivated=1,
                group_memberships_moved=4,
                guardian_links_moved=5,
                duplicate_guardian_links_removed=1,
                gallery_version=9,
            )

    async def fake_audit(
        _session: AsyncSession,
        actor: RequestActor,
        *,
        action: str,
        entity_type: str,
        entity_id: str | None,
        before: dict[str, object] | None,
        after: dict[str, object] | None,
    ) -> None:
        audit_calls.append(
            {
                "actor": actor.admin_id,
                "action": action,
                "entity_type": entity_type,
                "entity_id": entity_id,
                "before": before,
                "after": after,
            }
        )

    monkeypatch.setattr("backend.app.api.people_merge.audited_mutation", fake_audit)
    app = _authenticated_app(monkeypatch, _admin_user(AdminRole.ADMIN))
    app.dependency_overrides[get_people_merge_service] = lambda: FakePeopleMergeService()

    with TestClient(app) as client:
        response = client.post(
            f"/api/people/{survivor_id}/merge",
            headers={"x-admin-id": "00000000-0000-0000-0000-0000000000ad"},
            json={"duplicate_person_id": str(duplicate_id)},
        )

    assert response.status_code == 200
    assert response.json()["gallery_version"] == 9
    assert audit_calls[0]["action"] == "person.merge"
    assert audit_calls[0]["entity_id"] == str(survivor_id)


def test_create_scan_session_rejects_unknown_fields_before_service_call(
    monkeypatch: MonkeyPatch,
) -> None:
    with TestClient(_authenticated_app(monkeypatch, _admin_user(AdminRole.ADMIN))) as client:
        response = client.post(
            "/api/sessions",
            json={
                "device_id": "00000000-0000-0000-0000-000000000092",
                "location_id": "10000000-0000-0000-0000-000000000092",
                "unexpected": True,
            },
        )

    assert response.status_code == 422


def test_create_scan_session_audits_and_commits(monkeypatch: MonkeyPatch) -> None:
    session_id = UUID("40000000-0000-0000-0000-000000000092")
    device_id = UUID("00000000-0000-0000-0000-000000000092")
    location_id = UUID("10000000-0000-0000-0000-000000000092")
    started_at = datetime(2026, 8, 4, 8, 0, tzinfo=UTC)
    audit_calls: list[dict[str, object]] = []

    class FakeSessionsService:
        async def open(
            self,
            _session: AsyncSession,
            payload: object,
            *,
            operator_admin_id: UUID,
            now: datetime,
        ) -> ScanSession:
            return ScanSession(
                id=session_id,
                device_id=device_id,
                location_id=location_id,
                operator_admin_id=operator_admin_id,
                location_source=ScanSessionLocationSource.SESSION_DECLARED,
                started_at=started_at,
                last_activity_at=started_at,
                scan_count=0,
            )

    async def fake_audit(
        _session: AsyncSession,
        actor: RequestActor,
        *,
        action: str,
        entity_type: str,
        entity_id: str | None,
        before: dict[str, object] | None,
        after: dict[str, object] | None,
    ) -> None:
        audit_calls.append(
            {
                "actor": actor.admin_id,
                "action": action,
                "entity_type": entity_type,
                "entity_id": entity_id,
                "before": before,
                "after": after,
            }
        )

    monkeypatch.setattr("backend.app.api.sessions.audited_mutation", fake_audit)
    app = _authenticated_app(monkeypatch, _admin_user(AdminRole.ADMIN))
    app.dependency_overrides[get_sessions_service] = lambda: FakeSessionsService()

    with TestClient(app) as client:
        response = client.post(
            "/api/sessions",
            headers={"x-admin-id": "00000000-0000-0000-0000-0000000000ad"},
            json={"device_id": str(device_id), "location_id": str(location_id)},
        )

    assert response.status_code == 201
    assert response.json()["id"] == str(session_id)
    assert audit_calls[0]["action"] == "scan_session.create"
    assert audit_calls[0]["entity_id"] == str(session_id)


@pytest.mark.anyio
async def test_create_scan_session_closes_stale_open_session_before_starting_new_one() -> None:
    from backend.app.api.sessions import ScanSessionCreate, SessionsService
    from backend.app.models.devices import Device, DeviceDirection, DeviceFormFactor, DeviceMode

    class FakeSessionStore:
        def __init__(self) -> None:
            self.device = Device(
                id=UUID("00000000-0000-0000-0000-000000000092"),
                mode=DeviceMode.ROAMING,
                form_factor=DeviceFormFactor.PHONE,
                direction=DeviceDirection.BIDIRECTIONAL,
                token_hash="hash",
                token_display_prefix="tok_",
            )
            self.stale_session = ScanSession(
                id=UUID("40000000-0000-0000-0000-000000000001"),
                device_id=self.device.id,
                location_id=UUID("10000000-0000-0000-0000-000000000001"),
                operator_admin_id=UUID("00000000-0000-0000-0000-0000000000ad"),
                location_source=ScanSessionLocationSource.SESSION_DECLARED,
                started_at=datetime(2026, 8, 4, 8, 0, tzinfo=UTC),
                last_activity_at=datetime(2026, 8, 4, 8, 0, tzinfo=UTC),
                scan_count=0,
            )
            self.added: list[ScanSession] = []
            self.flush_count = 0

        async def get(self, model: object, identifier: UUID) -> Device | None:
            return self.device

        async def execute(self, query: object) -> object:
            class FakeResult:
                def scalar_one_or_none(self_inner: object) -> ScanSession:
                    return self.stale_session

            return FakeResult()

        def add(self, scan_session: ScanSession) -> None:
            self.added.append(scan_session)

        async def flush(self) -> None:
            self.flush_count += 1

    store = FakeSessionStore()
    service = SessionsService()

    opened = await service.open(
        cast(AsyncSession, store),
        ScanSessionCreate(
            device_id=store.device.id,
            location_id=UUID("10000000-0000-0000-0000-000000000002"),
        ),
        operator_admin_id=UUID("00000000-0000-0000-0000-0000000000ad"),
        now=datetime(2026, 8, 4, 8, 21, tzinfo=UTC),
    )

    assert store.stale_session.ended_at == datetime(2026, 8, 4, 8, 21, tzinfo=UTC)
    assert store.stale_session.end_reason == ScanSessionEndReason.IDLE_TIMEOUT
    assert opened.location_id == UUID("10000000-0000-0000-0000-000000000002")
    assert store.added == [opened]
    assert store.flush_count == 2


def test_supervisor_cannot_read_org_wide_groups(monkeypatch: MonkeyPatch) -> None:
    app = _authenticated_app(monkeypatch, _admin_user(AdminRole.SUPERVISOR))

    with TestClient(app) as client:
        response = client.get("/api/groups")

    assert response.status_code == 403
    assert response.json()["detail"] == "admin role cannot manage org-wide resources"
