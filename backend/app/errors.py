from enum import Enum
from typing import Dict, Any


class ErrorCode(str, Enum):
    NO_FACE = "NO_FACE"
    MULTIPLE_FACES = "MULTIPLE_FACES"
    FACE_TOO_SMALL = "FACE_TOO_SMALL"
    LOW_QUALITY = "LOW_QUALITY"
    LIVENESS_FAILED = "LIVENESS_FAILED"
    AMBIGUOUS = "AMBIGUOUS"
    LOW_CONFIDENCE = "LOW_CONFIDENCE"
    UNKNOWN_FACE = "UNKNOWN_FACE"
    COOLDOWN_ACTIVE = "COOLDOWN_ACTIVE"
    RATE_LIMITED = "RATE_LIMITED"
    LOCATION_CONFLICT = "LOCATION_CONFLICT"
    DEVICE_REVOKED = "DEVICE_REVOKED"
    SCAN_BACKEND_UNAVAILABLE = "SCAN_BACKEND_UNAVAILABLE"
    NO_CONSENT = "NO_CONSENT"
    DUPLICATE_ENROLLMENT = "DUPLICATE_ENROLLMENT"


_HTTP_STATUS: Dict[ErrorCode, int] = {
    ErrorCode.NO_FACE: 422,
    ErrorCode.MULTIPLE_FACES: 422,
    ErrorCode.FACE_TOO_SMALL: 422,
    ErrorCode.LOW_QUALITY: 422,
    ErrorCode.LIVENESS_FAILED: 403,
    ErrorCode.AMBIGUOUS: 409,
    ErrorCode.LOW_CONFIDENCE: 409,
    ErrorCode.UNKNOWN_FACE: 404,
    ErrorCode.COOLDOWN_ACTIVE: 200,
    ErrorCode.RATE_LIMITED: 429,
    ErrorCode.LOCATION_CONFLICT: 409,
    ErrorCode.DEVICE_REVOKED: 401,
    ErrorCode.SCAN_BACKEND_UNAVAILABLE: 503,
    ErrorCode.NO_CONSENT: 422,
    ErrorCode.DUPLICATE_ENROLLMENT: 409,
}


def make_error(code: ErrorCode, message: str, details: Any | None = None) -> Dict[str, Any]:
    env = {"error": {"code": code.value, "message": message}}
    if details is not None:
        env["error"]["details"] = details
    return env


def http_status_for(code: ErrorCode) -> int:
    return _HTTP_STATUS.get(code, 500)
