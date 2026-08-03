from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models.biometrics import Consent, ConsentType, FaceEmbedding


@dataclass(frozen=True)
class ConsentEnforcementError(Exception):
    message: str


async def require_active_biometric_enrollment_consent(
    session: AsyncSession,
    *,
    person_id: UUID,
    policy_version: str,
    as_of: datetime,
) -> Consent:
    consent = (
        await session.execute(
            select(Consent)
            .where(Consent.person_id == person_id)
            .where(Consent.consent_type == ConsentType.BIOMETRIC_PROCESSING)
            .where(Consent.policy_version == policy_version)
            .where(Consent.granted_at <= as_of)
            .where((Consent.revoked_at.is_(None)) | (as_of < Consent.revoked_at))
            .order_by(Consent.granted_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if consent is None:
        raise ConsentEnforcementError(
            "active biometric enrollment consent is required for the current policy version"
        )
    return consent


def require_embedding_matches_active_consent(
    embedding: FaceEmbedding,
    consent: Consent,
    *,
    policy_version: str,
    as_of: datetime,
) -> None:
    if embedding.person_id != consent.person_id:
        raise ConsentEnforcementError("embedding person must match consent person")
    if embedding.consent_id != consent.id:
        raise ConsentEnforcementError("embedding must reference the active consent")
    if consent.consent_type != ConsentType.BIOMETRIC_PROCESSING:
        raise ConsentEnforcementError("biometric enrollment requires biometric processing consent")
    if not consent.is_active_for_policy(policy_version, as_of=as_of):
        raise ConsentEnforcementError(
            "active biometric enrollment consent is required for the current policy version"
        )
