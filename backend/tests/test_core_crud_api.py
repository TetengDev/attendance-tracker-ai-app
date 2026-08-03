from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from uuid import UUID

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pytest import MonkeyPatch
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.api.common import RequestActor
from backend.app.api.groups import get_groups_service
from backend.app.api.people import get_people_service
from backend.app.config import get_settings
from backend.app.db.session import get_session
from backend.app.main import create_app
from backend.app.models.admin import AdminRole, AdminUser
from backend.app.models.people import Group, GroupKind, Person, PersonKind


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


def _app(monkeypatch: MonkeyPatch) -> FastAPI:
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://localhost:5432/attendance")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("BIOMETRIC_KEK", "test-kek")
    monkeypatch.setattr("backend.app.audit.middleware._append_entry", _skip_middleware_audit)
    get_settings.cache_clear()
    app = create_app()
    app.dependency_overrides[get_session] = fake_session
    return app


def test_core_crud_routers_are_registered(monkeypatch: MonkeyPatch) -> None:
    with TestClient(_app(monkeypatch)) as client:
        paths = set(client.get("/openapi.json").json()["paths"])

    assert "/api/people" in paths
    assert "/api/groups" in paths
    assert "/api/locations" in paths
    assert "/api/devices" in paths


def test_create_group_rejects_unknown_fields_before_service_call(monkeypatch: MonkeyPatch) -> None:
    with TestClient(_app(monkeypatch)) as client:
        response = client.post(
            "/api/groups",
            json={"kind": "section", "name": "7-A", "unexpected": True},
        )

    assert response.status_code == 422


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

    app = _app(monkeypatch)
    app.dependency_overrides[get_people_service] = lambda: FakePeopleService()
    with TestClient(app) as client:
        response = client.get(
            f"/api/people?admin_role=supervisor&scope_group_id={group_id}",
        )

    assert response.status_code == 200
    assert response.json()[0]["display_name"] == "Maria Santos"
    assert captured_admin == CapturedAdmin(AdminRole.SUPERVISOR, [group_id])
