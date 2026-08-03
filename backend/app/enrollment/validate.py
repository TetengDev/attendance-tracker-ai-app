from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum

import numpy as np

from backend.app.face.protocol import Detection, FaceEngine
from backend.app.settings.registry import SETTINGS_SCHEMA

MAX_ABS_YAW = 0.55


class EnrollmentRejectionCode(str, Enum):
    NO_FACE = "no_face"
    MULTIPLE_FACES = "multiple_faces"
    LOW_DETECTION_SCORE = "low_detection_score"
    FACE_TOO_SMALL = "face_too_small"
    MOTION_BLUR = "motion_blur"
    UNDER_EXPOSED = "under_exposed"
    OVER_EXPOSED = "over_exposed"
    EXTREME_POSE = "extreme_pose"


@dataclass(frozen=True)
class EnrollmentRejection:
    code: EnrollmentRejectionCode
    message: str


@dataclass(frozen=True)
class EnrollmentQuality:
    score: float
    det_score: float
    bbox_area_pct: float
    interocular_px: float
    sharpness: float
    brightness: float
    yaw: float


@dataclass(frozen=True)
class EnrollmentValidationResult:
    passed: bool
    quality: EnrollmentQuality | None
    rejection: EnrollmentRejection | None
    detection: Detection | None


REJECTION_MESSAGES: Mapping[EnrollmentRejectionCode, str] = {
    EnrollmentRejectionCode.NO_FACE: "No face was detected. Please center one face in the frame.",
    EnrollmentRejectionCode.MULTIPLE_FACES: "Multiple faces were detected. Please enroll one person at a time.",
    EnrollmentRejectionCode.LOW_DETECTION_SCORE: "The face detection confidence is too low. Please retake the image.",
    EnrollmentRejectionCode.FACE_TOO_SMALL: "The face is too small. Please move closer to the camera.",
    EnrollmentRejectionCode.MOTION_BLUR: "The image is too blurry. Please hold still and retake it.",
    EnrollmentRejectionCode.UNDER_EXPOSED: "The image is too dark. Please add more light and retake it.",
    EnrollmentRejectionCode.OVER_EXPOSED: "The image is too bright. Please reduce glare and retake it.",
    EnrollmentRejectionCode.EXTREME_POSE: "The face angle is too steep. Please face the camera more directly.",
}


def validate_enrollment_image(
    bgr: np.ndarray,
    face_engine: FaceEngine,
    *,
    settings: Mapping[str, object] | None = None,
) -> EnrollmentValidationResult:
    """Validate one candidate enrollment image before it is committed.

    The validator intentionally depends only on the shared ``FaceEngine`` protocol
    and NumPy image statistics, which keeps tests deterministic and avoids storing
    real face fixtures in the repository.
    """

    _assert_bgr_uint8_hwc(bgr)
    effective_settings = settings or {}
    detections = face_engine.detect(bgr)

    if not detections:
        return _rejected(EnrollmentRejectionCode.NO_FACE)
    if len(detections) > 1:
        return _rejected(EnrollmentRejectionCode.MULTIPLE_FACES)

    detection = detections[0]
    metrics = _quality_metrics(bgr, detection)
    thresholds = _thresholds(effective_settings)

    if metrics.det_score < thresholds.det_score_min:
        return _rejected(EnrollmentRejectionCode.LOW_DETECTION_SCORE, detection=detection)
    if (
        metrics.bbox_area_pct < thresholds.min_bbox_area_pct
        or metrics.interocular_px < thresholds.min_interocular_px
    ):
        return _rejected(EnrollmentRejectionCode.FACE_TOO_SMALL, detection=detection)
    if metrics.sharpness < thresholds.min_sharpness:
        return _rejected(EnrollmentRejectionCode.MOTION_BLUR, detection=detection)
    if metrics.brightness < thresholds.luma_min:
        return _rejected(EnrollmentRejectionCode.UNDER_EXPOSED, detection=detection)
    if metrics.brightness > thresholds.luma_max:
        return _rejected(EnrollmentRejectionCode.OVER_EXPOSED, detection=detection)
    if abs(metrics.yaw) > MAX_ABS_YAW:
        return _rejected(EnrollmentRejectionCode.EXTREME_POSE, detection=detection)

    quality = EnrollmentQuality(
        score=_quality_score(metrics, thresholds),
        det_score=metrics.det_score,
        bbox_area_pct=metrics.bbox_area_pct,
        interocular_px=metrics.interocular_px,
        sharpness=metrics.sharpness,
        brightness=metrics.brightness,
        yaw=metrics.yaw,
    )
    return EnrollmentValidationResult(
        passed=True,
        quality=quality,
        rejection=None,
        detection=detection,
    )


def estimate_yaw_from_landmarks(landmarks: np.ndarray) -> float:
    """Estimate coarse yaw from five-point landmarks.

    The result is a normalized eye-to-nose asymmetry value. Positive values mean
    the nose is shifted toward the right eye in image coordinates; negative values
    mean it is shifted toward the left eye.
    """

    if landmarks.shape != (5, 2):
        raise ValueError("landmarks must have shape (5, 2)")

    left_eye = landmarks[0]
    right_eye = landmarks[1]
    nose = landmarks[2]
    eye_mid_x = float((left_eye[0] + right_eye[0]) / 2.0)
    half_eye_distance = max(abs(float(right_eye[0] - left_eye[0])) / 2.0, 1.0)
    yaw = (float(nose[0]) - eye_mid_x) / half_eye_distance
    return float(np.clip(yaw, -1.0, 1.0))


def variance_of_laplacian(bgr: np.ndarray, bbox: tuple[int, int, int, int] | None = None) -> float:
    """Return a lightweight variance-of-Laplacian sharpness score."""

    _assert_bgr_uint8_hwc(bgr)
    crop = _crop(bgr, bbox) if bbox is not None else bgr
    if crop.shape[0] < 3 or crop.shape[1] < 3:
        return 0.0

    gray = (
        crop[:, :, 0].astype(np.float32) * 0.114
        + crop[:, :, 1].astype(np.float32) * 0.587
        + crop[:, :, 2].astype(np.float32) * 0.299
    )
    center = gray[1:-1, 1:-1]
    laplacian = (
        gray[:-2, 1:-1]
        + gray[2:, 1:-1]
        + gray[1:-1, :-2]
        + gray[1:-1, 2:]
        - (4.0 * center)
    )
    return float(np.var(laplacian))


@dataclass(frozen=True)
class _QualityMetrics:
    det_score: float
    bbox_area_pct: float
    interocular_px: float
    sharpness: float
    brightness: float
    yaw: float


@dataclass(frozen=True)
class _Thresholds:
    det_score_min: float
    min_bbox_area_pct: float
    min_interocular_px: float
    min_sharpness: float
    luma_min: float
    luma_max: float


def _quality_metrics(bgr: np.ndarray, detection: Detection) -> _QualityMetrics:
    height, width = bgr.shape[:2]
    bbox_width = max(0, detection.bbox[2] - detection.bbox[0])
    bbox_height = max(0, detection.bbox[3] - detection.bbox[1])
    image_area = max(width * height, 1)
    bbox_area_pct = (bbox_width * bbox_height / image_area) * 100.0
    interocular_px = float(np.linalg.norm(detection.landmarks[1] - detection.landmarks[0]))
    crop = _crop(bgr, detection.bbox)

    return _QualityMetrics(
        det_score=float(detection.det_score),
        bbox_area_pct=float(bbox_area_pct),
        interocular_px=interocular_px,
        sharpness=variance_of_laplacian(bgr, detection.bbox),
        brightness=_mean_luma(crop),
        yaw=estimate_yaw_from_landmarks(detection.landmarks),
    )


def _thresholds(settings: Mapping[str, object]) -> _Thresholds:
    return _Thresholds(
        det_score_min=_float_setting(settings, "face.det_score_min"),
        min_bbox_area_pct=_float_setting(settings, "kiosk.gate.min_bbox_area_pct"),
        min_interocular_px=_float_setting(settings, "kiosk.gate.min_interocular_px"),
        min_sharpness=_float_setting(settings, "kiosk.gate.min_sharpness"),
        luma_min=_float_setting(settings, "kiosk.gate.luma_min"),
        luma_max=_float_setting(settings, "kiosk.gate.luma_max"),
    )


def _quality_score(metrics: _QualityMetrics, thresholds: _Thresholds) -> float:
    exposure_midpoint = (thresholds.luma_min + thresholds.luma_max) / 2.0
    exposure_half_range = max((thresholds.luma_max - thresholds.luma_min) / 2.0, 1.0)
    exposure_score = 1.0 - min(abs(metrics.brightness - exposure_midpoint) / exposure_half_range, 1.0)
    component_scores = (
        _ratio_score(metrics.det_score, thresholds.det_score_min),
        _ratio_score(metrics.bbox_area_pct, thresholds.min_bbox_area_pct),
        _ratio_score(metrics.interocular_px, thresholds.min_interocular_px),
        _ratio_score(metrics.sharpness, thresholds.min_sharpness),
        max(0.0, 1.0 - (abs(metrics.yaw) / MAX_ABS_YAW)),
        exposure_score,
    )
    return round(float(sum(component_scores) / len(component_scores)), 4)


def _ratio_score(value: float, floor: float) -> float:
    if floor <= 0:
        return 1.0
    return float(np.clip(value / floor, 0.0, 1.0))


def _float_setting(settings: Mapping[str, object], key: str) -> float:
    value = settings.get(key, SETTINGS_SCHEMA[key].default)
    if isinstance(value, bool):
        raise TypeError(f"{key} must be numeric")
    if not isinstance(value, int | float | str):
        raise TypeError(f"{key} must be numeric")
    return float(value)


def _mean_luma(bgr: np.ndarray) -> float:
    if bgr.size == 0:
        return 0.0
    luma = (
        bgr[:, :, 0].astype(np.float32) * 0.114
        + bgr[:, :, 1].astype(np.float32) * 0.587
        + bgr[:, :, 2].astype(np.float32) * 0.299
    )
    return float(np.mean(luma))


def _crop(bgr: np.ndarray, bbox: tuple[int, int, int, int]) -> np.ndarray:
    height, width = bgr.shape[:2]
    x1 = int(np.clip(bbox[0], 0, width))
    y1 = int(np.clip(bbox[1], 0, height))
    x2 = int(np.clip(bbox[2], x1, width))
    y2 = int(np.clip(bbox[3], y1, height))
    return bgr[y1:y2, x1:x2]


def _rejected(
    code: EnrollmentRejectionCode,
    *,
    detection: Detection | None = None,
) -> EnrollmentValidationResult:
    return EnrollmentValidationResult(
        passed=False,
        quality=None,
        rejection=EnrollmentRejection(code=code, message=REJECTION_MESSAGES[code]),
        detection=detection,
    )


def _assert_bgr_uint8_hwc(image: np.ndarray) -> None:
    if image.dtype != np.uint8 or image.ndim != 3 or image.shape[2] != 3:
        raise ValueError("image must be BGR uint8 HWC")
