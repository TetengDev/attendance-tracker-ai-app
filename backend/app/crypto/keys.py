from __future__ import annotations

import base64
import binascii
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import NamedTuple

KEY_BYTES = 32
DEFAULT_KEY_ENV = "BIOMETRIC_KEK"
KEY_PREFIX = "kek."
BASE64URL_RE = re.compile(r"^[A-Za-z0-9_-]+={0,2}$")


class KeyConfigurationError(RuntimeError):
    """Raised when a biometric key-encryption key is missing or invalid."""


@dataclass(frozen=True)
class KeyEncryptionKey:
    """A 256-bit key-encryption key used only to wrap per-record data keys."""

    key_id: str
    material: bytes

    def __post_init__(self) -> None:
        if not self.key_id.strip():
            raise KeyConfigurationError("biometric KEK id must not be empty")
        if len(self.material) != KEY_BYTES:
            raise KeyConfigurationError("BIOMETRIC_KEK must decode to exactly 32 bytes")


class ParsedKey(NamedTuple):
    key_id: str
    material: bytes


def parse_kek(value: str) -> ParsedKey:
    """Decode a versioned base64url AES-256 key from configuration."""

    if not value:
        raise KeyConfigurationError("BIOMETRIC_KEK must not be empty")
    if value != value.strip() or any(char.isspace() for char in value):
        raise KeyConfigurationError("BIOMETRIC_KEK must not contain whitespace")
    if ":" not in value:
        raise KeyConfigurationError("BIOMETRIC_KEK must use kek.<id>:<base64url-key> format")

    key_label, encoded_key = value.split(":", 1)
    if not key_label.startswith(KEY_PREFIX) or key_label == KEY_PREFIX:
        raise KeyConfigurationError("BIOMETRIC_KEK key id must start with kek.")

    if not encoded_key:
        raise KeyConfigurationError("BIOMETRIC_KEK material must not be empty")
    if not BASE64URL_RE.fullmatch(encoded_key):
        raise KeyConfigurationError("BIOMETRIC_KEK material must be unpadded base64url")

    try:
        padded = encoded_key + "=" * (-len(encoded_key) % 4)
        decoded = base64.urlsafe_b64decode(padded.encode("ascii"))
    except (binascii.Error, UnicodeEncodeError) as exc:
        raise KeyConfigurationError("BIOMETRIC_KEK material must be base64url encoded") from exc

    if len(decoded) != KEY_BYTES:
        raise KeyConfigurationError("BIOMETRIC_KEK must decode to exactly 32 bytes")
    return ParsedKey(key_id=f"env:{key_label.removeprefix(KEY_PREFIX)}", material=decoded)


def load_kek_from_env(env: Mapping[str, str] = os.environ) -> KeyEncryptionKey:
    """Load the active biometric KEK.

    The key intentionally comes from process configuration only. It is never
    stored in the database, committed to the repo, or embedded in encrypted
    payload rows.
    """

    raw_key = env.get(DEFAULT_KEY_ENV)
    if raw_key is None:
        raise KeyConfigurationError("BIOMETRIC_KEK is required")
    parsed = parse_kek(raw_key)
    return KeyEncryptionKey(key_id=parsed.key_id, material=parsed.material)


def keyring_for(*keys: KeyEncryptionKey) -> Mapping[str, KeyEncryptionKey]:
    """Build an immutable keyring indexed by key id."""

    if not keys:
        raise KeyConfigurationError("At least one KEK is required")
    return MappingProxyType({key.key_id: key for key in keys})


ACTIVE_KEK = load_kek_from_env()
ACTIVE_KEYRING = keyring_for(ACTIVE_KEK)
