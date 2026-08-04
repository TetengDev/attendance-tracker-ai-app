from __future__ import annotations

from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import Select
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
    snapshot,
    translate_crud_error,
)
from backend.app.auth.rbac import scoped_people_query
from backend.app.models.admin import AdminUser
from backend.app.models.people import Person, PersonKind

router = APIRouter(prefix="/api/people", tags=["people"])
BusinessDateQuery = Annotated[date, Query(default_factory=date.today)]

PERSON_FIELDS = (
    "id",
    "external_id",
    "kind",
    "display_name",
    "preferred_name",
    "locale",
    "is_active",
)


class PersonCreate(StrictSchema):
    external_id: str | None = None
    kind: PersonKind
    display_name: str
    preferred_name: str | None = None
    locale: str = "en"
    is_active: bool = True


class PersonUpdate(StrictSchema):
    external_id: str | None = None
    kind: PersonKind | None = None
    display_name: str | None = None
    preferred_name: str | None = None
    locale: str | None = None
    is_active: bool | None = None


class PersonRead(StrictSchema):
    id: UUID
    external_id: str | None
    kind: PersonKind
    display_name: str
    preferred_name: str | None
    locale: str
    is_active: bool


class PeopleService:
    async def list(
        self,
        session: AsyncSession,
        admin_user: AdminUser,
        *,
        business_date: date,
        limit: int,
        offset: int,
    ) -> list[Person]:
        query = (
            scoped_people_query(admin_user, business_date=business_date).limit(limit).offset(offset)
        )
        return list((await session.execute(query)).scalars())

    async def get(
        self,
        session: AsyncSession,
        admin_user: AdminUser,
        person_id: UUID,
        *,
        business_date: date,
    ) -> Person:
        query: Select[tuple[Person]] = scoped_people_query(
            admin_user, business_date=business_date
        ).where(Person.id == person_id)
        person = (await session.execute(query)).scalar_one_or_none()
        if person is None:
            raise CrudError(CrudErrorCode.NOT_FOUND, "person not found")
        return person

    async def create(self, session: AsyncSession, payload: PersonCreate) -> Person:
        person = Person(**payload.model_dump())
        session.add(person)
        await session.flush()
        return person

    async def update(self, session: AsyncSession, person: Person, payload: PersonUpdate) -> Person:
        apply_updates(person, payload.model_dump(exclude_unset=True))
        await session.flush()
        return person

    async def delete(self, session: AsyncSession, person: Person) -> None:
        await session.delete(person)
        await session.flush()


def get_people_service() -> PeopleService:
    return PeopleService()


PeopleServiceDep = Annotated[PeopleService, Depends(get_people_service)]


@router.get("", response_model=list[PersonRead])
async def list_people(
    session: SessionDep,
    service: PeopleServiceDep,
    admin_user: AdminUserDep,
    page: Annotated[PageParams, Depends()],
    business_date: BusinessDateQuery,
) -> list[PersonRead]:
    people = await service.list(
        session,
        admin_user,
        business_date=business_date,
        limit=page.limit,
        offset=page.offset,
    )
    return [PersonRead.model_validate(person) for person in people]


@router.post("", response_model=PersonRead, status_code=201)
async def create_person(
    payload: PersonCreate,
    session: SessionDep,
    service: PeopleServiceDep,
    admin_user: AdminUserDep,
    actor: ActorDep,
) -> PersonRead:
    try:
        person = await service.create(session, payload)
        actor = RequestActor(admin_user.id, actor.request_id, actor.ip_address)
        await audited_mutation(
            session,
            actor,
            action="person.create",
            entity_type="person",
            entity_id=str(person.id),
            before=None,
            after=snapshot(person, PERSON_FIELDS),
        )
        await commit_or_422(session)
    except CrudError as exc:
        raise translate_crud_error(exc) from exc
    return PersonRead.model_validate(person)


@router.get("/{person_id}", response_model=PersonRead)
async def get_person(
    person_id: UUID,
    session: SessionDep,
    service: PeopleServiceDep,
    admin_user: AdminUserDep,
    business_date: BusinessDateQuery,
) -> PersonRead:
    try:
        person = await service.get(session, admin_user, person_id, business_date=business_date)
    except CrudError as exc:
        raise translate_crud_error(exc) from exc
    return PersonRead.model_validate(person)


@router.patch("/{person_id}", response_model=PersonRead)
async def update_person(
    person_id: UUID,
    payload: PersonUpdate,
    session: SessionDep,
    service: PeopleServiceDep,
    admin_user: AdminUserDep,
    actor: ActorDep,
    business_date: BusinessDateQuery,
) -> PersonRead:
    try:
        person = await service.get(session, admin_user, person_id, business_date=business_date)
        before = snapshot(person, PERSON_FIELDS)
        person = await service.update(session, person, payload)
        actor = RequestActor(admin_user.id, actor.request_id, actor.ip_address)
        await audited_mutation(
            session,
            actor,
            action="person.update",
            entity_type="person",
            entity_id=str(person.id),
            before=before,
            after=snapshot(person, PERSON_FIELDS),
        )
        await commit_or_422(session)
    except CrudError as exc:
        raise translate_crud_error(exc) from exc
    return PersonRead.model_validate(person)


@router.delete("/{person_id}", status_code=204)
async def delete_person(
    person_id: UUID,
    session: SessionDep,
    service: PeopleServiceDep,
    admin_user: AdminUserDep,
    actor: ActorDep,
    business_date: BusinessDateQuery,
) -> None:
    try:
        person = await service.get(session, admin_user, person_id, business_date=business_date)
        before = snapshot(person, PERSON_FIELDS)
        await service.delete(session, person)
        actor = RequestActor(admin_user.id, actor.request_id, actor.ip_address)
        await audited_mutation(
            session,
            actor,
            action="person.delete",
            entity_type="person",
            entity_id=str(person_id),
            before=before,
            after=None,
        )
        await commit_or_422(session)
    except CrudError as exc:
        raise translate_crud_error(exc) from exc
