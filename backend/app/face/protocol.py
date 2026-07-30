from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Tuple, List, Optional, Deque
import numpy as np
from collections import deque
import hashlib

Bbox = Tuple[int, int, int, int]  # x1, y1, x2, y2
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
    live_score: float
    per_model: Tuple[float, ...]
    passed: bool

@dataclass(frozen=True)
class Embedding:
    vector: np.ndarray  # (512,) float32, L2-normalized
    model_name: str
    model_version: str


class FaceEngine(Protocol):
    """Protocol representing the face engine contract used by the app.

    Implementations must accept BGR uint8 HWC images at every boundary.
    """

    def detect(self, bgr: np.ndarray) -> List[Detection]: ...

    def align(self, bgr: np.ndarray, lm: Landmarks) -> np.ndarray: ...  # -> (112,112,3) BGR

    def liveness(self, bgr: np.ndarray, bbox: Bbox) -> LivenessResult: ...

    def embed(self, aligned: np.ndarray) -> Embedding: ...

    @property
    def model_version(self) -> str: ...


class FakeFaceEngine(FaceEngine):
    """A deterministic, test-friendly fake FaceEngine used in unit tests.

    Usage patterns (supported):
    - next_result(person=str|None, score=float, liveness=float, n_faces=int)
      queues a single synthetic detection result that subsequent detect() calls will return.
    - queue_results(results: list[dict]) queues multiple results.
    - reset() clears queued results.

    Each queued result is a dict with optional keys: person (str|None), score (float),
    liveness (float), n_faces (int), det_score (float).
    """

    def __init__(self) -> None:
        self._q: Deque[dict] = deque()
        self._default_model_name = "fake-resnet"
        self._default_model_version = "0.0.0"

    def next_result(self, *, person: Optional[str] = None, score: float = 0.9,
                    liveness: float = 0.95, n_faces: int = 1,
                    det_score: float = 0.9) -> None:
        self._q.append({
            "person": person,
            "score": float(score),
            "liveness": float(liveness),
            "n_faces": int(n_faces),
            "det_score": float(det_score),
        })

    def queue_results(self, results: List[dict]) -> None:
        for r in results:
            # shallow validation
            r2 = dict(r)
            r2.setdefault("person", None)
            r2.setdefault("score", 0.9)
            r2.setdefault("liveness", 0.95)
            r2.setdefault("n_faces", 1)
            r2.setdefault("det_score", 0.9)
            self._q.append(r2)

    def reset(self) -> None:
        self._q.clear()

    # Protocol methods
    def detect(self, bgr: np.ndarray) -> List[Detection]:
        """Return a list of synthetic detections. If the queue is empty, returns []."""
        if not self._q:
            return []
        item = self._q.popleft()
        n = int(item.get("n_faces", 1))
        detections: List[Detection] = []
        h, w = bgr.shape[0], bgr.shape[1]
        for i in range(n):
            # make a simple centered bbox scaled by i
            pad = 20 + i * 5
            x1 = pad
            y1 = pad
            x2 = max(1, w - pad)
            y2 = max(1, h - pad)
            lm = np.zeros((5, 2), dtype=np.float32)
            det = Detection(
                bbox=(x1, y1, x2, y2),
                det_score=float(item.get("det_score", 0.9)),
                landmarks=lm,
                blur_var=100.0,
                brightness=128.0,
            )
            detections.append(det)
        return detections

    def align(self, bgr: np.ndarray, lm: Landmarks) -> np.ndarray:
        # Return a deterministic zeroed 112x112x3 uint8 crop to satisfy downstream callers
        return np.zeros((112, 112, 3), dtype=np.uint8)

    def liveness(self, bgr: np.ndarray, bbox: Bbox) -> LivenessResult:
        # If a queued item is available, use its liveness; otherwise default to 0.95
        # (Note: detect() already pops one queued item. This function is allowed to be
        #  called independently in tests, so peek if queue has items.)
        l = 0.95
        if self._q:
            # peek without consuming fully
            itm = self._q[0]
            l = float(itm.get("liveness", 0.95))
        passed = bool(l >= 0.5)
        return LivenessResult(live_score=float(l), per_model=(float(l),), passed=passed)

    def embed(self, aligned: np.ndarray) -> Embedding:
        # Produce a deterministic embedding by hashing the aligned image contents.
        # If the buffer is constant (zeros), fallback to a fixed pseudorandom vector.
        raw = aligned.tobytes()
        h = hashlib.sha256(raw).digest()
        seed = int.from_bytes(h[:8], "big")
        rng = np.random.default_rng(seed)
        vec = rng.standard_normal(512).astype(np.float32)
        # L2-normalize
        norm = np.linalg.norm(vec)
        if norm == 0:
            vec[0] = 1.0
            norm = np.linalg.norm(vec)
        vec = vec / norm
        return Embedding(vector=vec, model_name=self._default_model_name,
                         model_version=self._default_model_version)

    @property
    def model_version(self) -> str:
        return self._default_model_version
