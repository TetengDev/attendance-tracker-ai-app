from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, cast
from uuid import UUID

import pytest
from sqlalchemy import Table

from backend.app.models.devices import (
    DEVICE_HEARTBEAT_RETENTION_DAYS,
    Device,
    DeviceDirection,
    DeviceFormFactor,
    DeviceHeartbeat,
    DeviceMode,
    Location,
    heartbeat_is_retained,
    validate_iana_timezone,
)


def test_location_requires_valid_iana_timezone() -> None:
    location = Location(name="Main Campus", timezone="Asia/Manila")

    assert location.timezone == "Asia/Manila"
    assert validate_iana_timezone("America/New_York") == "America/New_York"


def test_location_rejects_missing_or_invalid_timezone() -> None:
    with pytest.raises(ValueError, match="timezone is required"):
        Location(name="Main Campus", timezone="")

    with pytest.raises(ValueError, match="invalid IANA timezone"):
        Location(name="Main Campus", timezone="Mars/Base")


def test_location_model_includes_geofence_coordinates() -> None:
    location = Location(
        name="Main Campus",
        timezone="Asia/Manila",
        latitude=Decimal("14.599512"),
        longitude=Decimal("120.984222"),
    )
    columns = cast(Table, Location.__table__).columns

    assert columns["timezone"].nullable is False
    assert cast(Any, columns["latitude"].type).precision == 8
    assert cast(Any, columns["longitude"].type).precision == 9
    assert location.latitude == Decimal("14.599512")
    assert location.longitude == Decimal("120.984222")


def test_device_model_supports_fixed_and_roaming_modes() -> None:
    constraints = {constraint.name for constraint in cast(Table, Device.__table__).constraints}

    assert Device.location_id.property.columns[0].nullable is True
    assert {
        "ck_devices_mode_valid",
        "ck_devices_form_factor_valid",
        "ck_devices_direction_valid",
        "ck_devices_fixed_devices_require_location",
    } <= constraints

    roaming = Device(
        mode=DeviceMode.ROAMING,
        form_factor=DeviceFormFactor.PHONE,
        direction=DeviceDirection.BIDIRECTIONAL,
        token_hash="hash",
        token_display_prefix="tok_",
    )

    assert roaming.location_id is None


def test_fixed_device_requires_location_application_guard() -> None:
    with pytest.raises(ValueError, match="fixed devices require a location"):
        Device(
            mode=DeviceMode.FIXED,
            form_factor=DeviceFormFactor.TABLET,
            direction=DeviceDirection.IN,
            token_hash="hash",
            token_display_prefix="tok_",
        )

    fixed = Device(
        mode=DeviceMode.FIXED,
        location_id=UUID("00000000-0000-0000-0000-000000000001"),
        form_factor=DeviceFormFactor.TABLET,
        direction=DeviceDirection.IN,
        token_hash="hash",
        token_display_prefix="tok_",
    )

    assert fixed.location_id == UUID("00000000-0000-0000-0000-000000000001")


def test_roaming_device_cannot_be_mutated_to_fixed_without_location() -> None:
    device = Device(
        mode=DeviceMode.ROAMING,
        form_factor=DeviceFormFactor.PHONE,
        direction=DeviceDirection.BIDIRECTIONAL,
        token_hash="hash",
        token_display_prefix="tok_",
    )

    with pytest.raises(ValueError, match="fixed devices require a location"):
        device.mode = DeviceMode.FIXED


def test_device_heartbeat_tracks_mobile_health_and_retention() -> None:
    now = datetime(2026, 7, 31, 8, 0, tzinfo=UTC)
    heartbeat = DeviceHeartbeat(
        device_id=UUID("00000000-0000-0000-0000-000000000001"),
        observed_at=now - timedelta(days=6),
        battery_pct=4,
        clock_skew_ms=1_500,
    )
    constraints = {
        constraint.name for constraint in cast(Table, DeviceHeartbeat.__table__).constraints
    }

    assert DEVICE_HEARTBEAT_RETENTION_DAYS == 7
    assert heartbeat.battery_pct == 4
    assert heartbeat.clock_skew_ms == 1_500
    assert heartbeat_is_retained(heartbeat.observed_at, now=now)
    assert not heartbeat_is_retained(now - timedelta(days=7), now=now)
    assert "ck_device_heartbeats_battery_pct_range" in constraints


def test_device_heartbeat_uses_bigint_identity_primary_key() -> None:
    assert cast(Any, DeviceHeartbeat.id).property.columns[0].identity is not None
