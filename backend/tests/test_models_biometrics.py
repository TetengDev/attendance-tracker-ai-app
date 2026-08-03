from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pytest
from sqlalchemy import Table

from backend.app.models.biometrics import (
    Consent,
    ConsentGrantor,
    ConsentMethod,
    ConsentType,
    EnrollmentAsset,
    FaceEmbedding,
    active_biometric_consent_for_policy,
    enrollment_complete,
    require_active_biometric_consent,
)


def test_active_consent_guard_requires_current_policy_version() -> None:
    now = datetime(2026, 7, 31, 8, 0, tzinfo=UTC)
    old_policy = Consent(
        consent_type=ConsentType.BIOMETRIC_PROCESSING,
        grantor=ConsentGrantor.SELF,
        method=ConsentMethod.DIGITAL_SIGNATURE,
        policy_version="privacy-v1",
        granted_at=now - timedelta(days=30),
    )
    current_policy = Consent(
        consent_type=ConsentType.BIOMETRIC_PROCESSING,
        grantor=ConsentGrantor.SELF,
        method=ConsentMethod.DIGITAL_SIGNATURE,
        policy_version="privacy-v2",
        granted_at=now - timedelta(days=1),
    )

    assert active_biometric_consent_for_policy(
        [old_policy, current_policy],
        "privacy-v2",
        as_of=now,
    ) is current_policy
    assert require_active_biometric_consent(
        [old_policy, current_policy],
        "privacy-v2",
        as_of=now,
    ) is current_policy


def test_revoked_consent_is_not_active() -> None:
    now = datetime(2026, 7, 31, 8, 0, tzinfo=UTC)
    consent = Consent(
        consent_type=ConsentType.BIOMETRIC_PROCESSING,
        grantor=ConsentGrantor.SELF,
        method=ConsentMethod.PAPER,
        policy_version="privacy-v2",
        granted_at=now - timedelta(days=10),
        revoked_at=now - timedelta(days=1),
    )

    with pytest.raises(ValueError, match="active biometric consent"):
        require_active_biometric_consent([consent], "privacy-v2", as_of=now)


def test_enrollment_requires_at_least_three_active_embeddings() -> None:
    assert not enrollment_complete(2)
    assert enrollment_complete(3)


def test_biometric_models_encode_encrypted_payload_columns() -> None:
    asset_columns = {column.name for column in cast(Table, EnrollmentAsset.__table__).columns}
    embedding_columns = {column.name for column in cast(Table, FaceEmbedding.__table__).columns}
    envelope_columns = {
        "envelope_version",
        "payload_alg",
        "dek_wrap_alg",
        "encryption_key_id",
        "wrapped_dek",
        "dek_nonce",
        "payload_nonce",
        "ciphertext",
    }

    assert envelope_columns <= asset_columns
    assert envelope_columns <= embedding_columns
    assert "vector" not in embedding_columns


def test_biometric_models_encode_required_constraints() -> None:
    consent_constraints = {constraint.name for constraint in cast(Table, Consent.__table__).constraints}
    asset_constraints = {constraint.name for constraint in cast(Table, EnrollmentAsset.__table__).constraints}
    embedding_constraints = {
        constraint.name for constraint in cast(Table, FaceEmbedding.__table__).constraints
    }
    embedding_indexes = {index.name for index in cast(Table, FaceEmbedding.__table__).indexes}

    assert "uq_consents_person_type_policy_version" in consent_constraints
    assert "ck_consents_guardian_consent_requires_guardian" in consent_constraints
    assert "ck_enrollment_assets_byte_size_positive" in asset_constraints
    assert "ck_face_embeddings_embedding_dimensions_512" in embedding_constraints
    assert "ck_face_embeddings_policy_version_non_empty" in embedding_constraints
    assert "uq_face_embeddings_person_model_asset" in embedding_constraints
    assert "uq_face_embeddings_active_person_model" in embedding_indexes


def test_embedding_model_uses_uuid_primary_key() -> None:
    assert cast(Any, FaceEmbedding.id).property.columns[0].server_default is not None
