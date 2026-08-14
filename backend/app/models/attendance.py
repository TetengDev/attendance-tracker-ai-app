from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Uuid

from backend.app.attendance.decision_table import AttendanceStatus
from backend.app.db.base import (
    PER_DAY_PERIOD_LABEL,
    Base,
    bigint_identity_pk,
    created_at_column,
    updated_at_column,
    uuid_pk,
)


class AttendanceEventDirection(str, Enum):
    IN = "in"
    OUT = "out"


class AttendanceLocationSource(str, Enum):
    DEVICE_FIXED = "device_fixed"
    SESSION_DECLARED = "session_declared"
    GEOFENCE = "geofence"


class AttendanceEventOutcome(str, Enum):
    ACCEPTED = "accepted"
    AMBIGUOUS = "ambiguous"
    LOW_CONFIDENCE = "low_confidence"
    UNKNOWN_FACE = "unknown_face"
    LOCATION_CONFLICT = "location_conflict"
    MANUAL_CORRECTION = "manual_correction"


class AttendanceEvent(Base):
    __tablename__ = "attendance_events"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_attendance_events_idempotency_key"),
        CheckConstraint("idempotency_key <> ''", name="idempotency_key_non_empty"),
        CheckConstraint("period_label IS NOT NULL", name="period_label_not_null"),
        CheckConstraint(
            "monotonic_offset_ms >= 0",
            name="monotonic_offset_ms_non_negative",
        ),
        CheckConstraint(
            "top1_score IS NULL OR top1_score BETWEEN 0 AND 1",
            name="top1_score_probability_range",
        ),
        CheckConstraint(
            "top2_other_person_score IS NULL OR top2_other_person_score BETWEEN 0 AND 1",
            name="top2_other_person_score_probability_range",
        ),
        CheckConstraint(
            "occurred_at <= server_received_at",
            name="occurred_at_not_after_server_received",
        ),
        Index("ix_attendance_events_person_business_date", "person_id", "business_date"),
        Index("ix_attendance_events_device_local_date", "device_id", "device_local_date"),
        Index("ix_attendance_events_session_id", "session_id"),
    )

    id: Mapped[int] = bigint_identity_pk()
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    person_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("people.id", ondelete="SET NULL"),
        nullable=True,
    )
    device_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("devices.id", ondelete="SET NULL"),
        nullable=True,
    )
    session_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("scan_sessions.id", ondelete="SET NULL"),
        nullable=True,
    )
    location_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("locations.id", ondelete="SET NULL"),
        nullable=True,
    )
    shift_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("shifts.id", ondelete="SET NULL"),
        nullable=True,
    )
    supersedes_event_id: Mapped[int | None] = mapped_column(
        ForeignKey("attendance_events.id", ondelete="SET NULL"),
        nullable=True,
    )
    direction: Mapped[AttendanceEventDirection] = mapped_column(String(8), nullable=False)
    outcome: Mapped[AttendanceEventOutcome] = mapped_column(String(32), nullable=False)
    location_source: Mapped[AttendanceLocationSource | None] = mapped_column(
        String(32), nullable=True
    )
    business_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    device_local_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    period_label: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default=PER_DAY_PERIOD_LABEL,
    )
    client_captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    server_received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    monotonic_offset_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    was_backdated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    top1_score: Mapped[float | None] = mapped_column(Numeric(6, 5), nullable=True)
    top2_other_person_score: Mapped[float | None] = mapped_column(Numeric(6, 5), nullable=True)
    event_metadata: Mapped[dict[str, object]] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        default=dict,
    )
    created_at: Mapped[datetime] = created_at_column()


class ExpectedAttendance(Base):
    __tablename__ = "expected_attendance"
    __table_args__ = (
        UniqueConstraint(
            "person_id",
            "business_date",
            "shift_id",
            "period_label",
            name="uq_expected_attendance_natural_key",
        ),
        CheckConstraint("period_label IS NOT NULL", name="period_label_not_null"),
        CheckConstraint(
            "expected_end_at > expected_start_at",
            name="expected_end_after_start",
        ),
        Index("ix_expected_attendance_business_date", "business_date"),
    )

    id: Mapped[UUID] = uuid_pk()
    person_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("people.id", ondelete="CASCADE"),
        nullable=False,
    )
    business_date: Mapped[date] = mapped_column(Date, nullable=False)
    shift_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("shifts.id", ondelete="RESTRICT"),
        nullable=False,
    )
    period_label: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default=PER_DAY_PERIOD_LABEL,
    )
    location_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("locations.id", ondelete="SET NULL"),
        nullable=True,
    )
    schedule_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("schedules.id", ondelete="SET NULL"),
        nullable=True,
    )
    expected_start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expected_end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    absent_after_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    is_working_day: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    voided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()


class AttendanceOverride(Base):
    __tablename__ = "attendance_overrides"
    __table_args__ = (
        UniqueConstraint(
            "person_id",
            "business_date",
            "shift_id",
            "period_label",
            name="uq_attendance_overrides_natural_key",
        ),
        CheckConstraint("period_label IS NOT NULL", name="period_label_not_null"),
        CheckConstraint("reason <> ''", name="reason_non_empty"),
    )

    id: Mapped[UUID] = uuid_pk()
    person_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("people.id", ondelete="CASCADE"),
        nullable=False,
    )
    business_date: Mapped[date] = mapped_column(Date, nullable=False)
    shift_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("shifts.id", ondelete="RESTRICT"),
        nullable=False,
    )
    period_label: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default=PER_DAY_PERIOD_LABEL,
    )
    status: Mapped[AttendanceStatus] = mapped_column(String(32), nullable=False)
    reason: Mapped[str] = mapped_column(String(512), nullable=False)
    actor_admin_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()


class AttendanceRecord(Base):
    __tablename__ = "attendance_records"
    __table_args__ = (
        UniqueConstraint(
            "person_id",
            "business_date",
            "shift_id",
            "period_label",
            name="uq_attendance_records_natural_key",
        ),
        CheckConstraint("period_label IS NOT NULL", name="period_label_not_null"),
        CheckConstraint(
            "late_minutes IS NULL OR late_minutes >= 0",
            name="late_minutes_non_negative",
        ),
        Index("ix_attendance_records_business_date_status", "business_date", "status"),
    )

    id: Mapped[UUID] = uuid_pk()
    expected_attendance_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("expected_attendance.id", ondelete="SET NULL"),
        nullable=True,
    )
    override_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("attendance_overrides.id", ondelete="SET NULL"),
        nullable=True,
    )
    person_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("people.id", ondelete="CASCADE"),
        nullable=False,
    )
    business_date: Mapped[date] = mapped_column(Date, nullable=False)
    shift_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("shifts.id", ondelete="RESTRICT"),
        nullable=False,
    )
    period_label: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default=PER_DAY_PERIOD_LABEL,
    )
    status: Mapped[AttendanceStatus] = mapped_column(String(32), nullable=False)
    first_event_id: Mapped[int | None] = mapped_column(
        ForeignKey("attendance_events.id", ondelete="SET NULL"),
        nullable=True,
    )
    last_event_id: Mapped[int | None] = mapped_column(
        ForeignKey("attendance_events.id", ondelete="SET NULL"),
        nullable=True,
    )
    late_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    flags: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=dict)
    resolved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()


@dataclass(frozen=True)
class AttendanceGrain:
    person_id: UUID
    business_date: date
    shift_id: UUID
    period_label: str = PER_DAY_PERIOD_LABEL


def grain_for_expected(expected: ExpectedAttendance) -> AttendanceGrain:
    return AttendanceGrain(
        person_id=expected.person_id,
        business_date=expected.business_date,
        shift_id=expected.shift_id,
        period_label=expected.period_label or PER_DAY_PERIOD_LABEL,
    )


def grain_for_override(override: AttendanceOverride) -> AttendanceGrain:
    return AttendanceGrain(
        person_id=override.person_id,
        business_date=override.business_date,
        shift_id=override.shift_id,
        period_label=override.period_label or PER_DAY_PERIOD_LABEL,
    )


def event_matches_grain(event: AttendanceEvent, grain: AttendanceGrain) -> bool:
    return (
        event.person_id == grain.person_id
        and event.business_date == grain.business_date
        and event.shift_id == grain.shift_id
        and (event.period_label or PER_DAY_PERIOD_LABEL) == grain.period_label
    )


def canonical_attendance_grain(
    grain: AttendanceGrain,
    merged_into: Mapping[UUID, UUID],
) -> AttendanceGrain:
    return AttendanceGrain(
        person_id=canonical_attendance_person_id(grain.person_id, merged_into),
        business_date=grain.business_date,
        shift_id=grain.shift_id,
        period_label=grain.period_label,
    )


def canonical_attendance_person_id(person_id: UUID, merged_into: Mapping[UUID, UUID]) -> UUID:
    seen: set[UUID] = set()
    current = person_id
    while current in merged_into:
        if current in seen:
            raise ValueError("cycle detected in person merge map")
        seen.add(current)
        current = merged_into[current]
    return current


def rebuild_attendance_records(
    expected_rows: list[ExpectedAttendance],
    events: list[AttendanceEvent],
    overrides: list[AttendanceOverride],
    *,
    resolved_at: datetime,
    merged_into: Mapping[UUID, UUID] | None = None,
) -> list[AttendanceRecord]:
    aliases = merged_into or {}
    overrides_by_grain = {
        canonical_attendance_grain(grain_for_override(override), aliases): override
        for override in overrides
    }
    expected_by_grain: dict[AttendanceGrain, ExpectedAttendance] = {}
    for expected in expected_rows:
        grain = canonical_attendance_grain(grain_for_expected(expected), aliases)
        expected_by_grain.setdefault(grain, expected)

    records: list[AttendanceRecord] = []

    for grain, expected in expected_by_grain.items():
        override = overrides_by_grain.get(grain)
        matching_events = sorted(
            [event for event in events if _event_matches_canonical_grain(event, grain, aliases)],
            key=lambda event: event.occurred_at,
        )
        first_event = matching_events[0] if matching_events else None
        last_event = matching_events[-1] if matching_events else None
        records.append(
            AttendanceRecord(
                expected_attendance_id=expected.id,
                override_id=override.id if override is not None else None,
                person_id=grain.person_id,
                business_date=grain.business_date,
                shift_id=grain.shift_id,
                period_label=grain.period_label,
                status=override.status
                if override is not None
                else (
                    AttendanceStatus.ON_TIME
                    if first_event is not None
                    else AttendanceStatus.PENDING
                ),
                first_event_id=first_event.id if first_event is not None else None,
                last_event_id=last_event.id if last_event is not None else None,
                flags={},
                resolved_at=resolved_at,
            )
        )

    return records


def _event_matches_canonical_grain(
    event: AttendanceEvent,
    grain: AttendanceGrain,
    merged_into: Mapping[UUID, UUID],
) -> bool:
    if event.person_id is None:
        return False
    return (
        canonical_attendance_person_id(event.person_id, merged_into) == grain.person_id
        and event.business_date == grain.business_date
        and event.shift_id == grain.shift_id
        and (event.period_label or PER_DAY_PERIOD_LABEL) == grain.period_label
    )


class ReportJobStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class ReportJob(Base):
    __tablename__ = "report_jobs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'processing', 'completed', 'failed')",
            name="status_valid",
        ),
        CheckConstraint("report_type <> ''", name="report_type_non_empty"),
        CheckConstraint("format IN ('csv', 'xlsx', 'pdf')", name="format_valid"),
    )

    id: Mapped[UUID] = uuid_pk()
    report_type: Mapped[str] = mapped_column(String(64), nullable=False)
    format: Mapped[str] = mapped_column(String(16), nullable=False)
    parameters: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    file_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    row_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()
