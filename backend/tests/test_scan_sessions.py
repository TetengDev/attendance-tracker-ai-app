from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, cast
from uuid import UUID

import pytest
from sqlalchemy import Table

from backend.app.models.attendance import AttendanceLocationSource
from backend.app.models.devices import Device, DeviceDirection, DeviceFormFactor, DeviceMode
from backend.app.models.sessions import ScanSession, ScanSessionEndReason, ScanSessionLocationSource
from backend.app.scan.sessions import (
    ScanSessionError,
    close_if_expired,
    close_scan_session,
    open_scan_session,
    require_scan_attribution,
)

DEVICE_ID = UUID("00000000-0000-0000-0000-000000000092")
LOCATION_A = UUID("10000000-0000-0000-0000-000000000092")
LOCATION_B = UUID("20000000-0000-0000-0000-000000000092")
OPERATOR_ID = UUID("30000000-0000-0000-0000-000000000092")
SESSION_ID = UUID("40000000-0000-0000-0000-000000000092")
STARTED_AT = datetime(2026, 8, 4, 8, 0, tzinfo=UTC)


def test_scan_session_model_encodes_lifecycle_constraints() -> None:
    table = cast(Table, ScanSession.__table__)
    constraints = {constraint.name for constraint in table.constraints}
    indexes = {index.name for index in table.indexes}

    assert {
        "ck_scan_sessions_location_source_valid",
        "ck_scan_sessions_end_reason_valid",
        "ck_scan_sessions_ended_state_matches_reason",
        "ck_scan_sessions_ended_at_not_before_started_at",
        "ck_scan_sessions_last_activity_not_before_started_at",
        "ck_scan_sessions_scan_count_non_negative",
        "ck_scan_sessions_start_lat_range",
        "ck_scan_sessions_start_lng_range",
        "ck_scan_sessions_gps_accuracy_non_negative",
    } <= constraints
    assert "uq_scan_sessions_open_device" in indexes
    assert "ix_scan_sessions_device_started_at" in indexes
    assert "ix_scan_sessions_location_started_at" in indexes
    assert cast(Any, table.columns["started_at"].type).timezone is True


def test_fixed_device_session_uses_device_location_and_ignores_operator_requirement() -> None:
    device = fixed_device()

    session = open_scan_session(
        device,
        location_id=LOCATION_A,
        operator_admin_id=None,
        location_source=ScanSessionLocationSource.SESSION_DECLARED,
        started_at=STARTED_AT,
    )

    assert session.location_id == LOCATION_A
    assert session.operator_admin_id is None
    assert session.location_source == ScanSessionLocationSource.DEVICE_FIXED
    assert session.is_open


def test_fixed_device_rejects_session_at_non_device_location() -> None:
    with pytest.raises(ScanSessionError, match="device location"):
        open_scan_session(
            fixed_device(),
            location_id=LOCATION_B,
            operator_admin_id=None,
            location_source=ScanSessionLocationSource.SESSION_DECLARED,
            started_at=STARTED_AT,
        )


def test_roaming_session_requires_operator_and_optional_geofence() -> None:
    device = roaming_device()

    with pytest.raises(ScanSessionError, match="require an operator"):
        open_scan_session(
            device,
            location_id=LOCATION_A,
            operator_admin_id=None,
            location_source=ScanSessionLocationSource.SESSION_DECLARED,
            started_at=STARTED_AT,
        )

    with pytest.raises(ScanSessionError, match="require geofence"):
        open_scan_session(
            device,
            location_id=LOCATION_A,
            operator_admin_id=OPERATOR_ID,
            location_source=ScanSessionLocationSource.SESSION_DECLARED,
            started_at=STARTED_AT,
            settings={"session.require_operator": True, "session.require_geofence": True},
        )

    session = open_scan_session(
        device,
        location_id=LOCATION_A,
        operator_admin_id=OPERATOR_ID,
        location_source=ScanSessionLocationSource.GEOFENCE,
        started_at=STARTED_AT,
        settings={"session.require_operator": True, "session.require_geofence": True},
        start_lat=Decimal("14.599512"),
        start_lng=Decimal("120.984222"),
        gps_accuracy_m=Decimal("8.00"),
    )

    assert session.location_source == ScanSessionLocationSource.GEOFENCE
    assert session.start_lat == Decimal("14.599512")


def test_roaming_device_cannot_scan_without_open_session() -> None:
    with pytest.raises(ScanSessionError, match="requires an open scan session"):
        require_scan_attribution(roaming_device(), None, now=STARTED_AT)


def test_scan_activity_returns_attribution_and_updates_session() -> None:
    device = roaming_device()
    session = scan_session(device_id=device.id, location_id=LOCATION_A)

    attribution = require_scan_attribution(
        device,
        session,
        now=STARTED_AT + timedelta(minutes=3),
    )

    assert attribution.session_id == SESSION_ID
    assert attribution.location_id == LOCATION_A
    assert attribution.location_source == AttendanceLocationSource.SESSION_DECLARED
    assert session.scan_count == 1
    assert session.last_activity_at == STARTED_AT + timedelta(minutes=3)


def test_ending_session_and_starting_another_changes_attribution() -> None:
    device = roaming_device()
    first = scan_session(device_id=device.id, location_id=LOCATION_A)
    close_scan_session(
        first,
        ended_at=STARTED_AT + timedelta(minutes=5),
        reason=ScanSessionEndReason.EXPLICIT,
    )
    second = scan_session(device_id=device.id, location_id=LOCATION_B)

    attribution = require_scan_attribution(
        device,
        second,
        now=STARTED_AT + timedelta(minutes=6),
    )

    assert first.ended_at == STARTED_AT + timedelta(minutes=5)
    assert first.end_reason == ScanSessionEndReason.EXPLICIT
    assert attribution.location_id == LOCATION_B


def test_idle_or_max_duration_expiry_closes_and_rejects_scan() -> None:
    device = roaming_device()
    idle_session = scan_session(device_id=device.id, location_id=LOCATION_A)

    with pytest.raises(ScanSessionError, match="closed"):
        require_scan_attribution(
            device,
            idle_session,
            now=STARTED_AT + timedelta(minutes=21),
        )

    assert idle_session.end_reason == ScanSessionEndReason.IDLE_TIMEOUT

    max_duration_session = scan_session(device_id=device.id, location_id=LOCATION_A)
    max_duration_session.last_activity_at = STARTED_AT + timedelta(minutes=230)

    closed = close_if_expired(
        max_duration_session,
        now=STARTED_AT + timedelta(minutes=241),
        settings={"session.idle_timeout_minutes": 60, "session.max_duration_minutes": 240},
    )

    assert closed is max_duration_session
    assert max_duration_session.end_reason == ScanSessionEndReason.MAX_DURATION


def test_fixed_device_scan_attribution_does_not_require_explicit_session() -> None:
    attribution = require_scan_attribution(fixed_device(), None, now=STARTED_AT)

    assert attribution.session_id is None
    assert attribution.location_id == LOCATION_A
    assert attribution.location_source == AttendanceLocationSource.DEVICE_FIXED


def fixed_device() -> Device:
    return Device(
        id=DEVICE_ID,
        mode=DeviceMode.FIXED,
        location_id=LOCATION_A,
        form_factor=DeviceFormFactor.TABLET,
        direction=DeviceDirection.BIDIRECTIONAL,
        token_hash="hash",
        token_display_prefix="tok_",
    )


def roaming_device() -> Device:
    return Device(
        id=DEVICE_ID,
        mode=DeviceMode.ROAMING,
        form_factor=DeviceFormFactor.PHONE,
        direction=DeviceDirection.BIDIRECTIONAL,
        token_hash="hash",
        token_display_prefix="tok_",
    )


def scan_session(*, device_id: UUID, location_id: UUID) -> ScanSession:
    return ScanSession(
        id=SESSION_ID,
        device_id=device_id,
        location_id=location_id,
        operator_admin_id=OPERATOR_ID,
        location_source=ScanSessionLocationSource.SESSION_DECLARED,
        started_at=STARTED_AT,
        last_activity_at=STARTED_AT,
        scan_count=0,
    )
