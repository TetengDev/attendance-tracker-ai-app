from __future__ import annotations

import base64
from collections.abc import AsyncIterator, Sequence
from datetime import datetime
from io import BytesIO
from uuid import UUID

import numpy as np
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image
from pytest import MonkeyPatch
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.api.common import authenticated_admin_user
from backend.app.api.enrollment import (
    EnrollmentCommit,
    EnrollmentCommitResponse,
    EnrollmentImageResult,
    EnrollmentValidationStatus,
    ImageCandidate,
    get_enrollment_service,
    get_face_engine,
    get_gallery_index,
)
from backend.app.config import get_settings
from backend.app.db.session import get_session
from backend.app.face.gallery import MatchCandidate, MatchDecision, MatchResult
from backend.app.face.protocol import FakeFaceEngine
from backend.app.main import create_app
from backend.app.models.admin import AdminRole, AdminUser
from backend.app.models.biometrics import (
    MIN_ACTIVE_EMBEDDINGS_FOR_ENROLLMENT,
    EnrollmentPose,
)


class FakeSession:
    committed = False
    rolled_back = False

    async def commit(self) -> None:
        self.committed = True

    async def rollback(self) -> None:
        self.rolled_back = True


async def fake_session() -> AsyncIterator[AsyncSession]:
    yield FakeSession()  # type: ignore[misc]


class FakeEnrollmentService:
    def __init__(self, *, active_embeddings_count: int) -> None:
        self.active_embeddings_count = active_embeddings_count
        self.calls: list[dict[str, object]] = []

    async def commit_images(
        self,
        _session: AsyncSession,
        _admin_user: AdminUser,
        *,
        person_id: UUID,
        candidates: Sequence[ImageCandidate],
        policy_version: str,
        face_engine: object,
        gallery_index: object,
        now: datetime,
    ) -> EnrollmentCommitResponse:
        commit = await self.prepare_commit(
            _session,
            _admin_user,
            person_id=person_id,
            candidates=candidates,
            policy_version=policy_version,
            face_engine=face_engine,
            gallery_index=gallery_index,
            now=now,
        )
        return commit.response

    async def prepare_commit(
        self,
        _session: AsyncSession,
        _admin_user: AdminUser,
        *,
        person_id: UUID,
        candidates: Sequence[ImageCandidate],
        policy_version: str,
        face_engine: object,
        gallery_index: object,
        now: datetime,
    ) -> EnrollmentCommit:
        candidate_list = list(candidates)
        self.calls.append(
            {
                "person_id": person_id,
                "candidate_count": len(candidate_list),
                "policy_version": policy_version,
                "poses": [candidate.pose for candidate in candidate_list],
                "now": now,
            }
        )
        results = [
            EnrollmentImageResult(
                filename=candidate.filename,
                status=EnrollmentValidationStatus.ACCEPTED,
                asset_id=UUID(f"10000000-0000-0000-0000-{index + 1:012d}"),
                embedding_id=UUID(f"20000000-0000-0000-0000-{index + 1:012d}"),
                pose=candidate.pose,
                quality_score=0.95,
            )
            for index, candidate in enumerate(candidate_list)
        ]
        return EnrollmentCommit(
            response=EnrollmentCommitResponse(
                person_id=person_id,
                accepted_count=len(results),
                rejected_count=0,
                active_embeddings_count=self.active_embeddings_count,
                enrollment_complete=self.active_embeddings_count
                >= MIN_ACTIVE_EMBEDDINGS_FOR_ENROLLMENT,
                results=results,
            ),
            gallery_entries=(),
        )


async def _skip_middleware_audit(_entry: object) -> None:
    return None


async def _skip_endpoint_audit(*_args: object, **_kwargs: object) -> None:
    return None


def _admin_user() -> AdminUser:
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


def _app(monkeypatch: MonkeyPatch, service: FakeEnrollmentService | None = None) -> FastAPI:
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://localhost:5432/attendance")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("BIOMETRIC_KEK", "test-kek")
    monkeypatch.setattr("backend.app.audit.middleware._append_entry", _skip_middleware_audit)
    monkeypatch.setattr("backend.app.api.enrollment.audited_mutation", _skip_endpoint_audit)
    get_settings.cache_clear()
    app = create_app()
    app.dependency_overrides[get_session] = fake_session
    app.dependency_overrides[authenticated_admin_user] = _admin_user
    app.dependency_overrides[get_face_engine] = lambda: object()
    app.dependency_overrides[get_gallery_index] = lambda: object()
    if service is not None:
        app.dependency_overrides[get_enrollment_service] = lambda: service
    return app


def test_enrollment_routers_are_registered(monkeypatch: MonkeyPatch) -> None:
    with TestClient(_app(monkeypatch)) as client:
        paths = set(client.get("/openapi.json").json()["paths"])

    assert "/api/enrollment/{person_id}/upload" in paths
    assert "/api/enrollment/{person_id}/capture" in paths


def test_upload_endpoint_returns_per_image_results(monkeypatch: MonkeyPatch) -> None:
    person_id = UUID("10000000-0000-0000-0000-000000000034")
    service = FakeEnrollmentService(active_embeddings_count=5)

    with TestClient(_app(monkeypatch, service)) as client:
        response = client.post(
            f"/api/enrollment/{person_id}/upload",
            headers={"x-admin-id": "00000000-0000-0000-0000-0000000000ad"},
            data={"policy_version": "privacy-v2", "capture_pose": "frontal"},
            files=[
                ("files", ("01.png", b"not decoded by fake service", "image/png")),
                ("files", ("02.png", b"not decoded by fake service", "image/png")),
            ],
        )

    assert response.status_code == 201
    assert response.json()["accepted_count"] == 2
    assert response.json()["enrollment_complete"] is True
    assert [result["filename"] for result in response.json()["results"]] == ["01.png", "02.png"]
    assert service.calls[0]["candidate_count"] == 2
    assert service.calls[0]["poses"] == [EnrollmentPose.FRONTAL, EnrollmentPose.FRONTAL]


def test_upload_endpoint_returns_inline_rejection_for_unsupported_file(
    monkeypatch: MonkeyPatch,
) -> None:
    person_id = UUID("10000000-0000-0000-0000-000000000037")
    service = FakeEnrollmentService(active_embeddings_count=1)

    with TestClient(_app(monkeypatch, service)) as client:
        response = client.post(
            f"/api/enrollment/{person_id}/upload",
            headers={"x-admin-id": "00000000-0000-0000-0000-0000000000ad"},
            data={"policy_version": "privacy-v2", "capture_pose": "frontal"},
            files=[
                ("files", ("good.png", b"not decoded by fake service", "image/png")),
                ("files", ("notes.txt", b"not an image", "text/plain")),
            ],
        )

    assert response.status_code == 201
    assert response.json()["accepted_count"] == 1
    assert response.json()["rejected_count"] == 1
    assert response.json()["results"][1]["filename"] == "notes.txt"
    assert response.json()["results"][1]["rejection_code"] == "unsupported_content_type"
    assert service.calls[0]["candidate_count"] == 1


def test_capture_endpoint_keeps_two_embedding_person_incomplete(monkeypatch: MonkeyPatch) -> None:
    person_id = UUID("10000000-0000-0000-0000-000000000035")
    service = FakeEnrollmentService(active_embeddings_count=2)

    with TestClient(_app(monkeypatch, service)) as client:
        response = client.post(
            f"/api/enrollment/{person_id}/capture",
            headers={"x-admin-id": "00000000-0000-0000-0000-0000000000ad"},
            data={"policy_version": "privacy-v2", "capture_pose": "yaw_left"},
            files={"file": ("capture.jpg", b"not decoded by fake service", "image/jpeg")},
        )

    assert response.status_code == 201
    assert response.json()["accepted_count"] == 1
    assert response.json()["active_embeddings_count"] == 2
    assert response.json()["enrollment_complete"] is False


def test_probe_endpoint_returns_gallery_identity(monkeypatch: MonkeyPatch) -> None:
    person_id = UUID("10000000-0000-0000-0000-000000000036")
    embedding_id = UUID("20000000-0000-0000-0000-000000000036")
    engine = FakeFaceEngine()
    engine.next_result(person="alice")

    class FakeGalleryIndex:
        def match(self, _query: np.ndarray) -> MatchResult:
            candidate = MatchCandidate(person_id=person_id, embedding_id=embedding_id, score=0.98)
            return MatchResult(
                decision=MatchDecision.ACCEPT,
                candidates=(candidate,),
                top1=candidate,
                top2_other_person=None,
                margin=None,
            )

    app = _app(monkeypatch)
    app.dependency_overrides[get_face_engine] = lambda: engine
    app.dependency_overrides[get_gallery_index] = lambda: FakeGalleryIndex()

    with TestClient(app) as client:
        response = client.post(
            "/api/enrollment/probe",
            headers={"x-admin-id": "00000000-0000-0000-0000-0000000000ad"},
            files={"file": ("probe.png", _sharp_png(), "image/png")},
        )

    assert response.status_code == 200
    assert response.json()["decision"] == "accept"
    assert response.json()["person_id"] == str(person_id)
    assert response.json()["embedding_id"] == str(embedding_id)
    assert response.json()["score"] == 0.98


def test_guided_websocket_enforces_pose_progression(monkeypatch: MonkeyPatch) -> None:
    person_id = UUID("10000000-0000-0000-0000-000000000036")
    service = FakeEnrollmentService(active_embeddings_count=3)

    with (
        TestClient(_app(monkeypatch, service)) as client,
        client.websocket_connect(
            f"/api/enrollment/{person_id}/guided?policy_version=privacy-v2",
            headers={"x-admin-id": "00000000-0000-0000-0000-0000000000ad"},
        ) as websocket,
    ):
        sequence = websocket.receive_json()
        assert sequence["type"] == "pose_sequence"
        assert sequence["next_pose"] == "frontal"
        websocket.send_json(
            {
                "filename": "left.jpg",
                "content_type": "image/jpeg",
                "pose": "yaw_left",
                "image_base64": base64.b64encode(b"frame").decode(),
            }
        )
        rejected = websocket.receive_json()
        websocket.send_json(
            {
                "filename": "front.jpg",
                "content_type": "image/jpeg",
                "pose": "frontal",
                "image_base64": base64.b64encode(b"frame").decode(),
            }
        )
        message = websocket.receive_json()

    assert rejected["type"] == "rejected"
    assert rejected["expected_pose"] == "frontal"
    assert message["type"] == "capture_result"
    assert message["pose"] == "frontal"
    assert message["next_pose"] == "yaw_left"
    assert message["enrollment_complete"] is True
    assert service.calls[0]["poses"] == [EnrollmentPose.FRONTAL]


def _sharp_png() -> bytes:
    image = np.full((260, 320, 3), 96, dtype=np.uint8)
    for x in range(70, 250, 8):
        image[30:230, x : x + 4, :] = 176
    buffer = BytesIO()
    Image.fromarray(image, mode="RGB").save(buffer, format="PNG")
    return buffer.getvalue()
