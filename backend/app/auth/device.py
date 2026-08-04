"""Device authentication, JWT session token, and revocation check helpers."""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import jwt

# ── Token hashing & verification ──────────────────────────────────────────

def get_device_token_key(kek: str) -> bytes:
    """Derive a 32-byte key from the KEK for HMAC operation."""
    return hashlib.sha256(kek.encode("utf-8")).digest()


def hash_device_token(token: str, secret_key: bytes) -> str:
    """Compute the HMAC-SHA256 hash of a device token."""
    return hmac.new(secret_key, token.encode("utf-8"), hashlib.sha256).hexdigest()


def verify_device_token(token: str, token_hash: str, secret_key: bytes) -> bool:
    """Verify that a device token matches its stored HMAC in constant time."""
    computed = hash_device_token(token, secret_key)
    return secrets.compare_digest(computed, token_hash)


# ── Pairing code utilities ───────────────────────────────────────────────

def generate_pairing_code() -> str:
    """Generate a cryptographically secure 8-character pairing code."""
    # Use uppercase letters and numbers to avoid ambiguous characters
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "".join(secrets.choice(alphabet) for _ in range(8))


def hash_pairing_code(code: str) -> str:
    """Hash a pairing code using SHA-256."""
    return hashlib.sha256(code.upper().encode("utf-8")).hexdigest()


def verify_pairing_code(code: str, code_hash: str) -> bool:
    """Verify a pairing code matches its stored hash in constant time."""
    if not code_hash:
        return False
    return secrets.compare_digest(hash_pairing_code(code), code_hash)


# ── JWT signing & validation ─────────────────────────────────────────────

def issue_device_jwt(
    device_id: UUID,
    raw_token: str,
    secret_key: str,
    expiry_minutes: int = 15,
) -> str:
    """Issue a 15-minute scan JWT for a device."""
    now = datetime.now(tz=UTC)
    payload = {
        "sub": str(device_id),
        "token": raw_token,
        "exp": int((now + timedelta(minutes=expiry_minutes)).timestamp()),
        "type": "scan_session",
    }
    return jwt.encode(payload, secret_key, algorithm="HS256")


def decode_device_jwt(token_jwt: str, secret_key: str) -> dict[str, Any]:
    """Decode and validate a device token JWT."""
    payload = jwt.decode(token_jwt, secret_key, algorithms=["HS256"])
    if payload.get("type") != "scan_session":
        raise jwt.InvalidTokenError("Invalid token type claim")
    return payload


# ── CIDR Validation ───────────────────────────────────────────────────────

def is_ip_allowed(ip_str: str, allowed_cidrs: list[str]) -> bool:
    """Verify that a client's IP falls within the device's allowed CIDRs.

    If allowed_cidrs is empty, we allow any IP by default.
    """
    if not allowed_cidrs:
        return True

    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return False

    for cidr in allowed_cidrs:
        try:
            network = ipaddress.ip_network(cidr, strict=False)
            if ip in network:
                return True
        except ValueError:
            continue

    return False


# ── Revocation Registry ───────────────────────────────────────────────────

class RevocationRegistry:
    """Abstract revocation registry.

    Production registry will check against Redis; tests use the InMemory stub.
    """

    def is_revoked(self, device_id: UUID) -> bool:
        """Return True if the device is revoked, else False."""
        return False

    def revoke(self, device_id: UUID) -> None:
        """Mark a device as revoked immediately."""


class InMemoryRevocationRegistry(RevocationRegistry):
    """In-memory revocation registry for tests and development."""

    def __init__(self) -> None:
        self._revoked: set[UUID] = set()

    def is_revoked(self, device_id: UUID) -> bool:
        return device_id in self._revoked

    def revoke(self, device_id: UUID) -> None:
        self._revoked.add(device_id)

    def reset(self) -> None:
        self._revoked.clear()


global_revocation_registry = InMemoryRevocationRegistry()
