from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
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
from backend.app.models.devices import Device
from backend.app.models.sessions import ScanSession, ScanSessionEndReason, ScanSessionLocationSource
from backend.app.scan.sessions import (
    ScanSessionError,
    active_scan_session_for_device,
    close_scan_session,
    open_scan_session,
)

router = APIRouter(prefix="/api/sessions", tags=["sessions"])

SCAN_SESSION_FIELDS = (
    "id",
    "device_id",
    "location_id",
    "operator_admin_id",
    "location_source",
    "started_at",
    "ended_at",
    "last_activity_at",
    "scan_count",
    "end_reason",
)


class ScanSessionCreate(StrictSchema):
    device_id: UUID
    location_id: UUID
    location_source: ScanSessionLocationSource = ScanSessionLocationSource.SESSION_DECLARED
    start_lat: Decimal | None = None
    start_lng: Decimal | None = None
    gps_accuracy_m: Decimal | None = None


class ScanSessionRead(StrictSchema):
    id: UUID
    device_id: UUID
    location_id: UUID
    operator_admin_id: UUID | None
    location_source: ScanSessionLocationSource
    started_at: datetime
    ended_at: datetime | None
    last_activity_at: datetime
    scan_count: int
    end_reason: ScanSessionEndReason | None


class SessionsService:
    async def open(
        self,
        session: AsyncSession,
        payload: ScanSessionCreate,
        *,
        operator_admin_id: UUID,
        now: datetime,
    ) -> ScanSession:
        device = await session.get(Device, payload.device_id)
        if device is None:
            raise CrudError(CrudErrorCode.NOT_FOUND, "device not found")
        existing = await active_scan_session_for_device(session, device_id=device.id)
        if existing is not None:
            raise CrudError(CrudErrorCode.CONFLICT, "device already has an open scan session")
        scan_session = open_scan_session(
            device,
            location_id=payload.location_id,
            operator_admin_id=operator_admin_id,
            location_source=payload.location_source,
            started_at=now,
            start_lat=payload.start_lat,
            start_lng=payload.start_lng,
            gps_accuracy_m=payload.gps_accuracy_m,
        )
        session.add(scan_session)
        await session.flush()
        return scan_session

    async def active(self, session: AsyncSession, *, device_id: UUID) -> ScanSession | None:
        return await active_scan_session_for_device(session, device_id=device_id)

    async def close(
        self,
        session: AsyncSession,
        *,
        session_id: UUID,
        now: datetime,
        reason: ScanSessionEndReason = ScanSessionEndReason.EXPLICIT,
    ) -> ScanSession:
        scan_session = await session.get(ScanSession, session_id)
        if scan_session is None:
            raise CrudError(CrudErrorCode.NOT_FOUND, "scan session not found")
        close_scan_session(scan_session, ended_at=now, reason=reason)
        await session.flush()
        return scan_session


def get_sessions_service() -> SessionsService:
    return SessionsService()


SessionsServiceDep = Annotated[SessionsService, Depends(get_sessions_service)]


@router.post("", response_model=ScanSessionRead, status_code=201)
async def create_scan_session(
    payload: ScanSessionCreate,
    session: SessionDep,
    service: SessionsServiceDep,
    admin_user: AdminUserDep,
    actor: ActorDep,
) -> ScanSessionRead:
    try:
        require_org_admin(admin_user)
        scan_session = await service.open(
            session,
            payload,
            operator_admin_id=admin_user.id,
            now=datetime.now(UTC),
        )
        actor = RequestActor(admin_user.id, actor.request_id, actor.ip_address)
        await audited_mutation(
            session,
            actor,
            action="scan_session.create",
            entity_type="scan_session",
            entity_id=str(scan_session.id),
            before=None,
            after=snapshot(scan_session, SCAN_SESSION_FIELDS),
        )
        await commit_or_422(session)
    except ScanSessionError as exc:
        raise translate_crud_error(CrudError(CrudErrorCode.INVALID_INPUT, str(exc))) from exc
    except CrudError as exc:
        raise translate_crud_error(exc) from exc
    return ScanSessionRead.model_validate(scan_session)


@router.get("/active/{device_id}", response_model=ScanSessionRead | None)
async def get_active_scan_session(
    device_id: UUID,
    session: SessionDep,
    service: SessionsServiceDep,
    admin_user: AdminUserDep,
) -> ScanSessionRead | None:
    try:
        require_org_admin(admin_user)
        scan_session = await service.active(session, device_id=device_id)
    except CrudError as exc:
        raise translate_crud_error(exc) from exc
    return None if scan_session is None else ScanSessionRead.model_validate(scan_session)


@router.post("/{session_id}/end", response_model=ScanSessionRead)
async def end_scan_session(
    session_id: UUID,
    session: SessionDep,
    service: SessionsServiceDep,
    admin_user: AdminUserDep,
    actor: ActorDep,
) -> ScanSessionRead:
    try:
        require_org_admin(admin_user)
        scan_session = await service.close(
            session,
            session_id=session_id,
            now=datetime.now(UTC),
        )
        actor = RequestActor(admin_user.id, actor.request_id, actor.ip_address)
        await audited_mutation(
            session,
            actor,
            action="scan_session.end",
            entity_type="scan_session",
            entity_id=str(scan_session.id),
            before=None,
            after=snapshot(scan_session, SCAN_SESSION_FIELDS),
        )
        await commit_or_422(session)
    except CrudError as exc:
        raise translate_crud_error(exc) from exc
    return ScanSessionRead.model_validate(scan_session)
