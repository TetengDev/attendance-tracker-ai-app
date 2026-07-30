from backend.app.db.base import (
    ATTENDANCE_NATURAL_KEY,
    NATURAL_KEYS,
    PARALLEL_SAFE_MAY_AUTHOR_MIGRATION,
    PER_DAY_PERIOD_LABEL,
    TableName,
    natural_key_for,
    uses_attendance_grain,
)


def test_attendance_tables_share_forward_compatible_natural_key() -> None:
    assert PER_DAY_PERIOD_LABEL == ""
    assert natural_key_for(TableName.EXPECTED_ATTENDANCE) == ATTENDANCE_NATURAL_KEY
    assert natural_key_for(TableName.ATTENDANCE_RECORDS) == ATTENDANCE_NATURAL_KEY
    assert natural_key_for(TableName.ATTENDANCE_OVERRIDES) == ATTENDANCE_NATURAL_KEY
    assert uses_attendance_grain(TableName.ATTENDANCE_RECORDS)


def test_append_only_event_and_migration_rules_are_encoded() -> None:
    assert natural_key_for(TableName.ATTENDANCE_EVENTS) == ("idempotency_key",)
    assert "append-only" in NATURAL_KEYS[TableName.ATTENDANCE_EVENTS].note
    assert PARALLEL_SAFE_MAY_AUTHOR_MIGRATION is False
