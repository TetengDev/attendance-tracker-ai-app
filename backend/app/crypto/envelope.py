from __future__ import annotations

import secrets
from collections.abc import Mapping
from dataclasses import dataclass, replace

import numpy as np
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from backend.app.crypto.keys import (
    ACTIVE_KEK,
    ACTIVE_KEYRING,
    KeyConfigurationError,
    KeyEncryptionKey,
)

AES_GCM_NONCE_BYTES = 12
DATA_KEY_BYTES = 32
EMBEDDING_DIMENSIONS = 512
ENVELOPE_VERSION = 1
PAYLOAD_ALG = "AES-256-GCM"
DEK_WRAP_ALG = "AES-256-GCM"


@dataclass(frozen=True)
class EncryptedPayload:
    """Database-ready encrypted payload and wrapped per-record data key."""

    version: int
    payload_alg: str
    dek_wrap_alg: str
    encryption_key_id: str
    wrapped_dek: bytes
    dek_nonce: bytes
    payload_nonce: bytes
    ciphertext: bytes


def encrypt_bytes(
    plaintext: bytes,
    *,
    aad: bytes = b"",
    kek: KeyEncryptionKey = ACTIVE_KEK,
) -> EncryptedPayload:
    """Encrypt bytes with a random DEK, then wrap that DEK with the active KEK."""

    dek = secrets.token_bytes(DATA_KEY_BYTES)
    payload_nonce = secrets.token_bytes(AES_GCM_NONCE_BYTES)
    ciphertext = AESGCM(dek).encrypt(payload_nonce, plaintext, aad)
    dek_nonce = secrets.token_bytes(AES_GCM_NONCE_BYTES)
    wrapped_dek = AESGCM(kek.material).encrypt(dek_nonce, dek, _dek_aad(payload_nonce))
    return EncryptedPayload(
        version=ENVELOPE_VERSION,
        payload_alg=PAYLOAD_ALG,
        dek_wrap_alg=DEK_WRAP_ALG,
        encryption_key_id=kek.key_id,
        wrapped_dek=wrapped_dek,
        dek_nonce=dek_nonce,
        payload_nonce=payload_nonce,
        ciphertext=ciphertext,
    )


def decrypt_bytes(
    payload: EncryptedPayload,
    *,
    aad: bytes = b"",
    keyring: Mapping[str, KeyEncryptionKey] = ACTIVE_KEYRING,
) -> bytes:
    """Decrypt an encrypted payload using the KEK named by its key id."""

    _validate_envelope(payload)
    dek = _unwrap_dek(payload, keyring=keyring)
    return AESGCM(dek).decrypt(payload.payload_nonce, payload.ciphertext, aad)


def rewrap_data_key(
    payload: EncryptedPayload,
    *,
    new_kek: KeyEncryptionKey,
    keyring: Mapping[str, KeyEncryptionKey] = ACTIVE_KEYRING,
) -> EncryptedPayload:
    """Rotate KEKs by rewrapping the DEK without touching payload ciphertext."""

    _validate_envelope(payload)
    dek = _unwrap_dek(payload, keyring=keyring)
    dek_nonce = secrets.token_bytes(AES_GCM_NONCE_BYTES)
    wrapped_dek = AESGCM(new_kek.material).encrypt(dek_nonce, dek, _dek_aad(payload.payload_nonce))
    return replace(
        payload,
        encryption_key_id=new_kek.key_id,
        wrapped_dek=wrapped_dek,
        dek_nonce=dek_nonce,
    )


def encrypt_embedding(
    embedding: np.ndarray,
    *,
    aad: bytes = b"",
    kek: KeyEncryptionKey = ACTIVE_KEK,
) -> EncryptedPayload:
    """Encrypt one 512-d float32 face embedding."""

    if embedding.shape != (EMBEDDING_DIMENSIONS,):
        raise ValueError("face embedding must be a 512-d vector")
    contiguous = np.ascontiguousarray(embedding, dtype=np.float32)
    return encrypt_bytes(contiguous.tobytes(), aad=aad, kek=kek)


def decrypt_embedding(
    payload: EncryptedPayload,
    *,
    aad: bytes = b"",
    keyring: Mapping[str, KeyEncryptionKey] = ACTIVE_KEYRING,
) -> np.ndarray:
    """Decrypt one 512-d float32 face embedding."""

    raw = decrypt_bytes(payload, aad=aad, keyring=keyring)
    expected_bytes = EMBEDDING_DIMENSIONS * np.dtype(np.float32).itemsize
    if len(raw) != expected_bytes:
        raise ValueError("decrypted face embedding has an invalid byte length")
    return np.frombuffer(raw, dtype=np.float32).copy()


def _unwrap_dek(
    payload: EncryptedPayload,
    *,
    keyring: Mapping[str, KeyEncryptionKey],
) -> bytes:
    try:
        kek = keyring[payload.encryption_key_id]
    except KeyError as exc:
        raise KeyConfigurationError("KEK not available for encrypted payload") from exc
    return AESGCM(kek.material).decrypt(
        payload.dek_nonce,
        payload.wrapped_dek,
        _dek_aad(payload.payload_nonce),
    )


def _validate_envelope(payload: EncryptedPayload) -> None:
    if payload.version != ENVELOPE_VERSION:
        raise ValueError("unsupported encrypted payload version")
    if payload.payload_alg != PAYLOAD_ALG:
        raise ValueError("unsupported payload encryption algorithm")
    if payload.dek_wrap_alg != DEK_WRAP_ALG:
        raise ValueError("unsupported DEK wrapping algorithm")


def _dek_aad(payload_nonce: bytes) -> bytes:
    return b"|".join(
        [
            b"attendance-tracker:v1:dek-wrap",
            b"payload_alg=" + PAYLOAD_ALG.encode(),
            b"dek_wrap_alg=" + DEK_WRAP_ALG.encode(),
            b"payload_nonce=" + payload_nonce,
        ]
    )
