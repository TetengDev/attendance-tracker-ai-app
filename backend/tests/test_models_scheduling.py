from __future__ import annotations

from datetime import date, time
from typing import Any, cast
from uuid import UUID

from sqlalchemy import Table

from backend.app.models.scheduling import (
    AssignmentContext,
    AssignmentScope,
    CalendarDay,
    CalendarDayKind,
    PersonException,
    PersonExceptionKind,
    Schedule,
    ScheduleAssignment,
    ScheduleRule,
    Shift,
    assignment_matches_context,
    resolve_schedule_assignment,
)

PERSON_ID = UUID("00000000-0000-0000-0000-000000000001")
GROUP_ID = UUID("00000000-0000-0000-0000-000000000002")
LOCATION_ID = UUID("00000000-0000-0000-0000-000000000003")
ORG_SCHEDULE_ID = UUID("00000000-0000-0000-0000-000000000010")
LOCATION_SCHEDULE_ID = UUID("00000000-0000-0000-0000-000000000011")
GROUP_SCHEDULE_ID = UUID("00000000-0000-0000-0000-000000000012")
PERSON_SCHEDULE_ID = UUID("00000000-0000-0000-0000-000000000013")


def test_schedule_assignment_resolution_order_is_person_group_location_org() -> None:
    business_date = date(2026, 7, 31)
    context = AssignmentContext(
        person_id=PERSON_ID,
        group_ids=(GROUP_ID,),
        location_id=LOCATION_ID,
    )
    assignments = [
        ScheduleAssignment(
            schedule_id=ORG_SCHEDULE_ID,
            scope=AssignmentScope.ORG,
            scope_id=None,
            effective_from=date(2026, 1, 1),
        ),
        ScheduleAssignment(
            schedule_id=LOCATION_SCHEDULE_ID,
            scope=AssignmentScope.LOCATION,
            scope_id=LOCATION_ID,
            effective_from=date(2026, 1, 1),
        ),
        ScheduleAssignment(
            schedule_id=GROUP_SCHEDULE_ID,
            scope=AssignmentScope.GROUP,
            scope_id=GROUP_ID,
            effective_from=date(2026, 1, 1),
        ),
        ScheduleAssignment(
            schedule_id=PERSON_SCHEDULE_ID,
            scope=AssignmentScope.PERSON,
            scope_id=PERSON_ID,
            effective_from=date(2026, 1, 1),
        ),
    ]

    selected = resolve_schedule_assignment(assignments, context, business_date)

    assert selected is not None
    assert selected.schedule_id == PERSON_SCHEDULE_ID


def test_schedule_assignment_priority_breaks_ties_within_scope() -> None:
    business_date = date(2026, 7, 31)
    context = AssignmentContext(person_id=PERSON_ID, group_ids=(GROUP_ID,), location_id=LOCATION_ID)
    low_priority = ScheduleAssignment(
        schedule_id=GROUP_SCHEDULE_ID,
        scope=AssignmentScope.GROUP,
        scope_id=GROUP_ID,
        priority=0,
        effective_from=date(2026, 1, 1),
    )
    high_priority = ScheduleAssignment(
        schedule_id=PERSON_SCHEDULE_ID,
        scope=AssignmentScope.GROUP,
        scope_id=GROUP_ID,
        priority=10,
        effective_from=date(2026, 1, 1),
    )

    assert (
        resolve_schedule_assignment(
            [low_priority, high_priority],
            context,
            business_date,
        )
        is high_priority
    )


def test_schedule_assignment_ignores_non_effective_rows() -> None:
    context = AssignmentContext(person_id=PERSON_ID, group_ids=(GROUP_ID,), location_id=LOCATION_ID)
    assignment = ScheduleAssignment(
        schedule_id=PERSON_SCHEDULE_ID,
        scope=AssignmentScope.PERSON,
        scope_id=PERSON_ID,
        effective_from=date(2026, 8, 1),
    )

    assert not assignment.is_effective_on(date(2026, 7, 31))
    assert resolve_schedule_assignment([assignment], context, date(2026, 7, 31)) is None


def test_assignment_matching_uses_scope_specific_context() -> None:
    context = AssignmentContext(person_id=PERSON_ID, group_ids=(GROUP_ID,), location_id=LOCATION_ID)

    assert assignment_matches_context(
        ScheduleAssignment(
            schedule_id=PERSON_SCHEDULE_ID,
            scope=AssignmentScope.PERSON,
            scope_id=PERSON_ID,
            effective_from=date(2026, 1, 1),
        ),
        context,
    )
    assert not assignment_matches_context(
        ScheduleAssignment(
            schedule_id=PERSON_SCHEDULE_ID,
            scope=AssignmentScope.PERSON,
            scope_id=GROUP_ID,
            effective_from=date(2026, 1, 1),
        ),
        context,
    )


def test_shift_model_encodes_timezone_naive_template() -> None:
    shift = Shift(
        name="Morning",
        starts_at=time(8, 0),
        ends_at=time(15, 0),
        crosses_midnight=False,
    )
    columns = cast(Table, Shift.__table__).columns

    assert shift.starts_at.tzinfo is None
    assert cast(Any, columns["starts_at"].type).timezone is False
    assert cast(Any, columns["ends_at"].type).timezone is False


def test_scheduling_models_encode_required_constraints() -> None:
    schedule_rule_constraints = {
        constraint.name for constraint in cast(Table, ScheduleRule.__table__).constraints
    }
    assignment_constraints = {
        constraint.name for constraint in cast(Table, ScheduleAssignment.__table__).constraints
    }
    calendar_constraints = {
        constraint.name for constraint in cast(Table, CalendarDay.__table__).constraints
    }
    exception_constraints = {
        constraint.name for constraint in cast(Table, PersonException.__table__).constraints
    }

    assert "ck_schedule_rules_weekday_range" in schedule_rule_constraints
    assert "ck_schedule_assignments_non_org_scope_requires_scope_id" in assignment_constraints
    assert "uq_calendar_days_location_date" in calendar_constraints
    assert "uq_person_exceptions_person_date_kind" in exception_constraints


def test_calendar_days_and_person_exceptions_are_editable_fact_models() -> None:
    calendar_day = CalendarDay(
        location_id=LOCATION_ID,
        business_date=date(2026, 7, 31),
        kind=CalendarDayKind.HOLIDAY,
        label="Founders Day",
        is_working_day=False,
    )
    exception = PersonException(
        person_id=PERSON_ID,
        business_date=date(2026, 7, 31),
        kind=PersonExceptionKind.EXCUSED,
        reason="Field trip",
    )

    assert calendar_day.is_working_day is False
    assert exception.kind == PersonExceptionKind.EXCUSED


def test_schedule_model_uses_uuid_primary_key() -> None:
    assert cast(Any, Schedule.id).property.columns[0].server_default is not None
