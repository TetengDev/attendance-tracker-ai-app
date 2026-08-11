from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Any, Protocol

import numpy as np

Bbox = tuple[int, int, int, int]  # x1, y1, x2, y2
Landmarks = np.ndarray  # (5, 2) float32


@dataclass(frozen=True)
class Detection:
    bbox: Bbox
    det_score: float
    landmarks: Landmarks
    blur_var: float
    brightness: float


@dataclass(frozen=True)
class LivenessResult:
    live_score: float  # combined[1] after summing both softmaxes / 2
    per_model: tuple[float, ...]
    passed: bool  # live_score >= liveness.threshold


@dataclass(frozen=True)
class Embedding:
    vector: np.ndarray  # (512,) float32, L2-normalized
    model_name: str
    model_version: str


class FaceEngine(Protocol):
    """Face engine contract.

    All image boundaries are BGR uint8 HWC. Implementations must not require
    RGB or float input before the model-specific preprocessing step.
    """

    def detect(self, bgr: np.ndarray) -> list[Detection]: ...

    def align(self, bgr: np.ndarray, lm: Landmarks) -> np.ndarray: ...

    def liveness(self, bgr: np.ndarray, bbox: Bbox) -> LivenessResult: ...

    def embed(self, aligned: np.ndarray) -> Embedding: ...

    @property
    def model_name(self) -> str: ...

    @property
    def model_version(self) -> str: ...


@dataclass(frozen=True)
class _FakeResult:
    person: str | None = None
    score: float = 0.9
    liveness: float = 0.95
    n_faces: int = 1
    det_score: float = 0.9


class FakeFaceEngine:
    """Deterministic FaceEngine for fast tests that do not load ONNX models."""

    def __init__(self, *, liveness_threshold: float = 0.75) -> None:
        self._queue: deque[_FakeResult] = deque()
        self._active: _FakeResult | None = None
        self._liveness_threshold = liveness_threshold
        self._model_name = "fake-face-engine"
        self._model_version = "fake-v1"

    def next_result(
        self,
        *,
        person: str | None = None,
        score: float = 0.9,
        liveness: float = 0.95,
        n_faces: int = 1,
        det_score: float = 0.9,
    ) -> None:
        self._queue.append(
            _FakeResult(
                person=person,
                score=float(score),
                liveness=float(liveness),
                n_faces=int(n_faces),
                det_score=float(det_score),
            )
        )

    def queue_results(self, results: list[dict[str, Any]]) -> None:
        for result in results:
            self.next_result(
                person=result.get("person"),
                score=result.get("score", 0.9),
                liveness=result.get("liveness", 0.95),
                n_faces=result.get("n_faces", 1),
                det_score=result.get("det_score", 0.9),
            )

    def reset(self) -> None:
        self._queue.clear()
        self._active = None

    def detect(self, bgr: np.ndarray) -> list[Detection]:
        self._assert_bgr_uint8_hwc(bgr)
        self._active = self._queue.popleft() if self._queue else _FakeResult(n_faces=0)
        if self._active.n_faces <= 0:
            return []

        height, width = bgr.shape[:2]
        detections: list[Detection] = []
        for index in range(self._active.n_faces):
            inset = min(20 + index * 8, max(width, height) // 4)
            x1 = min(inset, max(width - 2, 0))
            y1 = min(inset, max(height - 2, 0))
            x2 = max(x1 + 1, width - inset)
            y2 = max(y1 + 1, height - inset)
            landmarks = np.array(
                [
                    [x1 + (x2 - x1) * 0.30, y1 + (y2 - y1) * 0.35],
                    [x1 + (x2 - x1) * 0.70, y1 + (y2 - y1) * 0.35],
                    [x1 + (x2 - x1) * 0.50, y1 + (y2 - y1) * 0.52],
                    [x1 + (x2 - x1) * 0.35, y1 + (y2 - y1) * 0.72],
                    [x1 + (x2 - x1) * 0.65, y1 + (y2 - y1) * 0.72],
                ],
                dtype=np.float32,
            )
            detections.append(
                Detection(
                    bbox=(x1, y1, x2, y2),
                    det_score=self._active.det_score,
                    landmarks=landmarks,
                    blur_var=100.0,
                    brightness=128.0,
                )
            )
        return detections

    def align(self, bgr: np.ndarray, lm: Landmarks) -> np.ndarray:
        self._assert_bgr_uint8_hwc(bgr)
        if lm.shape != (5, 2):
            raise ValueError("landmarks must have shape (5, 2)")

        seed = self._seed_for_active_person()
        rng = np.random.default_rng(seed)
        return rng.integers(0, 256, size=(112, 112, 3), dtype=np.uint8)

    def liveness(self, bgr: np.ndarray, bbox: Bbox) -> LivenessResult:
        self._assert_bgr_uint8_hwc(bgr)
        if len(bbox) != 4:
            raise ValueError("bbox must contain x1, y1, x2, y2")

        live_score = self._active.liveness if self._active is not None else 0.95
        return LivenessResult(
            live_score=float(live_score),
            per_model=(float(live_score), float(live_score)),
            passed=bool(live_score >= self._liveness_threshold),
        )

    def embed(self, aligned: np.ndarray) -> Embedding:
        self._assert_bgr_uint8_hwc(aligned)
        seed = self._seed_for_active_person()
        rng = np.random.default_rng(seed)
        vector = rng.standard_normal(512).astype(np.float32)
        vector /= np.linalg.norm(vector)
        return Embedding(vector=vector, model_name=self._model_name, model_version=self._model_version)

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def model_version(self) -> str:
        return self._model_version

    def _seed_for_active_person(self) -> int:
        person = self._active.person if self._active is not None else None
        if person is None:
            return 0
        return sum((index + 1) * ord(char) for index, char in enumerate(person))

    @staticmethod
    def _assert_bgr_uint8_hwc(image: np.ndarray) -> None:
        if image.dtype != np.uint8 or image.ndim != 3 or image.shape[2] != 3:
            raise ValueError("image must be BGR uint8 HWC")
