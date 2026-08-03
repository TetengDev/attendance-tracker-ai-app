from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest

from backend.app.face.gallery import GalleryEntry, GalleryIndex, MatchDecision
from backend.app.models.attendance import (
    AttendanceEvent,
    AttendanceEventDirection,
    AttendanceEventOutcome,
    AttendanceLocationSource,
)
from backend.app.models.people import Person, PersonKind
from backend.app.people.merge import (
    PersonMergeError,
    attendance_totals_by_canonical_person,
    canonical_person_id,
    canonicalize_gallery_entries,
    mark_person_merged,
)
from backend.tests.factories.embeddings import embedding_with_cosine

SURVIVOR_ID = UUID("00000000-0000-0000-0000-000000000090")
DUPLICATE_ID = UUID("00000000-0000-0000-0000-000000000091")
OTHER_ID = UUID("00000000-0000-0000-0000-000000000092")
EMBEDDING_A = UUID("10000000-0000-0000-0000-000000000090")
EMBEDDING_B = UUID("10000000-0000-0000-0000-000000000091")
MERGED_AT = datetime(2026, 8, 3, 13, 5, tzinfo=UTC)
CAPTURED_AT = datetime(2026, 8, 3, 8, 0, tzinfo=UTC)


def test_mark_person_merged_sets_pointer_timestamp_and_inactive_flag() -> None:
    survivor = person(SURVIVOR_ID)
    duplicate = person(DUPLICATE_ID)

    mark_person_merged(survivor, duplicate, merged_at=MERGED_AT)

    assert duplicate.merged_into_person_id == SURVIVOR_ID
    assert duplicate.merged_at == MERGED_AT
    assert duplicate.is_active is False


def test_mark_person_merged_rejects_self_and_chained_merges() -> None:
    survivor = person(SURVIVOR_ID)

    with pytest.raises(PersonMergeError, match="different people"):
        mark_person_merged(survivor, survivor, merged_at=MERGED_AT)

    merged_survivor = person(SURVIVOR_ID, merged_into=OTHER_ID)
    duplicate = person(DUPLICATE_ID)

    with pytest.raises(PersonMergeError, match="survivor is already merged"):
        mark_person_merged(merged_survivor, duplicate, merged_at=MERGED_AT)


def test_canonical_person_id_resolves_aliases_and_rejects_cycles() -> None:
    assert canonical_person_id(DUPLICATE_ID, {DUPLICATE_ID: SURVIVOR_ID}) == SURVIVOR_ID

    with pytest.raises(PersonMergeError, match="cycle"):
        canonical_person_id(SURVIVOR_ID, {SURVIVOR_ID: DUPLICATE_ID, DUPLICATE_ID: SURVIVOR_ID})


def test_gallery_entries_canonicalize_duplicate_embeddings_to_survivor() -> None:
    pair = embedding_with_cosine(90, 0.96)
    entries = canonicalize_gallery_entries(
        [
            GalleryEntry(SURVIVOR_ID, EMBEDDING_A, pair.left),
            GalleryEntry(DUPLICATE_ID, EMBEDDING_B, pair.right),
        ],
        {DUPLICATE_ID: SURVIVOR_ID},
    )
    index = GalleryIndex()
    index.load(entries)

    result = index.match(pair.left)

    assert {entry.person_id for entry in entries} == {SURVIVOR_ID}
    assert result.decision == MatchDecision.ACCEPT
    assert result.top1 is not None
    assert result.top1.person_id == SURVIVOR_ID
    assert result.top2_other_person is None


def test_attendance_totals_resolve_to_survivor_without_double_counting_events() -> None:
    first = attendance_event(1, SURVIVOR_ID)
    second = attendance_event(2, DUPLICATE_ID)

    totals = attendance_totals_by_canonical_person(
        [first, second, second],
        {DUPLICATE_ID: SURVIVOR_ID},
    )

    assert len(totals) == 1
    assert totals[0].person_id == SURVIVOR_ID
    assert totals[0].event_count == 2


def person(
    person_id: UUID,
    *,
    merged_into: UUID | None = None,
) -> Person:
    return Person(
        id=person_id,
        external_id=None,
        kind=PersonKind.STUDENT,
        display_name=f"Person {person_id}",
        preferred_name=None,
        merged_into_person_id=merged_into,
        locale="en",
        is_active=True,
    )


def attendance_event(event_id: int, person_id: UUID) -> AttendanceEvent:
    return AttendanceEvent(
        id=event_id,
        idempotency_key=f"event-{event_id}",
        person_id=person_id,
        direction=AttendanceEventDirection.IN,
        outcome=AttendanceEventOutcome.ACCEPTED,
        location_source=AttendanceLocationSource.DEVICE_FIXED,
        business_date=CAPTURED_AT.date(),
        device_local_date=CAPTURED_AT.date(),
        client_captured_at=CAPTURED_AT,
        server_received_at=CAPTURED_AT,
        occurred_at=CAPTURED_AT,
        monotonic_offset_ms=0,
        was_backdated=False,
        event_metadata={},
    )
