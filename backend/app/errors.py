from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from http import HTTPStatus
from typing import Any


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


ERROR_HTTP_STATUS: dict[ErrorCode, int] = {
    ErrorCode.NO_FACE: HTTPStatus.UNPROCESSABLE_ENTITY,
    ErrorCode.MULTIPLE_FACES: HTTPStatus.UNPROCESSABLE_ENTITY,
    ErrorCode.FACE_TOO_SMALL: HTTPStatus.UNPROCESSABLE_ENTITY,
    ErrorCode.LOW_QUALITY: HTTPStatus.UNPROCESSABLE_ENTITY,
    ErrorCode.LIVENESS_FAILED: HTTPStatus.FORBIDDEN,
    ErrorCode.AMBIGUOUS: HTTPStatus.CONFLICT,
    ErrorCode.LOW_CONFIDENCE: HTTPStatus.CONFLICT,
    ErrorCode.UNKNOWN_FACE: HTTPStatus.NOT_FOUND,
    ErrorCode.COOLDOWN_ACTIVE: HTTPStatus.OK,
    ErrorCode.RATE_LIMITED: HTTPStatus.TOO_MANY_REQUESTS,
    ErrorCode.LOCATION_CONFLICT: HTTPStatus.CONFLICT,
    ErrorCode.DEVICE_REVOKED: HTTPStatus.UNAUTHORIZED,
    ErrorCode.SCAN_BACKEND_UNAVAILABLE: HTTPStatus.SERVICE_UNAVAILABLE,
    ErrorCode.NO_CONSENT: HTTPStatus.UNPROCESSABLE_ENTITY,
    ErrorCode.DUPLICATE_ENROLLMENT: HTTPStatus.CONFLICT,
}


ERROR_KIOSK_COPY: dict[ErrorCode, str] = {
    ErrorCode.NO_FACE: "Step into view",
    ErrorCode.MULTIPLE_FACES: "One person at a time",
    ErrorCode.FACE_TOO_SMALL: "Move closer",
    ErrorCode.LOW_QUALITY: "Hold still",
    ErrorCode.LIVENESS_FAILED: "Unable to verify — see an administrator",
    ErrorCode.AMBIGUOUS: "Try again",
    ErrorCode.LOW_CONFIDENCE: "Try again or use your PIN",
    ErrorCode.UNKNOWN_FACE: "Not recognized — use your PIN",
    ErrorCode.COOLDOWN_ACTIVE: "Already recorded at {time}",
    ErrorCode.RATE_LIMITED: "Please wait",
    ErrorCode.LOCATION_CONFLICT: "Recorded — flagged for review",
    ErrorCode.DEVICE_REVOKED: "This device needs re-pairing",
    ErrorCode.SCAN_BACKEND_UNAVAILABLE: "Temporarily unavailable — try again",
    ErrorCode.NO_CONSENT: "No active consent",
    ErrorCode.DUPLICATE_ENROLLMENT: "Duplicate enrollment",
}


@dataclass(frozen=True)
class DomainError(Exception):
    code: ErrorCode
    message: str | None = None
    details: dict[str, Any] | None = None

    def envelope(self) -> dict[str, Any]:
        return make_error(self.code, self.message or ERROR_KIOSK_COPY[self.code], self.details)


def make_error(
    code: ErrorCode,
    message: str | None = None,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {"code": code.value, "message": message or ERROR_KIOSK_COPY[code]}
    if details is not None:
        body["details"] = details
    return {"error": body}


def http_status_for(code: ErrorCode) -> int:
    return int(ERROR_HTTP_STATUS[code])
