from __future__ import annotations

from typing import Any, cast
from uuid import UUID

import numpy as np
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.face.gallery import (
    GALLERY_VERSION_NAMESPACE,
    GalleryEntry,
    GalleryIndex,
    GalleryVersionState,
    MatchDecision,
    MatchThresholds,
    bump_gallery_version,
    current_gallery_version,
    normalized_embedding,
)
from backend.tests.factories.embeddings import embedding_with_cosine, seeded_unit_embedding

PERSON_A = UUID("00000000-0000-0000-0000-000000000031")
PERSON_B = UUID("00000000-0000-0000-0000-000000000032")
EMBEDDING_A = UUID("10000000-0000-0000-0000-000000000031")
EMBEDDING_B = UUID("10000000-0000-0000-0000-000000000032")


def test_gallery_index_returns_exact_top_k_matches() -> None:
    alice = seeded_unit_embedding(1)
    bob = seeded_unit_embedding(2)
    index = GalleryIndex(version_state=GalleryVersionState())
    index.load(
        [
            GalleryEntry(PERSON_A, EMBEDDING_A, alice),
            GalleryEntry(PERSON_B, EMBEDDING_B, bob),
        ],
    )

    result = index.top_k(alice, k=2)

    assert result[0].person_id == PERSON_A
    assert result[0].embedding_id == EMBEDDING_A
    assert result[0].score == pytest.approx(1.0, abs=1e-6)
    assert len(result) == 2


def test_match_decision_accepts_only_when_margin_passes() -> None:
    pair = embedding_with_cosine(10, 0.96)
    index = GalleryIndex(version_state=GalleryVersionState())
    index.load(
        [
            GalleryEntry(PERSON_A, EMBEDDING_A, pair.left),
            GalleryEntry(PERSON_B, EMBEDDING_B, pair.right),
        ],
    )
    strict_margin = MatchThresholds(
        match_threshold=0.45,
        match_margin=0.10,
        low_confidence_threshold=0.38,
    )

    result = index.match(pair.left, thresholds=strict_margin)

    assert result.decision == MatchDecision.AMBIGUOUS
    assert result.top1 is not None
    assert result.top2_other_person is not None
    assert result.margin == pytest.approx(0.04, abs=0.005)


def test_match_decision_searches_nearest_other_beyond_returned_top_k() -> None:
    pair = embedding_with_cosine(11, 0.97)
    entries = [
        GalleryEntry(PERSON_A, UUID(f"10000000-0000-0000-0000-00000000000{index}"), pair.left)
        for index in range(1, 6)
    ]
    entries.append(GalleryEntry(PERSON_B, EMBEDDING_B, pair.right))
    index = GalleryIndex(version_state=GalleryVersionState())
    index.load(entries)

    result = index.match(
        pair.left,
        thresholds=MatchThresholds(
            match_threshold=0.45,
            match_margin=0.05,
            low_confidence_threshold=0.38,
        ),
        k=5,
    )

    assert len(result.candidates) == 5
    assert {candidate.person_id for candidate in result.candidates} == {PERSON_A}
    assert result.top2_other_person is not None
    assert result.top2_other_person.person_id == PERSON_B
    assert result.decision == MatchDecision.AMBIGUOUS


def test_match_decision_uses_low_confidence_and_unknown_bands() -> None:
    pair = embedding_with_cosine(20, 0.40)
    index = GalleryIndex(version_state=GalleryVersionState())
    index.load([GalleryEntry(PERSON_A, EMBEDDING_A, pair.left)])
    thresholds = MatchThresholds(
        match_threshold=0.45,
        match_margin=0.05,
        low_confidence_threshold=0.38,
    )

    assert index.match(pair.right, thresholds=thresholds).decision == MatchDecision.LOW_CONFIDENCE
    assert index.match(-pair.left, thresholds=thresholds).decision == MatchDecision.UNKNOWN


def test_gallery_mutations_update_loaded_version_and_delete_immediately() -> None:
    state = GalleryVersionState()
    index = GalleryIndex(version_state=state)
    index.load([])
    version_after_add = index.add(GalleryEntry(PERSON_A, EMBEDDING_A, seeded_unit_embedding(1)))

    assert version_after_add == state.loaded_version
    assert not state.is_diverged()
    assert index.top_k(seeded_unit_embedding(1))[0].embedding_id == EMBEDDING_A

    assert index.remove_embedding(EMBEDDING_A)

    assert index.top_k(seeded_unit_embedding(1)) == ()
    assert not state.is_diverged()


def test_gallery_version_state_reports_divergence_until_loaded() -> None:
    state = GalleryVersionState()

    required_version = state.bump_required_version()

    assert state.health() == {
        "gallery_version": required_version,
        "index_loaded_version": 0,
        "gallery_diverged": True,
    }

    state.mark_loaded(required_version)

    assert state.health()["gallery_diverged"] is False


@pytest.mark.anyio
async def test_durable_gallery_version_helpers_use_settings_version_namespace() -> None:
    session = FakeVersionSession(read_version=7, bumped_version=8)

    current = await current_gallery_version(cast(AsyncSession, session))
    bumped = await bump_gallery_version(cast(AsyncSession, session))

    assert current == 7
    assert bumped == 8
    assert session.namespaces == [GALLERY_VERSION_NAMESPACE, GALLERY_VERSION_NAMESPACE]
    assert "ON CONFLICT" in session.statements[1]


@pytest.mark.anyio
async def test_gallery_reload_if_stale_polls_durable_version() -> None:
    state = GalleryVersionState()
    index = GalleryIndex(version_state=state)
    session = FakeVersionSession(read_version=3, bumped_version=4)

    async def load_entries() -> list[GalleryEntry]:
        return [GalleryEntry(PERSON_A, EMBEDDING_A, seeded_unit_embedding(1))]

    reloaded = await index.reload_if_stale(cast(AsyncSession, session), load_entries)

    assert reloaded
    assert index.version == 3
    assert not state.is_diverged()
    assert index.top_k(seeded_unit_embedding(1))[0].person_id == PERSON_A


def test_normalized_embedding_rejects_invalid_vectors() -> None:
    with pytest.raises(ValueError, match="512-d"):
        normalized_embedding(np.zeros(511, dtype=np.float32))

    with pytest.raises(ValueError, match="zero vector"):
        normalized_embedding(np.zeros(512, dtype=np.float32))


class FakeResult:
    def __init__(self, value: int | None) -> None:
        self._value = value

    def scalar_one_or_none(self) -> int | None:
        return self._value

    def scalar_one(self) -> int:
        if self._value is None:
            raise AssertionError("expected scalar value")
        return self._value


class FakeVersionSession:
    def __init__(self, *, read_version: int | None, bumped_version: int) -> None:
        self._read_version = read_version
        self._bumped_version = bumped_version
        self.statements: list[str] = []
        self.namespaces: list[str] = []

    async def execute(self, statement: Any, params: dict[str, object] | None = None) -> FakeResult:
        self.statements.append(str(statement))
        if params is not None:
            self.namespaces.append(str(params["namespace"]))
            return FakeResult(self._bumped_version)
        self.namespaces.append(GALLERY_VERSION_NAMESPACE)
        return FakeResult(self._read_version)
