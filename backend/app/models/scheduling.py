from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from enum import Enum
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    Integer,
    String,
    Time,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Uuid

from backend.app.db.base import Base, created_at_column, updated_at_column, uuid_pk


class AssignmentScope(str, Enum):
    ORG = "org"
    LOCATION = "location"
    GROUP = "group"
    PERSON = "person"


class CalendarDayKind(str, Enum):
    WORKING_DAY = "working_day"
    HOLIDAY = "holiday"
    NOT_SCHEDULED = "not_scheduled"


class PersonExceptionKind(str, Enum):
    LEAVE = "leave"
    SICK = "sick"
    EXCUSED = "excused"
    FIELD_TRIP = "field_trip"


ASSIGNMENT_SCOPE_PRECEDENCE: dict[AssignmentScope, int] = {
    AssignmentScope.ORG: 0,
    AssignmentScope.LOCATION: 1,
    AssignmentScope.GROUP: 2,
    AssignmentScope.PERSON: 3,
}


class Shift(Base):
    __tablename__ = "shifts"
    __table_args__ = (
        UniqueConstraint("name", name="uq_shifts_name"),
        CheckConstraint("name <> ''", name="name_non_empty"),
    )

    id: Mapped[UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    starts_at: Mapped[time] = mapped_column(Time(timezone=False), nullable=False)
    ends_at: Mapped[time] = mapped_column(Time(timezone=False), nullable=False)
    crosses_midnight: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    grace_in_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    grace_out_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    absent_after_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    auto_close_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()


class Schedule(Base):
    __tablename__ = "schedules"
    __table_args__ = (
        UniqueConstraint("name", name="uq_schedules_name"),
        CheckConstraint("name <> ''", name="name_non_empty"),
    )

    id: Mapped[UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    timezone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()


class ScheduleRule(Base):
    __tablename__ = "schedule_rules"
    __table_args__ = (
        UniqueConstraint("schedule_id", "weekday", name="uq_schedule_rules_schedule_weekday"),
        CheckConstraint("weekday BETWEEN 0 AND 6", name="weekday_range"),
    )

    id: Mapped[UUID] = uuid_pk()
    schedule_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("schedules.id", ondelete="CASCADE"),
        nullable=False,
    )
    shift_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("shifts.id", ondelete="RESTRICT"),
        nullable=True,
    )
    weekday: Mapped[int] = mapped_column(Integer, nullable=False)
    is_working_day: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    period_label: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    created_at: Mapped[datetime] = created_at_column()


class ScheduleAssignment(Base):
    __tablename__ = "schedule_assignments"
    __table_args__ = (
        UniqueConstraint(
            "scope",
            "scope_id",
            "effective_from",
            "schedule_id",
            name="uq_schedule_assignments_scope_effective_schedule",
        ),
        CheckConstraint(
            "effective_to IS NULL OR effective_to >= effective_from",
            name="effective_to_not_before_from",
        ),
        CheckConstraint(
            "scope = 'org' OR scope_id IS NOT NULL",
            name="non_org_scope_requires_scope_id",
        ),
    )

    id: Mapped[UUID] = uuid_pk()
    schedule_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("schedules.id", ondelete="CASCADE"),
        nullable=False,
    )
    scope: Mapped[AssignmentScope] = mapped_column(String(32), nullable=False)
    scope_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = created_at_column()

    def is_effective_on(self, business_date: date) -> bool:
        return self.effective_from <= business_date and (
            self.effective_to is None or business_date <= self.effective_to
        )


class CalendarDay(Base):
    __tablename__ = "calendar_days"
    __table_args__ = (
        UniqueConstraint("location_id", "business_date", name="uq_calendar_days_location_date"),
        CheckConstraint("label <> ''", name="label_non_empty"),
    )

    id: Mapped[UUID] = uuid_pk()
    location_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("locations.id", ondelete="CASCADE"),
        nullable=False,
    )
    business_date: Mapped[date] = mapped_column(Date, nullable=False)
    kind: Mapped[CalendarDayKind] = mapped_column(String(32), nullable=False)
    label: Mapped[str] = mapped_column(String(128), nullable=False)
    is_working_day: Mapped[bool] = mapped_column(Boolean, nullable=False)
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()


class PersonException(Base):
    __tablename__ = "person_exceptions"
    __table_args__ = (
        UniqueConstraint(
            "person_id",
            "business_date",
            "kind",
            name="uq_person_exceptions_person_date_kind",
        ),
        CheckConstraint("reason <> ''", name="reason_non_empty"),
    )

    id: Mapped[UUID] = uuid_pk()
    person_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("people.id", ondelete="CASCADE"),
        nullable=False,
    )
    business_date: Mapped[date] = mapped_column(Date, nullable=False)
    kind: Mapped[PersonExceptionKind] = mapped_column(String(32), nullable=False)
    reason: Mapped[str] = mapped_column(String(512), nullable=False)
    created_by_admin_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()


@dataclass(frozen=True)
class AssignmentContext:
    person_id: UUID
    group_ids: tuple[UUID, ...]
    location_id: UUID


def resolve_schedule_assignment(
    assignments: list[ScheduleAssignment],
    context: AssignmentContext,
    business_date: date,
) -> ScheduleAssignment | None:
    applicable_assignments = [
        assignment
        for assignment in assignments
        if assignment.is_effective_on(business_date)
        and assignment_matches_context(assignment, context)
    ]
    if not applicable_assignments:
        return None
    return max(applicable_assignments, key=assignment_sort_key)


def assignment_matches_context(
    assignment: ScheduleAssignment,
    context: AssignmentContext,
) -> bool:
    if assignment.scope == AssignmentScope.PERSON:
        return assignment.scope_id == context.person_id
    if assignment.scope == AssignmentScope.GROUP:
        return assignment.scope_id in context.group_ids
    if assignment.scope == AssignmentScope.LOCATION:
        return assignment.scope_id == context.location_id
    return assignment.scope == AssignmentScope.ORG


def assignment_sort_key(assignment: ScheduleAssignment) -> tuple[int, int, date]:
    return (
        ASSIGNMENT_SCOPE_PRECEDENCE[assignment.scope],
        assignment.priority,
        assignment.effective_from,
    )
