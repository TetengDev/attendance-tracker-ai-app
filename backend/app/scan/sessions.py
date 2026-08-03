from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models.attendance import AttendanceLocationSource
from backend.app.models.devices import Device, DeviceMode
from backend.app.models.sessions import ScanSession, ScanSessionEndReason, ScanSessionLocationSource
from backend.app.settings.registry import default_settings


class ScanSessionError(ValueError):
    """Raised when a device cannot scan because its session state is invalid."""


@dataclass(frozen=True)
class ScanAttribution:
    session_id: UUID | None
    location_id: UUID
    location_source: AttendanceLocationSource


def open_scan_session(
    device: Device,
    *,
    location_id: UUID,
    operator_admin_id: UUID | None,
    location_source: ScanSessionLocationSource,
    started_at: datetime,
    settings: dict[str, object] | None = None,
    start_lat: Decimal | None = None,
    start_lng: Decimal | None = None,
    gps_accuracy_m: Decimal | None = None,
) -> ScanSession:
    values = _settings_with_defaults(settings)
    if DeviceMode(device.mode) is DeviceMode.FIXED:
        if device.location_id is None:
            raise ScanSessionError("fixed devices require a configured location")
        if location_id != device.location_id:
            raise ScanSessionError("fixed device sessions must use the device location")
        location_source = ScanSessionLocationSource.DEVICE_FIXED
    else:
        if _bool_setting(values, "session.require_operator") and operator_admin_id is None:
            raise ScanSessionError("roaming sessions require an operator")
        if (
            _bool_setting(values, "session.require_geofence")
            and location_source is not ScanSessionLocationSource.GEOFENCE
        ):
            raise ScanSessionError("roaming sessions require geofence confirmation")

    return ScanSession(
        device_id=device.id,
        location_id=location_id,
        operator_admin_id=operator_admin_id,
        location_source=location_source,
        started_at=started_at,
        last_activity_at=started_at,
        start_lat=start_lat,
        start_lng=start_lng,
        gps_accuracy_m=gps_accuracy_m,
        scan_count=0,
    )


def close_scan_session(
    scan_session: ScanSession,
    *,
    ended_at: datetime,
    reason: ScanSessionEndReason,
) -> ScanSession:
    if scan_session.ended_at is None:
        scan_session.ended_at = ended_at
        scan_session.end_reason = reason
    return scan_session


def close_if_expired(
    scan_session: ScanSession,
    *,
    now: datetime,
    settings: dict[str, object] | None = None,
) -> ScanSession | None:
    if scan_session.ended_at is not None:
        return scan_session

    values = _settings_with_defaults(settings)
    idle_timeout = timedelta(minutes=_int_setting(values, "session.idle_timeout_minutes"))
    max_duration = timedelta(minutes=_int_setting(values, "session.max_duration_minutes"))
    if now - scan_session.last_activity_at >= idle_timeout:
        return close_scan_session(
            scan_session,
            ended_at=now,
            reason=ScanSessionEndReason.IDLE_TIMEOUT,
        )
    if now - scan_session.started_at >= max_duration:
        return close_scan_session(
            scan_session,
            ended_at=now,
            reason=ScanSessionEndReason.MAX_DURATION,
        )
    return None


def require_scan_attribution(
    device: Device,
    scan_session: ScanSession | None,
    *,
    now: datetime,
    settings: dict[str, object] | None = None,
) -> ScanAttribution:
    if DeviceMode(device.mode) is DeviceMode.FIXED:
        if device.location_id is None:
            raise ScanSessionError("fixed devices require a configured location")
        return ScanAttribution(
            session_id=scan_session.id if scan_session is not None else None,
            location_id=device.location_id,
            location_source=AttendanceLocationSource.DEVICE_FIXED,
        )

    if scan_session is None or scan_session.ended_at is not None:
        raise ScanSessionError("roaming device requires an open scan session")
    if scan_session.device_id != device.id:
        raise ScanSessionError("scan session belongs to a different device")
    if close_if_expired(scan_session, now=now, settings=settings) is not None:
        raise ScanSessionError("scan session is closed")

    scan_session.last_activity_at = now
    scan_session.scan_count += 1
    return ScanAttribution(
        session_id=scan_session.id,
        location_id=scan_session.location_id,
        location_source=AttendanceLocationSource(scan_session.location_source),
    )


async def active_scan_session_for_device(
    session: AsyncSession,
    *,
    device_id: UUID,
) -> ScanSession | None:
    query: Select[tuple[ScanSession]] = (
        select(ScanSession)
        .where(ScanSession.device_id == device_id)
        .where(ScanSession.ended_at.is_(None))
        .limit(1)
    )
    return (await session.execute(query)).scalar_one_or_none()


def _bool_setting(settings: dict[str, object], key: str) -> bool:
    value = settings[key]
    if not isinstance(value, bool):
        raise TypeError(f"{key} must be bool")
    return value


def _int_setting(settings: dict[str, object], key: str) -> int:
    value = settings[key]
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{key} must be int")
    return value


def _settings_with_defaults(overrides: dict[str, object] | None) -> dict[str, object]:
    values = default_settings()
    if overrides is not None:
        values.update(overrides)
    return values
