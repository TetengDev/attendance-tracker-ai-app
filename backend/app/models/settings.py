from __future__ import annotations

from datetime import datetime
from enum import Enum
from uuid import UUID

from sqlalchemy import BigInteger, CheckConstraint, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Uuid

from backend.app.db.base import Base, created_at_column, updated_at_column, uuid_pk


class SettingScope(str, Enum):
    ORG = "org"
    LOCATION = "location"
    DEVICE = "device"


class Setting(Base):
    __tablename__ = "settings"
    __table_args__ = (
        UniqueConstraint("key", "scope", "scope_id", name="uq_settings_key_scope_scope_id"),
        CheckConstraint("key <> ''", name="key_non_empty"),
        CheckConstraint(
            "scope IN ('org', 'location', 'device')",
            name="scope_valid",
        ),
        CheckConstraint(
            "scope = 'org' OR scope_id IS NOT NULL",
            name="non_org_scope_requires_scope_id",
        ),
        CheckConstraint("version > 0", name="version_positive"),
    )

    id: Mapped[UUID] = uuid_pk()
    key: Mapped[str] = mapped_column(String(128), nullable=False)
    scope: Mapped[SettingScope] = mapped_column(String(16), nullable=False)
    scope_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    value: Mapped[object] = mapped_column(JSONB, nullable=False)
    version: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()


class SettingsVersion(Base):
    __tablename__ = "settings_versions"
    __table_args__ = (
        CheckConstraint("current_version > 0", name="current_version_positive"),
    )

    namespace: Mapped[str] = mapped_column(String(64), primary_key=True, default="global")
    current_version: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1)
    updated_at: Mapped[datetime] = updated_at_column()
