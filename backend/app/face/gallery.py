from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import Enum
from threading import RLock
from time import perf_counter
from uuid import UUID

import numpy as np
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models.settings import SettingsVersion
from backend.app.settings.registry import default_settings

EMBEDDING_DIMENSIONS = 512
GALLERY_VERSION_NAMESPACE = "gallery"


class MatchDecision(str, Enum):
    ACCEPT = "accept"
    AMBIGUOUS = "ambiguous"
    LOW_CONFIDENCE = "low_confidence"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class GalleryEntry:
    person_id: UUID
    embedding_id: UUID
    vector: np.ndarray


@dataclass(frozen=True)
class MatchThresholds:
    match_threshold: float
    match_margin: float
    low_confidence_threshold: float

    @classmethod
    def from_settings(cls, settings: dict[str, object] | None = None) -> MatchThresholds:
        values = default_settings() if settings is None else settings
        return cls(
            match_threshold=_float_setting(values, "face.match_threshold"),
            match_margin=_float_setting(values, "face.match_margin"),
            low_confidence_threshold=_float_setting(values, "face.low_confidence_threshold"),
        )


@dataclass(frozen=True)
class MatchCandidate:
    person_id: UUID
    embedding_id: UUID
    score: float


@dataclass(frozen=True)
class MatchResult:
    decision: MatchDecision
    candidates: tuple[MatchCandidate, ...]
    top1: MatchCandidate | None
    top2_other_person: MatchCandidate | None
    margin: float | None


@dataclass(frozen=True)
class GalleryStats:
    size: int
    dimensions: int
    version: int
    loaded_version: int
    load_seconds: float


class GalleryVersionState:
    """Process-local version contract for gallery consistency.

    Correctness must come from a monotonic durable gallery version. Pub/sub can
    wake other workers quickly, but workers still compare their loaded index
    version against the required version and reload/poll when they lag.
    """

    def __init__(self) -> None:
        self._lock = RLock()
        self._required_version = 1
        self._loaded_version = 0

    @property
    def required_version(self) -> int:
        with self._lock:
            return self._required_version

    @property
    def loaded_version(self) -> int:
        with self._lock:
            return self._loaded_version

    def bump_required_version(self) -> int:
        with self._lock:
            self._required_version += 1
            return self._required_version

    def observe_required_version(self, version: int) -> int:
        if version < 1:
            raise ValueError("gallery version must be positive")
        with self._lock:
            self._required_version = max(self._required_version, version)
            return self._required_version

    def mark_loaded(self, version: int | None = None) -> int:
        with self._lock:
            target_version = self._required_version if version is None else version
            self._loaded_version = max(self._loaded_version, target_version)
            return self._loaded_version

    def is_diverged(self) -> bool:
        return self.loaded_version < self.required_version

    def health(self) -> dict[str, object]:
        return {
            "gallery_version": self.required_version,
            "index_loaded_version": self.loaded_version,
            "gallery_diverged": self.is_diverged(),
        }


DEFAULT_GALLERY_STATE = GalleryVersionState()
GalleryEntryLoader = Callable[[], Awaitable[list[GalleryEntry]]]


class GalleryIndex:
    """Exact in-memory NumPy gallery for encrypted face embeddings."""

    def __init__(self, *, version_state: GalleryVersionState | None = None) -> None:
        self._lock = RLock()
        self._version_state = version_state or DEFAULT_GALLERY_STATE
        self._vectors = np.empty((0, EMBEDDING_DIMENSIONS), dtype=np.float32)
        self._person_ids: tuple[UUID, ...] = ()
        self._embedding_ids: tuple[UUID, ...] = ()
        self._version = 0
        self._load_seconds = 0.0

    @property
    def version(self) -> int:
        with self._lock:
            return self._version

    def load(self, entries: list[GalleryEntry], *, version: int | None = None) -> GalleryStats:
        started_at = perf_counter()
        vectors = np.empty((len(entries), EMBEDDING_DIMENSIONS), dtype=np.float32)
        person_ids: list[UUID] = []
        embedding_ids: list[UUID] = []
        for index, entry in enumerate(entries):
            vectors[index] = normalized_embedding(entry.vector)
            person_ids.append(entry.person_id)
            embedding_ids.append(entry.embedding_id)
        loaded_version = self._version_state.mark_loaded(version)
        with self._lock:
            self._vectors = vectors
            self._person_ids = tuple(person_ids)
            self._embedding_ids = tuple(embedding_ids)
            self._version = loaded_version
            self._load_seconds = perf_counter() - started_at
            return self.stats()

    def add(self, entry: GalleryEntry) -> int:
        vector = normalized_embedding(entry.vector).reshape(1, EMBEDDING_DIMENSIONS)
        with self._lock:
            self._vectors = np.concatenate([self._vectors, vector], axis=0)
            self._person_ids = (*self._person_ids, entry.person_id)
            self._embedding_ids = (*self._embedding_ids, entry.embedding_id)
            self._version = self._version_state.bump_required_version()
            self._version_state.mark_loaded(self._version)
            return self._version

    def remove_embedding(self, embedding_id: UUID) -> bool:
        with self._lock:
            matches = [index for index, existing in enumerate(self._embedding_ids) if existing == embedding_id]
            if not matches:
                return False
            keep_mask = np.ones(len(self._embedding_ids), dtype=bool)
            keep_mask[matches[0]] = False
            self._vectors = self._vectors[keep_mask]
            self._person_ids = tuple(person_id for index, person_id in enumerate(self._person_ids) if keep_mask[index])
            self._embedding_ids = tuple(
                existing for index, existing in enumerate(self._embedding_ids) if keep_mask[index]
            )
            self._version = self._version_state.bump_required_version()
            self._version_state.mark_loaded(self._version)
            return True

    def top_k(self, query: np.ndarray, *, k: int = 5) -> tuple[MatchCandidate, ...]:
        if k < 1:
            raise ValueError("k must be positive")
        query_vector = normalized_embedding(query)
        with self._lock:
            if len(self._embedding_ids) == 0:
                return ()
            scores = self._vectors @ query_vector
            count = min(k, len(scores))
            top_indexes = np.argpartition(scores, -count)[-count:]
            ordered_indexes = top_indexes[np.argsort(scores[top_indexes])[::-1]]
            return tuple(
                MatchCandidate(
                    person_id=self._person_ids[index],
                    embedding_id=self._embedding_ids[index],
                    score=float(scores[index]),
                )
                for index in ordered_indexes
            )

    def match(
        self,
        query: np.ndarray,
        *,
        thresholds: MatchThresholds | None = None,
        k: int = 5,
    ) -> MatchResult:
        candidates, top1, top2_other = self._ranked_candidates_and_nearest_other(query, k=k)
        settings = thresholds or MatchThresholds.from_settings()
        decision = _decision_for(top1, top2_other, settings)
        margin = None if top1 is None or top2_other is None else top1.score - top2_other.score
        return MatchResult(
            decision=decision,
            candidates=candidates,
            top1=top1,
            top2_other_person=top2_other,
            margin=margin,
        )

    async def reload_if_stale(
        self,
        session: AsyncSession,
        load_entries: GalleryEntryLoader,
    ) -> bool:
        required_version = await poll_gallery_version(session, self._version_state)
        if self._version >= required_version:
            return False
        entries = await load_entries()
        self.load(entries, version=required_version)
        return True

    def stats(self) -> GalleryStats:
        with self._lock:
            return GalleryStats(
                size=len(self._embedding_ids),
                dimensions=EMBEDDING_DIMENSIONS,
                version=self._version_state.required_version,
                loaded_version=self._version,
                load_seconds=self._load_seconds,
            )

    def _ranked_candidates_and_nearest_other(
        self,
        query: np.ndarray,
        *,
        k: int,
    ) -> tuple[tuple[MatchCandidate, ...], MatchCandidate | None, MatchCandidate | None]:
        if k < 1:
            raise ValueError("k must be positive")
        query_vector = normalized_embedding(query)
        with self._lock:
            if len(self._embedding_ids) == 0:
                return (), None, None
            scores = self._vectors @ query_vector
            count = min(k, len(scores))
            top_indexes = np.argpartition(scores, -count)[-count:]
            ordered_indexes = top_indexes[np.argsort(scores[top_indexes])[::-1]]
            candidates = tuple(self._candidate_for_index(index, scores) for index in ordered_indexes)
            top1_index = int(np.argmax(scores))
            top1 = self._candidate_for_index(top1_index, scores)
            other_mask = np.array(
                [person_id != top1.person_id for person_id in self._person_ids],
                dtype=bool,
            )
            if not np.any(other_mask):
                return candidates, top1, None
            other_indexes = np.flatnonzero(other_mask)
            nearest_other_index = int(other_indexes[np.argmax(scores[other_indexes])])
            return candidates, top1, self._candidate_for_index(nearest_other_index, scores)

    def _candidate_for_index(self, index: int, scores: np.ndarray) -> MatchCandidate:
        return MatchCandidate(
            person_id=self._person_ids[index],
            embedding_id=self._embedding_ids[index],
            score=float(scores[index]),
        )


def normalized_embedding(vector: np.ndarray) -> np.ndarray:
    if vector.shape != (EMBEDDING_DIMENSIONS,):
        raise ValueError("face embedding must be a 512-d vector")
    coerced = np.ascontiguousarray(vector, dtype=np.float32)
    norm = float(np.linalg.norm(coerced))
    if norm == 0.0:
        raise ValueError("face embedding must not be the zero vector")
    return coerced / norm


def _first_other_person(
    candidates: tuple[MatchCandidate, ...],
    person_id: UUID,
) -> MatchCandidate | None:
    return next((candidate for candidate in candidates if candidate.person_id != person_id), None)


def _decision_for(
    top1: MatchCandidate | None,
    top2_other: MatchCandidate | None,
    thresholds: MatchThresholds,
) -> MatchDecision:
    if top1 is None:
        return MatchDecision.UNKNOWN
    if top1.score >= thresholds.match_threshold:
        if top2_other is None or top1.score - top2_other.score >= thresholds.match_margin:
            return MatchDecision.ACCEPT
        return MatchDecision.AMBIGUOUS
    if top1.score >= thresholds.low_confidence_threshold:
        return MatchDecision.LOW_CONFIDENCE
    return MatchDecision.UNKNOWN


def _float_setting(settings: dict[str, object], key: str) -> float:
    value = settings[key]
    if not isinstance(value, int | float):
        raise TypeError(f"{key} must be numeric")
    return float(value)


async def current_gallery_version(session: AsyncSession) -> int:
    result = await session.execute(
        select(SettingsVersion.current_version).where(
            SettingsVersion.namespace == GALLERY_VERSION_NAMESPACE,
        )
    )
    return result.scalar_one_or_none() or 1


async def bump_gallery_version(session: AsyncSession) -> int:
    result = await session.execute(
        text(
            """
            INSERT INTO settings_versions (namespace, current_version)
            VALUES (:namespace, 2)
            ON CONFLICT (namespace) DO UPDATE
            SET current_version = settings_versions.current_version + 1,
                updated_at = now()
            RETURNING current_version
            """
        ),
        {"namespace": GALLERY_VERSION_NAMESPACE},
    )
    return int(result.scalar_one())


async def poll_gallery_version(
    session: AsyncSession,
    state: GalleryVersionState = DEFAULT_GALLERY_STATE,
) -> int:
    version = await current_gallery_version(session)
    return state.observe_required_version(version)


async def mark_gallery_loaded_from_db(
    session: AsyncSession,
    state: GalleryVersionState = DEFAULT_GALLERY_STATE,
) -> int:
    version = await poll_gallery_version(session, state)
    return state.mark_loaded(version)
