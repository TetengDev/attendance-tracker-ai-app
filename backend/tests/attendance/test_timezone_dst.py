from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest
import time_machine
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.attendance.decision_table import AttendanceStatus
from backend.app.attendance.resolver import rebuild_all_attendance, resolve
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
    CalendarDay,
    CalendarDayKind,
    PersonException,
    PersonExceptionKind,
)
from backend.app.settings.resolver import ResolvedSettings, SettingContext

# Constants
PERSON_ID = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
SHIFT_ID = UUID("11111111-1111-1111-1111-111111111111")
SCHEDULE_ID = UUID("22222222-2222-2222-2222-222222222222")
LOCATION_ID = UUID("33333333-3333-3333-3333-333333333333")
LOCATION_B_ID = UUID("33333333-3333-3333-3333-333333333334")
DEVICE_ID = UUID("55555555-5555-5555-5555-555555555555")
SESSION_ID = UUID("66666666-6666-6666-6666-666666666666")

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


def make_expected(
    start_utc: datetime,
    end_utc: datetime,
    shift_id: UUID = SHIFT_ID,
    is_working_day: bool = True,
    business_date: date = date(2026, 8, 14),
    period_label: str = "",
) -> ExpectedAttendance:
    ea = ExpectedAttendance(
        person_id=PERSON_ID,
        business_date=business_date,
        shift_id=shift_id,
        period_label=period_label,
    )
    ea.id = uuid4()
    ea.location_id = LOCATION_ID
    ea.schedule_id = SCHEDULE_ID
    ea.expected_start_at = start_utc
    ea.expected_end_at = end_utc
    ea.absent_after_at = start_utc + timedelta(minutes=60)
    ea.is_working_day = is_working_day
    ea.voided_at = None
    return ea


def make_event(
    occurred_at: datetime,
    outcome: AttendanceEventOutcome = AttendanceEventOutcome.ACCEPTED,
    location_id: UUID = LOCATION_ID,
    was_backdated: bool = False,
) -> AttendanceEvent:
    ev = AttendanceEvent(
        person_id=PERSON_ID,
        device_id=DEVICE_ID,
        session_id=SESSION_ID,
        occurred_at=occurred_at,
        outcome=outcome,
        direction=AttendanceEventDirection.IN,
        idempotency_key=f"key-{uuid4()}",
        client_captured_at=occurred_at,
        server_received_at=occurred_at,
        top1_score=0.95,
    )
    ev.id = 1000 + int(occurred_at.timestamp()) % 1000000
    ev.location_id = location_id
    ev.was_backdated = was_backdated
    ev.business_date = None
    ev.shift_id = None
    return ev


class MockResult:
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
        expected_pairs: list[tuple[UUID, date]] | None = None,
        event_pairs: list[tuple[UUID, date]] | None = None,
    ) -> None:
        super().__init__(bind=MagicMock())
        self.person = person or Person(id=PERSON_ID, display_name="Alice", is_active=True)
        self.expected_rows = expected_rows or []
        self.overrides = overrides or []
        self.exceptions = exceptions or []
        self.events = events or []
        self.existing_records = existing_records or []
        self.calendar_days = calendar_days or []
        self.expected_pairs = expected_pairs or []
        self.event_pairs = event_pairs or []
        self.added: list[Any] = []
        self.committed: int = 0

    async def execute(self, statement: Any, params: Any = None, *args: Any, **kwargs: Any) -> Any:
        sql = str(statement)
        if "person_exceptions" in sql:
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
            return MockResult(self.person)
        return MockResult(None)

    def add(self, instance: Any, _warn: bool = True) -> None:
        self.added.append(instance)

    async def commit(self) -> None:
        self.committed += 1


@dataclass
class TimezoneCase:
    name: str
    expected_rows: list[ExpectedAttendance]
    events: list[AttendanceEvent]
    as_of: datetime
    expected_status: AttendanceStatus
    expected_flags: dict[str, bool]
    exceptions: list[PersonException] = field(default_factory=list)
    overrides: list[AttendanceOverride] = field(default_factory=list)
    calendar_days: list[CalendarDay] = field(default_factory=list)


def get_test_cases() -> list[TimezoneCase]:
    cases = []
    
    # -----------------------------------------------------------------------
    # Weekday Standard Shift (08:00 - 17:00 Manila, UTC+8)
    # business_date = 2026-08-14
    # Local start = 2026-08-14 08:00 = 2026-08-14 00:00 UTC
    # Local end = 2026-08-14 17:00 = 2026-08-14 09:00 UTC
    # -----------------------------------------------------------------------
    std_expected = make_expected(
        start_utc=datetime(2026, 8, 14, 0, 0, tzinfo=UTC),
        end_utc=datetime(2026, 8, 14, 9, 0, tzinfo=UTC),
    )
    
    # 1. On time
    cases.append(TimezoneCase(
        name="std_on_time",
        expected_rows=[std_expected],
        events=[
            make_event(datetime(2026, 8, 13, 23, 55, tzinfo=UTC)), # 07:55 Manila
            make_event(datetime(2026, 8, 14, 9, 5, tzinfo=UTC)),   # 17:05 Manila
        ],
        as_of=datetime(2026, 8, 14, 10, 0, tzinfo=UTC),
        expected_status=AttendanceStatus.ON_TIME,
        expected_flags={"was_late": False, "left_early": False, "location_mismatch": False}
    ))
    
    # 2. Late
    cases.append(TimezoneCase(
        name="std_late",
        expected_rows=[std_expected],
        events=[
            make_event(datetime(2026, 8, 14, 0, 15, tzinfo=UTC)),  # 08:15 Manila (Grace in = 10 mins)
            make_event(datetime(2026, 8, 14, 9, 5, tzinfo=UTC)),
        ],
        as_of=datetime(2026, 8, 14, 10, 0, tzinfo=UTC),
        expected_status=AttendanceStatus.LATE,
        expected_flags={"was_late": True, "left_early": False, "location_mismatch": False}
    ))
    
    # 3. Late within grace
    cases.append(TimezoneCase(
        name="std_late_within_grace",
        expected_rows=[std_expected],
        events=[
            make_event(datetime(2026, 8, 14, 0, 5, tzinfo=UTC)),   # 08:05 Manila
            make_event(datetime(2026, 8, 14, 9, 5, tzinfo=UTC)),
        ],
        as_of=datetime(2026, 8, 14, 10, 0, tzinfo=UTC),
        expected_status=AttendanceStatus.ON_TIME,
        expected_flags={"was_late": False, "left_early": False}
    ))
    
    # 4. Early out
    cases.append(TimezoneCase(
        name="std_early_out",
        expected_rows=[std_expected],
        events=[
            make_event(datetime(2026, 8, 13, 23, 55, tzinfo=UTC)),
            make_event(datetime(2026, 8, 14, 8, 45, tzinfo=UTC)),  # 16:45 Manila (Grace out = 10 mins)
        ],
        as_of=datetime(2026, 8, 14, 10, 0, tzinfo=UTC),
        expected_status=AttendanceStatus.ON_TIME,
        expected_flags={"was_late": False, "left_early": True}
    ))

    # 5. Early out within grace
    cases.append(TimezoneCase(
        name="std_early_out_within_grace",
        expected_rows=[std_expected],
        events=[
            make_event(datetime(2026, 8, 13, 23, 55, tzinfo=UTC)),
            make_event(datetime(2026, 8, 14, 8, 55, tzinfo=UTC)),  # 16:55 Manila
        ],
        as_of=datetime(2026, 8, 14, 10, 0, tzinfo=UTC),
        expected_status=AttendanceStatus.ON_TIME,
        expected_flags={"was_late": False, "left_early": False}
    ))

    # 6. Late and early out
    cases.append(TimezoneCase(
        name="std_late_and_early_out",
        expected_rows=[std_expected],
        events=[
            make_event(datetime(2026, 8, 14, 0, 15, tzinfo=UTC)),
            make_event(datetime(2026, 8, 14, 8, 45, tzinfo=UTC)),
        ],
        as_of=datetime(2026, 8, 14, 10, 0, tzinfo=UTC),
        expected_status=AttendanceStatus.LATE,
        expected_flags={"was_late": True, "left_early": True}
    ))

    # 7. Absent
    cases.append(TimezoneCase(
        name="std_absent",
        expected_rows=[std_expected],
        events=[],
        as_of=datetime(2026, 8, 14, 1, 10, tzinfo=UTC),        # 09:10 Manila
        expected_status=AttendanceStatus.ABSENT,
        expected_flags={"was_late": False, "left_early": False}
    ))

    # 8. Pending
    cases.append(TimezoneCase(
        name="std_pending",
        expected_rows=[std_expected],
        events=[],
        as_of=datetime(2026, 8, 14, 0, 30, tzinfo=UTC),        # 08:30 Manila
        expected_status=AttendanceStatus.PENDING,
        expected_flags={"was_late": False, "left_early": False}
    ))

    # 9. Excused by exception
    exc_exception = PersonException(
        id=uuid4(),
        person_id=PERSON_ID,
        business_date=date(2026, 8, 14),
        kind=PersonExceptionKind.EXCUSED,
        reason="Sick",
    )
    cases.append(TimezoneCase(
        name="std_excused_by_exception",
        expected_rows=[std_expected],
        events=[],
        as_of=datetime(2026, 8, 14, 10, 0, tzinfo=UTC),
        exceptions=[exc_exception],
        expected_status=AttendanceStatus.EXCUSED,
        expected_flags={"was_late": False, "left_early": False}
    ))

    # 10. Holiday (via CalendarDay)
    std_cal_holiday = CalendarDay(
        location_id=LOCATION_ID,
        business_date=date(2026, 8, 14),
        kind=CalendarDayKind.HOLIDAY,
        label="Holiday",
        is_working_day=False,
    )
    std_cal_holiday.id = uuid4()
    cases.append(TimezoneCase(
        name="std_holiday",
        expected_rows=[std_expected],
        events=[],
        as_of=datetime(2026, 8, 14, 10, 0, tzinfo=UTC),
        expected_status=AttendanceStatus.HOLIDAY,
        expected_flags={"was_late": False, "left_early": False},
        calendar_days=[std_cal_holiday],
    ))

    # 11. Not scheduled (is_working_day=False on expected, no CalendarDay)
    not_scheduled_expected = make_expected(
        start_utc=datetime(2026, 8, 14, 0, 0, tzinfo=UTC),
        end_utc=datetime(2026, 8, 14, 9, 0, tzinfo=UTC),
        is_working_day=False,
    )
    cases.append(TimezoneCase(
        name="std_not_scheduled",
        expected_rows=[not_scheduled_expected],
        events=[],
        as_of=datetime(2026, 8, 14, 10, 0, tzinfo=UTC),
        expected_status=AttendanceStatus.NOT_SCHEDULED,
        expected_flags={"was_late": False, "left_early": False}
    ))

    # 12. Override
    std_override = AttendanceOverride(
        id=uuid4(),
        person_id=PERSON_ID,
        business_date=date(2026, 8, 14),
        shift_id=SHIFT_ID,
        period_label="",
        status=AttendanceStatus.EXCUSED,
        reason="Doctor visit",
    )
    cases.append(TimezoneCase(
        name="std_override",
        expected_rows=[std_expected],
        events=[],
        as_of=datetime(2026, 8, 14, 10, 0, tzinfo=UTC),
        overrides=[std_override],
        expected_status=AttendanceStatus.EXCUSED,
        expected_flags={"was_late": False, "left_early": False}
    ))

    # 13. Present unscheduled
    cases.append(TimezoneCase(
        name="unscheduled_present",
        expected_rows=[],
        events=[
            make_event(datetime(2026, 8, 14, 0, 0, tzinfo=UTC)),
            make_event(datetime(2026, 8, 14, 9, 0, tzinfo=UTC)),
        ],
        as_of=datetime(2026, 8, 14, 10, 0, tzinfo=UTC),
        expected_status=AttendanceStatus.PRESENT_UNSCHEDULED,
        expected_flags={"was_late": False, "left_early": False}
    ))

    # -----------------------------------------------------------------------
    # Overnight Shift (22:00 - 06:00 Manila, UTC+8)
    # business_date = 2026-08-14
    # Local start = 2026-08-14 22:00 = 2026-08-14 14:00 UTC
    # Local end = 2026-08-15 06:00 = 2026-08-14 22:00 UTC
    # -----------------------------------------------------------------------
    overnight_expected = make_expected(
        start_utc=datetime(2026, 8, 14, 14, 0, tzinfo=UTC),
        end_utc=datetime(2026, 8, 14, 22, 0, tzinfo=UTC),
    )

    # 14. Overnight on time
    cases.append(TimezoneCase(
        name="overnight_on_time",
        expected_rows=[overnight_expected],
        events=[
            make_event(datetime(2026, 8, 14, 13, 55, tzinfo=UTC)),
            make_event(datetime(2026, 8, 14, 22, 5, tzinfo=UTC)),
        ],
        as_of=datetime(2026, 8, 14, 23, 0, tzinfo=UTC),
        expected_status=AttendanceStatus.ON_TIME,
        expected_flags={"was_late": False, "left_early": False}
    ))

    # 15. Overnight late
    cases.append(TimezoneCase(
        name="overnight_late",
        expected_rows=[overnight_expected],
        events=[
            make_event(datetime(2026, 8, 14, 14, 15, tzinfo=UTC)),
            make_event(datetime(2026, 8, 14, 22, 5, tzinfo=UTC)),
        ],
        as_of=datetime(2026, 8, 14, 23, 0, tzinfo=UTC),
        expected_status=AttendanceStatus.LATE,
        expected_flags={"was_late": True, "left_early": False}
    ))

    # 16. Overnight early out
    cases.append(TimezoneCase(
        name="overnight_early_out",
        expected_rows=[overnight_expected],
        events=[
            make_event(datetime(2026, 8, 14, 13, 55, tzinfo=UTC)),
            make_event(datetime(2026, 8, 14, 21, 45, tzinfo=UTC)),
        ],
        as_of=datetime(2026, 8, 14, 23, 0, tzinfo=UTC),
        expected_status=AttendanceStatus.ON_TIME,
        expected_flags={"was_late": False, "left_early": True}
    ))

    # 17. Overnight absent
    cases.append(TimezoneCase(
        name="overnight_absent",
        expected_rows=[overnight_expected],
        events=[],
        as_of=datetime(2026, 8, 14, 15, 10, tzinfo=UTC),
        expected_status=AttendanceStatus.ABSENT,
        expected_flags={"was_late": False, "left_early": False}
    ))

    # 18. Overnight pending
    cases.append(TimezoneCase(
        name="overnight_pending",
        expected_rows=[overnight_expected],
        events=[],
        as_of=datetime(2026, 8, 14, 14, 30, tzinfo=UTC),
        expected_status=AttendanceStatus.PENDING,
        expected_flags={"was_late": False, "left_early": False}
    ))

    # 19. Overnight holiday (via CalendarDay)
    overnight_cal_holiday = CalendarDay(
        location_id=LOCATION_ID,
        business_date=date(2026, 8, 14),
        kind=CalendarDayKind.HOLIDAY,
        label="Holiday",
        is_working_day=False,
    )
    overnight_cal_holiday.id = uuid4()
    cases.append(TimezoneCase(
        name="overnight_holiday",
        expected_rows=[overnight_expected],
        events=[],
        as_of=datetime(2026, 8, 14, 23, 0, tzinfo=UTC),
        expected_status=AttendanceStatus.HOLIDAY,
        expected_flags={"was_late": False, "left_early": False},
        calendar_days=[overnight_cal_holiday],
    ))

    # 20. Overnight excused
    cases.append(TimezoneCase(
        name="overnight_excused",
        expected_rows=[overnight_expected],
        events=[],
        as_of=datetime(2026, 8, 14, 23, 0, tzinfo=UTC),
        exceptions=[exc_exception],
        expected_status=AttendanceStatus.EXCUSED,
        expected_flags={"was_late": False, "left_early": False}
    ))

    # 21. Overnight not_scheduled
    overnight_not_scheduled = make_expected(
        start_utc=datetime(2026, 8, 14, 14, 0, tzinfo=UTC),
        end_utc=datetime(2026, 8, 14, 22, 0, tzinfo=UTC),
        is_working_day=False,
    )
    cases.append(TimezoneCase(
        name="overnight_not_scheduled",
        expected_rows=[overnight_not_scheduled],
        events=[],
        as_of=datetime(2026, 8, 15, 1, 0, tzinfo=UTC),
        expected_status=AttendanceStatus.NOT_SCHEDULED,
        expected_flags={"was_late": False, "left_early": False}
    ))

    # 22. Overnight override
    overnight_override = AttendanceOverride(
        id=uuid4(),
        person_id=PERSON_ID,
        business_date=date(2026, 8, 14),
        shift_id=SHIFT_ID,
        period_label="",
        status=AttendanceStatus.EXCUSED,
        reason="Doctor",
    )
    cases.append(TimezoneCase(
        name="overnight_override",
        expected_rows=[overnight_expected],
        events=[],
        as_of=datetime(2026, 8, 14, 23, 0, tzinfo=UTC),
        overrides=[overnight_override],
        expected_status=AttendanceStatus.EXCUSED,
        expected_flags={"was_late": False, "left_early": False}
    ))

    # -----------------------------------------------------------------------
    # DST Spring Forward (America/New_York, UTC-5 to UTC-4)
    # business_date = 2026-03-08
    # Shift local: 01:00 - 09:00 New York (jump at 02:00)
    # Local start = 01:00 New York = 06:00 UTC
    # Local end = 09:00 New York = 13:00 UTC
    # -----------------------------------------------------------------------
    spring_expected = make_expected(
        start_utc=datetime(2026, 3, 8, 6, 0, tzinfo=UTC),
        end_utc=datetime(2026, 3, 8, 13, 0, tzinfo=UTC),
        business_date=date(2026, 3, 8),
    )

    # 23. spring_dst_on_time
    cases.append(TimezoneCase(
        name="spring_dst_on_time",
        expected_rows=[spring_expected],
        events=[
            make_event(datetime(2026, 3, 8, 5, 55, tzinfo=UTC)),
            make_event(datetime(2026, 3, 8, 13, 5, tzinfo=UTC)),
        ],
        as_of=datetime(2026, 3, 8, 14, 0, tzinfo=UTC),
        expected_status=AttendanceStatus.ON_TIME,
        expected_flags={"was_late": False, "left_early": False}
    ))

    # 24. spring_dst_late
    cases.append(TimezoneCase(
        name="spring_dst_late",
        expected_rows=[spring_expected],
        events=[
            make_event(datetime(2026, 3, 8, 6, 15, tzinfo=UTC)),
            make_event(datetime(2026, 3, 8, 13, 5, tzinfo=UTC)),
        ],
        as_of=datetime(2026, 3, 8, 14, 0, tzinfo=UTC),
        expected_status=AttendanceStatus.LATE,
        expected_flags={"was_late": True, "left_early": False}
    ))

    # 25. spring_dst_early_out
    cases.append(TimezoneCase(
        name="spring_dst_early_out",
        expected_rows=[spring_expected],
        events=[
            make_event(datetime(2026, 3, 8, 5, 55, tzinfo=UTC)),
            make_event(datetime(2026, 3, 8, 12, 45, tzinfo=UTC)),
        ],
        as_of=datetime(2026, 3, 8, 14, 0, tzinfo=UTC),
        expected_status=AttendanceStatus.ON_TIME,
        expected_flags={"was_late": False, "left_early": True}
    ))

    # 26. spring_dst_absent
    cases.append(TimezoneCase(
        name="spring_dst_absent",
        expected_rows=[spring_expected],
        events=[],
        as_of=datetime(2026, 3, 8, 7, 15, tzinfo=UTC),
        expected_status=AttendanceStatus.ABSENT,
        expected_flags={"was_late": False, "left_early": False}
    ))

    # 27. spring_dst_pending
    cases.append(TimezoneCase(
        name="spring_dst_pending",
        expected_rows=[spring_expected],
        events=[],
        as_of=datetime(2026, 3, 8, 6, 30, tzinfo=UTC),
        expected_status=AttendanceStatus.PENDING,
        expected_flags={"was_late": False, "left_early": False}
    ))

    # 28. spring_dst_holiday (via CalendarDay)
    spring_cal_holiday = CalendarDay(
        location_id=LOCATION_ID,
        business_date=date(2026, 3, 8),
        kind=CalendarDayKind.HOLIDAY,
        label="Holiday",
        is_working_day=False,
    )
    spring_cal_holiday.id = uuid4()
    cases.append(TimezoneCase(
        name="spring_dst_holiday",
        expected_rows=[spring_expected],
        events=[],
        as_of=datetime(2026, 3, 8, 14, 0, tzinfo=UTC),
        expected_status=AttendanceStatus.HOLIDAY,
        expected_flags={"was_late": False, "left_early": False},
        calendar_days=[spring_cal_holiday],
    ))

    # 29. spring_dst_excused
    spring_exception = PersonException(
        id=uuid4(),
        person_id=PERSON_ID,
        business_date=date(2026, 3, 8),
        kind=PersonExceptionKind.EXCUSED,
        reason="Sick",
    )
    cases.append(TimezoneCase(
        name="spring_dst_excused",
        expected_rows=[spring_expected],
        events=[],
        as_of=datetime(2026, 3, 8, 14, 0, tzinfo=UTC),
        exceptions=[spring_exception],
        expected_status=AttendanceStatus.EXCUSED,
        expected_flags={"was_late": False, "left_early": False}
    ))

    # 30. spring_dst_not_scheduled
    spring_not_scheduled = make_expected(
        start_utc=datetime(2026, 3, 8, 6, 0, tzinfo=UTC),
        end_utc=datetime(2026, 3, 8, 13, 0, tzinfo=UTC),
        business_date=date(2026, 3, 8),
        is_working_day=False,
    )
    cases.append(TimezoneCase(
        name="spring_dst_not_scheduled",
        expected_rows=[spring_not_scheduled],
        events=[],
        as_of=datetime(2026, 3, 8, 15, 30, tzinfo=UTC),
        expected_status=AttendanceStatus.NOT_SCHEDULED,
        expected_flags={"was_late": False, "left_early": False}
    ))

    # -----------------------------------------------------------------------
    # DST Fall Back (America/New_York, UTC-4 to UTC-5)
    # business_date = 2026-11-01
    # Shift local: 01:00 - 09:00 New York (fall back at 02:00)
    # Local start = 01:00 New York = 05:00 UTC
    # Local end = 09:00 New York = 14:00 UTC
    # -----------------------------------------------------------------------
    fall_expected = make_expected(
        start_utc=datetime(2026, 11, 1, 5, 0, tzinfo=UTC),
        end_utc=datetime(2026, 11, 1, 14, 0, tzinfo=UTC),
        business_date=date(2026, 11, 1),
    )

    # 31. fall_dst_on_time
    cases.append(TimezoneCase(
        name="fall_dst_on_time",
        expected_rows=[fall_expected],
        events=[
            make_event(datetime(2026, 11, 1, 4, 55, tzinfo=UTC)),
            make_event(datetime(2026, 11, 1, 14, 5, tzinfo=UTC)),
        ],
        as_of=datetime(2026, 11, 1, 15, 0, tzinfo=UTC),
        expected_status=AttendanceStatus.ON_TIME,
        expected_flags={"was_late": False, "left_early": False}
    ))

    # 32. fall_dst_late
    cases.append(TimezoneCase(
        name="fall_dst_late",
        expected_rows=[fall_expected],
        events=[
            make_event(datetime(2026, 11, 1, 5, 15, tzinfo=UTC)),
            make_event(datetime(2026, 11, 1, 14, 5, tzinfo=UTC)),
        ],
        as_of=datetime(2026, 11, 1, 15, 0, tzinfo=UTC),
        expected_status=AttendanceStatus.LATE,
        expected_flags={"was_late": True, "left_early": False}
    ))

    # 33. fall_dst_early_out
    cases.append(TimezoneCase(
        name="fall_dst_early_out",
        expected_rows=[fall_expected],
        events=[
            make_event(datetime(2026, 11, 1, 4, 55, tzinfo=UTC)),
            make_event(datetime(2026, 11, 1, 13, 45, tzinfo=UTC)),
        ],
        as_of=datetime(2026, 11, 1, 15, 0, tzinfo=UTC),
        expected_status=AttendanceStatus.ON_TIME,
        expected_flags={"was_late": False, "left_early": True}
    ))

    # 34. fall_dst_absent
    cases.append(TimezoneCase(
        name="fall_dst_absent",
        expected_rows=[fall_expected],
        events=[],
        as_of=datetime(2026, 11, 1, 6, 15, tzinfo=UTC),
        expected_status=AttendanceStatus.ABSENT,
        expected_flags={"was_late": False, "left_early": False}
    ))

    # 35. fall_dst_pending
    cases.append(TimezoneCase(
        name="fall_dst_pending",
        expected_rows=[fall_expected],
        events=[],
        as_of=datetime(2026, 11, 1, 5, 30, tzinfo=UTC),
        expected_status=AttendanceStatus.PENDING,
        expected_flags={"was_late": False, "left_early": False}
    ))

    # 36. fall_dst_holiday (via CalendarDay)
    fall_cal_holiday = CalendarDay(
        location_id=LOCATION_ID,
        business_date=date(2026, 11, 1),
        kind=CalendarDayKind.HOLIDAY,
        label="Holiday",
        is_working_day=False,
    )
    fall_cal_holiday.id = uuid4()
    cases.append(TimezoneCase(
        name="fall_dst_holiday",
        expected_rows=[fall_expected],
        events=[],
        as_of=datetime(2026, 11, 1, 15, 0, tzinfo=UTC),
        expected_status=AttendanceStatus.HOLIDAY,
        expected_flags={"was_late": False, "left_early": False},
        calendar_days=[fall_cal_holiday],
    ))

    # 37. fall_dst_excused
    fall_exception = PersonException(
        id=uuid4(),
        person_id=PERSON_ID,
        business_date=date(2026, 11, 1),
        kind=PersonExceptionKind.EXCUSED,
        reason="Sick",
    )
    cases.append(TimezoneCase(
        name="fall_dst_excused",
        expected_rows=[fall_expected],
        events=[],
        as_of=datetime(2026, 11, 1, 15, 0, tzinfo=UTC),
        exceptions=[fall_exception],
        expected_status=AttendanceStatus.EXCUSED,
        expected_flags={"was_late": False, "left_early": False}
    ))

    # 38. fall_dst_not_scheduled
    fall_not_scheduled = make_expected(
        start_utc=datetime(2026, 11, 1, 5, 0, tzinfo=UTC),
        end_utc=datetime(2026, 11, 1, 14, 0, tzinfo=UTC),
        business_date=date(2026, 11, 1),
        is_working_day=False,
    )
    cases.append(TimezoneCase(
        name="fall_dst_not_scheduled",
        expected_rows=[fall_not_scheduled],
        events=[],
        as_of=datetime(2026, 11, 1, 16, 30, tzinfo=UTC),
        expected_status=AttendanceStatus.NOT_SCHEDULED,
        expected_flags={"was_late": False, "left_early": False}
    ))

    # -----------------------------------------------------------------------
    # Multi-location & Multi-period
    # -----------------------------------------------------------------------
    # 39. multi_location_match
    cases.append(TimezoneCase(
        name="multi_location_match",
        expected_rows=[std_expected],
        events=[
            make_event(datetime(2026, 8, 13, 23, 55, tzinfo=UTC), location_id=LOCATION_ID),
            make_event(datetime(2026, 8, 14, 9, 5, tzinfo=UTC), location_id=LOCATION_ID),
        ],
        as_of=datetime(2026, 8, 14, 10, 0, tzinfo=UTC),
        expected_status=AttendanceStatus.ON_TIME,
        expected_flags={"location_mismatch": False}
    ))

    # 40. multi_location_mismatch
    cases.append(TimezoneCase(
        name="multi_location_mismatch",
        expected_rows=[std_expected],
        events=[
            make_event(datetime(2026, 8, 13, 23, 55, tzinfo=UTC), location_id=LOCATION_B_ID),
            make_event(datetime(2026, 8, 14, 9, 5, tzinfo=UTC), location_id=LOCATION_B_ID),
        ],
        as_of=datetime(2026, 8, 14, 10, 0, tzinfo=UTC),
        expected_status=AttendanceStatus.ON_TIME,
        expected_flags={"location_mismatch": True}
    ))

    # 41. multi_period_morning
    morning_expected = make_expected(
        start_utc=datetime(2026, 8, 14, 0, 0, tzinfo=UTC),      # 08:00 Manila
        end_utc=datetime(2026, 8, 14, 4, 0, tzinfo=UTC),        # 12:00 Manila
        period_label="morning",
    )
    cases.append(TimezoneCase(
        name="multi_period_morning",
        expected_rows=[morning_expected],
        events=[
            make_event(datetime(2026, 8, 13, 23, 55, tzinfo=UTC)),
            make_event(datetime(2026, 8, 14, 4, 5, tzinfo=UTC)),
        ],
        as_of=datetime(2026, 8, 14, 5, 0, tzinfo=UTC),
        expected_status=AttendanceStatus.ON_TIME,
        expected_flags={"was_late": False, "left_early": False}
    ))

    # 42. multi_period_afternoon
    afternoon_expected = make_expected(
        start_utc=datetime(2026, 8, 14, 5, 0, tzinfo=UTC),      # 13:00 Manila
        end_utc=datetime(2026, 8, 14, 9, 0, tzinfo=UTC),        # 17:00 Manila
        period_label="afternoon",
    )
    cases.append(TimezoneCase(
        name="multi_period_afternoon",
        expected_rows=[afternoon_expected],
        events=[
            make_event(datetime(2026, 8, 14, 4, 55, tzinfo=UTC)),
            make_event(datetime(2026, 8, 14, 9, 5, tzinfo=UTC)),
        ],
        as_of=datetime(2026, 8, 14, 10, 0, tzinfo=UTC),
        expected_status=AttendanceStatus.ON_TIME,
        expected_flags={"was_late": False, "left_early": False}
    ))

    # 43. multi_period_morning_late
    cases.append(TimezoneCase(
        name="multi_period_morning_late",
        expected_rows=[morning_expected],
        events=[
            make_event(datetime(2026, 8, 14, 0, 15, tzinfo=UTC)),  # 08:15 Manila
            make_event(datetime(2026, 8, 14, 4, 5, tzinfo=UTC)),
        ],
        as_of=datetime(2026, 8, 14, 5, 0, tzinfo=UTC),
        expected_status=AttendanceStatus.LATE,
        expected_flags={"was_late": True, "left_early": False}
    ))

    # 44. multi_period_afternoon_early_out
    cases.append(TimezoneCase(
        name="multi_period_afternoon_early_out",
        expected_rows=[afternoon_expected],
        events=[
            make_event(datetime(2026, 8, 14, 4, 55, tzinfo=UTC)),
            make_event(datetime(2026, 8, 14, 8, 45, tzinfo=UTC)),  # 16:45 Manila
        ],
        as_of=datetime(2026, 8, 14, 10, 0, tzinfo=UTC),
        expected_status=AttendanceStatus.ON_TIME,
        expected_flags={"was_late": False, "left_early": True}
    ))

    # 45. cross_timezone_scanning
    cases.append(TimezoneCase(
        name="cross_timezone_scanning",
        expected_rows=[std_expected],
        events=[
            make_event(datetime(2026, 8, 13, 23, 30, tzinfo=UTC), location_id=LOCATION_ID),
            make_event(datetime(2026, 8, 14, 9, 5, tzinfo=UTC), location_id=LOCATION_ID),
        ],
        as_of=datetime(2026, 8, 14, 10, 0, tzinfo=UTC),
        expected_status=AttendanceStatus.ON_TIME,
        expected_flags={"was_late": False, "left_early": False}
    ))

    # 46. timezone_business_date_isolation
    cases.append(TimezoneCase(
        name="timezone_business_date_isolation",
        expected_rows=[std_expected],
        events=[
            make_event(datetime(2026, 8, 13, 23, 30, tzinfo=UTC)),
        ],
        as_of=datetime(2026, 8, 14, 10, 0, tzinfo=UTC),
        expected_status=AttendanceStatus.ON_TIME,
        expected_flags={"was_late": False}
    ))

    return cases


@pytest.mark.anyio
@pytest.mark.parametrize("case", get_test_cases(), ids=lambda c: c.name)
async def test_table_driven_cases(case: TimezoneCase) -> None:
    with time_machine.travel(case.as_of):
        session = MockSession(
            expected_rows=case.expected_rows,
            events=case.events,
            exceptions=case.exceptions,
            overrides=case.overrides,
            calendar_days=case.calendar_days,
        )
        
        b_date = case.expected_rows[0].business_date if case.expected_rows else date(2026, 8, 14)
        await resolve(session, PERSON_ID, b_date, as_of=case.as_of)
        
        records = [r for r in session.added if isinstance(r, AttendanceRecord)]
        if not case.expected_rows and case.expected_status not in (AttendanceStatus.PRESENT_UNSCHEDULED,):
            assert len(records) == 0
            return
            
        assert len(records) >= 1
        record = records[0]
        assert record.status == case.expected_status
        for flag_name, expected_val in case.expected_flags.items():
            assert record.flags.get(flag_name, False) == expected_val


@pytest.mark.anyio
async def test_rebuild_attendance_cache_property() -> None:
    expected = make_expected(
        start_utc=datetime(2026, 8, 14, 0, 0, tzinfo=UTC),
        end_utc=datetime(2026, 8, 14, 9, 0, tzinfo=UTC),
    )
    event = make_event(datetime(2026, 8, 14, 0, 5, tzinfo=UTC))
    override = AttendanceOverride(
        id=uuid4(),
        person_id=PERSON_ID,
        business_date=date(2026, 8, 14),
        shift_id=SHIFT_ID,
        period_label="",
        status=AttendanceStatus.EXCUSED,
        reason="Excused reason",
    )

    session1 = MockSession(
        expected_rows=[expected],
        events=[event],
        overrides=[override],
        expected_pairs=[(PERSON_ID, date(2026, 8, 14))],
        event_pairs=[(PERSON_ID, date(2026, 8, 14))],
    )
    await resolve(session1, PERSON_ID, date(2026, 8, 14), as_of=datetime(2026, 8, 14, 10, 0, tzinfo=UTC))
    records1 = [r for r in session1.added if isinstance(r, AttendanceRecord)]
    assert len(records1) == 1
    orig_status = records1[0].status
    orig_override_id = records1[0].override_id

    session2 = MockSession(
        expected_rows=[expected],
        events=[event],
        overrides=[override],
        expected_pairs=[(PERSON_ID, date(2026, 8, 14))],
        event_pairs=[(PERSON_ID, date(2026, 8, 14))],
    )
    await rebuild_all_attendance(session2, as_of=datetime(2026, 8, 14, 10, 0, tzinfo=UTC))
    records2 = [r for r in session2.added if isinstance(r, AttendanceRecord)]

    assert len(records2) == 1
    assert records2[0].status == orig_status
    assert records2[0].override_id == orig_override_id
    assert records2[0].status == AttendanceStatus.EXCUSED


@pytest.mark.anyio
async def test_resolve_idempotence() -> None:
    expected = make_expected(
        start_utc=datetime(2026, 8, 14, 0, 0, tzinfo=UTC),
        end_utc=datetime(2026, 8, 14, 9, 0, tzinfo=UTC),
    )
    event = make_event(datetime(2026, 8, 14, 0, 5, tzinfo=UTC))

    session1 = MockSession(expected_rows=[expected], events=[event])
    as_of = datetime(2026, 8, 14, 10, 0, tzinfo=UTC)
    await resolve(session1, PERSON_ID, date(2026, 8, 14), as_of=as_of)
    records1 = [r for r in session1.added if isinstance(r, AttendanceRecord)]
    assert len(records1) == 1

    session2 = MockSession(
        expected_rows=[expected], events=[event], existing_records=list(records1)
    )
    await resolve(session2, PERSON_ID, date(2026, 8, 14), as_of=as_of)
    records2 = [r for r in session2.added if isinstance(r, AttendanceRecord)]
    assert len(records2) == 1
    assert records2[0].status == records1[0].status
    assert records2[0].late_minutes == records1[0].late_minutes


@pytest.mark.anyio
async def test_resolve_pending_status() -> None:
    expected = make_expected(
        start_utc=datetime(2026, 8, 14, 0, 0, tzinfo=UTC),
        end_utc=datetime(2026, 8, 14, 9, 0, tzinfo=UTC),
    )
    early_as_of = datetime(2026, 8, 14, 0, 5, tzinfo=UTC)

    session = MockSession(expected_rows=[expected], events=[])
    await resolve(session, PERSON_ID, date(2026, 8, 14), as_of=early_as_of)

    records = [r for r in session.added if isinstance(r, AttendanceRecord)]
    assert len(records) == 1
    assert records[0].status == AttendanceStatus.PENDING


# ---------------------------------------------------------------------------
# Standalone Incomplete Tests (require auto_close_enabled=True via monkeypatch)
# ---------------------------------------------------------------------------


async def _mock_settings_autoclose(db: Any, context: SettingContext) -> ResolvedSettings:
    s = dict(DEFAULT_SETTINGS)
    s["attendance.auto_close_enabled"] = True
    s["attendance.auto_close_minutes"] = 30
    return ResolvedSettings(settings=s, settings_version=1)


@pytest.mark.anyio
async def test_std_incomplete(monkeypatch: pytest.MonkeyPatch) -> None:
    """Standard shift: arrived, no departure, auto_close past window → INCOMPLETE."""
    import backend.app.attendance.resolver as resolver_mod

    monkeypatch.setattr(resolver_mod, "resolve_db_settings", _mock_settings_autoclose)

    expected = make_expected(
        start_utc=datetime(2026, 8, 14, 0, 0, tzinfo=UTC),
        end_utc=datetime(2026, 8, 14, 9, 0, tzinfo=UTC),
    )
    event = make_event(datetime(2026, 8, 13, 23, 55, tzinfo=UTC))
    late_as_of = datetime(2026, 8, 14, 12, 0, tzinfo=UTC)

    session = MockSession(expected_rows=[expected], events=[event])
    await resolve(session, PERSON_ID, date(2026, 8, 14), as_of=late_as_of)

    records = [r for r in session.added if isinstance(r, AttendanceRecord)]
    assert len(records) == 1
    assert records[0].status == AttendanceStatus.INCOMPLETE
    assert records[0].flags["auto_closed"] is True


@pytest.mark.anyio
async def test_overnight_incomplete(monkeypatch: pytest.MonkeyPatch) -> None:
    """Overnight shift: arrived, no departure, auto_close past window → INCOMPLETE."""
    import backend.app.attendance.resolver as resolver_mod

    monkeypatch.setattr(resolver_mod, "resolve_db_settings", _mock_settings_autoclose)

    expected = make_expected(
        start_utc=datetime(2026, 8, 14, 14, 0, tzinfo=UTC),
        end_utc=datetime(2026, 8, 14, 22, 0, tzinfo=UTC),
    )
    event = make_event(datetime(2026, 8, 14, 13, 55, tzinfo=UTC))
    late_as_of = datetime(2026, 8, 15, 1, 0, tzinfo=UTC)

    session = MockSession(expected_rows=[expected], events=[event])
    await resolve(session, PERSON_ID, date(2026, 8, 14), as_of=late_as_of)

    records = [r for r in session.added if isinstance(r, AttendanceRecord)]
    assert len(records) == 1
    assert records[0].status == AttendanceStatus.INCOMPLETE
    assert records[0].flags["auto_closed"] is True


@pytest.mark.anyio
async def test_spring_dst_incomplete(monkeypatch: pytest.MonkeyPatch) -> None:
    """Spring DST shift: arrived, no departure, auto_close past window → INCOMPLETE."""
    import backend.app.attendance.resolver as resolver_mod

    monkeypatch.setattr(resolver_mod, "resolve_db_settings", _mock_settings_autoclose)

    expected = make_expected(
        start_utc=datetime(2026, 3, 8, 6, 0, tzinfo=UTC),
        end_utc=datetime(2026, 3, 8, 13, 0, tzinfo=UTC),
        business_date=date(2026, 3, 8),
    )
    event = make_event(datetime(2026, 3, 8, 5, 55, tzinfo=UTC))
    late_as_of = datetime(2026, 3, 8, 15, 30, tzinfo=UTC)

    session = MockSession(expected_rows=[expected], events=[event])
    await resolve(session, PERSON_ID, date(2026, 3, 8), as_of=late_as_of)

    records = [r for r in session.added if isinstance(r, AttendanceRecord)]
    assert len(records) == 1
    assert records[0].status == AttendanceStatus.INCOMPLETE
    assert records[0].flags["auto_closed"] is True


@pytest.mark.anyio
async def test_fall_dst_incomplete(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fall DST shift: arrived, no departure, auto_close past window → INCOMPLETE."""
    import backend.app.attendance.resolver as resolver_mod

    monkeypatch.setattr(resolver_mod, "resolve_db_settings", _mock_settings_autoclose)

    expected = make_expected(
        start_utc=datetime(2026, 11, 1, 5, 0, tzinfo=UTC),
        end_utc=datetime(2026, 11, 1, 14, 0, tzinfo=UTC),
        business_date=date(2026, 11, 1),
    )
    event = make_event(datetime(2026, 11, 1, 4, 55, tzinfo=UTC))
    late_as_of = datetime(2026, 11, 1, 16, 30, tzinfo=UTC)

    session = MockSession(expected_rows=[expected], events=[event])
    await resolve(session, PERSON_ID, date(2026, 11, 1), as_of=late_as_of)

    records = [r for r in session.added if isinstance(r, AttendanceRecord)]
    assert len(records) == 1
    assert records[0].status == AttendanceStatus.INCOMPLETE
    assert records[0].flags["auto_closed"] is True
