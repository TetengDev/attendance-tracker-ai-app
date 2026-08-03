from __future__ import annotations

from uuid import UUID

import numpy as np
import pytest

from backend.app.face.gallery import (
    GalleryEntry,
    GalleryIndex,
    GalleryVersionState,
    MatchDecision,
    MatchThresholds,
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


def test_normalized_embedding_rejects_invalid_vectors() -> None:
    with pytest.raises(ValueError, match="512-d"):
        normalized_embedding(np.zeros(511, dtype=np.float32))

    with pytest.raises(ValueError, match="zero vector"):
        normalized_embedding(np.zeros(512, dtype=np.float32))
