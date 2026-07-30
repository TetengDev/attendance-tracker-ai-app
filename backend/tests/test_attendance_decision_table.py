from backend.app.attendance.decision_table import (
    DECISION_TABLE,
    INDEPENDENT_FLAGS,
    AttendanceFlag,
    AttendanceStatus,
    assert_decision_table_integrity,
)


def test_decision_table_is_ordered_first_match_data() -> None:
    assert_decision_table_integrity()
    assert [rule.order for rule in DECISION_TABLE] == list(range(1, 11))
    assert DECISION_TABLE[0].statuses == ("override.status",)
    assert DECISION_TABLE[4].statuses == (AttendanceStatus.PENDING,)


def test_independent_flags_include_late_and_early_out_separately() -> None:
    assert AttendanceFlag.WAS_LATE in INDEPENDENT_FLAGS
    assert AttendanceFlag.LEFT_EARLY in INDEPENDENT_FLAGS
