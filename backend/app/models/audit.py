from __future__ import annotations

from datetime import datetime
from enum import Enum
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, Index, LargeBinary, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Uuid

from backend.app.db.base import Base, bigint_identity_pk, created_at_column

AUDIT_HASH_BYTES = 32


class AuditActorKind(str, Enum):
    ADMIN = "admin"
    DEVICE = "device"
    SYSTEM = "system"
    JOB = "job"


class AuditLog(Base):
    __tablename__ = "audit_log"
    __table_args__ = (
        CheckConstraint(
            "actor_kind IN ('admin', 'device', 'system', 'job')",
            name="actor_kind_valid",
        ),
        CheckConstraint("action <> ''", name="action_non_empty"),
        CheckConstraint("entity_type <> ''", name="entity_type_non_empty"),
        CheckConstraint("request_id <> ''", name="request_id_non_empty"),
        CheckConstraint(
            "octet_length(hash) = 32",
            name="hash_sha256_length",
        ),
        CheckConstraint(
            "prev_hash IS NULL OR octet_length(prev_hash) = 32",
            name="prev_hash_sha256_length",
        ),
        Index("ix_audit_log_entity", "entity_type", "entity_id"),
        Index("ix_audit_log_created_at", "created_at"),
        Index("ix_audit_log_actor", "actor_kind", "actor_id"),
    )

    id: Mapped[int] = bigint_identity_pk()
    actor_kind: Mapped[AuditActorKind] = mapped_column(String(16), nullable=False)
    actor_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    action: Mapped[str] = mapped_column(String(128), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(128), nullable=False)
    entity_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    before: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)
    after: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    request_id: Mapped[str] = mapped_column(String(128), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    prev_hash: Mapped[bytes | None] = mapped_column(LargeBinary(AUDIT_HASH_BYTES), nullable=True)
    hash: Mapped[bytes] = mapped_column(LargeBinary(AUDIT_HASH_BYTES), nullable=False)
    created_at: Mapped[datetime] = created_at_column()
