from __future__ import annotations

from datetime import UTC, datetime
from typing import cast
from uuid import UUID

import pytest
from sqlalchemy import Table

from backend.app.audit.chain import AuditChainError, AuditEntry, make_audit_log, verify_audit_chain
from backend.app.models.audit import AuditActorKind, AuditLog

ADMIN_ID = UUID("00000000-0000-0000-0000-000000000029")
OCCURRED_AT = datetime(2026, 8, 3, 10, 0, tzinfo=UTC)


def test_audit_model_uses_append_only_identity_and_hash_columns() -> None:
    table = cast(Table, AuditLog.__table__)
    columns = table.columns
    constraints = {constraint.name for constraint in table.constraints}
    indexes = {index.name for index in table.indexes}

    assert AuditLog.__tablename__ == "audit_log"
    assert columns["id"].primary_key
    assert columns["id"].identity is not None
    assert columns["prev_hash"].nullable is True
    assert columns["hash"].nullable is False
    assert "ck_audit_log_hash_sha256_length" in constraints
    assert "ck_audit_log_prev_hash_sha256_length" in constraints
    assert "ix_audit_log_entity" in indexes
    assert "ix_audit_log_actor" in indexes


def test_hash_chain_links_rows_and_returns_chain_head() -> None:
    first = make_audit_log(_entry(action="people.create"), prev_hash=None)
    first.id = 1
    second = make_audit_log(_entry(action="people.update"), prev_hash=first.hash)
    second.id = 2

    assert second.prev_hash == first.hash
    assert verify_audit_chain([first, second]) == second.hash


def test_hash_payload_is_stable_for_json_key_ordering() -> None:
    left = _entry(action="people.update")
    right = AuditEntry(
        actor_kind=left.actor_kind,
        actor_id=left.actor_id,
        action=left.action,
        entity_type=left.entity_type,
        entity_id=left.entity_id,
        before={"b": 2, "a": 1},
        after={"z": 26, "m": 13},
        ip_address=left.ip_address,
        request_id=left.request_id,
        occurred_at=left.occurred_at,
    )
    equivalent = AuditEntry(
        actor_kind=right.actor_kind,
        actor_id=right.actor_id,
        action=right.action,
        entity_type=right.entity_type,
        entity_id=right.entity_id,
        before={"a": 1, "b": 2},
        after={"m": 13, "z": 26},
        ip_address=right.ip_address,
        request_id=right.request_id,
        occurred_at=right.occurred_at,
    )

    assert make_audit_log(right, prev_hash=None).hash == make_audit_log(equivalent, prev_hash=None).hash


def test_hash_chain_detects_hand_edited_row() -> None:
    row = make_audit_log(_entry(action="people.create"), prev_hash=None)
    row.id = 1
    row.after = {"display_name": "Mallory"}

    with pytest.raises(AuditChainError, match="hash does not match"):
        verify_audit_chain([row])


def test_hash_chain_detects_relinked_history() -> None:
    first = make_audit_log(_entry(action="people.create"), prev_hash=None)
    first.id = 1
    second = make_audit_log(_entry(action="people.update"), prev_hash=b"x" * 32)
    second.id = 2

    with pytest.raises(AuditChainError, match="unexpected previous hash"):
        verify_audit_chain([first, second])


def _entry(action: str) -> AuditEntry:
    return AuditEntry(
        actor_kind=AuditActorKind.ADMIN,
        actor_id=ADMIN_ID,
        action=action,
        entity_type="people",
        entity_id="person-1",
        before=None,
        after={"display_name": "Maria"},
        ip_address="127.0.0.1",
        request_id="req-1",
        occurred_at=OCCURRED_AT,
    )
