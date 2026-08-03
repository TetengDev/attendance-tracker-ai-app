from __future__ import annotations

from datetime import date
from typing import Any
from uuid import UUID

from sqlalchemy import Select
from sqlalchemy.dialects import postgresql

from backend.app.auth.rbac import scoped_people_query
from backend.app.models.admin import AdminRole, AdminUser


def _sql(query: Select[tuple[Any]]) -> str:
    return str(
        query.compile(
            dialect=postgresql.dialect(),  # type: ignore[no-untyped-call]
            compile_kwargs={"literal_binds": True},
        ),
    )


def test_supervisor_people_query_is_scoped_at_repository_layer() -> None:
    group_id = UUID("00000000-0000-0000-0000-000000000111")
    supervisor = AdminUser(
        email="supervisor@example.test",
        display_name="Supervisor",
        password_hash="hash",
        role=AdminRole.SUPERVISOR,
        scope_group_ids=[group_id],
    )

    sql = _sql(scoped_people_query(supervisor, business_date=date(2026, 8, 3)))

    assert "EXISTS" in sql
    assert "person_groups.person_id = people.id" in sql
    assert "person_groups.group_id IN" in sql
    assert str(group_id) in sql
    assert "person_groups.effective_from <= '2026-08-03'" in sql


def test_supervisor_without_scope_cannot_read_any_people() -> None:
    supervisor = AdminUser(
        email="supervisor@example.test",
        display_name="Supervisor",
        password_hash="hash",
        role=AdminRole.SUPERVISOR,
        scope_group_ids=[],
    )

    sql = _sql(scoped_people_query(supervisor, business_date=date(2026, 8, 3)))

    assert "false" in sql


def test_owner_people_query_is_unscoped() -> None:
    owner = AdminUser(
        email="owner@example.test",
        display_name="Owner",
        password_hash="hash",
        role=AdminRole.OWNER,
        scope_group_ids=[],
        totp_secret=b"x" * 32,
    )

    sql = _sql(scoped_people_query(owner, business_date=date(2026, 8, 3)))

    assert "person_groups" not in sql
