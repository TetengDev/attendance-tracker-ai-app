from __future__ import annotations

from decimal import Decimal
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.api.common import (
    ActorDep,
    CrudError,
    CrudErrorCode,
    PageParams,
    SessionDep,
    StrictSchema,
    apply_updates,
    audited_mutation,
    commit_or_422,
    snapshot,
    translate_crud_error,
)
from backend.app.models.devices import Location

router = APIRouter(prefix="/api/locations", tags=["locations"])

LOCATION_FIELDS = ("id", "name", "timezone", "latitude", "longitude")


class LocationCreate(StrictSchema):
    name: str
    timezone: str
    latitude: Decimal | None = None
    longitude: Decimal | None = None


class LocationUpdate(StrictSchema):
    name: str | None = None
    timezone: str | None = None
    latitude: Decimal | None = None
    longitude: Decimal | None = None


class LocationRead(StrictSchema):
    id: UUID
    name: str
    timezone: str
    latitude: Decimal | None
    longitude: Decimal | None


class LocationsService:
    async def list(self, session: AsyncSession, *, limit: int, offset: int) -> list[Location]:
        return list((await session.execute(select(Location).limit(limit).offset(offset))).scalars())

    async def get(self, session: AsyncSession, location_id: UUID) -> Location:
        location = await session.get(Location, location_id)
        if location is None:
            raise CrudError(CrudErrorCode.NOT_FOUND, "location not found")
        return location

    async def create(self, session: AsyncSession, payload: LocationCreate) -> Location:
        location = Location(**payload.model_dump())
        session.add(location)
        await session.flush()
        return location

    async def update(self, session: AsyncSession, location: Location, payload: LocationUpdate) -> Location:
        apply_updates(location, payload.model_dump(exclude_unset=True))
        await session.flush()
        return location

    async def delete(self, session: AsyncSession, location: Location) -> None:
        await session.delete(location)
        await session.flush()


def get_locations_service() -> LocationsService:
    return LocationsService()


LocationsServiceDep = Annotated[LocationsService, Depends(get_locations_service)]


@router.get("", response_model=list[LocationRead])
async def list_locations(
    session: SessionDep,
    service: LocationsServiceDep,
    page: Annotated[PageParams, Depends()],
) -> list[LocationRead]:
    locations = await service.list(session, limit=page.limit, offset=page.offset)
    return [LocationRead.model_validate(location) for location in locations]


@router.post("", response_model=LocationRead, status_code=201)
async def create_location(
    payload: LocationCreate,
    session: SessionDep,
    service: LocationsServiceDep,
    actor: ActorDep,
) -> LocationRead:
    try:
        location = await service.create(session, payload)
        await audited_mutation(
            session,
            actor,
            action="location.create",
            entity_type="location",
            entity_id=str(location.id),
            before=None,
            after=snapshot(location, LOCATION_FIELDS),
        )
        await commit_or_422(session)
    except CrudError as exc:
        raise translate_crud_error(exc) from exc
    return LocationRead.model_validate(location)


@router.get("/{location_id}", response_model=LocationRead)
async def get_location(
    location_id: UUID,
    session: SessionDep,
    service: LocationsServiceDep,
) -> LocationRead:
    try:
        return LocationRead.model_validate(await service.get(session, location_id))
    except CrudError as exc:
        raise translate_crud_error(exc) from exc


@router.patch("/{location_id}", response_model=LocationRead)
async def update_location(
    location_id: UUID,
    payload: LocationUpdate,
    session: SessionDep,
    service: LocationsServiceDep,
    actor: ActorDep,
) -> LocationRead:
    try:
        location = await service.get(session, location_id)
        before = snapshot(location, LOCATION_FIELDS)
        location = await service.update(session, location, payload)
        await audited_mutation(
            session,
            actor,
            action="location.update",
            entity_type="location",
            entity_id=str(location.id),
            before=before,
            after=snapshot(location, LOCATION_FIELDS),
        )
        await commit_or_422(session)
    except CrudError as exc:
        raise translate_crud_error(exc) from exc
    return LocationRead.model_validate(location)


@router.delete("/{location_id}", status_code=204)
async def delete_location(
    location_id: UUID,
    session: SessionDep,
    service: LocationsServiceDep,
    actor: ActorDep,
) -> None:
    try:
        location = await service.get(session, location_id)
        before = snapshot(location, LOCATION_FIELDS)
        await service.delete(session, location)
        await audited_mutation(
            session,
            actor,
            action="location.delete",
            entity_type="location",
            entity_id=str(location_id),
            before=before,
            after=None,
        )
        await commit_or_422(session)
    except CrudError as exc:
        raise translate_crud_error(exc) from exc
