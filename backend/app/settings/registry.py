from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Literal
from uuid import UUID

SettingType = Literal["bool", "enum", "float", "int", "str", "uuid?"]
SettingScope = Literal["O", "O·L", "O·D", "O·L·D"]


class SettingValidationError(ValueError):
    """Raised when a setting key or value does not match SETTINGS_SCHEMA."""


class LowConfidenceAction(str, Enum):
    REJECT = "reject"
    CONFIRM = "confirm"


class CooldownScope(str, Enum):
    DEVICE = "device"
    LOCATION = "location"
    GLOBAL = "global"


class LivenessMode(str, Enum):
    OFF = "off"
    MONITOR = "monitor"
    ENFORCE = "enforce"


class CameraFacing(str, Enum):
    USER = "user"
    ENVIRONMENT = "environment"


class ScanMode(str, Enum):
    CONTINUOUS = "continuous"
    TAP_TO_SCAN = "tap_to_scan"


class PairingStrategy(str, Enum):
    DEVICE_DIRECTION = "device_direction"
    TOGGLE = "toggle"
    FIRST_LAST = "first_last"


class PrivacyRegion(str, Enum):
    PH = "PH"
    US = "US"
    EU = "EU"
    OTHER = "OTHER"


@dataclass(frozen=True)
class SettingSpec:
    type: SettingType
    default: Any
    scope: SettingScope
    min: int | float | None = None
    max: int | float | None = None
    enum: tuple[str, ...] | None = None
    max_length: int | None = None
    format: str | None = None
    note: str | None = None


SETTINGS_SCHEMA: dict[str, SettingSpec] = {
    "face.match_threshold": SettingSpec("float", 0.45, "O", min=0.20, max=0.80),
    "face.match_margin": SettingSpec("float", 0.05, "O", min=0.0, max=0.30),
    "face.low_confidence_threshold": SettingSpec("float", 0.38, "O", min=0.20, max=0.80),
    "face.low_confidence_action": SettingSpec(
        "enum",
        LowConfidenceAction.REJECT.value,
        "O·L",
        enum=tuple(e.value for e in LowConfidenceAction),
    ),
    "face.det_score_min": SettingSpec("float", 0.60, "O", min=0.10, max=0.99),
    "face.det_size": SettingSpec("int", 384, "O", min=128, max=800),
    "liveness.mode": SettingSpec(
        "enum", LivenessMode.MONITOR.value, "O·L·D", enum=tuple(e.value for e in LivenessMode)
    ),
    "liveness.threshold": SettingSpec("float", 0.75, "O", min=0.0, max=1.0),
    "scan.cooldown_seconds": SettingSpec("int", 60, "O·L", min=0, max=3600),
    "scan.cooldown_scope": SettingSpec(
        "enum", CooldownScope.LOCATION.value, "O", enum=tuple(e.value for e in CooldownScope)
    ),
    "scan.duplicate_window_seconds": SettingSpec("int", 300, "O", min=0, max=3600),
    "scan.rate_per_second": SettingSpec("int", 2, "O·D", min=1, max=20),
    "scan.unknown_rate_per_minute": SettingSpec("int", 10, "O·D", min=1, max=120),
    "scan.unknown_lockout_seconds": SettingSpec("int", 60, "O·D", min=0, max=3600),
    "scan.min_inter_location_seconds": SettingSpec("int", 120, "O", min=0, max=7200),
    "scan.max_offline_backdate_minutes": SettingSpec("int", 240, "O", min=0, max=1440),
    "session.require_operator": SettingSpec("bool", True, "O", note="roaming devices"),
    "session.max_duration_minutes": SettingSpec("int", 240, "O·L", min=5, max=1440),
    "session.idle_timeout_minutes": SettingSpec("int", 20, "O·L", min=1, max=240),
    "session.require_geofence": SettingSpec("bool", False, "O·L"),
    "session.geofence_radius_m": SettingSpec("int", 150, "O·L", min=25, max=5000),
    "kiosk.camera_facing": SettingSpec(
        "enum", CameraFacing.USER.value, "O·D", enum=tuple(e.value for e in CameraFacing)
    ),
    "kiosk.scan_mode": SettingSpec(
        "enum", ScanMode.CONTINUOUS.value, "O·L·D", enum=tuple(e.value for e in ScanMode)
    ),
    "kiosk.low_battery_pct": SettingSpec("int", 15, "O", min=0, max=50),
    "kiosk.gate.min_bbox_area_pct": SettingSpec("float", 8.0, "O·D", min=1, max=50),
    "kiosk.gate.min_interocular_px": SettingSpec("int", 90, "O·D", min=30, max=300),
    "kiosk.gate.max_center_offset_pct": SettingSpec("float", 20.0, "O·D", min=5, max=50),
    "kiosk.gate.min_sharpness": SettingSpec("float", 60.0, "O·D", min=0, max=1000),
    "kiosk.gate.luma_min": SettingSpec("int", 40, "O·D", min=0, max=255),
    "kiosk.gate.luma_max": SettingSpec("int", 220, "O·D", min=0, max=255),
    "kiosk.gate.stability_iou": SettingSpec("float", 0.90, "O", min=0.5, max=1.0),
    "kiosk.gate.stability_frames": SettingSpec("int", 3, "O", min=1, max=10),
    "kiosk.gate.stability_ms": SettingSpec("int", 120, "O", min=0, max=2000),
    "kiosk.submit_throttle_ms": SettingSpec("int", 400, "O·D", min=100, max=5000),
    "kiosk.burst_count": SettingSpec("int", 2, "O", min=1, max=5),
    "kiosk.burst_interval_ms": SettingSpec("int", 150, "O", min=50, max=1000),
    "kiosk.crop_expand": SettingSpec("float", 4.0, "O", min=2.0, max=6.0),
    "kiosk.greeting_text": SettingSpec("str", "Welcome", "O·L·D", max_length=120),
    "kiosk.locale": SettingSpec("str", "en", "O·L·D", format="BCP-47"),
    "kiosk.result_duration_ms": SettingSpec("int", 3000, "O·L·D", min=500, max=15000),
    "kiosk.sound_enabled": SettingSpec("bool", True, "O·L·D"),
    "kiosk.show_photo": SettingSpec("bool", True, "O·L·D"),
    "branding.org_name": SettingSpec("str", "", "O", max_length=120),
    "branding.logo_asset_id": SettingSpec("uuid?", None, "O·L"),
    "branding.primary_color": SettingSpec("str", "#5e6ad2", "O·L", format="hex"),
    "branding.accent_color": SettingSpec("str", "#4cb782", "O·L", format="hex"),
    "attendance.grace_in_minutes": SettingSpec("int", 10, "O·L", min=0, max=240),
    "attendance.grace_out_minutes": SettingSpec("int", 10, "O·L", min=0, max=240),
    "attendance.absent_after_minutes": SettingSpec("int", 60, "O·L", min=5, max=1440),
    "attendance.min_dwell_minutes": SettingSpec("int", 5, "O·L", min=0, max=480),
    "attendance.pairing_strategy": SettingSpec(
        "enum",
        PairingStrategy.FIRST_LAST.value,
        "O·L",
        enum=tuple(e.value for e in PairingStrategy),
    ),
    "attendance.day_boundary_hour": SettingSpec("int", 0, "O·L", min=0, max=23),
    "attendance.auto_close_enabled": SettingSpec("bool", False, "O·L"),
    "attendance.absence_notify_delay_minutes": SettingSpec("int", 10, "O", min=0, max=240),
    "privacy.region": SettingSpec(
        "enum", PrivacyRegion.PH.value, "O", enum=tuple(e.value for e in PrivacyRegion)
    ),
    "privacy.store_enrollment_originals": SettingSpec("bool", True, "O"),
    "privacy.store_failed_scans": SettingSpec("bool", False, "O"),
    "privacy.debug_capture_mode": SettingSpec("bool", False, "O·D", note="auto-expires 24h"),
    "retention.embeddings_days_after_inactive": SettingSpec("int", 1095, "O", min=30, max=3650),
    "retention.enrollment_images_days": SettingSpec("int", 1095, "O", min=30, max=3650),
    "retention.unknown_face_hours": SettingSpec("int", 72, "O", min=1, max=720),
    "retention.events_days": SettingSpec("int", 2555, "O", min=365, max=3650),
    "retention.records_days": SettingSpec("int", 2555, "O", min=365, max=3650),
    "retention.audit_days": SettingSpec("int", 2555, "O", min=365, max=3650),
}


def default_settings() -> dict[str, Any]:
    return {key: spec.default for key, spec in SETTINGS_SCHEMA.items()}


def validate_setting(key: str, value: Any) -> Any:
    try:
        spec = SETTINGS_SCHEMA[key]
    except KeyError as exc:
        raise SettingValidationError(f"unknown setting key: {key}") from exc

    coerced = _coerce_value(spec, value)
    _validate_range(key, spec, coerced)
    _validate_format(key, spec, coerced)
    return coerced


def _coerce_value(spec: SettingSpec, value: Any) -> Any:
    if spec.type == "bool":
        if isinstance(value, bool):
            return value
        raise SettingValidationError("expected bool")
    if spec.type == "enum":
        if not isinstance(value, str):
            raise SettingValidationError("expected enum string")
        if spec.enum is not None and value not in spec.enum:
            raise SettingValidationError(f"expected one of: {', '.join(spec.enum)}")
        return value
    if spec.type == "float":
        if isinstance(value, bool):
            raise SettingValidationError("expected float")
        return float(value)
    if spec.type == "int":
        if isinstance(value, bool):
            raise SettingValidationError("expected int")
        if isinstance(value, float) and not value.is_integer():
            raise SettingValidationError("expected int")
        return int(value)
    if spec.type == "str":
        if not isinstance(value, str):
            raise SettingValidationError("expected string")
        return value
    if spec.type == "uuid?":
        if value is None:
            return None
        return str(UUID(str(value)))
    raise AssertionError(f"unhandled setting type: {spec.type}")


def _validate_range(key: str, spec: SettingSpec, value: Any) -> None:
    if spec.min is not None and value < spec.min:
        raise SettingValidationError(f"{key} must be >= {spec.min}")
    if spec.max is not None and value > spec.max:
        raise SettingValidationError(f"{key} must be <= {spec.max}")
    if spec.max_length is not None and len(value) > spec.max_length:
        raise SettingValidationError(f"{key} must be <= {spec.max_length} characters")


def _validate_format(key: str, spec: SettingSpec, value: Any) -> None:
    if spec.format == "hex":
        if not isinstance(value, str) or len(value) != 7 or value[0] != "#":
            raise SettingValidationError(f"{key} must be a #RRGGBB hex color")
        try:
            int(value[1:], 16)
        except ValueError as exc:
            raise SettingValidationError(f"{key} must be a #RRGGBB hex color") from exc
