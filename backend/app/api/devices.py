from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.api.common import (
    ActorDep,
    AdminUserDep,
    CrudError,
    CrudErrorCode,
    PageParams,
    RequestActor,
    SessionDep,
    StrictSchema,
    apply_updates,
    audited_mutation,
    commit_or_422,
    require_org_admin,
    snapshot,
    translate_crud_error,
)
from backend.app.models.devices import Device, DeviceDirection, DeviceFormFactor, DeviceMode

router = APIRouter(prefix="/api/devices", tags=["devices"])

DEVICE_FIELDS = (
    "id",
    "location_id",
    "mode",
    "form_factor",
    "direction",
    "token_display_prefix",
    "pairing_code_expires_at",
    "settings_override",
    "allowed_cidrs",
)


class DeviceCreate(StrictSchema):
    location_id: UUID | None = None
    mode: DeviceMode = DeviceMode.FIXED
    form_factor: DeviceFormFactor
    direction: DeviceDirection = DeviceDirection.BIDIRECTIONAL
    token_hash: str
    token_display_prefix: str
    pairing_code_hash: str | None = None
    pairing_code_expires_at: datetime | None = None
    settings_override: dict[str, object] = Field(default_factory=dict)
    allowed_cidrs: list[str] = Field(default_factory=list)


class DeviceUpdate(StrictSchema):
    location_id: UUID | None = None
    mode: DeviceMode | None = None
    form_factor: DeviceFormFactor | None = None
    direction: DeviceDirection | None = None
    token_hash: str | None = None
    token_display_prefix: str | None = None
    pairing_code_hash: str | None = None
    pairing_code_expires_at: datetime | None = None
    settings_override: dict[str, object] | None = None
    allowed_cidrs: list[str] | None = None


class DeviceRead(StrictSchema):
    id: UUID
    location_id: UUID | None
    mode: DeviceMode
    form_factor: DeviceFormFactor
    direction: DeviceDirection
    token_display_prefix: str
    pairing_code_expires_at: datetime | None
    settings_override: dict[str, object]
    allowed_cidrs: list[str]


class DevicesService:
    async def list(self, session: AsyncSession, *, limit: int, offset: int) -> list[Device]:
        return list((await session.execute(select(Device).limit(limit).offset(offset))).scalars())

    async def get(self, session: AsyncSession, device_id: UUID) -> Device:
        device = await session.get(Device, device_id)
        if device is None:
            raise CrudError(CrudErrorCode.NOT_FOUND, "device not found")
        return device

    async def create(self, session: AsyncSession, payload: DeviceCreate) -> Device:
        device = Device(**payload.model_dump())
        session.add(device)
        await session.flush()
        return device

    async def update(self, session: AsyncSession, device: Device, payload: DeviceUpdate) -> Device:
        apply_updates(device, payload.model_dump(exclude_unset=True))
        await session.flush()
        return device

    async def delete(self, session: AsyncSession, device: Device) -> None:
        await session.delete(device)
        await session.flush()


def get_devices_service() -> DevicesService:
    return DevicesService()


DevicesServiceDep = Annotated[DevicesService, Depends(get_devices_service)]


@router.get("", response_model=list[DeviceRead])
async def list_devices(
    session: SessionDep,
    service: DevicesServiceDep,
    admin_user: AdminUserDep,
    page: Annotated[PageParams, Depends()],
) -> list[DeviceRead]:
    try:
        require_org_admin(admin_user)
        devices = await service.list(session, limit=page.limit, offset=page.offset)
    except CrudError as exc:
        raise translate_crud_error(exc) from exc
    return [DeviceRead.model_validate(device) for device in devices]


@router.post("", response_model=DeviceRead, status_code=201)
async def create_device(
    payload: DeviceCreate,
    session: SessionDep,
    service: DevicesServiceDep,
    admin_user: AdminUserDep,
    actor: ActorDep,
) -> DeviceRead:
    try:
        require_org_admin(admin_user)
        device = await service.create(session, payload)
        actor = RequestActor(admin_user.id, actor.request_id, actor.ip_address)
        await audited_mutation(
            session,
            actor,
            action="device.create",
            entity_type="device",
            entity_id=str(device.id),
            before=None,
            after=snapshot(device, DEVICE_FIELDS),
        )
        await commit_or_422(session)
    except CrudError as exc:
        raise translate_crud_error(exc) from exc
    return DeviceRead.model_validate(device)


@router.get("/{device_id}", response_model=DeviceRead)
async def get_device(
    device_id: UUID,
    session: SessionDep,
    service: DevicesServiceDep,
    admin_user: AdminUserDep,
) -> DeviceRead:
    try:
        require_org_admin(admin_user)
        return DeviceRead.model_validate(await service.get(session, device_id))
    except CrudError as exc:
        raise translate_crud_error(exc) from exc


@router.patch("/{device_id}", response_model=DeviceRead)
async def update_device(
    device_id: UUID,
    payload: DeviceUpdate,
    session: SessionDep,
    service: DevicesServiceDep,
    admin_user: AdminUserDep,
    actor: ActorDep,
) -> DeviceRead:
    try:
        require_org_admin(admin_user)
        device = await service.get(session, device_id)
        before = snapshot(device, DEVICE_FIELDS)
        device = await service.update(session, device, payload)
        actor = RequestActor(admin_user.id, actor.request_id, actor.ip_address)
        await audited_mutation(
            session,
            actor,
            action="device.update",
            entity_type="device",
            entity_id=str(device.id),
            before=before,
            after=snapshot(device, DEVICE_FIELDS),
        )
        await commit_or_422(session)
    except CrudError as exc:
        raise translate_crud_error(exc) from exc
    return DeviceRead.model_validate(device)


@router.delete("/{device_id}", status_code=204)
async def delete_device(
    device_id: UUID,
    session: SessionDep,
    service: DevicesServiceDep,
    admin_user: AdminUserDep,
    actor: ActorDep,
) -> None:
    try:
        require_org_admin(admin_user)
        device = await service.get(session, device_id)
        before = snapshot(device, DEVICE_FIELDS)
        await service.delete(session, device)
        actor = RequestActor(admin_user.id, actor.request_id, actor.ip_address)
        await audited_mutation(
            session,
            actor,
            action="device.delete",
            entity_type="device",
            entity_id=str(device_id),
            before=before,
            after=None,
        )
        await commit_or_422(session)
    except CrudError as exc:
        raise translate_crud_error(exc) from exc
