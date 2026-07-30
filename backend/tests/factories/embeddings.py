from __future__ import annotations

from dataclasses import dataclass

import numpy as np

EMBEDDING_DIM = 512


@dataclass(frozen=True)
class EmbeddingPair:
    left: np.ndarray
    right: np.ndarray
    target_cosine: float

    @property
    def actual_cosine(self) -> float:
        return float(np.dot(self.left, self.right))


def seeded_unit_embedding(seed: int, *, dim: int = EMBEDDING_DIM) -> np.ndarray:
    rng = np.random.default_rng(seed)
    vector = rng.standard_normal(dim).astype(np.float32)
    return _normalize(vector)


def embedding_with_cosine(seed: int, cosine: float, *, dim: int = EMBEDDING_DIM) -> EmbeddingPair:
    if cosine < -1.0 or cosine > 1.0:
        raise ValueError("cosine must be between -1.0 and 1.0")

    left = seeded_unit_embedding(seed, dim=dim)
    rng = np.random.default_rng(seed + 1)
    candidate = rng.standard_normal(dim).astype(np.float32)
    orthogonal = candidate - np.dot(candidate, left) * left
    orthogonal = _normalize(orthogonal)

    right = cosine * left + np.sqrt(max(0.0, 1.0 - cosine * cosine)) * orthogonal
    right = _normalize(right.astype(np.float32))
    return EmbeddingPair(left=left, right=right, target_cosine=cosine)


def _normalize(vector: np.ndarray) -> np.ndarray:
    norm = np.linalg.norm(vector)
    if norm == 0:
        raise ValueError("cannot normalize a zero vector")
    normalized: np.ndarray = (vector / norm).astype(np.float32)
    return normalized
