from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import Enum
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, validates
from sqlalchemy.orm import relationship as orm_relationship
from sqlalchemy.types import Uuid

from backend.app.db.base import (
    Base,
    bigint_identity_pk,
    created_at_column,
    updated_at_column,
    uuid_pk,
)

DEVICE_HEARTBEAT_RETENTION_DAYS = 7


class DeviceMode(str, Enum):
    FIXED = "fixed"
    ROAMING = "roaming"


class DeviceDirection(str, Enum):
    IN = "in"
    OUT = "out"
    BIDIRECTIONAL = "bidirectional"


class DeviceFormFactor(str, Enum):
    PHONE = "phone"
    TABLET = "tablet"
    DESKTOP = "desktop"


def validate_iana_timezone(value: str) -> str:
    if not value:
        raise ValueError("timezone is required")
    try:
        ZoneInfo(value)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"invalid IANA timezone: {value}") from exc
    return value


class Location(Base):
    __tablename__ = "locations"
    __table_args__ = (
        CheckConstraint("name <> ''", name="name_non_empty"),
        CheckConstraint("timezone <> ''", name="timezone_non_empty"),
        CheckConstraint("latitude IS NULL OR latitude BETWEEN -90 AND 90", name="latitude_range"),
        CheckConstraint("longitude IS NULL OR longitude BETWEEN -180 AND 180", name="longitude_range"),
    )

    id: Mapped[UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False)
    latitude: Mapped[Decimal | None] = mapped_column(Numeric(8, 6), nullable=True)
    longitude: Mapped[Decimal | None] = mapped_column(Numeric(9, 6), nullable=True)
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()

    devices: Mapped[list[Device]] = orm_relationship(back_populates="location")

    @validates("timezone")
    def validate_timezone(self, _key: str, value: str) -> str:
        return validate_iana_timezone(value)


class Device(Base):
    __tablename__ = "devices"
    __table_args__ = (
        CheckConstraint(
            "mode IN ('fixed', 'roaming')",
            name="mode_valid",
        ),
        CheckConstraint(
            "form_factor IN ('phone', 'tablet', 'desktop')",
            name="form_factor_valid",
        ),
        CheckConstraint(
            "direction IN ('in', 'out', 'bidirectional')",
            name="direction_valid",
        ),
        CheckConstraint(
            "mode <> 'fixed' OR location_id IS NOT NULL",
            name="fixed_devices_require_location",
        ),
        CheckConstraint("token_hash <> ''", name="token_hash_non_empty"),
        CheckConstraint("token_display_prefix <> ''", name="token_display_prefix_non_empty"),
        CheckConstraint(
            "pairing_code_hash IS NULL OR pairing_code_expires_at IS NOT NULL",
            name="pairing_code_requires_expiry",
        ),
    )

    id: Mapped[UUID] = uuid_pk()
    location_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("locations.id", ondelete="SET NULL"),
        nullable=True,
    )
    mode: Mapped[DeviceMode] = mapped_column(
        String(16),
        nullable=False,
        default=DeviceMode.FIXED,
    )
    form_factor: Mapped[DeviceFormFactor] = mapped_column(String(16), nullable=False)
    direction: Mapped[DeviceDirection] = mapped_column(
        String(16),
        nullable=False,
        default=DeviceDirection.BIDIRECTIONAL,
    )
    token_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    token_display_prefix: Mapped[str] = mapped_column(String(32), nullable=False)
    pairing_code_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    pairing_code_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    settings_override: Mapped[dict[str, object]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
    )
    allowed_cidrs: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()

    location: Mapped[Location | None] = orm_relationship(back_populates="devices")
    heartbeats: Mapped[list[DeviceHeartbeat]] = orm_relationship(
        back_populates="device",
        cascade="all, delete-orphan",
    )

    def __init__(self, **kwargs: object) -> None:
        object.__setattr__(self, "_allow_incomplete_device_state", True)
        super().__init__(**kwargs)
        object.__setattr__(self, "_allow_incomplete_device_state", False)
        self.require_valid_location_mode(self.mode, self.location_id)

    @validates("location_id", "mode")
    def validate_location_mode(self, key: str, value: DeviceMode | UUID | None) -> DeviceMode | UUID | None:
        if getattr(self, "_allow_incomplete_device_state", False):
            return value
        candidate_mode = value if key == "mode" else self.mode
        candidate_location_id = value if key == "location_id" else self.location_id
        self.require_valid_location_mode(candidate_mode, candidate_location_id)
        return value

    @staticmethod
    def require_valid_location_mode(
        mode: DeviceMode | UUID | None,
        location_id: DeviceMode | UUID | None,
    ) -> None:
        if mode == DeviceMode.FIXED and location_id is None:
            raise ValueError("fixed devices require a location")


class DeviceHeartbeat(Base):
    __tablename__ = "device_heartbeats"
    __table_args__ = (
        CheckConstraint(
            "battery_pct IS NULL OR battery_pct BETWEEN 0 AND 100",
            name="battery_pct_range",
        ),
    )

    id: Mapped[int] = bigint_identity_pk()
    device_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("devices.id", ondelete="CASCADE"),
        nullable=False,
    )
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    battery_pct: Mapped[int | None] = mapped_column(Integer, nullable=True)
    clock_skew_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = created_at_column()

    device: Mapped[Device] = orm_relationship(back_populates="heartbeats")


def heartbeat_is_retained(observed_at: datetime, *, now: datetime) -> bool:
    return (now - observed_at).days < DEVICE_HEARTBEAT_RETENTION_DAYS
