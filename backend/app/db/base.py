from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from uuid import UUID

from sqlalchemy import BigInteger, DateTime, Identity, MetaData, func, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import Uuid

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Declarative base shared by all SQLAlchemy models."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def uuid_pk() -> Mapped[UUID]:
    """UUID primary key backed by Postgres `gen_random_uuid()`."""

    return mapped_column(
        Uuid(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )


def bigint_identity_pk() -> Mapped[int]:
    """Bigint identity primary key for high-volume append-only tables."""

    return mapped_column(BigInteger, Identity(), primary_key=True)


def created_at_column() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


def updated_at_column() -> Mapped[datetime]:
    return mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


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
