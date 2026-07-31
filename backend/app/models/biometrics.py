from __future__ import annotations

from datetime import datetime
from enum import Enum
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    LargeBinary,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.orm import relationship as orm_relationship
from sqlalchemy.types import Uuid

from backend.app.db.base import Base, created_at_column, updated_at_column, uuid_pk

MIN_ACTIVE_EMBEDDINGS_FOR_ENROLLMENT = 3
TARGET_EMBEDDINGS_PER_PERSON = 5


class ConsentType(str, Enum):
    BIOMETRIC_PROCESSING = "biometric_processing"
    BIOMETRIC_RETENTION = "biometric_retention"


class ConsentGrantor(str, Enum):
    SELF = "self"
    GUARDIAN = "guardian"


class ConsentMethod(str, Enum):
    PAPER = "paper"
    DIGITAL_SIGNATURE = "digital_signature"
    ADMIN_ATTESTATION = "admin_attestation"


class EnrollmentAssetKind(str, Enum):
    ORIGINAL_IMAGE = "original_image"
    ALIGNED_FACE = "aligned_face"


class EnrollmentPose(str, Enum):
    FRONTAL = "frontal"
    YAW_LEFT = "yaw_left"
    YAW_RIGHT = "yaw_right"
    SLIGHT_UP = "slight_up"
    GLASSES = "glasses"
    OTHER = "other"


class Consent(Base):
    __tablename__ = "consents"
    __table_args__ = (
        UniqueConstraint(
            "person_id",
            "consent_type",
            "policy_version",
            name="uq_consents_person_type_policy_version",
        ),
        CheckConstraint("policy_version <> ''", name="policy_version_non_empty"),
        CheckConstraint(
            "revoked_at IS NULL OR revoked_at >= granted_at",
            name="revoked_at_not_before_granted_at",
        ),
        CheckConstraint(
            "grantor <> 'guardian' OR guardian_id IS NOT NULL",
            name="guardian_consent_requires_guardian",
        ),
    )

    id: Mapped[UUID] = uuid_pk()
    person_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("people.id", ondelete="CASCADE"),
        nullable=False,
    )
    guardian_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("guardians.id", ondelete="SET NULL"),
        nullable=True,
    )
    consent_type: Mapped[ConsentType] = mapped_column(String(64), nullable=False)
    grantor: Mapped[ConsentGrantor] = mapped_column(String(32), nullable=False)
    grantor_relationship: Mapped[str | None] = mapped_column(String(64), nullable=True)
    method: Mapped[ConsentMethod] = mapped_column(String(64), nullable=False)
    policy_version: Mapped[str] = mapped_column(String(64), nullable=False)
    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    evidence_ref: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()

    enrollment_assets: Mapped[list[EnrollmentAsset]] = orm_relationship(
        back_populates="consent",
        cascade="all, delete-orphan",
    )
    face_embeddings: Mapped[list[FaceEmbedding]] = orm_relationship(
        back_populates="consent",
        cascade="all, delete-orphan",
    )

    def is_active_for_policy(self, policy_version: str, *, as_of: datetime) -> bool:
        return (
            self.policy_version == policy_version
            and self.granted_at <= as_of
            and (self.revoked_at is None or as_of < self.revoked_at)
        )


class EncryptedPayloadColumns:
    envelope_version: Mapped[int] = mapped_column(nullable=False)
    payload_alg: Mapped[str] = mapped_column(String(64), nullable=False)
    dek_wrap_alg: Mapped[str] = mapped_column(String(64), nullable=False)
    encryption_key_id: Mapped[str] = mapped_column(String(128), nullable=False)
    wrapped_dek: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    dek_nonce: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    payload_nonce: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    ciphertext: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)


class EnrollmentAsset(EncryptedPayloadColumns, Base):
    __tablename__ = "enrollment_assets"
    __table_args__ = (
        CheckConstraint("byte_size > 0", name="byte_size_positive"),
        CheckConstraint("content_type <> ''", name="content_type_non_empty"),
        CheckConstraint("capture_pose <> ''", name="capture_pose_non_empty"),
    )

    id: Mapped[UUID] = uuid_pk()
    person_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("people.id", ondelete="CASCADE"),
        nullable=False,
    )
    consent_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("consents.id", ondelete="RESTRICT"),
        nullable=False,
    )
    kind: Mapped[EnrollmentAssetKind] = mapped_column(String(32), nullable=False)
    capture_pose: Mapped[EnrollmentPose] = mapped_column(String(32), nullable=False)
    content_type: Mapped[str] = mapped_column(String(128), nullable=False)
    byte_size: Mapped[int] = mapped_column(nullable=False)
    checksum_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = created_at_column()

    consent: Mapped[Consent] = orm_relationship(back_populates="enrollment_assets")


class FaceEmbedding(EncryptedPayloadColumns, Base):
    __tablename__ = "face_embeddings"
    __table_args__ = (
        UniqueConstraint(
            "person_id",
            "model_name",
            "model_version",
            "asset_id",
            name="uq_face_embeddings_person_model_asset",
        ),
        CheckConstraint("model_name <> ''", name="model_name_non_empty"),
        CheckConstraint("model_version <> ''", name="model_version_non_empty"),
        CheckConstraint("embedding_dimensions = 512", name="embedding_dimensions_512"),
        Index(
            "uq_face_embeddings_active_person_model",
            "person_id",
            "model_name",
            "model_version",
            unique=True,
            postgresql_where=text("is_active"),
        ),
    )

    id: Mapped[UUID] = uuid_pk()
    person_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("people.id", ondelete="CASCADE"),
        nullable=False,
    )
    consent_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("consents.id", ondelete="RESTRICT"),
        nullable=False,
    )
    asset_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("enrollment_assets.id", ondelete="SET NULL"),
        nullable=True,
    )
    model_name: Mapped[str] = mapped_column(String(128), nullable=False)
    model_version: Mapped[str] = mapped_column(String(128), nullable=False)
    embedding_dimensions: Mapped[int] = mapped_column(nullable=False, default=512)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    quality: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = created_at_column()

    consent: Mapped[Consent] = orm_relationship(back_populates="face_embeddings")
    asset: Mapped[EnrollmentAsset | None] = orm_relationship()


def active_biometric_consent_for_policy(
    consents: list[Consent],
    policy_version: str,
    *,
    as_of: datetime,
) -> Consent | None:
    active_consents = [
        consent
        for consent in consents
        if consent.consent_type == ConsentType.BIOMETRIC_PROCESSING
        and consent.is_active_for_policy(policy_version, as_of=as_of)
    ]
    if not active_consents:
        return None
    return max(active_consents, key=lambda consent: consent.granted_at)


def require_active_biometric_consent(
    consents: list[Consent],
    policy_version: str,
    *,
    as_of: datetime,
) -> Consent:
    consent = active_biometric_consent_for_policy(consents, policy_version, as_of=as_of)
    if consent is None:
        raise ValueError("active biometric consent is required for the current policy version")
    return consent


def enrollment_complete(active_embeddings_count: int) -> bool:
    return active_embeddings_count >= MIN_ACTIVE_EMBEDDINGS_FOR_ENROLLMENT
