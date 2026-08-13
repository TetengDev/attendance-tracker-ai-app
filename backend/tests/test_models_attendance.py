from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any, cast
from uuid import UUID

from sqlalchemy import Table

from backend.app.attendance.decision_table import AttendanceStatus
from backend.app.db.base import ATTENDANCE_NATURAL_KEY, PER_DAY_PERIOD_LABEL
from backend.app.models.attendance import (
    AttendanceEvent,
    AttendanceEventDirection,
    AttendanceEventOutcome,
    AttendanceGrain,
    AttendanceOverride,
    AttendanceRecord,
    ExpectedAttendance,
    canonical_attendance_grain,
    event_matches_grain,
    grain_for_expected,
    grain_for_override,
    rebuild_attendance_records,
)

PERSON_ID = UUID("00000000-0000-0000-0000-000000000001")
SHIFT_ID = UUID("00000000-0000-0000-0000-000000000002")
DEVICE_ID = UUID("00000000-0000-0000-0000-000000000003")
EXPECTED_ID = UUID("00000000-0000-0000-0000-000000000004")
OVERRIDE_ID = UUID("00000000-0000-0000-0000-000000000005")
OTHER_SHIFT_ID = UUID("00000000-0000-0000-0000-000000000006")
MERGED_PERSON_ID = UUID("00000000-0000-0000-0000-000000000007")
BUSINESS_DATE = date(2026, 7, 31)
CAPTURED_AT = datetime(2026, 7, 31, 0, 0, tzinfo=UTC)
START_AT = datetime(2026, 7, 31, 8, 0, tzinfo=UTC)
END_AT = datetime(2026, 7, 31, 16, 0, tzinfo=UTC)
RESOLVED_AT = datetime(2026, 7, 31, 9, 0, tzinfo=UTC)


def test_attendance_models_define_four_table_split() -> None:
    assert AttendanceEvent.__tablename__ == "attendance_events"
    assert ExpectedAttendance.__tablename__ == "expected_attendance"
    assert AttendanceRecord.__tablename__ == "attendance_records"
    assert AttendanceOverride.__tablename__ == "attendance_overrides"


def test_attendance_event_uses_bigint_identity_and_nullable_business_date() -> None:
    event_columns = cast(Table, AttendanceEvent.__table__).columns
    event_indexes = {index.name for index in cast(Table, AttendanceEvent.__table__).indexes}

    assert event_columns["id"].primary_key
    assert event_columns["id"].identity is not None
    assert event_columns["session_id"].nullable is True
    assert event_columns["business_date"].nullable is True
    assert event_columns["device_local_date"].nullable is True
    assert "ix_attendance_events_session_id" in event_indexes
    assert cast(Any, event_columns["client_captured_at"].type).timezone is True
    assert cast(Any, event_columns["server_received_at"].type).timezone is True
    assert cast(Any, event_columns["occurred_at"].type).timezone is True


def test_attendance_event_constraints_encode_replay_and_score_invariants() -> None:
    constraints = {
        constraint.name for constraint in cast(Table, AttendanceEvent.__table__).constraints
    }

    assert "uq_attendance_events_idempotency_key" in constraints
    assert "ck_attendance_events_idempotency_key_non_empty" in constraints
    assert "ck_attendance_events_monotonic_offset_ms_non_negative" in constraints
    assert "ck_attendance_events_top1_score_probability_range" in constraints
    assert "ck_attendance_events_top2_other_person_score_probability_range" in constraints
    assert "ck_attendance_events_occurred_at_not_after_server_received" in constraints


def test_attendance_grain_tables_share_natural_key_and_period_default() -> None:
    for model in (ExpectedAttendance, AttendanceRecord, AttendanceOverride):
        table = cast(Table, model.__table__)
        constraints = {constraint.name for constraint in table.constraints}

        assert tuple(ATTENDANCE_NATURAL_KEY) == (
            "person_id",
            "business_date",
            "shift_id",
            "period_label",
        )
        assert table.columns["period_label"].nullable is False
        assert table.columns["period_label"].default is not None
        assert cast(Any, table.columns["period_label"].default).arg == PER_DAY_PERIOD_LABEL
        assert f"uq_{model.__tablename__}_natural_key" in constraints


def test_attendance_records_support_pending_without_owning_override_fact() -> None:
    record_columns = cast(Table, AttendanceRecord.__table__).columns

    record = AttendanceRecord(
        person_id=PERSON_ID,
        business_date=BUSINESS_DATE,
        shift_id=SHIFT_ID,
        status=AttendanceStatus.PENDING,
        resolved_at=RESOLVED_AT,
    )

    assert record.status == AttendanceStatus.PENDING
    assert "is_manual_override" not in record_columns
    assert "override_id" in record_columns


def test_attendance_override_has_actor_reason_and_status() -> None:
    override = AttendanceOverride(
        person_id=PERSON_ID,
        business_date=BUSINESS_DATE,
        shift_id=SHIFT_ID,
        status=AttendanceStatus.EXCUSED,
        reason="Approved leave",
        actor_admin_id=UUID("00000000-0000-0000-0000-000000000007"),
    )
    constraints = {
        constraint.name for constraint in cast(Table, AttendanceOverride.__table__).constraints
    }

    assert override.status == AttendanceStatus.EXCUSED
    assert override.reason == "Approved leave"
    assert override.actor_admin_id is not None
    assert "ck_attendance_overrides_reason_non_empty" in constraints


def test_event_matching_uses_resolver_stamped_business_date() -> None:
    grain = AttendanceGrain(PERSON_ID, BUSINESS_DATE, SHIFT_ID)
    event = attendance_event(
        event_id=1,
        person_id=PERSON_ID,
        business_date=BUSINESS_DATE,
        shift_id=SHIFT_ID,
    )
    unresolved_hot_path_event = attendance_event(
        event_id=2,
        person_id=PERSON_ID,
        business_date=None,
        shift_id=SHIFT_ID,
    )

    assert event_matches_grain(event, grain)
    assert not event_matches_grain(unresolved_hot_path_event, grain)


def test_grain_helpers_use_forward_compatible_period_label() -> None:
    expected = expected_attendance()
    override = attendance_override()

    assert grain_for_expected(expected) == AttendanceGrain(
        person_id=PERSON_ID,
        business_date=BUSINESS_DATE,
        shift_id=SHIFT_ID,
        period_label=PER_DAY_PERIOD_LABEL,
    )
    assert grain_for_override(override) == AttendanceGrain(
        person_id=PERSON_ID,
        business_date=BUSINESS_DATE,
        shift_id=SHIFT_ID,
        period_label=PER_DAY_PERIOD_LABEL,
    )


def test_rebuild_records_from_expected_and_events() -> None:
    expected = expected_attendance()
    first_event = attendance_event(
        event_id=1,
        person_id=PERSON_ID,
        business_date=BUSINESS_DATE,
        shift_id=SHIFT_ID,
        occurred_at=START_AT,
    )
    last_event = attendance_event(
        event_id=2,
        person_id=PERSON_ID,
        business_date=BUSINESS_DATE,
        shift_id=SHIFT_ID,
        occurred_at=START_AT + timedelta(minutes=5),
    )

    records = rebuild_attendance_records(
        [expected],
        [last_event, first_event],
        [],
        resolved_at=RESOLVED_AT,
    )

    assert len(records) == 1
    assert records[0].expected_attendance_id == EXPECTED_ID
    assert records[0].status == AttendanceStatus.ON_TIME
    assert records[0].first_event_id == first_event.id
    assert records[0].last_event_id == last_event.id
    assert records[0].override_id is None


def test_rebuild_preserves_override_effect_after_records_are_dropped() -> None:
    expected = expected_attendance()
    override = attendance_override(status=AttendanceStatus.EXCUSED)
    unrelated_event = attendance_event(
        event_id=3,
        person_id=PERSON_ID,
        business_date=BUSINESS_DATE,
        shift_id=OTHER_SHIFT_ID,
    )

    records = rebuild_attendance_records(
        [expected],
        [unrelated_event],
        [override],
        resolved_at=RESOLVED_AT,
    )

    assert len(records) == 1
    assert records[0].override_id == OVERRIDE_ID
    assert records[0].status == AttendanceStatus.EXCUSED
    assert records[0].first_event_id is None
    assert records[0].last_event_id is None


def test_rebuild_attendance_records_collapses_merged_person_rows() -> None:
    survivor_expected = expected_attendance()
    duplicate_expected = expected_attendance(person_id=MERGED_PERSON_ID)
    survivor_event = attendance_event(
        event_id=10,
        person_id=PERSON_ID,
        business_date=BUSINESS_DATE,
        shift_id=SHIFT_ID,
        occurred_at=START_AT,
    )
    duplicate_event = attendance_event(
        event_id=11,
        person_id=MERGED_PERSON_ID,
        business_date=BUSINESS_DATE,
        shift_id=SHIFT_ID,
        occurred_at=START_AT + timedelta(minutes=5),
    )

    records = rebuild_attendance_records(
        [survivor_expected, duplicate_expected],
        [duplicate_event, survivor_event],
        [],
        resolved_at=RESOLVED_AT,
        merged_into={MERGED_PERSON_ID: PERSON_ID},
    )

    assert (
        canonical_attendance_grain(
            AttendanceGrain(MERGED_PERSON_ID, BUSINESS_DATE, SHIFT_ID),
            {MERGED_PERSON_ID: PERSON_ID},
        ).person_id
        == PERSON_ID
    )
    assert len(records) == 1
    assert records[0].person_id == PERSON_ID
    assert records[0].first_event_id == survivor_event.id
    assert records[0].last_event_id == duplicate_event.id


def expected_attendance(*, person_id: UUID = PERSON_ID) -> ExpectedAttendance:
    return ExpectedAttendance(
        id=EXPECTED_ID,
        person_id=person_id,
        business_date=BUSINESS_DATE,
        shift_id=SHIFT_ID,
        expected_start_at=START_AT,
        expected_end_at=END_AT,
        absent_after_at=START_AT + timedelta(minutes=30),
    )


def attendance_override(
    *,
    status: AttendanceStatus = AttendanceStatus.EXCUSED,
) -> AttendanceOverride:
    return AttendanceOverride(
        id=OVERRIDE_ID,
        person_id=PERSON_ID,
        business_date=BUSINESS_DATE,
        shift_id=SHIFT_ID,
        status=status,
        reason="Approved exception",
    )


def attendance_event(
    *,
    event_id: int,
    person_id: UUID | None,
    business_date: date | None,
    shift_id: UUID | None,
    occurred_at: datetime = START_AT,
) -> AttendanceEvent:
    return AttendanceEvent(
        id=event_id,
        idempotency_key=f"event-{event_id}",
        person_id=person_id,
        device_id=DEVICE_ID,
        session_id=None,
        business_date=business_date,
        device_local_date=BUSINESS_DATE,
        shift_id=shift_id,
        direction=AttendanceEventDirection.IN,
        outcome=AttendanceEventOutcome.ACCEPTED,
        client_captured_at=CAPTURED_AT,
        server_received_at=occurred_at,
        occurred_at=occurred_at,
    )
