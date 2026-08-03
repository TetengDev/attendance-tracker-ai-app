from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from uuid import UUID

from backend.app.models.audit import AuditActorKind, AuditLog

AUDIT_CHAIN_VERSION = 1


class AuditChainError(ValueError):
    """Raised when an audit row no longer matches the expected chain."""


@dataclass(frozen=True)
class AuditEntry:
    actor_kind: AuditActorKind
    actor_id: UUID | None
    action: str
    entity_type: str
    entity_id: str | None
    before: dict[str, object] | None
    after: dict[str, object] | None
    ip_address: str | None
    request_id: str
    occurred_at: datetime


def compute_audit_hash(entry: AuditEntry, *, prev_hash: bytes | None) -> bytes:
    payload = {
        "version": AUDIT_CHAIN_VERSION,
        "prev_hash": prev_hash.hex() if prev_hash is not None else None,
        "actor_kind": entry.actor_kind.value,
        "actor_id": str(entry.actor_id) if entry.actor_id is not None else None,
        "action": entry.action,
        "entity_type": entry.entity_type,
        "entity_id": entry.entity_id,
        "before": entry.before,
        "after": entry.after,
        "ip_address": entry.ip_address,
        "request_id": entry.request_id,
        "occurred_at": entry.occurred_at.isoformat(),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=_json_default)
    return hashlib.sha256(encoded.encode("utf-8")).digest()


def make_audit_log(entry: AuditEntry, *, prev_hash: bytes | None) -> AuditLog:
    row_hash = compute_audit_hash(entry, prev_hash=prev_hash)
    return AuditLog(
        actor_kind=entry.actor_kind,
        actor_id=entry.actor_id,
        action=entry.action,
        entity_type=entry.entity_type,
        entity_id=entry.entity_id,
        before=entry.before,
        after=entry.after,
        ip_address=entry.ip_address,
        request_id=entry.request_id,
        occurred_at=entry.occurred_at,
        prev_hash=prev_hash,
        hash=row_hash,
    )


def verify_audit_chain(rows: list[AuditLog]) -> bytes | None:
    prev_hash: bytes | None = None
    for row in rows:
        if row.prev_hash != prev_hash:
            raise AuditChainError(f"audit row {row.id} has an unexpected previous hash")
        expected = compute_audit_hash(_entry_from_row(row), prev_hash=prev_hash)
        if row.hash != expected:
            raise AuditChainError(f"audit row {row.id} hash does not match row contents")
        prev_hash = row.hash
    return prev_hash


def _entry_from_row(row: AuditLog) -> AuditEntry:
    actor_kind = row.actor_kind
    if isinstance(actor_kind, str):
        actor_kind = AuditActorKind(actor_kind)
    return AuditEntry(
        actor_kind=actor_kind,
        actor_id=row.actor_id,
        action=row.action,
        entity_type=row.entity_type,
        entity_id=row.entity_id,
        before=row.before,
        after=row.after,
        ip_address=row.ip_address,
        request_id=row.request_id,
        occurred_at=row.occurred_at,
    )


def _json_default(value: object) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, (UUID, Enum)):
        return str(value)
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")
