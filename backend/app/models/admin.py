from __future__ import annotations

from datetime import datetime
from enum import Enum
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    LargeBinary,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.orm import relationship as orm_relationship
from sqlalchemy.types import Uuid

from backend.app.db.base import Base, created_at_column, updated_at_column, uuid_pk


class AdminRole(str, Enum):
    OWNER = "owner"
    ADMIN = "admin"
    HR = "hr"
    SUPERVISOR = "supervisor"
    VIEWER = "viewer"


PII_EXPORT_ROLES = frozenset({AdminRole.OWNER, AdminRole.ADMIN, AdminRole.HR})


class AdminUser(Base):
    __tablename__ = "admin_users"
    __table_args__ = (
        UniqueConstraint("email", name="uq_admin_users_email"),
        CheckConstraint("email <> ''", name="email_non_empty"),
        CheckConstraint("display_name <> ''", name="display_name_non_empty"),
        CheckConstraint("password_hash <> ''", name="password_hash_non_empty"),
        CheckConstraint(
            "role IN ('owner', 'admin', 'hr', 'supervisor', 'viewer')",
            name="role_valid",
        ),
        CheckConstraint(
            "totp_secret IS NOT NULL OR role NOT IN ('owner', 'admin', 'hr')",
            name="pii_export_roles_require_totp",
        ),
    )

    id: Mapped[UUID] = uuid_pk()
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    display_name: Mapped[str] = mapped_column(String(256), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(512), nullable=False)
    role: Mapped[AdminRole] = mapped_column(String(32), nullable=False)
    scope_group_ids: Mapped[list[UUID]] = mapped_column(
        ARRAY(Uuid(as_uuid=True)),
        nullable=False,
        default=list,
        server_default="{}",
    )
    totp_secret: Mapped[bytes | None] = mapped_column(LargeBinary(length=32), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    password_changed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failed_login_count: Mapped[int] = mapped_column(nullable=False, default=0, server_default="0")
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()

    sessions: Mapped[list[AdminSession]] = orm_relationship(
        back_populates="admin_user",
        cascade="all, delete-orphan",
    )

    @property
    def can_export_pii(self) -> bool:
        return AdminRole(self.role) in PII_EXPORT_ROLES


class AdminSession(Base):
    __tablename__ = "admin_sessions"
    __table_args__ = (
        UniqueConstraint("session_hash", name="uq_admin_sessions_session_hash"),
        CheckConstraint("octet_length(session_hash) = 32", name="session_hash_sha256_length"),
        CheckConstraint(
            "csrf_token_hash IS NULL OR octet_length(csrf_token_hash) = 32",
            name="csrf_hash_sha256_length",
        ),
        CheckConstraint("absolute_expires_at > created_at", name="absolute_expiry_after_created"),
        CheckConstraint("idle_expires_at > created_at", name="idle_expiry_after_created"),
    )

    id: Mapped[UUID] = uuid_pk()
    admin_user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("admin_users.id", ondelete="CASCADE"),
        nullable=False,
    )
    session_hash: Mapped[bytes] = mapped_column(LargeBinary(length=32), nullable=False)
    csrf_token_hash: Mapped[bytes | None] = mapped_column(LargeBinary(length=32), nullable=True)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    idle_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    absolute_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rotated_from_session_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("admin_sessions.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()

    admin_user: Mapped[AdminUser] = orm_relationship(back_populates="sessions")
