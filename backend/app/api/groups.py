from __future__ import annotations

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
from backend.app.models.people import Group, GroupKind

router = APIRouter(prefix="/api/groups", tags=["groups"])

GROUP_FIELDS = ("id", "parent_group_id", "kind", "name", "code", "is_active")


class GroupCreate(StrictSchema):
    parent_group_id: UUID | None = None
    kind: GroupKind
    name: str
    code: str | None = None
    is_active: bool = True


class GroupUpdate(StrictSchema):
    parent_group_id: UUID | None = None
    kind: GroupKind | None = None
    name: str | None = None
    code: str | None = None
    is_active: bool | None = None


class GroupRead(StrictSchema):
    id: UUID
    parent_group_id: UUID | None
    kind: GroupKind
    name: str
    code: str | None
    is_active: bool


class GroupsService:
    async def list(self, session: AsyncSession, *, limit: int, offset: int) -> list[Group]:
        return list((await session.execute(select(Group).limit(limit).offset(offset))).scalars())

    async def get(self, session: AsyncSession, group_id: UUID) -> Group:
        group = await session.get(Group, group_id)
        if group is None:
            raise CrudError(CrudErrorCode.NOT_FOUND, "group not found")
        return group

    async def create(self, session: AsyncSession, payload: GroupCreate) -> Group:
        group = Group(**payload.model_dump())
        session.add(group)
        await session.flush()
        return group

    async def update(self, session: AsyncSession, group: Group, payload: GroupUpdate) -> Group:
        apply_updates(group, payload.model_dump(exclude_unset=True))
        await session.flush()
        return group

    async def delete(self, session: AsyncSession, group: Group) -> None:
        await session.delete(group)
        await session.flush()


def get_groups_service() -> GroupsService:
    return GroupsService()


GroupsServiceDep = Annotated[GroupsService, Depends(get_groups_service)]


@router.get("", response_model=list[GroupRead])
async def list_groups(
    session: SessionDep,
    service: GroupsServiceDep,
    page: Annotated[PageParams, Depends()],
) -> list[GroupRead]:
    return [GroupRead.model_validate(group) for group in await service.list(session, limit=page.limit, offset=page.offset)]


@router.post("", response_model=GroupRead, status_code=201)
async def create_group(
    payload: GroupCreate,
    session: SessionDep,
    service: GroupsServiceDep,
    actor: ActorDep,
) -> GroupRead:
    try:
        group = await service.create(session, payload)
        await audited_mutation(
            session,
            actor,
            action="group.create",
            entity_type="group",
            entity_id=str(group.id),
            before=None,
            after=snapshot(group, GROUP_FIELDS),
        )
        await commit_or_422(session)
    except CrudError as exc:
        raise translate_crud_error(exc) from exc
    return GroupRead.model_validate(group)


@router.get("/{group_id}", response_model=GroupRead)
async def get_group(group_id: UUID, session: SessionDep, service: GroupsServiceDep) -> GroupRead:
    try:
        return GroupRead.model_validate(await service.get(session, group_id))
    except CrudError as exc:
        raise translate_crud_error(exc) from exc


@router.patch("/{group_id}", response_model=GroupRead)
async def update_group(
    group_id: UUID,
    payload: GroupUpdate,
    session: SessionDep,
    service: GroupsServiceDep,
    actor: ActorDep,
) -> GroupRead:
    try:
        group = await service.get(session, group_id)
        before = snapshot(group, GROUP_FIELDS)
        group = await service.update(session, group, payload)
        await audited_mutation(
            session,
            actor,
            action="group.update",
            entity_type="group",
            entity_id=str(group.id),
            before=before,
            after=snapshot(group, GROUP_FIELDS),
        )
        await commit_or_422(session)
    except CrudError as exc:
        raise translate_crud_error(exc) from exc
    return GroupRead.model_validate(group)


@router.delete("/{group_id}", status_code=204)
async def delete_group(
    group_id: UUID,
    session: SessionDep,
    service: GroupsServiceDep,
    actor: ActorDep,
) -> None:
    try:
        group = await service.get(session, group_id)
        before = snapshot(group, GROUP_FIELDS)
        await service.delete(session, group)
        await audited_mutation(
            session,
            actor,
            action="group.delete",
            entity_type="group",
            entity_id=str(group_id),
            before=before,
            after=None,
        )
        await commit_or_422(session)
    except CrudError as exc:
        raise translate_crud_error(exc) from exc
