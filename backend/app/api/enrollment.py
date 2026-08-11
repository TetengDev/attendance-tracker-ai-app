from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from enum import Enum
from typing import Annotated, Any
from uuid import UUID

import numpy as np
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.api.common import (
    ActorDep,
    AdminUserDep,
    CrudError,
    CrudErrorCode,
    RequestActor,
    SessionDep,
    StrictSchema,
    audited_mutation,
    commit_or_422,
    translate_crud_error,
)
from backend.app.auth.rbac import scoped_people_query
from backend.app.enrollment.consent import (
    ConsentEnforcementError,
    add_consented_face_embedding,
    require_active_biometric_enrollment_consent,
)
from backend.app.enrollment.duplicates import check_duplicate_enrollment
from backend.app.enrollment.validate import EnrollmentValidationResult, validate_enrollment_image
from backend.app.errors import ErrorCode, make_error
from backend.app.face.decode import decode_image_to_bgr
from backend.app.face.gallery import (
    GalleryEntry,
    GalleryIndex,
    MatchDecision,
    MatchResult,
    bump_gallery_version,
)
from backend.app.face.protocol import FaceEngine, FakeFaceEngine
from backend.app.models.admin import AdminUser
from backend.app.models.biometrics import (
    MIN_ACTIVE_EMBEDDINGS_FOR_ENROLLMENT,
    TARGET_EMBEDDINGS_PER_PERSON,
    EnrollmentAsset,
    EnrollmentAssetKind,
    EnrollmentPose,
    FaceEmbedding,
    enrollment_complete,
)
from backend.app.models.people import Person

router = APIRouter(prefix="/api/enrollment", tags=["enrollment"])
DEFAULT_FACE_ENGINE = FakeFaceEngine()
DEFAULT_GALLERY_INDEX = GalleryIndex()
SUPPORTED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}


class EnrollmentValidationStatus(str, Enum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class EnrollmentImageResult(StrictSchema):
    filename: str
    status: EnrollmentValidationStatus
    asset_id: UUID | None = None
    embedding_id: UUID | None = None
    pose: EnrollmentPose
    quality_score: float | None = None
    rejection_code: str | None = None
    rejection_message: str | None = None


class EnrollmentCommitResponse(StrictSchema):
    person_id: UUID
    accepted_count: int
    rejected_count: int
    active_embeddings_count: int
    enrollment_complete: bool
    target_embeddings: int = TARGET_EMBEDDINGS_PER_PERSON
    minimum_complete_embeddings: int = MIN_ACTIVE_EMBEDDINGS_FOR_ENROLLMENT
    results: list[EnrollmentImageResult]


class EnrollmentProbeCandidate(StrictSchema):
    person_id: UUID
    embedding_id: UUID
    score: float


class EnrollmentProbeResponse(StrictSchema):
    decision: MatchDecision
    person_id: UUID | None
    embedding_id: UUID | None
    score: float | None
    margin: float | None
    candidates: list[EnrollmentProbeCandidate]


@dataclass(frozen=True)
class ImageCandidate:
    filename: str
    content_type: str
    payload: bytes
    pose: EnrollmentPose


@dataclass(frozen=True)
class RejectedUploadCandidate:
    result: EnrollmentImageResult


@dataclass(frozen=True)
class StoredEnrollmentImage:
    result: EnrollmentImageResult
    gallery_entry: GalleryEntry | None


@dataclass(frozen=True)
class EnrollmentCommit:
    response: EnrollmentCommitResponse
    gallery_entries: tuple[GalleryEntry, ...]


class EnrollmentService:
    async def commit_images(
        self,
        session: AsyncSession,
        admin_user: AdminUser,
        *,
        person_id: UUID,
        candidates: Sequence[ImageCandidate],
        policy_version: str,
        face_engine: FaceEngine,
        gallery_index: GalleryIndex,
        now: datetime,
    ) -> EnrollmentCommitResponse:
        commit = await self.prepare_commit(
            session,
            admin_user,
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
        session: AsyncSession,
        admin_user: AdminUser,
        *,
        person_id: UUID,
        candidates: Sequence[ImageCandidate],
        policy_version: str,
        face_engine: FaceEngine,
        gallery_index: GalleryIndex,
        now: datetime,
    ) -> EnrollmentCommit:
        await self._require_person_visible(
            session,
            admin_user,
            person_id=person_id,
            business_date=now.date(),
        )
        try:
            consent = await require_active_biometric_enrollment_consent(
                session,
                person_id=person_id,
                policy_version=policy_version,
                as_of=now,
            )
        except ConsentEnforcementError as exc:
            raise CrudError(CrudErrorCode.INVALID_INPUT, exc.message) from exc

        stored_images: list[StoredEnrollmentImage] = []
        for candidate in candidates:
            stored_images.append(
                await self._validate_and_store_candidate(
                    session,
                    person_id=person_id,
                    candidate=candidate,
                    policy_version=policy_version,
                    consent_id=consent.id,
                    face_engine=face_engine,
                    now=now,
                )
            )

        _ = gallery_index

        active_count = await self._active_embeddings_count(session, person_id=person_id)
        results = [image.result for image in stored_images]
        return EnrollmentCommit(
            response=EnrollmentCommitResponse(
                person_id=person_id,
                accepted_count=sum(1 for result in results if result.status == EnrollmentValidationStatus.ACCEPTED),
                rejected_count=sum(1 for result in results if result.status == EnrollmentValidationStatus.REJECTED),
                active_embeddings_count=active_count,
                enrollment_complete=enrollment_complete(active_count),
                results=results,
            ),
            gallery_entries=tuple(
                image.gallery_entry for image in stored_images if image.gallery_entry is not None
            ),
        )

    async def _validate_and_store_candidate(
        self,
        session: AsyncSession,
        *,
        person_id: UUID,
        candidate: ImageCandidate,
        policy_version: str,
        consent_id: UUID,
        face_engine: FaceEngine,
        now: datetime,
    ) -> StoredEnrollmentImage:
        try:
            bgr = decode_image_to_bgr(candidate.payload)
            validation = validate_enrollment_image(bgr, face_engine)
        except ValueError as exc:
            return StoredEnrollmentImage(
                result=_rejected_result(candidate, "invalid_image", str(exc)),
                gallery_entry=None,
            )

        if not validation.passed or validation.detection is None or validation.quality is None:
            return StoredEnrollmentImage(
                result=_validation_rejected_result(candidate, validation),
                gallery_entry=None,
            )

        liveness = face_engine.liveness(bgr, validation.detection.bbox)
        
        # Check liveness mode setting (MONITOR/OFF skips validation block)
        liveness_mode = "monitor"
        from backend.app.models.settings import Setting
        stmt = select(Setting.value).where(Setting.key == "liveness.mode")
        res = await session.execute(stmt)
        val = res.scalar_one_or_none()
        if val is not None:
            liveness_mode = str(val)

        if liveness_mode == "enforce" and not liveness.passed:
            return StoredEnrollmentImage(
                result=_rejected_result(candidate, "liveness_failed", "Liveness check failed."),
                gallery_entry=None,
            )

        aligned = face_engine.align(bgr, validation.detection.landmarks)
        embedding = face_engine.embed(aligned)
        from backend.app.crypto.envelope import encrypt_bytes, encrypt_embedding

        original_payload = encrypt_bytes(
            candidate.payload,
            aad=_asset_aad(person_id=person_id, filename=candidate.filename),
        )
        asset = EnrollmentAsset(
            person_id=person_id,
            consent_id=consent_id,
            kind=EnrollmentAssetKind.ORIGINAL_IMAGE,
            capture_pose=candidate.pose,
            content_type=candidate.content_type,
            byte_size=len(candidate.payload),
            checksum_sha256=hashlib.sha256(candidate.payload).hexdigest(),
            captured_at=now,
            **_payload_columns(original_payload),
        )
        session.add(asset)
        await session.flush()

        embedding_payload = encrypt_embedding(
            embedding.vector,
            aad=_embedding_aad(person_id=person_id, asset_id=asset.id),
        )
        face_embedding = FaceEmbedding(
            person_id=person_id,
            consent_id=consent_id,
            asset_id=asset.id,
            encryption_asset_id=asset.id,
            model_name=embedding.model_name,
            model_version=embedding.model_version,
            policy_version=policy_version,
            embedding_dimensions=512,
            is_active=True,
            quality={
                "score": validation.quality.score,
                "det_score": validation.quality.det_score,
                "bbox_area_pct": validation.quality.bbox_area_pct,
                "interocular_px": validation.quality.interocular_px,
                "sharpness": validation.quality.sharpness,
                "brightness": validation.quality.brightness,
                "yaw": validation.quality.yaw,
                "liveness_score": liveness.live_score,
            },
            **_payload_columns(embedding_payload),
        )
        await add_consented_face_embedding(
            session,
            face_embedding,
            await require_active_biometric_enrollment_consent(
                session,
                person_id=person_id,
                policy_version=policy_version,
                as_of=now,
            ),
            policy_version=policy_version,
            as_of=now,
        )

        # TEN-227: Enrollment self-test
        try:
            import logging

            from backend.app.crypto.envelope import EncryptedPayload, decrypt_embedding
            payload = EncryptedPayload(
                version=face_embedding.envelope_version,
                payload_alg=face_embedding.payload_alg,
                dek_wrap_alg=face_embedding.dek_wrap_alg,
                encryption_key_id=face_embedding.encryption_key_id,
                wrapped_dek=face_embedding.wrapped_dek,
                dek_nonce=face_embedding.dek_nonce,
                payload_nonce=face_embedding.payload_nonce,
                ciphertext=face_embedding.ciphertext,
            )
            aad = f"face-embedding:{person_id}:{asset.id}".encode()
            decrypted_vector = decrypt_embedding(payload, aad=aad)
            
            # cosine similarity
            similarity = float(np.dot(decrypted_vector, embedding.vector))
            if similarity < 0.95:
                logging.getLogger(__name__).error("Enrollment self-test failed: cosine similarity %.3f < 0.95", similarity)
                raise CrudError(CrudErrorCode.INVALID_INPUT, "Enrollment self-test failed. Internal storage error.")
        except Exception as exc:
            if isinstance(exc, CrudError):
                raise
            logging.getLogger(__name__).error("Enrollment self-test error: %s", exc)
            raise CrudError(CrudErrorCode.INVALID_INPUT, "Enrollment self-test failed.") from exc

        return StoredEnrollmentImage(
            result=EnrollmentImageResult(
                filename=candidate.filename,
                status=EnrollmentValidationStatus.ACCEPTED,
                asset_id=asset.id,
                embedding_id=face_embedding.id,
                pose=candidate.pose,
                quality_score=validation.quality.score,
            ),
            gallery_entry=GalleryEntry(
                person_id=person_id,
                embedding_id=face_embedding.id,
                vector=embedding.vector,
            ),
        )

    async def _require_person_visible(
        self,
        session: AsyncSession,
        admin_user: AdminUser,
        *,
        person_id: UUID,
        business_date: date,
    ) -> Person:
        person = (
            await session.execute(
                scoped_people_query(admin_user, business_date=business_date).where(Person.id == person_id)
            )
        ).scalar_one_or_none()
        if person is None:
            raise CrudError(CrudErrorCode.NOT_FOUND, "person not found")
        return person

    async def _active_embeddings_count(self, session: AsyncSession, *, person_id: UUID) -> int:
        count = (
            await session.execute(
                select(func.count(FaceEmbedding.id)).where(
                    FaceEmbedding.person_id == person_id,
                    FaceEmbedding.is_active.is_(True),
                )
            )
        ).scalar_one()
        return int(count)


def get_enrollment_service() -> EnrollmentService:
    return EnrollmentService()


_face_engine: FaceEngine | None = None


def get_face_engine() -> FaceEngine:
    global _face_engine
    if _face_engine is None:
        import os
        import sys

        if "pytest" in sys.modules or "PYTEST_CURRENT_TEST" in os.environ:
            _face_engine = DEFAULT_FACE_ENGINE
        else:
            from backend.app.face.engine import ONNXFaceEngine

            model_dir = os.environ.get("FACE_MODEL_DIR", "models")
            _face_engine = ONNXFaceEngine(model_dir=model_dir)
    return _face_engine


def get_gallery_index() -> GalleryIndex:
    return DEFAULT_GALLERY_INDEX


EnrollmentServiceDep = Annotated[EnrollmentService, Depends(get_enrollment_service)]
FaceEngineDep = Annotated[FaceEngine, Depends(get_face_engine)]
GalleryIndexDep = Annotated[GalleryIndex, Depends(get_gallery_index)]


@router.post("/{person_id}/upload", response_model=EnrollmentCommitResponse, status_code=201)
async def upload_enrollment_images(
    person_id: UUID,
    session: SessionDep,
    service: EnrollmentServiceDep,
    admin_user: AdminUserDep,
    actor: ActorDep,
    face_engine: FaceEngineDep,
    gallery_index: GalleryIndexDep,
    policy_version: Annotated[str, Form(min_length=1)],
    files: Annotated[list[UploadFile], File(min_length=1)],
    capture_pose: Annotated[EnrollmentPose, Form()] = EnrollmentPose.OTHER,
) -> EnrollmentCommitResponse:
    return await _commit_uploads(
        session,
        service,
        admin_user,
        actor,
        face_engine,
        gallery_index,
        person_id=person_id,
        policy_version=policy_version,
        files=files,
        default_pose=capture_pose,
        audit_action="enrollment.upload.commit",
    )


@router.post("/{person_id}/capture", response_model=EnrollmentCommitResponse, status_code=201)
async def capture_enrollment_image(
    person_id: UUID,
    session: SessionDep,
    service: EnrollmentServiceDep,
    admin_user: AdminUserDep,
    actor: ActorDep,
    face_engine: FaceEngineDep,
    gallery_index: GalleryIndexDep,
    policy_version: Annotated[str, Form(min_length=1)],
    file: Annotated[UploadFile, File()],
    capture_pose: Annotated[EnrollmentPose, Form()] = EnrollmentPose.FRONTAL,
) -> EnrollmentCommitResponse:
    return await _commit_uploads(
        session,
        service,
        admin_user,
        actor,
        face_engine,
        gallery_index,
        person_id=person_id,
        policy_version=policy_version,
        files=[file],
        default_pose=capture_pose,
        audit_action="enrollment.capture.commit",
    )


@router.post("/probe", response_model=EnrollmentProbeResponse)
async def probe_enrollment_identity(
    session: SessionDep,
    admin_user: AdminUserDep,
    face_engine: FaceEngineDep,
    gallery_index: GalleryIndexDep,
    file: Annotated[UploadFile, File()],
) -> EnrollmentProbeResponse:
    _ = session, admin_user
    try:
        candidate = await _candidate_from_upload(file, default_pose=EnrollmentPose.OTHER)
        if isinstance(candidate, RejectedUploadCandidate):
            message = candidate.result.rejection_message or "Probe image failed validation."
            raise CrudError(CrudErrorCode.INVALID_INPUT, message)
        bgr = decode_image_to_bgr(candidate.payload)
        validation = validate_enrollment_image(bgr, face_engine)
    except CrudError as exc:
        raise translate_crud_error(exc) from exc
    except ValueError as exc:
        raise translate_crud_error(CrudError(CrudErrorCode.INVALID_INPUT, str(exc))) from exc
    if not validation.passed or validation.detection is None:
        rejection = validation.rejection.message if validation.rejection else "Probe image failed validation."
        raise translate_crud_error(CrudError(CrudErrorCode.INVALID_INPUT, rejection))

    liveness = face_engine.liveness(bgr, validation.detection.bbox)
    if not liveness.passed:
        raise translate_crud_error(CrudError(CrudErrorCode.INVALID_INPUT, "Liveness check failed."))

    aligned = face_engine.align(bgr, validation.detection.landmarks)
    embedding = face_engine.embed(aligned)
    return _probe_response(gallery_index.match(embedding.vector))


async def _commit_uploads(
    session: AsyncSession,
    service: EnrollmentService,
    admin_user: AdminUser,
    actor: RequestActor,
    face_engine: FaceEngine,
    gallery_index: GalleryIndex,
    *,
    person_id: UUID,
    policy_version: str,
    files: Sequence[UploadFile],
    default_pose: EnrollmentPose,
    audit_action: str,
) -> EnrollmentCommitResponse:
    try:
        prepared_uploads = [await _candidate_from_upload(file, default_pose=default_pose) for file in files]
        rejected_uploads = [
            prepared.result for prepared in prepared_uploads if isinstance(prepared, RejectedUploadCandidate)
        ]
        candidates = [prepared for prepared in prepared_uploads if isinstance(prepared, ImageCandidate)]
        commit = await service.prepare_commit(
            session,
            admin_user,
            person_id=person_id,
            candidates=candidates,
            policy_version=policy_version,
            face_engine=face_engine,
            gallery_index=gallery_index,
            now=datetime.now(UTC),
        )
        if commit.gallery_entries:
            vectors = [entry.vector for entry in commit.gallery_entries]
            conflicts = await check_duplicate_enrollment(
                session,
                vectors,
                person_id,
                gallery_index,
            )
            if conflicts:
                first = conflicts[0]
                raise HTTPException(
                    status_code=409,
                    detail=make_error(
                        ErrorCode.DUPLICATE_ENROLLMENT,
                        f"Face already enrolled under person {first['person_id']} ({first['display_name']})",
                        details=first,
                    ),
                )
        response = _merge_rejected_uploads(commit.response, rejected_uploads)
        actor = RequestActor(admin_user.id, actor.request_id, actor.ip_address)
        await audited_mutation(
            session,
            actor,
            action=audit_action,
            entity_type="person",
            entity_id=str(person_id),
            before=None,
            after={
                "accepted_count": response.accepted_count,
                "rejected_count": response.rejected_count,
                "active_embeddings_count": response.active_embeddings_count,
                "enrollment_complete": response.enrollment_complete,
            },
        )
        await commit_or_422(session)
        await _apply_gallery_entries(session, gallery_index, commit.gallery_entries)
        await session.commit()  # TEN-222: persist gallery version bump
    except CrudError as exc:
        raise translate_crud_error(exc) from exc
    return response


async def _candidate_from_upload(
    file: UploadFile,
    *,
    default_pose: EnrollmentPose,
) -> ImageCandidate | RejectedUploadCandidate:
    content_type = file.content_type or "application/octet-stream"
    if content_type not in SUPPORTED_IMAGE_TYPES:
        filename = file.filename or "capture"
        return RejectedUploadCandidate(
            result=EnrollmentImageResult(
                filename=filename,
                status=EnrollmentValidationStatus.REJECTED,
                pose=default_pose,
                rejection_code="unsupported_content_type",
                rejection_message=f"Unsupported image content type: {content_type}",
            )
        )
    return ImageCandidate(
        filename=file.filename or "capture",
        content_type=content_type,
        payload=await file.read(),
        pose=default_pose,
    )


async def _apply_gallery_entries(
    session: AsyncSession,
    gallery_index: GalleryIndex,
    entries: Sequence[GalleryEntry],
) -> None:
    for entry in entries:
        await bump_gallery_version(session)
        gallery_index.add(entry)


def _merge_rejected_uploads(
    response: EnrollmentCommitResponse,
    rejected_uploads: Sequence[EnrollmentImageResult],
) -> EnrollmentCommitResponse:
    if not rejected_uploads:
        return response
    return EnrollmentCommitResponse(
        person_id=response.person_id,
        accepted_count=response.accepted_count,
        rejected_count=response.rejected_count + len(rejected_uploads),
        active_embeddings_count=response.active_embeddings_count,
        enrollment_complete=response.enrollment_complete,
        target_embeddings=response.target_embeddings,
        minimum_complete_embeddings=response.minimum_complete_embeddings,
        results=[*response.results, *rejected_uploads],
    )


# decode_image_to_bgr is imported from backend.app.face.decode (TEN-223).
# Re-exported here for backward compatibility with callers that import
# from this module.
__all__ = ["decode_image_to_bgr"]


def _validation_rejected_result(
    candidate: ImageCandidate,
    validation: EnrollmentValidationResult,
) -> EnrollmentImageResult:
    if validation.rejection is None:
        return _rejected_result(candidate, "invalid_image", "Enrollment image failed validation.")
    return _rejected_result(
        candidate,
        validation.rejection.code.value,
        validation.rejection.message,
    )


def _rejected_result(
    candidate: ImageCandidate,
    code: str,
    message: str,
) -> EnrollmentImageResult:
    return EnrollmentImageResult(
        filename=candidate.filename,
        status=EnrollmentValidationStatus.REJECTED,
        pose=candidate.pose,
        rejection_code=code,
        rejection_message=message,
    )


def _payload_columns(payload: Any) -> dict[str, object]:
    return {
        "envelope_version": payload.version,
        "payload_alg": payload.payload_alg,
        "dek_wrap_alg": payload.dek_wrap_alg,
        "encryption_key_id": payload.encryption_key_id,
        "wrapped_dek": payload.wrapped_dek,
        "dek_nonce": payload.dek_nonce,
        "payload_nonce": payload.payload_nonce,
        "ciphertext": payload.ciphertext,
    }


def _probe_response(result: MatchResult) -> EnrollmentProbeResponse:
    return EnrollmentProbeResponse(
        decision=result.decision,
        person_id=result.top1.person_id if result.top1 is not None else None,
        embedding_id=result.top1.embedding_id if result.top1 is not None else None,
        score=result.top1.score if result.top1 is not None else None,
        margin=result.margin,
        candidates=[
            EnrollmentProbeCandidate(
                person_id=candidate.person_id,
                embedding_id=candidate.embedding_id,
                score=candidate.score,
            )
            for candidate in result.candidates
        ],
    )


def _asset_aad(*, person_id: UUID, filename: str) -> bytes:
    return f"enrollment-asset:{person_id}:{filename}".encode()


def _embedding_aad(*, person_id: UUID, asset_id: UUID) -> bytes:
    return f"face-embedding:{person_id}:{asset_id}".encode()
