from __future__ import annotations

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
    translate_crud_error,
)
from backend.app.people.merge import PersonMergeError, PersonMergeSummary, merge_duplicate_person

router = APIRouter(prefix="/api/people", tags=["people"])


class PersonMergeCreate(StrictSchema):
    duplicate_person_id: UUID


class PersonMergeRead(StrictSchema):
    survivor_id: UUID
    duplicate_id: UUID
    consents_moved: int
    enrollment_assets_moved: int
    embeddings_moved: int
    embeddings_deactivated: int
    group_memberships_moved: int
    guardian_links_moved: int
    duplicate_guardian_links_removed: int
    gallery_version: int


class PeopleMergeService:
    async def merge(
        self,
        session: AsyncSession,
        *,
        survivor_id: UUID,
        duplicate_id: UUID,
    ) -> PersonMergeSummary:
        return await merge_duplicate_person(
            session,
            survivor_id=survivor_id,
            duplicate_id=duplicate_id,
        )


def get_people_merge_service() -> PeopleMergeService:
    return PeopleMergeService()


PeopleMergeServiceDep = Annotated[PeopleMergeService, Depends(get_people_merge_service)]


@router.post("/{survivor_id}/merge", response_model=PersonMergeRead)
async def merge_person(
    survivor_id: UUID,
    payload: PersonMergeCreate,
    session: SessionDep,
    service: PeopleMergeServiceDep,
    admin_user: AdminUserDep,
    actor: ActorDep,
) -> PersonMergeRead:
    try:
        require_org_admin(admin_user)
        summary = await service.merge(
            session,
            survivor_id=survivor_id,
            duplicate_id=payload.duplicate_person_id,
        )
        actor = RequestActor(admin_user.id, actor.request_id, actor.ip_address)
        await audited_mutation(
            session,
            actor,
            action="person.merge",
            entity_type="person",
            entity_id=str(survivor_id),
            before={"duplicate_id": str(payload.duplicate_person_id)},
            after={
                "survivor_id": str(summary.survivor_id),
                "duplicate_id": str(summary.duplicate_id),
                "gallery_version": summary.gallery_version,
            },
        )
        await commit_or_422(session)
    except PersonMergeError as exc:
        raise translate_crud_error(CrudError(CrudErrorCode.INVALID_INPUT, str(exc))) from exc
    except CrudError as exc:
        raise translate_crud_error(exc) from exc
    return PersonMergeRead.model_validate(summary)
