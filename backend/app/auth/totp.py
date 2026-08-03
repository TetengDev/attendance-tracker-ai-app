from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
from datetime import UTC, datetime

TOTP_SECRET_BYTES = 32
TOTP_DIGITS = 6
TOTP_STEP_SECONDS = 30
TOTP_DRIFT_STEPS = 1


def generate_totp_secret() -> bytes:
    return secrets.token_bytes(TOTP_SECRET_BYTES)


def totp_secret_uri(secret: bytes, *, account_name: str, issuer: str = "Attendance Tracker") -> str:
    encoded_secret = base64.b32encode(secret).decode("ascii").rstrip("=")
    return f"otpauth://totp/{issuer}:{account_name}?secret={encoded_secret}&issuer={issuer}&digits=6"


def totp_code(secret: bytes, *, at: datetime | None = None) -> str:
    if len(secret) < 20:
        raise ValueError("TOTP secret must be at least 160 bits")
    timestamp = (at or datetime.now(UTC)).timestamp()
    counter = int(timestamp // TOTP_STEP_SECONDS)
    digest = hmac.new(secret, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    truncated = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return f"{truncated % (10**TOTP_DIGITS):0{TOTP_DIGITS}d}"


def verify_totp(secret: bytes, code: str, *, at: datetime | None = None) -> bool:
    if not code.isdigit() or len(code) != TOTP_DIGITS:
        return False
    current = at or datetime.now(UTC)
    for drift in range(-TOTP_DRIFT_STEPS, TOTP_DRIFT_STEPS + 1):
        drifted = datetime.fromtimestamp(
            current.timestamp() + (drift * TOTP_STEP_SECONDS),
            tz=UTC,
        )
        if hmac.compare_digest(totp_code(secret, at=drifted), code):
            return True
    return False
