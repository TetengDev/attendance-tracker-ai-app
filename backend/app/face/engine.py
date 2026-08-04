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

        # Startup assertion: Warm-up sessions and verify correct index mappings.
        # Use the committed Tester-Zero fixture image for a real classification
        # check when available (asserts Index 1 = Live on a known real face).
        fixture_path = os.path.join("fixtures", "faces", "Lester Bryan Ilao - 1.JPG")
        if os.path.exists(fixture_path):
            import cv2  # local import to avoid hard dep at module level

            fixture_img = cv2.imread(fixture_path)
            if fixture_img is not None:
                dets = self.detector.detect(fixture_img, det_thresh=self.det_score_min)
                assert len(dets) >= 1, "Startup check: no face detected in Tester-Zero fixture."
                res = self.liveness_detector.check_liveness(fixture_img, dets[0].bbox)
                assert res.passed, (
                    f"Startup check: Tester-Zero fixture should be classified as live, "
                    f"but got score={res.live_score:.4f} (threshold={liveness_threshold}). "
                    f"Index 1 mapping may be incorrect."
                )
        else:
            # Fallback: structural warm-up when fixture images are not deployed
            dummy_img = np.zeros((80, 80, 3), dtype=np.uint8)
            dummy_bbox = (0, 0, 80, 80)
            res = self.liveness_detector.check_liveness(dummy_img, dummy_bbox)
            assert len(res.per_model) == 2, (
                "Startup check: MiniFASNet liveness ensemble models loaded incorrectly."
            )
            assert isinstance(res.live_score, float), (
                "Startup check: liveness score must be a float."
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
