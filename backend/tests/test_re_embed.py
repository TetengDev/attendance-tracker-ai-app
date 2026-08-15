"""Unit tests for the re-embed CLI job."""

from __future__ import annotations

import base64
import os
from collections.abc import Sequence
from typing import Any, Self
from uuid import uuid4

import cv2
import numpy as np
import pytest

SECRET_KEY = "kek.test:" + base64.urlsafe_b64encode(bytes([9]) * 32).decode().rstrip("=")
os.environ["BIOMETRIC_KEK"] = SECRET_KEY

from backend.app.cli.re_embed import run_re_embed
from backend.app.crypto.envelope import encrypt_bytes
from backend.app.crypto.keys import KeyEncryptionKey
from backend.app.models.biometrics import EnrollmentAssetKind, FaceEmbedding


@pytest.mark.anyio
async def test_re_embed_job(monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.app.face.protocol import Detection, Embedding

    class FakeFaceEngine:
        model_name = "test-model-v2"
        model_version = "v2"

        def detect(self, bgr: np.ndarray) -> list[Detection]:
            return [
                Detection(
                    bbox=(0, 0, 10, 10),
                    det_score=0.95,
                    landmarks=np.zeros((5, 2)),
                    blur_var=100.0,
                    brightness=120.0,
                )
            ]

        def align(self, bgr: np.ndarray, lm: np.ndarray) -> np.ndarray:
            return np.zeros((112, 112, 3), dtype=np.uint8)

        def embed(self, aligned: np.ndarray) -> Embedding:
            return Embedding(
                vector=np.ones(512, dtype=np.float32),
                model_name="test-model-v2",
                model_version="v2",
            )

    # Prepare mock original image
    img = np.zeros((100, 100, 3), dtype=np.uint8)
    _, buf = cv2.imencode(".jpg", img)
    raw_bytes = buf.tobytes()

    person_id = uuid4()
    consent_id = uuid4()
    asset_id = uuid4()

    from backend.app.api.enrollment import _asset_aad

    kek = KeyEncryptionKey(key_id="env:test", material=bytes([9]) * 32)
    encrypted_payload = encrypt_bytes(
        raw_bytes, aad=_asset_aad(person_id=person_id, filename="photo.jpg"), kek=kek
    )

    class FakeConsent:
        policy_version = "policy-v1"

    class FakeAsset:
        def __init__(self) -> None:
            self.id = asset_id
            self.person_id = person_id
            self.consent_id = consent_id
            self.kind = EnrollmentAssetKind.ORIGINAL_IMAGE
            self.filename = "photo.jpg"
            self.envelope_version = encrypted_payload.version
            self.payload_alg = encrypted_payload.payload_alg
            self.dek_wrap_alg = encrypted_payload.dek_wrap_alg
            self.encryption_key_id = encrypted_payload.encryption_key_id
            self.wrapped_dek = encrypted_payload.wrapped_dek
            self.dek_nonce = encrypted_payload.dek_nonce
            self.payload_nonce = encrypted_payload.payload_nonce
            self.ciphertext = encrypted_payload.ciphertext
            self.consent = FakeConsent()

    added_embeddings: list[FaceEmbedding] = []

    class FakeSession:
        async def execute(
            self,
            statement: object,
            params: Any = None,
            *args: Any,
            **kwargs: Any,
        ) -> object:
            class FakeResult:
                def __init__(self, val: object) -> None:
                    self.val = val

                def scalars(self_inner) -> Sequence[object]:
                    return [self_inner.val] if self_inner.val is not None else []

                def scalar_one_or_none(self_inner) -> object | None:
                    return self_inner.val

            if "FROM enrollment_assets" in str(statement):
                return FakeResult(FakeAsset())
            if "FROM face_embeddings" in str(statement):
                return FakeResult(None)
            return None

        def add(self, obj: object) -> None:
            if isinstance(obj, FaceEmbedding):
                added_embeddings.append(obj)

        async def flush(self) -> None:
            pass

        async def commit(self) -> None:
            pass

        async def __aenter__(self) -> Self:
            return self

        async def __aexit__(self, exc_type: object, exc_val: object, exc_tb: object) -> None:
            pass

    monkeypatch.setattr("backend.app.cli.re_embed.get_face_engine", lambda: FakeFaceEngine())
    monkeypatch.setattr(
        "backend.app.cli.re_embed.get_session_factory", lambda: lambda: FakeSession()
    )

    await run_re_embed()

    assert len(added_embeddings) == 1
    new_emb = added_embeddings[0]
    assert new_emb.person_id == person_id
    assert new_emb.model_name == "test-model-v2"
    assert new_emb.model_version == "v2"
    assert new_emb.asset_id == asset_id
    assert new_emb.quality["det_score"] == 0.95
