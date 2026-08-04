import cv2
import numpy as np
import onnxruntime  # type: ignore[import-untyped]

from backend.app.face.protocol import Embedding


class ArcFaceEmbedder:
    def __init__(self, model_path: str) -> None:
        self.session = onnxruntime.InferenceSession(model_path)
        self.input_name = self.session.get_inputs()[0].name
        self.output_name = self.session.get_outputs()[0].name
        self._model_name = "w600k_r50"
        self._model_version = "buffalo_l"

    def embed(self, aligned: np.ndarray) -> Embedding:
        """Extract a 512-dimensional L2-normalized embedding from an aligned 112x112 image."""
        if aligned.shape != (112, 112, 3):
            raise ValueError("aligned image must be 112x112x3")
        if aligned.dtype != np.uint8:
            raise ValueError("aligned image must be uint8")

        # Preprocess: BGR to RGB, normalize (pixel - 127.5) / 127.5
        # We can also do (pixel - 127.5) / 128.0. InsightFace standard is / 127.5.
        # Let's use 127.5 as standard.
        img = cv2.cvtColor(aligned, cv2.COLOR_BGR2RGB)
        blob = (img.astype(np.float32) - 127.5) / 127.5
        blob = np.transpose(blob, (2, 0, 1))
        blob = np.expand_dims(blob, axis=0)

        # Run inference
        outputs = self.session.run([self.output_name], {self.input_name: blob})
        vector = outputs[0][0]  # shape (512,)

        # L2-normalize
        norm = np.linalg.norm(vector)
        if norm > 0:
            vector = vector / norm

        return Embedding(
            vector=vector.astype(np.float32),
            model_name=self._model_name,
            model_version=self._model_version,
        )
