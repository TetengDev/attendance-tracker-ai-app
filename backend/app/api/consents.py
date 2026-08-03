from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
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
    require_org_admin,
    snapshot,
    translate_crud_error,
)
from backend.app.enrollment.consent import (
    ConsentEnforcementError,
    require_active_biometric_enrollment_consent,
)
from backend.app.models.biometrics import Consent, ConsentGrantor, ConsentMethod, ConsentType

router = APIRouter(prefix="/api/consents", tags=["consents"])

CONSENT_FIELDS = (
    "id",
    "person_id",
    "guardian_id",
    "consent_type",
    "grantor",
    "grantor_relationship",
    "method",
    "policy_version",
    "granted_at",
    "revoked_at",
    "ip_address",
    "evidence_ref",
)


class BiometricConsentCreate(StrictSchema):
    person_id: UUID
    guardian_id: UUID | None = None
    grantor: ConsentGrantor
    grantor_relationship: str | None = None
    method: ConsentMethod
    policy_version: str
    granted_at: datetime | None = None
    evidence_ref: str | None = None


class BiometricConsentAuthorize(StrictSchema):
    person_id: UUID
    policy_version: str


class ConsentRead(StrictSchema):
    id: UUID
    person_id: UUID
    guardian_id: UUID | None
    consent_type: ConsentType
    grantor: ConsentGrantor
    grantor_relationship: str | None
    method: ConsentMethod
    policy_version: str
    granted_at: datetime
    revoked_at: datetime | None
    ip_address: str | None
    evidence_ref: str | None


class ConsentsService:
    async def create_biometric_enrollment(
        self,
        session: AsyncSession,
        payload: BiometricConsentCreate,
        *,
        ip_address: str | None,
        now: datetime,
    ) -> Consent:
        consent = Consent(
            person_id=payload.person_id,
            guardian_id=payload.guardian_id,
            consent_type=ConsentType.BIOMETRIC_PROCESSING,
            grantor=payload.grantor,
            grantor_relationship=payload.grantor_relationship,
            method=payload.method,
            policy_version=payload.policy_version,
            granted_at=payload.granted_at or now,
            ip_address=ip_address,
            evidence_ref=payload.evidence_ref,
        )
        session.add(consent)
        await session.flush()
        return consent

    async def revoke(
        self,
        session: AsyncSession,
        *,
        consent_id: UUID,
        revoked_at: datetime,
    ) -> Consent:
        consent = await session.get(Consent, consent_id)
        if consent is None:
            raise CrudError(CrudErrorCode.NOT_FOUND, "consent not found")
        consent.revoked_at = revoked_at
        await session.flush()
        return consent

    async def authorize_biometric_enrollment(
        self,
        session: AsyncSession,
        payload: BiometricConsentAuthorize,
        *,
        as_of: datetime,
    ) -> Consent:
        try:
            return await require_active_biometric_enrollment_consent(
                session,
                person_id=payload.person_id,
                policy_version=payload.policy_version,
                as_of=as_of,
            )
        except ConsentEnforcementError as exc:
            raise CrudError(CrudErrorCode.INVALID_INPUT, exc.message) from exc


def get_consents_service() -> ConsentsService:
    return ConsentsService()


ConsentsServiceDep = Annotated[ConsentsService, Depends(get_consents_service)]


@router.post("/biometric-enrollment", response_model=ConsentRead, status_code=201)
async def create_biometric_enrollment_consent(
    payload: BiometricConsentCreate,
    session: SessionDep,
    service: ConsentsServiceDep,
    admin_user: AdminUserDep,
    actor: ActorDep,
) -> ConsentRead:
    try:
        require_org_admin(admin_user)
        actor = RequestActor(admin_user.id, actor.request_id, actor.ip_address)
        consent = await service.create_biometric_enrollment(
            session,
            payload,
            ip_address=actor.ip_address,
            now=datetime.now(UTC),
        )
        await audited_mutation(
            session,
            actor,
            action="consent.biometric_enrollment.create",
            entity_type="consent",
            entity_id=str(consent.id),
            before=None,
            after=snapshot(consent, CONSENT_FIELDS),
        )
        await commit_or_422(session)
    except CrudError as exc:
        raise translate_crud_error(exc) from exc
    return ConsentRead.model_validate(consent)


@router.post("/biometric-enrollment/authorize", response_model=ConsentRead)
async def authorize_biometric_enrollment(
    payload: BiometricConsentAuthorize,
    session: SessionDep,
    service: ConsentsServiceDep,
    admin_user: AdminUserDep,
) -> ConsentRead:
    try:
        require_org_admin(admin_user)
        consent = await service.authorize_biometric_enrollment(
            session,
            payload,
            as_of=datetime.now(UTC),
        )
    except CrudError as exc:
        raise translate_crud_error(exc) from exc
    return ConsentRead.model_validate(consent)


@router.post("/{consent_id}/revoke", response_model=ConsentRead)
async def revoke_consent(
    consent_id: UUID,
    session: SessionDep,
    service: ConsentsServiceDep,
    admin_user: AdminUserDep,
    actor: ActorDep,
) -> ConsentRead:
    try:
        require_org_admin(admin_user)
        consent = await service.revoke(session, consent_id=consent_id, revoked_at=datetime.now(UTC))
        actor = RequestActor(admin_user.id, actor.request_id, actor.ip_address)
        await audited_mutation(
            session,
            actor,
            action="consent.revoke",
            entity_type="consent",
            entity_id=str(consent.id),
            before=None,
            after=snapshot(consent, CONSENT_FIELDS),
        )
        await commit_or_422(session)
    except CrudError as exc:
        raise translate_crud_error(exc) from exc
    return ConsentRead.model_validate(consent)
