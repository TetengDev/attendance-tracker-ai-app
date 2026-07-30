from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class AttendanceStatus(str, Enum):
    EXCUSED = "excused"
    HOLIDAY = "holiday"
    NOT_SCHEDULED = "not_scheduled"
    PRESENT_UNSCHEDULED = "present_unscheduled"
    PENDING = "pending"
    ABSENT = "absent"
    ON_TIME = "on_time"
    LATE = "late"
    INCOMPLETE = "incomplete"
    COMPLETE = "complete"


class AttendanceFlag(str, Enum):
    WAS_LATE = "was_late"
    LEFT_EARLY = "left_early"
    LOCATION_MISMATCH = "location_mismatch"
    WAS_BACKDATED = "was_backdated"
    AUTO_CLOSED = "auto_closed"


@dataclass(frozen=True)
class DecisionRule:
    order: int
    condition: str
    statuses: tuple[AttendanceStatus | str, ...]
    derived_fields: tuple[str, ...] = ()
    note: str | None = None


DECISION_TABLE: tuple[DecisionRule, ...] = (
    DecisionRule(
        order=1,
        condition="attendance_overrides row exists",
        statuses=("override.status",),
        note="override status wins before schedule/event classification",
    ),
    DecisionRule(
        order=2,
        condition="person_exceptions covers the date",
        statuses=(AttendanceStatus.EXCUSED,),
    ),
    DecisionRule(
        order=3,
        condition="calendar_days non-working, or rule is_working_day = false",
        statuses=(AttendanceStatus.HOLIDAY, AttendanceStatus.NOT_SCHEDULED),
    ),
    DecisionRule(
        order=4,
        condition="no expected row, events exist",
        statuses=(AttendanceStatus.PRESENT_UNSCHEDULED,),
    ),
    DecisionRule(
        order=5,
        condition="no IN and as_of < S + absent_after_minutes",
        statuses=(AttendanceStatus.PENDING,),
    ),
    DecisionRule(
        order=6,
        condition="no IN and as_of >= S + absent_after_minutes",
        statuses=(AttendanceStatus.ABSENT,),
    ),
    DecisionRule(
        order=7,
        condition="first IN <= S + grace_in_minutes",
        statuses=(AttendanceStatus.ON_TIME,),
    ),
    DecisionRule(
        order=8,
        condition="first IN <= S + absent_after_minutes",
        statuses=(AttendanceStatus.LATE,),
        derived_fields=("late_minutes = in - (S + grace_in_minutes)",),
    ),
    DecisionRule(
        order=9,
        condition="IN, no OUT, as_of > E + auto_close",
        statuses=(AttendanceStatus.INCOMPLETE,),
    ),
    DecisionRule(
        order=10,
        condition="otherwise",
        statuses=(AttendanceStatus.ON_TIME, AttendanceStatus.COMPLETE),
    ),
)

INDEPENDENT_FLAGS: tuple[AttendanceFlag, ...] = (
    AttendanceFlag.WAS_LATE,
    AttendanceFlag.LEFT_EARLY,
    AttendanceFlag.LOCATION_MISMATCH,
    AttendanceFlag.WAS_BACKDATED,
    AttendanceFlag.AUTO_CLOSED,
)


def assert_decision_table_integrity() -> None:
    orders = [rule.order for rule in DECISION_TABLE]
    expected = list(range(1, len(DECISION_TABLE) + 1))
    if orders != expected:
        raise ValueError(f"decision table order must be contiguous first-match order: {orders}")
    if DECISION_TABLE[0].condition != "attendance_overrides row exists":
        raise ValueError("override row must be the first decision rule")
    if DECISION_TABLE[4].statuses != (AttendanceStatus.PENDING,):
        raise ValueError("row 5 must be the pending status")
