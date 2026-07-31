from typing import Any, cast

from backend.app.db.base import (
    ATTENDANCE_NATURAL_KEY,
    NAMING_CONVENTION,
    NATURAL_KEYS,
    PARALLEL_SAFE_MAY_AUTHOR_MIGRATION,
    PER_DAY_PERIOD_LABEL,
    Base,
    TableName,
    TimestampColumn,
    bigint_identity_pk,
    created_at_column,
    natural_key_for,
    updated_at_column,
    uses_attendance_grain,
    uuid_pk,
)
from backend.app.db.session import create_engine, create_session_factory


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


def test_declarative_base_has_stable_naming_convention() -> None:
    assert Base.metadata.naming_convention == NAMING_CONVENTION
    assert NAMING_CONVENTION["pk"] == "pk_%(table_name)s"
    assert NAMING_CONVENTION["fk"] == "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s"


def test_column_convention_helpers_encode_phase_2_defaults() -> None:
    assert TimestampColumn.CREATED_AT.value == "created_at"
    assert cast(Any, uuid_pk()).column.server_default is not None
    assert cast(Any, bigint_identity_pk()).column.identity is not None
    assert cast(Any, created_at_column()).column.server_default is not None
    assert cast(Any, updated_at_column()).column.onupdate is not None


def test_async_session_factory_uses_non_expiring_sessions() -> None:
    engine = create_engine("postgresql+asyncpg://attendance:attendance@localhost:5432/attendance")
    session_factory = create_session_factory(engine)

    assert session_factory.kw["expire_on_commit"] is False
