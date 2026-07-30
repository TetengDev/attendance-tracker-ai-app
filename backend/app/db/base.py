from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class TableName(str, Enum):
    ATTENDANCE_EVENTS = "attendance_events"
    EXPECTED_ATTENDANCE = "expected_attendance"
    ATTENDANCE_RECORDS = "attendance_records"
    ATTENDANCE_OVERRIDES = "attendance_overrides"
    FACE_EMBEDDINGS = "face_embeddings"
    SETTINGS = "settings"


class TimestampColumn(str, Enum):
    CLIENT_CAPTURED_AT = "client_captured_at"
    SERVER_RECEIVED_AT = "server_received_at"
    OCCURRED_AT = "occurred_at"
    CREATED_AT = "created_at"
    UPDATED_AT = "updated_at"


ATTENDANCE_NATURAL_KEY: tuple[str, ...] = (
    "person_id",
    "business_date",
    "shift_id",
    "period_label",
)

PER_DAY_PERIOD_LABEL = ""


@dataclass(frozen=True)
class NaturalKeySpec:
    table: TableName
    columns: tuple[str, ...]
    note: str


NATURAL_KEYS: dict[TableName, NaturalKeySpec] = {
    TableName.ATTENDANCE_EVENTS: NaturalKeySpec(
        table=TableName.ATTENDANCE_EVENTS,
        columns=("idempotency_key",),
        note="unique; table is append-only and corrections use supersedes_event_id",
    ),
    TableName.EXPECTED_ATTENDANCE: NaturalKeySpec(
        table=TableName.EXPECTED_ATTENDANCE,
        columns=ATTENDANCE_NATURAL_KEY,
        note="period_label is NOT NULL DEFAULT ''",
    ),
    TableName.ATTENDANCE_RECORDS: NaturalKeySpec(
        table=TableName.ATTENDANCE_RECORDS,
        columns=ATTENDANCE_NATURAL_KEY,
        note="derived cache; resolve() is the sole writer",
    ),
    TableName.ATTENDANCE_OVERRIDES: NaturalKeySpec(
        table=TableName.ATTENDANCE_OVERRIDES,
        columns=ATTENDANCE_NATURAL_KEY,
        note="separate from records; recomputation must never clobber rows",
    ),
    TableName.FACE_EMBEDDINGS: NaturalKeySpec(
        table=TableName.FACE_EMBEDDINGS,
        columns=("person_id", "model_name", "model_version"),
        note="partial unique WHERE is_active; vector column is encrypted bytea",
    ),
    TableName.SETTINGS: NaturalKeySpec(
        table=TableName.SETTINGS,
        columns=("key", "scope", "scope_id"),
        note="key must exist in SETTINGS_SCHEMA",
    ),
}


PARALLEL_SAFE_MAY_AUTHOR_MIGRATION = False


def natural_key_for(table: TableName) -> tuple[str, ...]:
    return NATURAL_KEYS[table].columns


def uses_attendance_grain(table: TableName) -> bool:
    return natural_key_for(table) == ATTENDANCE_NATURAL_KEY
