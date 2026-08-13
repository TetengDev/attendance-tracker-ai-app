from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import Enum
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, Numeric, String, text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Uuid

from backend.app.db.base import Base, created_at_column, updated_at_column, uuid_pk


class ScanSessionLocationSource(str, Enum):
    DEVICE_FIXED = "device_fixed"
    SESSION_DECLARED = "session_declared"
    GEOFENCE = "geofence"


class ScanSessionEndReason(str, Enum):
    EXPLICIT = "explicit"
    IDLE_TIMEOUT = "idle_timeout"
    MAX_DURATION = "max_duration"
    TOKEN_REVOKED = "token_revoked"


class ScanSession(Base):
    __tablename__ = "scan_sessions"
    __table_args__ = (
        CheckConstraint(
            "location_source IN ('device_fixed', 'session_declared', 'geofence')",
            name="location_source_valid",
        ),
        CheckConstraint(
            "end_reason IS NULL OR end_reason IN ('explicit', 'idle_timeout', 'max_duration', 'token_revoked')",
            name="end_reason_valid",
        ),
        CheckConstraint(
            "(ended_at IS NULL AND end_reason IS NULL) OR (ended_at IS NOT NULL AND end_reason IS NOT NULL)",
            name="ended_state_matches_reason",
        ),
        CheckConstraint(
            "ended_at IS NULL OR ended_at >= started_at",
            name="ended_at_not_before_started_at",
        ),
        CheckConstraint(
            "last_activity_at >= started_at",
            name="last_activity_not_before_started_at",
        ),
        CheckConstraint("scan_count >= 0", name="scan_count_non_negative"),
        CheckConstraint(
            "start_lat IS NULL OR start_lat BETWEEN -90 AND 90", name="start_lat_range"
        ),
        CheckConstraint(
            "start_lng IS NULL OR start_lng BETWEEN -180 AND 180", name="start_lng_range"
        ),
        CheckConstraint(
            "gps_accuracy_m IS NULL OR gps_accuracy_m >= 0", name="gps_accuracy_non_negative"
        ),
        Index(
            "uq_scan_sessions_open_device",
            "device_id",
            unique=True,
            postgresql_where=text("ended_at IS NULL"),
        ),
        Index("ix_scan_sessions_device_started_at", "device_id", "started_at"),
        Index("ix_scan_sessions_location_started_at", "location_id", "started_at"),
    )

    id: Mapped[UUID] = uuid_pk()
    device_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("devices.id", ondelete="CASCADE"),
        nullable=False,
    )
    location_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("locations.id", ondelete="RESTRICT"),
        nullable=False,
    )
    operator_admin_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("admin_users.id", ondelete="SET NULL"),
        nullable=True,
    )
    location_source: Mapped[ScanSessionLocationSource] = mapped_column(String(32), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_activity_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    start_lat: Mapped[Decimal | None] = mapped_column(Numeric(8, 6), nullable=True)
    start_lng: Mapped[Decimal | None] = mapped_column(Numeric(9, 6), nullable=True)
    gps_accuracy_m: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), nullable=True)
    scan_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    end_reason: Mapped[ScanSessionEndReason | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()

    @property
    def is_open(self) -> bool:
        return self.ended_at is None
