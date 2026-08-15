from __future__ import annotations

import base64
import os
import subprocess
import sys
from dataclasses import replace

import numpy as np
import pytest
from cryptography.exceptions import InvalidTag

_previous_biometric_kek = os.environ.get("BIOMETRIC_KEK")
os.environ["BIOMETRIC_KEK"] = "kek.test:" + base64.urlsafe_b64encode(
    bytes([9]) * 32
).decode().rstrip("=")

from backend.app.crypto.envelope import (
    decrypt_embedding,
    encrypt_embedding,
    rewrap_data_key,
)
from backend.app.crypto.keys import (
    KeyConfigurationError,
    KeyEncryptionKey,
    keyring_for,
    parse_kek,
)

if _previous_biometric_kek is None:
    os.environ.pop("BIOMETRIC_KEK", None)
else:
    os.environ["BIOMETRIC_KEK"] = _previous_biometric_kek


def _encoded_key(byte: int) -> str:
    return base64.urlsafe_b64encode(bytes([byte]) * 32).decode().rstrip("=")


def test_parse_kek_requires_versioned_32_byte_base64url_value() -> None:
    assert parse_kek(f"kek.v1:{_encoded_key(7)}") == ("env:v1", bytes([7]) * 32)

    with pytest.raises(KeyConfigurationError):
        parse_kek(_encoded_key(7))

    with pytest.raises(KeyConfigurationError):
        parse_kek(f"kek.v1:{base64.urlsafe_b64encode(b'too-short').decode()}")

    with pytest.raises(KeyConfigurationError):
        parse_kek(f" kek.v1:{_encoded_key(7)}")

    with pytest.raises(KeyConfigurationError):
        parse_kek("kek.v1:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA+A")


def test_crypto_keys_import_fails_loudly_without_biometric_kek() -> None:
    env = os.environ.copy()
    env.pop("BIOMETRIC_KEK", None)
    env.pop("BIOMETRIC_KEK_ID", None)

    result = subprocess.run(
        [sys.executable, "-c", "import backend.app.crypto.keys"],
        check=False,
        env=env,
        stderr=subprocess.PIPE,
        text=True,
    )

    assert result.returncode != 0
    assert "BIOMETRIC_KEK is required" in result.stderr


def test_encrypt_decrypt_round_trips_512d_float32_embedding() -> None:
    key = KeyEncryptionKey(key_id="kek-v1", material=bytes([1]) * 32)
    embedding = np.linspace(-1.0, 1.0, 512, dtype=np.float32)
    aad = b"face_embeddings:person-1:model-v1"

    encrypted = encrypt_embedding(embedding, aad=aad, kek=key)
    decrypted = decrypt_embedding(encrypted, aad=aad, keyring=keyring_for(key))

    assert encrypted.encryption_key_id == "kek-v1"
    assert encrypted.version == 1
    assert encrypted.payload_alg == "AES-256-GCM"
    assert encrypted.dek_wrap_alg == "AES-256-GCM"
    assert encrypted.ciphertext != embedding.tobytes()
    np.testing.assert_array_equal(decrypted, embedding)


def test_encrypting_same_embedding_twice_uses_distinct_randomness() -> None:
    key = KeyEncryptionKey(key_id="kek-v1", material=bytes([1]) * 32)
    embedding = np.zeros(512, dtype=np.float32)

    first = encrypt_embedding(embedding, aad=b"row:1", kek=key)
    second = encrypt_embedding(embedding, aad=b"row:1", kek=key)

    assert first.payload_nonce != second.payload_nonce
    assert first.dek_nonce != second.dek_nonce
    assert first.ciphertext != second.ciphertext
    assert first.wrapped_dek != second.wrapped_dek


def test_aad_mismatch_rejects_decryption() -> None:
    key = KeyEncryptionKey(key_id="kek-v1", material=bytes([1]) * 32)
    encrypted = encrypt_embedding(np.zeros(512, dtype=np.float32), aad=b"row:1", kek=key)

    with pytest.raises(InvalidTag):
        decrypt_embedding(encrypted, aad=b"row:2", keyring=keyring_for(key))


def test_wrong_kek_and_tampered_payloads_fail_closed() -> None:
    key = KeyEncryptionKey(key_id="kek-v1", material=bytes([1]) * 32)
    wrong_key = KeyEncryptionKey(key_id="kek-v1", material=bytes([2]) * 32)
    encrypted = encrypt_embedding(np.zeros(512, dtype=np.float32), aad=b"row:1", kek=key)

    with pytest.raises(InvalidTag):
        decrypt_embedding(encrypted, aad=b"row:1", keyring=keyring_for(wrong_key))

    with pytest.raises(InvalidTag):
        decrypt_embedding(
            replace(encrypted, ciphertext=encrypted.ciphertext[:-1] + b"\x00"),
            aad=b"row:1",
            keyring=keyring_for(key),
        )

    with pytest.raises(InvalidTag):
        decrypt_embedding(
            replace(encrypted, wrapped_dek=encrypted.wrapped_dek[:-1] + b"\x00"),
            aad=b"row:1",
            keyring=keyring_for(key),
        )

    with pytest.raises(ValueError):
        decrypt_embedding(
            replace(encrypted, version=2),
            aad=b"row:1",
            keyring=keyring_for(key),
        )


def test_rewrap_rotates_dek_without_touching_payload_ciphertext() -> None:
    old_key = KeyEncryptionKey(key_id="kek-v1", material=bytes([1]) * 32)
    new_key = KeyEncryptionKey(key_id="kek-v2", material=bytes([2]) * 32)
    embedding = np.arange(512, dtype=np.float32)
    aad = b"face_embeddings:person-1:model-v1"

    encrypted = encrypt_embedding(embedding, aad=aad, kek=old_key)
    rotated = rewrap_data_key(
        encrypted,
        new_kek=new_key,
        keyring=keyring_for(old_key),
    )

    assert rotated.encryption_key_id == "kek-v2"
    assert rotated.ciphertext == encrypted.ciphertext
    assert rotated.payload_nonce == encrypted.payload_nonce
    assert rotated.wrapped_dek != encrypted.wrapped_dek
    np.testing.assert_array_equal(
        decrypt_embedding(rotated, aad=aad, keyring=keyring_for(new_key)),
        embedding,
    )

    with pytest.raises(KeyConfigurationError):
        decrypt_embedding(rotated, aad=aad, keyring=keyring_for(old_key))
