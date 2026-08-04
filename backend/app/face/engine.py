import os

import numpy as np

from backend.app.face.align import align_face
from backend.app.face.detect import SCRFDDetector
from backend.app.face.embed import ArcFaceEmbedder
from backend.app.face.liveness import MiniFASNetLiveness
from backend.app.face.protocol import Bbox, Detection, Embedding, Landmarks, LivenessResult


class ONNXFaceEngine:
    """Production FaceEngine implementation running raw ONNX models via onnxruntime."""

    def __init__(
        self,
        *,
        model_dir: str = "models",
        liveness_threshold: float = 0.75,
        det_size: int = 384,
        det_score_min: float = 0.60,
    ) -> None:
        self.detector = SCRFDDetector(os.path.join(model_dir, "det_10g.onnx"), det_size=det_size)
        self.embedder = ArcFaceEmbedder(os.path.join(model_dir, "w600k_r50.onnx"))
        self.liveness_detector = MiniFASNetLiveness(
            os.path.join(model_dir, "2.7_80x80_MiniFASNetV2.onnx"),
            os.path.join(model_dir, "4_0_0_80x80_MiniFASNetV1SE.onnx"),
            threshold=liveness_threshold,
        )
        self._model_version = "buffalo_l"
        self.det_score_min = det_score_min

        # Startup assertion: Warm-up session and verify correct index mappings
        dummy_img = np.zeros((80, 80, 3), dtype=np.uint8)
        dummy_bbox = (0, 0, 80, 80)
        res = self.liveness_detector.check_liveness(dummy_img, dummy_bbox)
        assert len(res.per_model) == 2, (
            "Startup check: MiniFASNet liveness ensemble models loaded incorrectly."
        )
        assert isinstance(res.live_score, float), "Startup check: liveness score must be a float."
        assert isinstance(res.passed, bool), (
            "Startup check: liveness passed status must be a boolean."
        )

    def detect(self, bgr: np.ndarray) -> list[Detection]:
        return self.detector.detect(bgr, det_thresh=self.det_score_min)

    def align(self, bgr: np.ndarray, lm: Landmarks) -> np.ndarray:
        return align_face(bgr, lm)

    def liveness(self, bgr: np.ndarray, bbox: Bbox) -> LivenessResult:
        return self.liveness_detector.check_liveness(bgr, bbox)

    def embed(self, aligned: np.ndarray) -> Embedding:
        return self.embedder.embed(aligned)

    @property
    def model_version(self) -> str:
        return self._model_version
