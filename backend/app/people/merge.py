from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import Select, delete, exists, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from backend.app.face.gallery import GalleryEntry
from backend.app.models.attendance import AttendanceEvent
from backend.app.models.biometrics import Consent, EnrollmentAsset, FaceEmbedding
from backend.app.models.people import Person, PersonGroup, PersonGuardian


class PersonMergeError(ValueError):
    """Raised when a duplicate identity merge cannot be performed safely."""


@dataclass(frozen=True)
class PersonMergeSummary:
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


@dataclass(frozen=True)
class CanonicalAttendanceTotal:
    person_id: UUID
    event_count: int


async def merge_duplicate_person(
    session: AsyncSession,
    *,
    survivor_id: UUID,
    duplicate_id: UUID,
) -> PersonMergeSummary:
    """Merge one duplicate person into the survivor while preserving event immutability."""

    if survivor_id == duplicate_id:
        raise PersonMergeError("survivor and duplicate must be different people")

    survivor = await _locked_person(session, survivor_id)
    duplicate = await _locked_person(session, duplicate_id)
    if survivor is None:
        raise PersonMergeError("survivor person not found")
    if duplicate is None:
        raise PersonMergeError("duplicate person not found")
    if survivor.merged_into_person_id is not None:
        raise PersonMergeError("survivor is already merged into another person")
    if duplicate.merged_into_person_id is not None:
        raise PersonMergeError("duplicate is already merged into another person")

    embeddings_deactivated = await _deactivate_conflicting_active_embeddings(
        session,
        survivor_id=survivor_id,
        duplicate_id=duplicate_id,
    )
    guardian_links_removed = await _dedupe_guardian_links(
        session,
        survivor_id=survivor_id,
        duplicate_id=duplicate_id,
    )
    consents_moved = await _move_consents(
        session,
        survivor_id=survivor_id,
        duplicate_id=duplicate_id,
    )
    group_memberships_moved = await _move_group_memberships(
        session,
        survivor_id=survivor_id,
        duplicate_id=duplicate_id,
    )
    enrollment_assets_moved = await _move_rows(
        session,
        EnrollmentAsset,
        survivor_id=survivor_id,
        duplicate_id=duplicate_id,
    )
    embeddings_moved = await _move_rows(
        session,
        FaceEmbedding,
        survivor_id=survivor_id,
        duplicate_id=duplicate_id,
    )
    guardian_links_moved = await _move_rows(
        session,
        PersonGuardian,
        survivor_id=survivor_id,
        duplicate_id=duplicate_id,
    )

    mark_person_merged(survivor, duplicate, merged_at=datetime.now(UTC))
    gallery_version = await _bump_gallery_version(session)
    await session.flush()

    return PersonMergeSummary(
        survivor_id=survivor_id,
        duplicate_id=duplicate_id,
        consents_moved=consents_moved,
        enrollment_assets_moved=enrollment_assets_moved,
        embeddings_moved=embeddings_moved,
        embeddings_deactivated=embeddings_deactivated,
        group_memberships_moved=group_memberships_moved,
        guardian_links_moved=guardian_links_moved,
        duplicate_guardian_links_removed=guardian_links_removed,
        gallery_version=gallery_version,
    )


def mark_person_merged(survivor: Person, duplicate: Person, *, merged_at: datetime) -> None:
    if survivor.id == duplicate.id:
        raise PersonMergeError("survivor and duplicate must be different people")
    if survivor.merged_into_person_id is not None:
        raise PersonMergeError("survivor is already merged into another person")
    if duplicate.merged_into_person_id is not None:
        raise PersonMergeError("duplicate is already merged into another person")

    duplicate.merged_into_person_id = survivor.id
    duplicate.merged_at = merged_at
    duplicate.is_active = False


def canonical_person_id(person_id: UUID | None, merged_into: Mapping[UUID, UUID]) -> UUID | None:
    if person_id is None:
        return None

    seen: set[UUID] = set()
    current = person_id
    while current in merged_into:
        if current in seen:
            raise PersonMergeError("cycle detected in person merge map")
        seen.add(current)
        current = merged_into[current]
    return current


def canonicalize_gallery_entries(
    entries: Iterable[GalleryEntry],
    merged_into: Mapping[UUID, UUID],
) -> list[GalleryEntry]:
    return [
        GalleryEntry(
            person_id=canonical_person_id(entry.person_id, merged_into) or entry.person_id,
            embedding_id=entry.embedding_id,
            vector=entry.vector,
        )
        for entry in entries
    ]


def attendance_totals_by_canonical_person(
    events: Iterable[AttendanceEvent],
    merged_into: Mapping[UUID, UUID],
) -> tuple[CanonicalAttendanceTotal, ...]:
    counts: Counter[UUID] = Counter()
    counted_event_ids: set[int] = set()
    for event in events:
        if event.id in counted_event_ids or event.person_id is None:
            continue
        counted_event_ids.add(event.id)
        person_id = canonical_person_id(event.person_id, merged_into)
        if person_id is not None:
            counts[person_id] += 1
    return tuple(
        CanonicalAttendanceTotal(person_id=person_id, event_count=count)
        for person_id, count in sorted(counts.items(), key=lambda item: str(item[0]))
    )


async def _locked_person(session: AsyncSession, person_id: UUID) -> Person | None:
    query: Select[tuple[Person]] = select(Person).where(Person.id == person_id).with_for_update()
    return (await session.execute(query)).scalar_one_or_none()


async def _deactivate_conflicting_active_embeddings(
    session: AsyncSession,
    *,
    survivor_id: UUID,
    duplicate_id: UUID,
) -> int:
    survivor_embedding = aliased(FaceEmbedding)
    statement = (
        update(FaceEmbedding)
        .where(FaceEmbedding.person_id == duplicate_id)
        .where(FaceEmbedding.is_active)
        .where(
            exists()
            .where(survivor_embedding.person_id == survivor_id)
            .where(survivor_embedding.is_active)
            .where(survivor_embedding.model_name == FaceEmbedding.model_name)
            .where(survivor_embedding.model_version == FaceEmbedding.model_version)
        )
        .values(is_active=False)
    )
    result = await session.execute(statement)
    return _rowcount(result)


async def _dedupe_guardian_links(
    session: AsyncSession,
    *,
    survivor_id: UUID,
    duplicate_id: UUID,
) -> int:
    survivor_guardian_ids = select(PersonGuardian.guardian_id).where(
        PersonGuardian.person_id == survivor_id,
    )
    statement = delete(PersonGuardian).where(
        PersonGuardian.person_id == duplicate_id,
        PersonGuardian.guardian_id.in_(survivor_guardian_ids),
    )
    result = await session.execute(statement)
    return _rowcount(result)


async def _move_consents(
    session: AsyncSession,
    *,
    survivor_id: UUID,
    duplicate_id: UUID,
) -> int:
    survivor_keys = (
        select(Consent.consent_type, Consent.policy_version)
        .where(Consent.person_id == survivor_id)
        .subquery()
    )
    statement = (
        update(Consent)
        .where(Consent.person_id == duplicate_id)
        .where(
            ~exists()
            .where(survivor_keys.c.consent_type == Consent.consent_type)
            .where(survivor_keys.c.policy_version == Consent.policy_version)
        )
        .values(person_id=survivor_id)
    )
    result = await session.execute(statement)
    return _rowcount(result)


async def _move_group_memberships(
    session: AsyncSession,
    *,
    survivor_id: UUID,
    duplicate_id: UUID,
) -> int:
    survivor_keys = (
        select(PersonGroup.group_id, PersonGroup.effective_from)
        .where(PersonGroup.person_id == survivor_id)
        .subquery()
    )
    statement = (
        update(PersonGroup)
        .where(PersonGroup.person_id == duplicate_id)
        .where(
            ~exists()
            .where(survivor_keys.c.group_id == PersonGroup.group_id)
            .where(survivor_keys.c.effective_from == PersonGroup.effective_from)
        )
        .values(person_id=survivor_id)
    )
    result = await session.execute(statement)
    return _rowcount(result)


async def _move_rows(
    session: AsyncSession,
    model: type[EnrollmentAsset | FaceEmbedding | PersonGuardian],
    *,
    survivor_id: UUID,
    duplicate_id: UUID,
) -> int:
    statement = update(model).where(model.person_id == duplicate_id).values(person_id=survivor_id)
    result = await session.execute(statement)
    return _rowcount(result)


async def _bump_gallery_version(session: AsyncSession) -> int:
    from backend.app.face.gallery import bump_gallery_version

    return await bump_gallery_version(session)


def _rowcount(result: object) -> int:
    value = getattr(result, "rowcount", 0)
    if not isinstance(value, int):
        return 0
    return value
