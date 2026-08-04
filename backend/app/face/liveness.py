import cv2
import numpy as np
import onnxruntime  # type: ignore[import-untyped]

from backend.app.face.protocol import Bbox, LivenessResult


def softmax(x: np.ndarray) -> np.ndarray:
    e_x = np.exp(x - np.max(x, axis=-1, keepdims=True))
    return e_x / np.sum(e_x, axis=-1, keepdims=True)  # type: ignore[no-any-return]


def crop_with_padding(img: np.ndarray, bbox: Bbox, scale: float) -> np.ndarray:
    """Crop face box with padding to prevent clamping of the scale factor."""
    x1, y1, x2, y2 = bbox
    box_w = x2 - x1
    box_h = y2 - y1

    new_width = round(box_w * scale)
    new_height = round(box_h * scale)
    center_x = round(x1 + box_w / 2.0)
    center_y = round(y1 + box_h / 2.0)

    left_top_x = center_x - new_width // 2
    left_top_y = center_y - new_height // 2
    right_bottom_x = left_top_x + new_width
    right_bottom_y = left_top_y + new_height

    pad_left = max(0, -left_top_x)
    pad_top = max(0, -left_top_y)
    pad_right = max(0, right_bottom_x - img.shape[1])
    pad_bottom = max(0, right_bottom_y - img.shape[0])

    x1_pad = left_top_x + pad_left
    y1_pad = left_top_y + pad_top
    x2_pad = right_bottom_x + pad_left
    y2_pad = right_bottom_y + pad_top

    padded = cv2.copyMakeBorder(
        img, pad_top, pad_bottom, pad_left, pad_right, cv2.BORDER_CONSTANT, value=[0, 0, 0]
    )
    crop = padded[y1_pad:y2_pad, x1_pad:x2_pad]
    return crop


def get_new_box_clamped(
    src_w: int, src_h: int, bbox: Bbox, scale: float
) -> tuple[int, int, int, int]:
    """Calculate clamped crop coordinates, matching the original training repository's behavior."""
    x1, y1, x2, y2 = bbox
    box_w = x2 - x1
    box_h = y2 - y1
    scale = min((src_h - 1) / box_h, min((src_w - 1) / box_w, scale))
    new_width = box_w * scale
    new_height = box_h * scale
    center_x, center_y = box_w / 2.0 + x1, box_h / 2.0 + y1
    left_top_x = int(center_x - new_width / 2.0)
    left_top_y = int(center_y - new_height / 2.0)
    right_bottom_x = int(center_x + new_width / 2.0)
    right_bottom_y = int(center_y + new_height / 2.0)

    if left_top_x < 0:
        right_bottom_x -= left_top_x
        left_top_x = 0
    if left_top_y < 0:
        right_bottom_y -= left_top_y
        left_top_y = 0
    if right_bottom_x > src_w - 1:
        left_top_x -= right_bottom_x - src_w + 1
        right_bottom_x = src_w - 1
    if right_bottom_y > src_h - 1:
        left_top_y -= right_bottom_y - src_h + 1
        right_bottom_y = src_h - 1
    return left_top_x, left_top_y, right_bottom_x, right_bottom_y


class MiniFASNetLiveness:
    def __init__(self, model_path_v2: str, model_path_v1se: str, threshold: float = 0.75) -> None:
        self.sess_v2 = onnxruntime.InferenceSession(model_path_v2)
        self.sess_v1se = onnxruntime.InferenceSession(model_path_v1se)
        self.threshold = threshold

    def check_liveness(self, bgr: np.ndarray, bbox: Bbox) -> LivenessResult:
        """Evaluate passive liveness from image crop using MiniFASNet v2 and v1se models."""
        src_h, src_w, _ = bgr.shape

        # 1. Process V2 Model (Scale 2.7 with padding)
        crop_27 = crop_with_padding(bgr, bbox, 2.7)
        resized_27 = cv2.resize(crop_27, (80, 80))
        # NOTE: No division by 255.0 here. The Silent-Face-Anti-Spoofing training
        # repository uses a custom ToTensor that comments out .div(255). These
        # specific model weights expect float32 in [0, 255]. Dividing by 255
        # drops real-face scores from 0.983 → 0.007, causing false positives.
        # See: https://github.com/minivision-ai/Silent-Face-Anti-Spoofing
        blob_27 = resized_27.astype(np.float32)
        blob_27 = np.transpose(blob_27, (2, 0, 1))
        blob_27 = np.expand_dims(blob_27, axis=0)

        # 2. Process V1SE Model (Scale 4.0 with clamping)
        x1_40, y1_40, x2_40, y2_40 = get_new_box_clamped(src_w, src_h, bbox, 4.0)
        crop_40 = bgr[y1_40 : y2_40 + 1, x1_40 : x2_40 + 1]
        resized_40 = cv2.resize(crop_40, (80, 80))
        blob_40 = resized_40.astype(np.float32)
        blob_40 = np.transpose(blob_40, (2, 0, 1))
        blob_40 = np.expand_dims(blob_40, axis=0)

        # Run inference
        outputs_v2 = self.sess_v2.run(None, {self.sess_v2.get_inputs()[0].name: blob_27})
        outputs_v1se = self.sess_v1se.run(None, {self.sess_v1se.get_inputs()[0].name: blob_40})

        # Apply Softmax to raw logits
        prob_v2 = softmax(outputs_v2[0])[0]  # Shape (3,)
        prob_v1se = softmax(outputs_v1se[0])[0]  # Shape (3,)

        # Combine probabilities: sum then divide by 2
        combined = (prob_v2 + prob_v1se) / 2.0
        live_score = float(combined[1])  # Index 1 is live

        passed = live_score >= self.threshold
        return LivenessResult(
            live_score=live_score, per_model=(float(prob_v2[1]), float(prob_v1se[1])), passed=passed
        )
