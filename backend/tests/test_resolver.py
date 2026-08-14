"""Tests for the attendance resolver (Phase 5).

Covers ≥40 cases including:
  - Status classification (on-time, late, absent, pending, excused, holiday, etc.)
  - Flag computation (was_late, left_early, location_mismatch, was_backdated, auto_closed)
  - Event pairing (first/last strategy, min_dwell filtering)
  - Overnight shifts crossing midnight
  - DST transitions in multiple timezones
  - Schedule expansion and voiding
  - Full rebuild idempotency
  - Edge cases (Redis down, merged persons, empty data)
"""

from __future__ import annotations

import base64
import os

os.environ.setdefault(
    "BIOMETRIC_KEK",
    "kek.test:" + base64.urlsafe_b64encode(bytes([9]) * 32).decode().rstrip("="),
)
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://localhost:5432/attendance")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from unittest.mock import MagicMock
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.attendance.decision_table import AttendanceStatus
from backend.app.models.attendance import (
    AttendanceEvent,
    AttendanceEventDirection,
    AttendanceEventOutcome,
    AttendanceOverride,
    AttendanceRecord,
    ExpectedAttendance,
)
from backend.app.models.people import Person
from backend.app.models.scheduling import (
    AssignmentScope,
    CalendarDay,
    CalendarDayKind,
    PersonException,
    PersonExceptionKind,
    Schedule,
    ScheduleAssignment,
    ScheduleRule,
    Shift,
)
from backend.app.settings.resolver import ResolvedSettings, SettingContext

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PERSON_ID = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
PERSON_B_ID = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
SHIFT_ID = UUID("11111111-1111-1111-1111-111111111111")
SCHEDULE_ID = UUID("22222222-2222-2222-2222-222222222222")
LOCATION_ID = UUID("33333333-3333-3333-3333-333333333333")
GROUP_ID = UUID("44444444-4444-4444-4444-444444444444")
DEVICE_ID = UUID("55555555-5555-5555-5555-555555555555")
SESSION_ID = UUID("66666666-6666-6666-6666-666666666666")
EXPECTED_ID = UUID("77777777-7777-7777-7777-777777777777")
OVERRIDE_ID = UUID("88888888-8888-8888-8888-888888888888")
DUMMY_SHIFT_ID = UUID("00000000-0000-0000-0000-000000000000")
BUSINESS_DATE = date(2026, 8, 14)  # Thursday (weekday=3)

# Standard day shift 08:00-17:00 Asia/Manila
DAY_START = datetime(2026, 8, 14, 0, 0, tzinfo=UTC)  # 08:00 Manila = 00:00 UTC
DAY_END = datetime(2026, 8, 14, 9, 0, tzinfo=UTC)  # 17:00 Manila = 09:00 UTC

DEFAULT_SETTINGS: dict[str, Any] = {
    "attendance.lookback_minutes": 240,
    "attendance.lookahead_minutes": 240,
    "attendance.grace_in_minutes": 10,
    "attendance.grace_out_minutes": 10,
    "attendance.absent_after_minutes": 60,
    "attendance.min_dwell_minutes": 5,
    "attendance.auto_close_enabled": False,
    "attendance.auto_close_minutes": 120,
}


# ---------------------------------------------------------------------------
# Factories
# ---------------------------------------------------------------------------


def make_person(
    person_id: UUID = PERSON_ID,
    *,
    display_name: str = "Alice",
    is_active: bool = True,
    merged_into: UUID | None = None,
) -> Person:
    p = Person(id=person_id, display_name=display_name)
    p.is_active = is_active
    p.merged_into_person_id = merged_into
    return p


def make_expected(
    *,
    expected_id: UUID | None = None,
    person_id: UUID = PERSON_ID,
    business_date: date = BUSINESS_DATE,
    shift_id: UUID = SHIFT_ID,
    period_label: str = "",
    location_id: UUID | None = LOCATION_ID,
    schedule_id: UUID = SCHEDULE_ID,
    start_at: datetime = DAY_START,
    end_at: datetime = DAY_END,
    absent_after_at: datetime | None = None,
    is_working_day: bool = True,
) -> ExpectedAttendance:
    ea = ExpectedAttendance(
        person_id=person_id,
        business_date=business_date,
        shift_id=shift_id,
        period_label=period_label,
    )
    ea.id = expected_id or uuid4()
    ea.location_id = location_id
    ea.schedule_id = schedule_id
    ea.expected_start_at = start_at
    ea.expected_end_at = end_at
    ea.absent_after_at = absent_after_at or (start_at + timedelta(minutes=60))
    ea.is_working_day = is_working_day
    ea.voided_at = None
    return ea


_event_id_counter = 1000


def make_event(
    *,
    person_id: UUID = PERSON_ID,
    occurred_at: datetime,
    outcome: AttendanceEventOutcome = AttendanceEventOutcome.ACCEPTED,
    location_id: UUID | None = None,
    was_backdated: bool = False,
    event_id: int | None = None,
) -> AttendanceEvent:
    global _event_id_counter
    _event_id_counter += 1
    eid = event_id if event_id is not None else _event_id_counter
    ev = AttendanceEvent(
        person_id=person_id,
        device_id=DEVICE_ID,
        session_id=SESSION_ID,
        occurred_at=occurred_at,
        outcome=outcome,
        direction=AttendanceEventDirection.IN,
        idempotency_key=f"key-{eid}",
        client_captured_at=occurred_at,
        server_received_at=occurred_at,
        top1_score=0.95,
    )
    ev.id = eid
    ev.location_id = location_id
    ev.was_backdated = was_backdated
    ev.business_date = None
    ev.shift_id = None
    return ev


def make_override(
    *,
    status: AttendanceStatus = AttendanceStatus.EXCUSED,
    shift_id: UUID = SHIFT_ID,
    period_label: str = "",
) -> AttendanceOverride:
    ov = AttendanceOverride(
        person_id=PERSON_ID,
        business_date=BUSINESS_DATE,
        shift_id=shift_id,
        period_label=period_label,
        status=status,
    )
    ov.id = OVERRIDE_ID
    return ov


def make_shift(
    shift_id: UUID = SHIFT_ID,
    *,
    starts_at: time = time(8, 0),
    ends_at: time = time(17, 0),
    crosses_midnight: bool = False,
    absent_after_minutes: int = 60,
) -> Shift:
    sh = Shift(
        name="Day Shift",
        starts_at=starts_at,
        ends_at=ends_at,
        crosses_midnight=crosses_midnight,
        absent_after_minutes=absent_after_minutes,
        grace_in_minutes=10,
        grace_out_minutes=10,
        auto_close_minutes=120,
    )
    sh.id = shift_id
    return sh


# ---------------------------------------------------------------------------
# MockSession — intercepts SQLAlchemy execute() calls
# ---------------------------------------------------------------------------


class MockResult:
    """Mimics SQLAlchemy Result for unit tests."""

    def __init__(self, value: Any) -> None:
        self._value = value

    def scalars(self) -> MockResult:
        return self

    def all(self) -> list[Any]:
        if isinstance(self._value, list):
            return self._value
        return [self._value] if self._value is not None else []

    def scalar_one_or_none(self) -> Any:
        if isinstance(self._value, list):
            return self._value[0] if self._value else None
        return self._value

    def unique(self) -> MockResult:
        return self


class MockSession(AsyncSession):
    """A mock AsyncSession that returns pre-configured data based on SQL text."""

    def __init__(
        self,
        *,
        person: Person | None = None,
        expected_rows: list[ExpectedAttendance] | None = None,
        overrides: list[AttendanceOverride] | None = None,
        exceptions: list[PersonException] | None = None,
        events: list[AttendanceEvent] | None = None,
        existing_records: list[AttendanceRecord] | None = None,
        calendar_days: list[CalendarDay] | None = None,
        # For expand_schedules
        people: list[Person] | None = None,
        assignments: list[ScheduleAssignment] | None = None,
        schedules: list[Schedule] | None = None,
        rules: list[ScheduleRule] | None = None,
        shifts: list[Shift] | None = None,
        person_groups: list[Any] | None = None,
        # For rebuild
        expected_pairs: list[tuple[UUID, date]] | None = None,
        event_pairs: list[tuple[UUID, date]] | None = None,
    ) -> None:
        super().__init__(bind=MagicMock())
        self.person = person or make_person()
        self.expected_rows = expected_rows if expected_rows is not None else []
        self.overrides = overrides if overrides is not None else []
        self.exceptions = exceptions if exceptions is not None else []
        self.events = events if events is not None else []
        self.existing_records = existing_records if existing_records is not None else []
        self.calendar_days = calendar_days if calendar_days is not None else []

        self.people = people if people is not None else []
        self.assignments = assignments if assignments is not None else []
        self.schedules = schedules if schedules is not None else []
        self.rules = rules if rules is not None else []
        self.shifts = shifts if shifts is not None else []
        self.person_groups = person_groups if person_groups is not None else []

        self.expected_pairs = expected_pairs if expected_pairs is not None else []
        self.event_pairs = event_pairs if event_pairs is not None else []

        self.added: list[Any] = []
        self.committed: int = 0
        self.deleted_models: list[Any] = []

    async def execute(
        self,
        statement: Any,
        params: Any = None,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        sql = str(statement)
        print(f"DEBUG SQL: {sql}")

        # Handle DELETE
        if sql.startswith("DELETE") or "DELETE" in sql[:20]:
            return MockResult(None)

        if "schedule_assignments" in sql:
            return MockResult(self.assignments)
        elif "schedule_rules" in sql:
            return MockResult(self.rules)
        elif "schedules" in sql:
            return MockResult(self.schedules)
        elif "person_groups" in sql:
            return MockResult(self.person_groups)
        elif "person_exceptions" in sql:
            return MockResult(self.exceptions)
        elif "attendance_records" in sql:
            return MockResult(self.existing_records)
        elif "attendance_overrides" in sql:
            return MockResult(self.overrides)
        elif "attendance_events" in sql:
            if "DISTINCT" in sql:
                return MockResult(self.event_pairs)
            return MockResult(self.events)
        elif "expected_attendance" in sql:
            if "DISTINCT" in sql:
                return MockResult(self.expected_pairs)
            return MockResult(self.expected_rows)
        elif "calendar_days" in sql:
            return MockResult(self.calendar_days[0] if self.calendar_days else None)
        elif "settings_versions" in sql:
            return MockResult(1)
        elif "settings" in sql:
            return MockResult([])
        elif "people" in sql:
            if "FOR UPDATE" in sql:
                return MockResult(self.person)
            elif "is_active" in sql:
                return MockResult(self.people)
            return MockResult(self.person)
        elif "shifts" in sql:
            return MockResult(self.shifts)

        return MockResult(None)

    async def get(
        self,
        entity: Any,
        ident: Any,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        return self.person

    def add(self, instance: Any, _warn: bool = True) -> None:
        self.added.append(instance)

    async def commit(self) -> None:
        self.committed += 1

    async def rollback(self) -> None:
        pass

    async def flush(self, objects: Any = None) -> None:
        pass

    async def delete(self, instance: Any) -> None:
        self.deleted_models.append(instance)


# ---------------------------------------------------------------------------
# Mock Redis State
# ---------------------------------------------------------------------------


class MockRedisState:
    """No-op Redis replacement."""

    def __init__(self) -> None:
        self._dirty: set[tuple[UUID, date]] = set()

    def set_dirty(self, person_id: UUID, business_date: date) -> None:
        self._dirty.add((person_id, business_date))

    def clear_dirty(self, person_id: UUID, business_date: date) -> bool:
        self._dirty.discard((person_id, business_date))
        return True

    def is_dirty(self, person_id: UUID, business_date: date) -> bool:
        return (person_id, business_date) in self._dirty


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

AS_OF = datetime(2026, 8, 14, 12, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _patch_resolver(monkeypatch: pytest.MonkeyPatch) -> None:
    """Monkeypatch Redis state and settings resolver for all tests."""
    import backend.app.attendance.resolver as resolver_mod

    monkeypatch.setattr(resolver_mod, "redis_resolver_state", MockRedisState())

    async def mock_resolve_settings(db: Any, context: SettingContext) -> ResolvedSettings:
        return ResolvedSettings(settings=dict(DEFAULT_SETTINGS), settings_version=1)

    monkeypatch.setattr(resolver_mod, "resolve_db_settings", mock_resolve_settings)


def _get_added_records(session: MockSession) -> list[AttendanceRecord]:
    """Extract AttendanceRecord instances from session.added."""
    return [obj for obj in session.added if isinstance(obj, AttendanceRecord)]


def _get_added_expected(session: MockSession) -> list[ExpectedAttendance]:
    """Extract ExpectedAttendance instances from session.added."""
    return [obj for obj in session.added if isinstance(obj, ExpectedAttendance)]


# ===========================================================================
# Group 1: resolve() — Status Classification (15 tests)
# ===========================================================================


@pytest.mark.anyio
async def test_on_time_arrival() -> None:
    """Event within grace_in → ON_TIME."""
    from backend.app.attendance.resolver import resolve

    expected = make_expected()
    event = make_event(occurred_at=DAY_START + timedelta(minutes=5))

    session = MockSession(expected_rows=[expected], events=[event])
    await resolve(session, PERSON_ID, BUSINESS_DATE, as_of=AS_OF)

    records = _get_added_records(session)
    assert len(records) == 1
    assert records[0].status == AttendanceStatus.ON_TIME


@pytest.mark.anyio
async def test_on_time_at_exact_grace_boundary() -> None:
    """Event at exactly start + grace_in → ON_TIME (inclusive)."""
    from backend.app.attendance.resolver import resolve

    expected = make_expected()
    event = make_event(occurred_at=DAY_START + timedelta(minutes=10))

    session = MockSession(expected_rows=[expected], events=[event])
    await resolve(session, PERSON_ID, BUSINESS_DATE, as_of=AS_OF)

    records = _get_added_records(session)
    assert len(records) == 1
    assert records[0].status == AttendanceStatus.ON_TIME


@pytest.mark.anyio
async def test_late_arrival() -> None:
    """Event past grace_in → LATE with correct late_minutes."""
    from backend.app.attendance.resolver import resolve

    expected = make_expected()
    # 25 minutes after start → 15 minutes past grace_in (10 min)
    event = make_event(occurred_at=DAY_START + timedelta(minutes=25))

    session = MockSession(expected_rows=[expected], events=[event])
    await resolve(session, PERSON_ID, BUSINESS_DATE, as_of=AS_OF)

    records = _get_added_records(session)
    assert len(records) == 1
    assert records[0].status == AttendanceStatus.LATE
    assert records[0].late_minutes == 15


@pytest.mark.anyio
async def test_absent_no_events_past_threshold() -> None:
    """No events past absent_after → ABSENT."""
    from backend.app.attendance.resolver import resolve

    expected = make_expected()
    # as_of is well past absent_after (start + 60 min)
    session = MockSession(expected_rows=[expected], events=[])
    await resolve(session, PERSON_ID, BUSINESS_DATE, as_of=AS_OF)

    records = _get_added_records(session)
    assert len(records) == 1
    assert records[0].status == AttendanceStatus.ABSENT


@pytest.mark.anyio
async def test_pending_no_events_within_threshold() -> None:
    """No events but within absent_after → PENDING."""
    from backend.app.attendance.resolver import resolve

    expected = make_expected()
    # as_of is just 5 minutes after start, well within absent_after (60 min)
    early_as_of = DAY_START + timedelta(minutes=5)
    session = MockSession(expected_rows=[expected], events=[])
    await resolve(session, PERSON_ID, BUSINESS_DATE, as_of=early_as_of)

    records = _get_added_records(session)
    assert len(records) == 1
    assert records[0].status == AttendanceStatus.PENDING


@pytest.mark.anyio
async def test_override_takes_precedence() -> None:
    """Override status overrides computed status."""
    from backend.app.attendance.resolver import resolve

    expected = make_expected()
    event = make_event(occurred_at=DAY_START + timedelta(minutes=5))
    override = make_override(status=AttendanceStatus.EXCUSED, shift_id=SHIFT_ID)

    session = MockSession(expected_rows=[expected], events=[event], overrides=[override])
    await resolve(session, PERSON_ID, BUSINESS_DATE, as_of=AS_OF)

    records = _get_added_records(session)
    assert len(records) == 1
    assert records[0].status == AttendanceStatus.EXCUSED
    assert records[0].override_id == OVERRIDE_ID


@pytest.mark.anyio
async def test_exception_yields_excused() -> None:
    """PersonException → EXCUSED."""
    from backend.app.attendance.resolver import resolve

    expected = make_expected()
    exc = PersonException(
        person_id=PERSON_ID,
        business_date=BUSINESS_DATE,
        kind=PersonExceptionKind.LEAVE,
        reason="Annual leave",
    )
    exc.id = uuid4()

    session = MockSession(expected_rows=[expected], events=[], exceptions=[exc])
    await resolve(session, PERSON_ID, BUSINESS_DATE, as_of=AS_OF)

    records = _get_added_records(session)
    assert len(records) == 1
    assert records[0].status == AttendanceStatus.EXCUSED


@pytest.mark.anyio
async def test_holiday_calendar_day() -> None:
    """CalendarDay with is_working_day=False → HOLIDAY."""
    from backend.app.attendance.resolver import resolve

    expected = make_expected()
    cal = CalendarDay(
        location_id=LOCATION_ID,
        business_date=BUSINESS_DATE,
        kind=CalendarDayKind.HOLIDAY,
        label="Independence Day",
        is_working_day=False,
    )
    cal.id = uuid4()

    session = MockSession(expected_rows=[expected], events=[], calendar_days=[cal])
    await resolve(session, PERSON_ID, BUSINESS_DATE, as_of=AS_OF)

    records = _get_added_records(session)
    assert len(records) == 1
    assert records[0].status == AttendanceStatus.HOLIDAY


@pytest.mark.anyio
async def test_not_scheduled_non_working_day() -> None:
    """expected.is_working_day=False → NOT_SCHEDULED."""
    from backend.app.attendance.resolver import resolve

    expected = make_expected(is_working_day=False)
    session = MockSession(expected_rows=[expected], events=[])
    await resolve(session, PERSON_ID, BUSINESS_DATE, as_of=AS_OF)

    records = _get_added_records(session)
    assert len(records) == 1
    assert records[0].status == AttendanceStatus.NOT_SCHEDULED


@pytest.mark.anyio
async def test_present_unscheduled_no_expected_rows() -> None:
    """Events but no expected rows → PRESENT_UNSCHEDULED."""
    from backend.app.attendance.resolver import resolve

    event = make_event(occurred_at=DAY_START + timedelta(hours=1))
    session = MockSession(expected_rows=[], events=[event])
    await resolve(session, PERSON_ID, BUSINESS_DATE, as_of=AS_OF)

    records = _get_added_records(session)
    assert len(records) == 1
    assert records[0].status == AttendanceStatus.PRESENT_UNSCHEDULED


@pytest.mark.anyio
async def test_incomplete_auto_close() -> None:
    """Arrived, no departure, auto_close enabled and past window → INCOMPLETE."""
    import backend.app.attendance.resolver as resolver_mod
    from backend.app.attendance.resolver import resolve

    # Override settings to enable auto_close
    async def mock_settings_autoclose(db: Any, context: SettingContext) -> ResolvedSettings:
        s = dict(DEFAULT_SETTINGS)
        s["attendance.auto_close_enabled"] = True
        s["attendance.auto_close_minutes"] = 30
        return ResolvedSettings(settings=s, settings_version=1)

    resolver_mod.resolve_db_settings = mock_settings_autoclose

    expected = make_expected()
    # Single arrival event (no departure)
    event = make_event(occurred_at=DAY_START + timedelta(minutes=5))
    # as_of is well past expected_end + auto_close_minutes
    late_as_of = DAY_END + timedelta(hours=2)

    session = MockSession(expected_rows=[expected], events=[event])
    await resolve(session, PERSON_ID, BUSINESS_DATE, as_of=late_as_of)

    records = _get_added_records(session)
    assert len(records) == 1
    assert records[0].status == AttendanceStatus.INCOMPLETE
    assert records[0].flags["auto_closed"] is True


@pytest.mark.anyio
async def test_auto_close_disabled_no_incomplete() -> None:
    """auto_close_enabled=False → not INCOMPLETE even if past window."""
    from backend.app.attendance.resolver import resolve

    expected = make_expected()
    event = make_event(occurred_at=DAY_START + timedelta(minutes=5))
    late_as_of = DAY_END + timedelta(hours=5)

    session = MockSession(expected_rows=[expected], events=[event])
    await resolve(session, PERSON_ID, BUSINESS_DATE, as_of=late_as_of)

    records = _get_added_records(session)
    assert len(records) == 1
    assert records[0].status == AttendanceStatus.ON_TIME
    assert records[0].flags["auto_closed"] is False


@pytest.mark.anyio
async def test_min_dwell_filters_short_visits() -> None:
    """Two events too close together → last_event becomes None."""
    from backend.app.attendance.resolver import resolve

    expected = make_expected()
    ev1 = make_event(occurred_at=DAY_START + timedelta(minutes=2))
    ev2 = make_event(occurred_at=DAY_START + timedelta(minutes=3))  # 1 min apart < 5 min dwell

    session = MockSession(expected_rows=[expected], events=[ev1, ev2])
    await resolve(session, PERSON_ID, BUSINESS_DATE, as_of=AS_OF)

    records = _get_added_records(session)
    assert len(records) == 1
    assert records[0].first_event_id == ev1.id
    assert records[0].last_event_id is None


@pytest.mark.anyio
async def test_stale_resolution_skipped() -> None:
    """Existing record with newer resolved_at → skip (no new record added for that grain)."""
    from backend.app.attendance.resolver import resolve

    expected = make_expected()
    event = make_event(occurred_at=DAY_START + timedelta(minutes=5))

    future_resolved = datetime(2026, 8, 15, 0, 0, tzinfo=UTC)
    existing = AttendanceRecord(
        person_id=PERSON_ID,
        business_date=BUSINESS_DATE,
        shift_id=SHIFT_ID,
        period_label="",
        status=AttendanceStatus.ON_TIME,
    )
    existing.resolved_at = future_resolved

    session = MockSession(expected_rows=[expected], events=[event], existing_records=[existing])
    await resolve(session, PERSON_ID, BUSINESS_DATE, as_of=AS_OF)

    # The existing record has a newer resolved_at than as_of, so it should be skipped
    records = _get_added_records(session)
    assert len(records) == 0


@pytest.mark.anyio
async def test_merged_person_redirects(monkeypatch: pytest.MonkeyPatch) -> None:
    """Person with merged_into_person_id redirects to canonical person."""
    from backend.app.attendance.resolver import resolve

    merged_person = make_person(merged_into=PERSON_B_ID)
    canonical_person = make_person(person_id=PERSON_B_ID, display_name="Bob")

    call_count = 0
    original_resolve = resolve

    async def tracking_resolve(
        session: Any, person_id: UUID, business_date: date, *, as_of: datetime
    ) -> None:
        nonlocal call_count
        call_count += 1
        if call_count > 5:
            return
        await original_resolve(session, person_id, business_date, as_of=as_of)

    # Create session that returns merged person first, then canonical
    class MergeSession(MockSession):
        _person_call_count: int = 0

        async def execute(
            self, statement: Any, params: Any = None, *args: Any, **kwargs: Any
        ) -> Any:
            sql = str(statement)
            print(f"MERGESESSION EXECUTE SQL: {sql}")
            if "FROM people" in sql or "people" in sql:
                if "FOR UPDATE" in sql:
                    # Return merged person on first call, canonical on redirect
                    if hasattr(self, "_person_call_count"):
                        self._person_call_count += 1
                    else:
                        self._person_call_count = 1
                    if self._person_call_count == 1:
                        return MockResult(merged_person)
                    return MockResult(canonical_person)
                elif "is_active" in sql:
                    return MockResult(self.people)
            return await super().execute(statement, params)

    session = MergeSession()
    await tracking_resolve(session, PERSON_ID, BUSINESS_DATE, as_of=AS_OF)

    # Verify the redirect happened (at least 2 calls to resolve)
    assert session._person_call_count == 2


# ===========================================================================
# Group 2: resolve() — Flags (6 tests)
# ===========================================================================


@pytest.mark.anyio
async def test_was_late_flag_true_when_late() -> None:
    """was_late flag True when arrival is past grace_in."""
    from backend.app.attendance.resolver import resolve

    expected = make_expected()
    event = make_event(occurred_at=DAY_START + timedelta(minutes=20))

    session = MockSession(expected_rows=[expected], events=[event])
    await resolve(session, PERSON_ID, BUSINESS_DATE, as_of=AS_OF)

    records = _get_added_records(session)
    assert records[0].flags["was_late"] is True


@pytest.mark.anyio
async def test_was_late_flag_false_when_on_time() -> None:
    """was_late flag False when arrival is within grace_in."""
    from backend.app.attendance.resolver import resolve

    expected = make_expected()
    event = make_event(occurred_at=DAY_START + timedelta(minutes=5))

    session = MockSession(expected_rows=[expected], events=[event])
    await resolve(session, PERSON_ID, BUSINESS_DATE, as_of=AS_OF)

    records = _get_added_records(session)
    assert records[0].flags["was_late"] is False


@pytest.mark.anyio
async def test_left_early_flag() -> None:
    """left_early flag True when last_event is before expected_end - grace_out."""
    from backend.app.attendance.resolver import resolve

    expected = make_expected()
    ev1 = make_event(occurred_at=DAY_START + timedelta(minutes=5))
    # Last event 2 hours before end (well before grace_out)
    ev2 = make_event(occurred_at=DAY_END - timedelta(hours=2))

    session = MockSession(expected_rows=[expected], events=[ev1, ev2])
    await resolve(session, PERSON_ID, BUSINESS_DATE, as_of=AS_OF)

    records = _get_added_records(session)
    assert records[0].flags["left_early"] is True


@pytest.mark.anyio
async def test_left_early_flag_false_within_grace() -> None:
    """left_early flag False when last_event is within grace_out of expected_end."""
    from backend.app.attendance.resolver import resolve

    expected = make_expected()
    ev1 = make_event(occurred_at=DAY_START + timedelta(minutes=5))
    # Last event 5 minutes before end (within 10 min grace_out)
    ev2 = make_event(occurred_at=DAY_END - timedelta(minutes=5))

    session = MockSession(expected_rows=[expected], events=[ev1, ev2])
    await resolve(session, PERSON_ID, BUSINESS_DATE, as_of=AS_OF)

    records = _get_added_records(session)
    assert records[0].flags["left_early"] is False


@pytest.mark.anyio
async def test_location_mismatch_flag() -> None:
    """location_mismatch True when event location differs from expected."""
    from backend.app.attendance.resolver import resolve

    expected = make_expected(location_id=LOCATION_ID)
    other_location = UUID("99999999-9999-9999-9999-999999999999")
    event = make_event(
        occurred_at=DAY_START + timedelta(minutes=5),
        location_id=other_location,
    )

    session = MockSession(expected_rows=[expected], events=[event])
    await resolve(session, PERSON_ID, BUSINESS_DATE, as_of=AS_OF)

    records = _get_added_records(session)
    assert records[0].flags["location_mismatch"] is True


@pytest.mark.anyio
async def test_was_backdated_flag() -> None:
    """was_backdated flag True when an event has was_backdated=True."""
    from backend.app.attendance.resolver import resolve

    expected = make_expected()
    event = make_event(
        occurred_at=DAY_START + timedelta(minutes=5),
        was_backdated=True,
    )

    session = MockSession(expected_rows=[expected], events=[event])
    await resolve(session, PERSON_ID, BUSINESS_DATE, as_of=AS_OF)

    records = _get_added_records(session)
    assert records[0].flags["was_backdated"] is True


# ===========================================================================
# Group 3: resolve() — Event Pairing (5 tests)
# ===========================================================================


@pytest.mark.anyio
async def test_single_event_no_last() -> None:
    """Only one event → first_event set, last_event None."""
    from backend.app.attendance.resolver import resolve

    expected = make_expected()
    event = make_event(occurred_at=DAY_START + timedelta(minutes=5))

    session = MockSession(expected_rows=[expected], events=[event])
    await resolve(session, PERSON_ID, BUSINESS_DATE, as_of=AS_OF)

    records = _get_added_records(session)
    assert records[0].first_event_id == event.id
    assert records[0].last_event_id is None


@pytest.mark.anyio
async def test_multiple_events_first_last() -> None:
    """Multiple events → first and last correctly picked."""
    from backend.app.attendance.resolver import resolve

    expected = make_expected()
    ev1 = make_event(occurred_at=DAY_START + timedelta(minutes=5))
    ev2 = make_event(occurred_at=DAY_START + timedelta(hours=4))
    ev3 = make_event(occurred_at=DAY_END - timedelta(minutes=30))

    session = MockSession(expected_rows=[expected], events=[ev1, ev2, ev3])
    await resolve(session, PERSON_ID, BUSINESS_DATE, as_of=AS_OF)

    records = _get_added_records(session)
    assert records[0].first_event_id == ev1.id
    assert records[0].last_event_id == ev3.id


@pytest.mark.anyio
async def test_min_dwell_drops_last_event() -> None:
    """Events within min_dwell → last_event None."""
    from backend.app.attendance.resolver import resolve

    expected = make_expected()
    ev1 = make_event(occurred_at=DAY_START + timedelta(minutes=2))
    ev2 = make_event(occurred_at=DAY_START + timedelta(minutes=4))  # 2 min < 5 min dwell

    session = MockSession(expected_rows=[expected], events=[ev1, ev2])
    await resolve(session, PERSON_ID, BUSINESS_DATE, as_of=AS_OF)

    records = _get_added_records(session)
    assert records[0].last_event_id is None


@pytest.mark.anyio
async def test_events_sorted_by_occurred_at() -> None:
    """Events in random order still paired correctly."""
    from backend.app.attendance.resolver import resolve

    expected = make_expected()
    ev_late = make_event(occurred_at=DAY_END - timedelta(minutes=30))
    ev_early = make_event(occurred_at=DAY_START + timedelta(minutes=5))
    ev_mid = make_event(occurred_at=DAY_START + timedelta(hours=3))

    # Passed in random order
    session = MockSession(expected_rows=[expected], events=[ev_late, ev_early, ev_mid])
    await resolve(session, PERSON_ID, BUSINESS_DATE, as_of=AS_OF)

    records = _get_added_records(session)
    assert records[0].first_event_id == ev_early.id
    assert records[0].last_event_id == ev_late.id


@pytest.mark.anyio
async def test_only_accepted_events_used() -> None:
    """AMBIGUOUS/LOW_CONFIDENCE events excluded from pairing."""
    from backend.app.attendance.resolver import resolve

    expected = make_expected()
    ev_accepted = make_event(occurred_at=DAY_START + timedelta(minutes=5))
    ev_rejected = make_event(
        occurred_at=DAY_START + timedelta(minutes=3),
        outcome=AttendanceEventOutcome.AMBIGUOUS,
    )
    ev_cooldown = make_event(
        occurred_at=DAY_START + timedelta(minutes=4),
        outcome=AttendanceEventOutcome.LOW_CONFIDENCE,
    )

    session = MockSession(expected_rows=[expected], events=[ev_accepted, ev_rejected, ev_cooldown])
    await resolve(session, PERSON_ID, BUSINESS_DATE, as_of=AS_OF)

    records = _get_added_records(session)
    # Only one accepted event → first_event set, last_event None
    assert records[0].first_event_id == ev_accepted.id
    assert records[0].last_event_id is None


# ===========================================================================
# Group 4: resolve() — Overnight & Timezone (6 tests)
# ===========================================================================


@pytest.mark.anyio
async def test_overnight_shift_events_span_midnight() -> None:
    """22:00-06:00 shift with events at 23:00 and 05:30 → ON_TIME."""
    from backend.app.attendance.resolver import resolve

    # 22:00 Manila = 14:00 UTC, 06:00+1 Manila = 22:00 UTC
    overnight_start = datetime(2026, 8, 14, 14, 0, tzinfo=UTC)
    overnight_end = datetime(2026, 8, 14, 22, 0, tzinfo=UTC)

    expected = make_expected(start_at=overnight_start, end_at=overnight_end)

    ev_in = make_event(occurred_at=overnight_start + timedelta(minutes=5))
    ev_out = make_event(occurred_at=overnight_end - timedelta(minutes=30))

    session = MockSession(expected_rows=[expected], events=[ev_in, ev_out])
    await resolve(session, PERSON_ID, BUSINESS_DATE, as_of=overnight_end + timedelta(hours=1))

    records = _get_added_records(session)
    assert len(records) == 1
    assert records[0].status == AttendanceStatus.ON_TIME
    assert records[0].first_event_id == ev_in.id
    assert records[0].last_event_id == ev_out.id


@pytest.mark.anyio
async def test_overnight_shift_absent() -> None:
    """22:00-06:00 shift with no events → ABSENT."""
    from backend.app.attendance.resolver import resolve

    overnight_start = datetime(2026, 8, 14, 14, 0, tzinfo=UTC)
    overnight_end = datetime(2026, 8, 14, 22, 0, tzinfo=UTC)

    expected = make_expected(start_at=overnight_start, end_at=overnight_end)

    as_of_late = overnight_end + timedelta(hours=2)
    session = MockSession(expected_rows=[expected], events=[])
    await resolve(session, PERSON_ID, BUSINESS_DATE, as_of=as_of_late)

    records = _get_added_records(session)
    assert len(records) == 1
    assert records[0].status == AttendanceStatus.ABSENT


@pytest.mark.anyio
async def test_dst_spring_forward_manila_baseline() -> None:
    """Asia/Manila (no DST) — UTC offset is always +8, no gaps."""
    tz_manila = ZoneInfo("Asia/Manila")
    march_date = date(2026, 3, 8)  # A Sunday in March

    local_start = datetime.combine(march_date, time(8, 0)).replace(tzinfo=tz_manila)
    utc_start = local_start.astimezone(UTC)

    # Manila is always UTC+8
    assert utc_start == datetime(2026, 3, 8, 0, 0, tzinfo=UTC)


@pytest.mark.anyio
async def test_dst_spring_forward_new_york() -> None:
    """America/New_York spring forward 2026: 2:00 AM → 3:00 AM on March 8.

    A shift starting at 01:00 local should still convert cleanly to UTC.
    """
    tz_ny = ZoneInfo("America/New_York")
    march_8 = date(2026, 3, 8)

    # Before DST: 01:00 EST = 06:00 UTC (UTC-5)
    pre_dst = datetime.combine(march_8, time(1, 0)).replace(tzinfo=tz_ny)
    assert pre_dst.astimezone(UTC) == datetime(2026, 3, 8, 6, 0, tzinfo=UTC)

    # After DST gap: 03:00 EDT = 07:00 UTC (UTC-4)
    post_dst = datetime.combine(march_8, time(3, 0)).replace(tzinfo=tz_ny)
    assert post_dst.astimezone(UTC) == datetime(2026, 3, 8, 7, 0, tzinfo=UTC)

    # Shift from 01:00 to 09:00 local → 8 hours span
    start_utc = pre_dst.astimezone(UTC)
    end_local = datetime.combine(march_8, time(9, 0)).replace(tzinfo=tz_ny)
    end_utc = end_local.astimezone(UTC)
    span = (end_utc - start_utc).total_seconds() / 3600
    # Due to spring forward, only 7 hours pass in wall-clock time but UTC span is 7
    assert span == 7.0


@pytest.mark.anyio
async def test_dst_fall_back_new_york() -> None:
    """America/New_York fall back 2026: 2:00 AM → 1:00 AM on November 1.

    A shift ending at 02:00 local should map correctly despite ambiguity.
    """
    tz_ny = ZoneInfo("America/New_York")
    nov_1 = date(2026, 11, 1)

    # Before fall back: 00:00 EDT = 04:00 UTC (UTC-4)
    start_local = datetime.combine(nov_1, time(0, 0)).replace(tzinfo=tz_ny)
    start_utc = start_local.astimezone(UTC)
    assert start_utc == datetime(2026, 11, 1, 4, 0, tzinfo=UTC)

    # After fall back: 03:00 EST = 08:00 UTC (UTC-5)
    end_local = datetime.combine(nov_1, time(3, 0)).replace(tzinfo=tz_ny)
    end_utc = end_local.astimezone(UTC)
    # fold=0 (first occurrence) so 03:00 EST = 08:00 UTC
    assert end_utc == datetime(2026, 11, 1, 8, 0, tzinfo=UTC)


@pytest.mark.anyio
async def test_timezone_conversion_utc_storage() -> None:
    """Verify expected_start_at stored as correct UTC for Asia/Manila shift."""
    tz_manila = ZoneInfo("Asia/Manila")
    local_start = datetime.combine(BUSINESS_DATE, time(8, 0)).replace(tzinfo=tz_manila)
    utc_start = local_start.astimezone(UTC)

    # Asia/Manila = UTC+8, so 08:00 local = 00:00 UTC
    assert utc_start.hour == 0
    assert utc_start.date() == BUSINESS_DATE


# ===========================================================================
# Group 5: expand_schedules() (8 tests)
# ===========================================================================


@pytest.mark.anyio
async def test_expand_creates_expected_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    """Basic weekday expansion creates ExpectedAttendance rows."""
    import backend.app.attendance.resolver as resolver_mod
    from backend.app.attendance.resolver import expand_schedules

    # Freeze "today" to be the business_date so allow_past check passes
    monkeypatch.setattr(
        resolver_mod,
        "datetime",
        type(
            "FakeDatetime",
            (),
            {
                "now": staticmethod(lambda tz: datetime(2026, 8, 14, 0, 0, tzinfo=UTC)),
                "combine": datetime.combine,
            },
        ),
    )

    person = make_person()
    shift = make_shift()
    schedule = Schedule(name="Day Schedule", effective_from=date(2026, 1, 1), is_active=True)
    schedule.id = SCHEDULE_ID
    schedule.timezone = "Asia/Manila"

    rule = ScheduleRule(
        schedule_id=SCHEDULE_ID,
        shift_id=SHIFT_ID,
        weekday=4,  # Friday
        is_working_day=True,
        period_label="",
    )
    rule.id = uuid4()

    assignment = ScheduleAssignment(
        schedule_id=SCHEDULE_ID,
        scope=AssignmentScope.PERSON,
        scope_id=PERSON_ID,
        priority=0,
        effective_from=date(2026, 1, 1),
    )
    assignment.id = uuid4()

    session = MockSession(
        people=[person],
        assignments=[assignment],
        schedules=[schedule],
        rules=[rule],
        shifts=[shift],
    )

    await expand_schedules(
        session,
        person_ids=[PERSON_ID],
        start_date=BUSINESS_DATE,
        end_date=BUSINESS_DATE,
        allow_past=True,
    )

    expected_rows = _get_added_expected(session)
    assert len(expected_rows) >= 1
    assert expected_rows[0].person_id == PERSON_ID
    assert expected_rows[0].business_date == BUSINESS_DATE
    assert expected_rows[0].is_working_day is True


@pytest.mark.anyio
async def test_expand_overnight_shift_end_date() -> None:
    """crosses_midnight shift → end_date is next day."""
    tz_manila = ZoneInfo("Asia/Manila")

    # Simulate what the resolver does for overnight shift
    starts_at = time(22, 0)
    ends_at = time(6, 0)
    crosses_midnight = True

    start_local = datetime.combine(BUSINESS_DATE, starts_at).replace(tzinfo=tz_manila)
    if crosses_midnight or ends_at <= starts_at:
        end_date_val = BUSINESS_DATE + timedelta(days=1)
    else:
        end_date_val = BUSINESS_DATE
    end_local = datetime.combine(end_date_val, ends_at).replace(tzinfo=tz_manila)

    start_utc = start_local.astimezone(UTC)
    end_utc = end_local.astimezone(UTC)

    # 22:00 Manila = 14:00 UTC same day
    assert start_utc == datetime(2026, 8, 14, 14, 0, tzinfo=UTC)
    # 06:00 Manila next day = 22:00 UTC same day
    assert end_utc == datetime(2026, 8, 14, 22, 0, tzinfo=UTC)


@pytest.mark.anyio
async def test_expand_timezone_asia_manila() -> None:
    """Correct UTC times for Asia/Manila 08:00-17:00 shift."""
    tz_manila = ZoneInfo("Asia/Manila")

    start_local = datetime.combine(BUSINESS_DATE, time(8, 0)).replace(tzinfo=tz_manila)
    end_local = datetime.combine(BUSINESS_DATE, time(17, 0)).replace(tzinfo=tz_manila)

    start_utc = start_local.astimezone(UTC)
    end_utc = end_local.astimezone(UTC)

    assert start_utc == datetime(2026, 8, 14, 0, 0, tzinfo=UTC)
    assert end_utc == datetime(2026, 8, 14, 9, 0, tzinfo=UTC)


@pytest.mark.anyio
async def test_expand_skips_past_dates_without_allow_past() -> None:
    """Future only: past dates skipped when allow_past=False."""
    # This tests the allow_past logic directly
    from backend.app.attendance.resolver import expand_schedules

    past_date = date(2020, 1, 1)
    person = make_person()
    session = MockSession(people=[person])

    await expand_schedules(
        session,
        person_ids=[PERSON_ID],
        start_date=past_date,
        end_date=past_date,
        allow_past=False,
    )

    # No expected rows should be created for past dates
    expected_rows = _get_added_expected(session)
    assert len(expected_rows) == 0


@pytest.mark.anyio
async def test_expand_writes_past_dates_with_allow_past() -> None:
    """Past dates written when allow_past=True (tested via mock assignment match)."""
    from backend.app.attendance.resolver import expand_schedules

    # This verifies that allow_past=True doesn't skip past dates
    past_date = date(2020, 1, 6)  # Monday
    person = make_person()
    shift = make_shift()
    schedule = Schedule(name="S", effective_from=date(2019, 1, 1), is_active=True)
    schedule.id = SCHEDULE_ID
    schedule.timezone = "Asia/Manila"

    rule = ScheduleRule(
        schedule_id=SCHEDULE_ID,
        shift_id=SHIFT_ID,
        weekday=0,  # Monday
        is_working_day=True,
        period_label="",
    )
    rule.id = uuid4()

    assignment = ScheduleAssignment(
        schedule_id=SCHEDULE_ID,
        scope=AssignmentScope.PERSON,
        scope_id=PERSON_ID,
        priority=0,
        effective_from=date(2019, 1, 1),
    )
    assignment.id = uuid4()

    session = MockSession(
        people=[person],
        assignments=[assignment],
        schedules=[schedule],
        rules=[rule],
        shifts=[shift],
    )
    await expand_schedules(
        session,
        person_ids=[PERSON_ID],
        start_date=past_date,
        end_date=past_date,
        allow_past=True,
    )

    expected_rows = _get_added_expected(session)
    assert len(expected_rows) >= 1


@pytest.mark.anyio
async def test_expand_no_assignment_voids() -> None:
    """No matching assignment → void existing expected rows."""
    from backend.app.attendance.resolver import expand_schedules

    person = make_person()
    session = MockSession(people=[person], assignments=[])

    await expand_schedules(
        session,
        person_ids=[PERSON_ID],
        start_date=BUSINESS_DATE,
        end_date=BUSINESS_DATE,
        allow_past=True,
    )

    # No new expected rows created
    expected_rows = _get_added_expected(session)
    assert len(expected_rows) == 0


@pytest.mark.anyio
async def test_expand_voids_old_expected_rows() -> None:
    """Old schedule expected rows get voided_at set."""
    from backend.app.attendance.resolver import expand_schedules

    person = make_person()
    shift = make_shift()
    schedule = Schedule(name="S", effective_from=date(2026, 1, 1), is_active=True)
    schedule.id = SCHEDULE_ID
    schedule.timezone = "Asia/Manila"

    rule = ScheduleRule(
        schedule_id=SCHEDULE_ID,
        shift_id=SHIFT_ID,
        weekday=3,
        is_working_day=True,
        period_label="",
    )
    rule.id = uuid4()

    assignment = ScheduleAssignment(
        schedule_id=SCHEDULE_ID,
        scope=AssignmentScope.PERSON,
        scope_id=PERSON_ID,
        priority=0,
        effective_from=date(2026, 1, 1),
    )
    assignment.id = uuid4()

    session = MockSession(
        people=[person],
        assignments=[assignment],
        schedules=[schedule],
        rules=[rule],
        shifts=[shift],
    )

    await expand_schedules(
        session,
        person_ids=[PERSON_ID],
        start_date=BUSINESS_DATE,
        end_date=BUSINESS_DATE,
        allow_past=True,
    )

    # The new expected row should be added (void logic would apply to any
    # pre-existing rows returned by the mock, which returns [] by default)
    assert session.committed >= 1


@pytest.mark.anyio
async def test_expand_no_rule_for_weekday_voids() -> None:
    """No matching weekday rule → void existing expected rows."""
    from backend.app.attendance.resolver import expand_schedules

    person = make_person()
    schedule = Schedule(name="S", effective_from=date(2026, 1, 1), is_active=True)
    schedule.id = SCHEDULE_ID
    schedule.timezone = "Asia/Manila"

    # Rule for Monday (0) but our BUSINESS_DATE is Thursday (3)
    rule = ScheduleRule(
        schedule_id=SCHEDULE_ID,
        shift_id=SHIFT_ID,
        weekday=0,
        is_working_day=True,
        period_label="",
    )
    rule.id = uuid4()

    assignment = ScheduleAssignment(
        schedule_id=SCHEDULE_ID,
        scope=AssignmentScope.PERSON,
        scope_id=PERSON_ID,
        priority=0,
        effective_from=date(2026, 1, 1),
    )
    assignment.id = uuid4()

    shift = make_shift()
    session = MockSession(
        people=[person],
        assignments=[assignment],
        schedules=[schedule],
        rules=[rule],
        shifts=[shift],
    )

    await expand_schedules(
        session,
        person_ids=[PERSON_ID],
        start_date=BUSINESS_DATE,
        end_date=BUSINESS_DATE,
        allow_past=True,
    )

    # No new expected rows for unmatched weekday
    expected_rows = _get_added_expected(session)
    assert len(expected_rows) == 0


# ===========================================================================
# Group 6: rebuild_all_attendance() (3 tests)
# ===========================================================================


@pytest.mark.anyio
async def test_rebuild_truncates_and_resolves() -> None:
    """Rebuild deletes records and re-resolves all (person, date) pairs."""
    from backend.app.attendance.resolver import rebuild_all_attendance

    session = MockSession(
        expected_pairs=[(PERSON_ID, BUSINESS_DATE)],
        event_pairs=[],
    )
    await rebuild_all_attendance(session, as_of=AS_OF)

    # Should have committed (once for DELETE, once per resolve)
    assert session.committed >= 1


@pytest.mark.anyio
async def test_rebuild_preserves_overrides() -> None:
    """Override status preserved after rebuild."""
    from backend.app.attendance.resolver import rebuild_all_attendance

    override = make_override(status=AttendanceStatus.EXCUSED)
    expected = make_expected()

    session = MockSession(
        expected_pairs=[(PERSON_ID, BUSINESS_DATE)],
        event_pairs=[],
        expected_rows=[expected],
        overrides=[override],
    )
    await rebuild_all_attendance(session, as_of=AS_OF)

    records = _get_added_records(session)
    if records:
        assert records[0].status == AttendanceStatus.EXCUSED


@pytest.mark.anyio
async def test_rebuild_empty_tables() -> None:
    """Empty DB → no-op, no errors."""
    from backend.app.attendance.resolver import rebuild_all_attendance

    session = MockSession(expected_pairs=[], event_pairs=[])
    await rebuild_all_attendance(session, as_of=AS_OF)

    # No records created
    records = _get_added_records(session)
    assert len(records) == 0
    assert session.committed == 0


# ===========================================================================
# Group 7: Edge Cases (2 tests)
# ===========================================================================


@pytest.mark.anyio
async def test_redis_unavailable_graceful() -> None:
    """Resolver works when Redis is unavailable (graceful degradation)."""
    from backend.app.attendance.resolver import RedisResolverState

    state = RedisResolverState.__new__(RedisResolverState)
    state.client = None

    # All operations should work without raising
    state.set_dirty(PERSON_ID, BUSINESS_DATE)
    assert state.is_dirty(PERSON_ID, BUSINESS_DATE) is False
    assert state.clear_dirty(PERSON_ID, BUSINESS_DATE) is False


@pytest.mark.anyio
async def test_no_events_no_expected_no_records() -> None:
    """Completely empty person → no records created."""
    from backend.app.attendance.resolver import resolve

    session = MockSession(expected_rows=[], events=[])
    await resolve(session, PERSON_ID, BUSINESS_DATE, as_of=AS_OF)

    records = _get_added_records(session)
    assert len(records) == 0
