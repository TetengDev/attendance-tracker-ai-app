from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from backend.app.enrollment.consent import (
    ConsentEnforcementError,
    require_embedding_matches_active_consent,
)
from backend.app.models.biometrics import (
    Consent,
    ConsentGrantor,
    ConsentMethod,
    ConsentType,
    FaceEmbedding,
)


def _consent(
    *,
    consent_id: UUID,
    person_id: UUID,
    policy_version: str,
    granted_at: datetime,
    revoked_at: datetime | None = None,
    consent_type: ConsentType = ConsentType.BIOMETRIC_PROCESSING,
) -> Consent:
    return Consent(
        id=consent_id,
        person_id=person_id,
        consent_type=consent_type,
        grantor=ConsentGrantor.SELF,
        method=ConsentMethod.DIGITAL_SIGNATURE,
        policy_version=policy_version,
        granted_at=granted_at,
        revoked_at=revoked_at,
    )


def _embedding(*, person_id: UUID, consent_id: UUID) -> FaceEmbedding:
    return FaceEmbedding(
        person_id=person_id,
        consent_id=consent_id,
        model_name="arcface",
        model_version="w600k-r50-v1",
        embedding_dimensions=512,
        envelope_version=1,
        payload_alg="AES-256-GCM",
        dek_wrap_alg="AES-KW",
        encryption_key_id="kek.test",
        wrapped_dek=b"wrapped",
        dek_nonce=b"dek-nonce",
        payload_nonce=b"payload-nonce",
        ciphertext=b"ciphertext",
    )


def test_embedding_write_accepts_active_current_policy_consent() -> None:
    now = datetime(2026, 8, 4, 8, 0, tzinfo=UTC)
    person_id = UUID("10000000-0000-0000-0000-000000000033")
    consent_id = UUID("20000000-0000-0000-0000-000000000033")

    require_embedding_matches_active_consent(
        _embedding(person_id=person_id, consent_id=consent_id),
        _consent(
            consent_id=consent_id,
            person_id=person_id,
            policy_version="privacy-v2",
            granted_at=now - timedelta(days=1),
        ),
        policy_version="privacy-v2",
        as_of=now,
    )


def test_embedding_write_rejects_revoked_consent() -> None:
    now = datetime(2026, 8, 4, 8, 0, tzinfo=UTC)
    person_id = UUID("10000000-0000-0000-0000-000000000034")
    consent_id = UUID("20000000-0000-0000-0000-000000000034")

    with pytest.raises(ConsentEnforcementError, match="active biometric enrollment consent"):
        require_embedding_matches_active_consent(
            _embedding(person_id=person_id, consent_id=consent_id),
            _consent(
                consent_id=consent_id,
                person_id=person_id,
                policy_version="privacy-v2",
                granted_at=now - timedelta(days=10),
                revoked_at=now - timedelta(days=1),
            ),
            policy_version="privacy-v2",
            as_of=now,
        )


def test_embedding_write_rejects_prior_policy_version_consent() -> None:
    now = datetime(2026, 8, 4, 8, 0, tzinfo=UTC)
    person_id = UUID("10000000-0000-0000-0000-000000000035")
    consent_id = UUID("20000000-0000-0000-0000-000000000035")

    with pytest.raises(ConsentEnforcementError, match="active biometric enrollment consent"):
        require_embedding_matches_active_consent(
            _embedding(person_id=person_id, consent_id=consent_id),
            _consent(
                consent_id=consent_id,
                person_id=person_id,
                policy_version="privacy-v1",
                granted_at=now - timedelta(days=10),
            ),
            policy_version="privacy-v2",
            as_of=now,
        )


def test_embedding_write_rejects_embedding_that_references_different_consent() -> None:
    now = datetime(2026, 8, 4, 8, 0, tzinfo=UTC)
    person_id = UUID("10000000-0000-0000-0000-000000000036")

    with pytest.raises(ConsentEnforcementError, match="active consent"):
        require_embedding_matches_active_consent(
            _embedding(
                person_id=person_id,
                consent_id=UUID("20000000-0000-0000-0000-000000000036"),
            ),
            _consent(
                consent_id=UUID("30000000-0000-0000-0000-000000000036"),
                person_id=person_id,
                policy_version="privacy-v2",
                granted_at=now - timedelta(days=1),
            ),
            policy_version="privacy-v2",
            as_of=now,
        )
