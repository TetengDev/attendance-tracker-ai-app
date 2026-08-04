from __future__ import annotations

import io
import logging
from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID, uuid4

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.api.common import authenticated_admin_user
from backend.app.api.enrollment import get_face_engine, get_gallery_index
from backend.app.crypto.envelope import encrypt_embedding
from backend.app.db.session import get_session
from backend.app.enrollment.duplicates import (
    check_duplicate_enrollment,
    find_all_gallery_duplicates,
    get_duplicate_threshold,
)
from backend.app.face.gallery import GalleryIndex
from backend.app.face.protocol import FakeFaceEngine
from backend.app.main import create_app
from backend.app.models.admin import AdminRole, AdminUser
from backend.app.models.biometrics import FaceEmbedding
from backend.app.models.people import Person
from backend.app.models.settings import SettingScope
from backend.tests.factories.embeddings import embedding_with_cosine, seeded_unit_embedding

logger = logging.getLogger(__name__)


class FakeSetting:
    def __init__(self, key: str, scope: SettingScope, scope_id: UUID | None, value: Any, version: int) -> None:
        self.key = key
        self.scope = scope
        self.scope_id = scope_id
        self.value = value
        self.version = version


class FakeScalars:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def all(self) -> list[Any]:
        return self._rows


class FakeResult:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def scalars(self) -> FakeScalars:
        return FakeScalars(self._rows)

    def scalar_one_or_none(self) -> Any:
        return self._rows[0] if self._rows else None

    def scalar_one(self) -> Any:
        if self._rows and isinstance(self._rows[0], int):
            return self._rows[0]
        return len(self._rows)


class FakeSession:
    def __init__(self) -> None:
        self.embeddings: list[FaceEmbedding] = []
        self.settings: list[FakeSetting] = []
        self.people: dict[UUID, Person] = {}
        self.committed = False
        self.rolled_back = False

    async def execute(self, query: Any, params: Any = None) -> FakeResult:
        q_str = str(query)
        if "count" in q_str.lower():
            if "face_embeddings" in q_str:
                return FakeResult([len(self.embeddings)])
            return FakeResult([0])

        if "face_embeddings" in q_str:
            return FakeResult(self.embeddings)
        elif "settings_versions" in q_str:
            return FakeResult([1])
        elif "settings" in q_str:
            return FakeResult(self.settings)
        elif "people" in q_str or "person" in q_str:
            for pid, person in self.people.items():
                if str(pid) in q_str:
                    return FakeResult([person])
            return FakeResult(list(self.people.values()))
        return FakeResult([])

    async def get(self, model_class: Any, obj_id: Any) -> Any:
        if model_class is Person:
            return self.people.get(obj_id)
        return None

    async def commit(self) -> None:
        self.committed = True

    async def rollback(self) -> None:
        self.rolled_back = True

    async def flush(self) -> None:
        pass

    def add(self, model: Any) -> None:
        pass


def make_mock_embedding(person_id: UUID, emb_id: UUID, vector: np.ndarray, asset_id: UUID | None = None) -> FaceEmbedding:
    a_id = asset_id or uuid4()
    payload = encrypt_embedding(vector, aad=f"face-embedding:{person_id}:{a_id}".encode())
    return FaceEmbedding(
        id=emb_id,
        person_id=person_id,
        asset_id=a_id,
        envelope_version=payload.version,
        payload_alg=payload.payload_alg,
        dek_wrap_alg=payload.dek_wrap_alg,
        encryption_key_id=payload.encryption_key_id,
        wrapped_dek=payload.wrapped_dek,
        dek_nonce=payload.dek_nonce,
        payload_nonce=payload.payload_nonce,
        ciphertext=payload.ciphertext,
        is_active=True,
    )


@pytest.mark.anyio
async def test_get_duplicate_threshold_returns_default_when_not_set() -> None:
    session = FakeSession()
    threshold = await get_duplicate_threshold(cast_session(session))
    assert threshold == 0.75


@pytest.mark.anyio
async def test_get_duplicate_threshold_returns_configured_value() -> None:
    session = FakeSession()
    session.settings.append(
        FakeSetting("face.duplicate_threshold", SettingScope.ORG, None, 0.85, 1)
    )
    threshold = await get_duplicate_threshold(cast_session(session))
    assert threshold == 0.85


@pytest.mark.anyio
async def test_check_duplicate_enrollment_allows_new_embedding_when_gallery_empty() -> None:
    session = FakeSession()
    gallery_index = GalleryIndex()
    person_id = uuid4()
    candidate = seeded_unit_embedding(1)

    conflicts = await check_duplicate_enrollment(
        cast_session(session), [candidate], person_id, gallery_index
    )
    assert len(conflicts) == 0


@pytest.mark.anyio
async def test_check_duplicate_enrollment_allows_match_with_same_person() -> None:
    session = FakeSession()
    gallery_index = GalleryIndex()
    person_id = uuid4()
    emb_id = uuid4()
    vector = seeded_unit_embedding(1)

    session.embeddings.append(make_mock_embedding(person_id, emb_id, vector))
    session.people[person_id] = Person(id=person_id, display_name="Alice")

    # Match with Alice (same person_id) should be allowed even if score is 1.0
    conflicts = await check_duplicate_enrollment(
        cast_session(session), [vector], person_id, gallery_index
    )
    assert len(conflicts) == 0


@pytest.mark.anyio
async def test_check_duplicate_enrollment_blocks_match_with_different_person_above_threshold() -> None:
    session = FakeSession()
    gallery_index = GalleryIndex()
    alice_id = uuid4()
    bob_id = uuid4()

    # Generate a pair of embeddings with cosine similarity 0.85 (above default threshold 0.75)
    pair = embedding_with_cosine(1, 0.85)

    session.embeddings.append(make_mock_embedding(alice_id, uuid4(), pair.left))
    session.people[alice_id] = Person(id=alice_id, display_name="Alice")

    # Enrolling Bob with the right embedding (which matches Alice at 0.85) should be blocked
    conflicts = await check_duplicate_enrollment(
        cast_session(session), [pair.right], bob_id, gallery_index
    )
    assert len(conflicts) == 1
    assert conflicts[0]["person_id"] == str(alice_id)
    assert conflicts[0]["display_name"] == "Alice"
    assert conflicts[0]["score"] == pytest.approx(0.85, abs=1e-5)


@pytest.mark.anyio
async def test_check_duplicate_enrollment_allows_match_below_threshold() -> None:
    session = FakeSession()
    gallery_index = GalleryIndex()
    alice_id = uuid4()
    bob_id = uuid4()

    # Generate a pair of embeddings with cosine similarity 0.65 (below default threshold 0.75)
    pair = embedding_with_cosine(1, 0.65)

    session.embeddings.append(make_mock_embedding(alice_id, uuid4(), pair.left))
    session.people[alice_id] = Person(id=alice_id, display_name="Alice")

    conflicts = await check_duplicate_enrollment(
        cast_session(session), [pair.right], bob_id, gallery_index
    )
    assert len(conflicts) == 0


@pytest.mark.anyio
async def test_find_all_gallery_duplicates_returns_all_matches() -> None:
    session = FakeSession()
    gallery_index = GalleryIndex()

    alice_id = uuid4()
    bob_id = uuid4()
    charlie_id = uuid4()

    pair_ab = embedding_with_cosine(1, 0.90)  # Alice & Bob (duplicates)
    charlie_vec = seeded_unit_embedding(100)  # Charlie (independent)

    session.embeddings.append(make_mock_embedding(alice_id, uuid4(), pair_ab.left))
    session.embeddings.append(make_mock_embedding(bob_id, uuid4(), pair_ab.right))
    session.embeddings.append(make_mock_embedding(charlie_id, uuid4(), charlie_vec))

    session.people[alice_id] = Person(id=alice_id, display_name="Alice")
    session.people[bob_id] = Person(id=bob_id, display_name="Bob")
    session.people[charlie_id] = Person(id=charlie_id, display_name="Charlie")

    duplicates = await find_all_gallery_duplicates(cast_session(session), gallery_index)

    assert len(duplicates) == 1
    # Check that Alice & Bob are identified as duplicates
    p1 = duplicates[0]["person_1"]["id"]
    p2 = duplicates[0]["person_2"]["id"]
    assert {p1, p2} == {str(alice_id), str(bob_id)}
    assert duplicates[0]["score"] == pytest.approx(0.90, abs=1e-5)


def test_upload_duplicate_face_returns_409_conflict(monkeypatch: pytest.MonkeyPatch) -> None:
    alice_id = uuid4()
    bob_id = uuid4()

    # 1. Prepare fake DB session populated with Alice's details and active embedding
    session = FakeSession()
    engine = FakeFaceEngine()
    engine.next_result(person="Alice")
    img = np.zeros((112, 112, 3), dtype=np.uint8)
    _ = engine.detect(img)
    aligned = engine.align(img, np.zeros((5, 2), dtype=np.float32))
    alice_embedding = engine.embed(aligned)

    session.embeddings.append(make_mock_embedding(alice_id, uuid4(), alice_embedding.vector))
    session.people[alice_id] = Person(id=alice_id, display_name="Alice")
    session.people[bob_id] = Person(id=bob_id, display_name="Bob")

    # 2. Configure FakeFaceEngine for Bob's enrollment to output the SAME vector (Alice's face)
    test_engine = FakeFaceEngine()
    test_engine.next_result(person="Alice")
    # Manually activate test_engine's Alice configuration so embed() matches Alice
    test_engine._active = test_engine._queue.popleft()

    # 3. Instantiate local TestClient with overridden dependencies
    app = create_app()

    async def fake_get_session() -> AsyncIterator[AsyncSession]:
        yield cast_session(session)

    def fake_admin_user() -> AdminUser:
        return AdminUser(
            id=UUID("00000000-0000-0000-0000-0000000000ad"),
            email="admin@example.test",
            display_name="Admin",
            password_hash="hash",
            role=AdminRole.ADMIN,
            scope_group_ids=[],
            is_active=True,
            totp_secret=b"x" * 32,
        )

    app.dependency_overrides[get_session] = fake_get_session
    app.dependency_overrides[authenticated_admin_user] = fake_admin_user
    app.dependency_overrides[get_face_engine] = lambda: test_engine

    gallery_index = GalleryIndex()
    app.dependency_overrides[get_gallery_index] = lambda: gallery_index

    # Bypass audit logging
    async def fake_append_entry(*a: Any, **k: Any) -> None:
        pass

    async def fake_audited_mutation(*a: Any, **k: Any) -> None:
        pass

    monkeypatch.setattr("backend.app.api.enrollment.audited_mutation", fake_audited_mutation)
    monkeypatch.setattr("backend.app.audit.middleware._append_entry", fake_append_entry)

    # Mock validate_enrollment_image to always pass
    def fake_validate_enrollment_image(bgr: np.ndarray, face_engine: Any, *args: Any, **kwargs: Any) -> Any:
        from backend.app.enrollment.validate import EnrollmentQuality, EnrollmentValidationResult
        from backend.app.face.protocol import Detection
        det = Detection(
            bbox=(10, 10, 100, 100),
            det_score=0.95,
            landmarks=np.zeros((5, 2), dtype=np.float32),
            blur_var=100.0,
            brightness=128.0,
        )
        quality = EnrollmentQuality(
            score=0.95,
            det_score=0.95,
            bbox_area_pct=15.0,
            interocular_px=120.0,
            sharpness=100.0,
            brightness=128.0,
            yaw=0.0,
        )
        return EnrollmentValidationResult(
            passed=True,
            quality=quality,
            rejection=None,
            detection=det,
        )

    monkeypatch.setattr(
        "backend.app.api.enrollment.validate_enrollment_image",
        fake_validate_enrollment_image,
    )

    # Mock consent check to always succeed
    async def fake_require_consent(*a: Any, **k: Any) -> Any:
        class FakeConsent:
            id = uuid4()
        return FakeConsent()

    async def fake_add_consented_face_embedding(*a: Any, **k: Any) -> None:
        pass

    monkeypatch.setattr(
        "backend.app.api.enrollment.require_active_biometric_enrollment_consent",
        fake_require_consent,
    )
    monkeypatch.setattr(
        "backend.app.api.enrollment.add_consented_face_embedding",
        fake_add_consented_face_embedding,
    )

    # Create fake image upload bytes
    buf = io.BytesIO()
    Image.new("RGB", (320, 240), color="red").save(buf, format="JPEG")
    jpeg_bytes = buf.getvalue()

    with TestClient(app) as client:
        response = client.post(
            f"/api/enrollment/{bob_id}/upload",
            headers={"x-admin-id": "00000000-0000-0000-0000-0000000000ad"},
            data={"policy_version": "privacy-v2", "capture_pose": "frontal"},
            files=[
                ("files", ("bob.jpg", jpeg_bytes, "image/jpeg")),
            ],
        )

    assert response.status_code == 409
    error_wrapper = response.json()["detail"]
    assert error_wrapper["error"]["code"] == "DUPLICATE_ENROLLMENT"
    assert error_wrapper["error"]["details"]["person_id"] == str(alice_id)


def cast_session(fake: FakeSession) -> AsyncSession:
    return fake  # type: ignore[return-value]
