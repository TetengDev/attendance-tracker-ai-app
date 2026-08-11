from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest

from backend.app.enrollment.validate import (
    EnrollmentRejectionCode,
    EnrollmentValidationResult,
    estimate_yaw_from_landmarks,
    validate_enrollment_image,
    variance_of_laplacian,
)
from backend.app.face.protocol import Detection, Embedding, LivenessResult


class StaticFaceEngine:
    def __init__(self, detections: list[Detection]) -> None:
        self._detections = detections

    def detect(self, bgr: np.ndarray) -> list[Detection]:
        return self._detections

    def align(self, bgr: np.ndarray, lm: np.ndarray) -> np.ndarray:
        return np.zeros((112, 112, 3), dtype=np.uint8)

    def liveness(self, bgr: np.ndarray, bbox: tuple[int, int, int, int]) -> LivenessResult:
        return LivenessResult(live_score=1.0, per_model=(1.0,), passed=True)

    def embed(self, aligned: np.ndarray) -> Embedding:
        vector = np.zeros(512, dtype=np.float32)
        vector[0] = 1.0
        return Embedding(vector=vector, model_name="static", model_version="static-v1")

    @property
    def model_name(self) -> str:
        return "static"

    @property
    def model_version(self) -> str:
        return "static-v1"


def test_good_frontal_image_passes_with_quality_score() -> None:
    result = validate_enrollment_image(sharp_face_image(), StaticFaceEngine([good_detection()]))

    assert result.passed
    assert result.rejection is None
    assert result.quality is not None
    assert result.quality.score > 0.8
    assert result.quality.yaw == pytest.approx(0.0)


def test_no_face_rejected() -> None:
    result = validate_enrollment_image(sharp_face_image(), StaticFaceEngine([]))

    assert_rejection(result, EnrollmentRejectionCode.NO_FACE)


def test_multiple_faces_rejected() -> None:
    detection = good_detection()

    result = validate_enrollment_image(sharp_face_image(), StaticFaceEngine([detection, detection]))

    assert_rejection(result, EnrollmentRejectionCode.MULTIPLE_FACES)


def test_low_detection_score_rejected() -> None:
    detection = replace(good_detection(), det_score=0.40)

    result = validate_enrollment_image(sharp_face_image(), StaticFaceEngine([detection]))

    assert_rejection(result, EnrollmentRejectionCode.LOW_DETECTION_SCORE)


def test_face_too_small_rejected_by_bbox_area() -> None:
    detection = replace(
        good_detection(),
        bbox=(120, 80, 170, 140),
        landmarks=landmarks(left_eye=(132, 100), right_eye=(158, 100), nose=(145, 116)),
    )

    result = validate_enrollment_image(sharp_face_image(), StaticFaceEngine([detection]))

    assert_rejection(result, EnrollmentRejectionCode.FACE_TOO_SMALL)


def test_face_too_small_rejected_by_interocular_distance() -> None:
    detection = replace(
        good_detection(),
        landmarks=landmarks(left_eye=(145, 100), right_eye=(175, 100), nose=(160, 120)),
    )

    result = validate_enrollment_image(sharp_face_image(), StaticFaceEngine([detection]))

    assert_rejection(result, EnrollmentRejectionCode.FACE_TOO_SMALL)


def test_deliberately_blurred_copy_rejected() -> None:
    sharp = sharp_face_image()
    blurred = box_blur(sharp, passes=8)

    assert variance_of_laplacian(sharp, good_detection().bbox) > 60.0
    assert variance_of_laplacian(blurred, good_detection().bbox) < 60.0

    result = validate_enrollment_image(blurred, StaticFaceEngine([good_detection()]))

    assert_rejection(result, EnrollmentRejectionCode.MOTION_BLUR)


def test_under_exposed_image_rejected() -> None:
    result = validate_enrollment_image(
        sharp_face_image(dark=True),
        StaticFaceEngine([good_detection()]),
    )

    assert_rejection(result, EnrollmentRejectionCode.UNDER_EXPOSED)


def test_over_exposed_image_rejected() -> None:
    result = validate_enrollment_image(
        sharp_face_image(bright=True),
        StaticFaceEngine([good_detection()]),
    )

    assert_rejection(result, EnrollmentRejectionCode.OVER_EXPOSED)


def test_extreme_pose_rejected_and_yaw_is_coarse_eye_to_nose_asymmetry() -> None:
    detection = replace(
        good_detection(),
        landmarks=landmarks(left_eye=(110, 100), right_eye=(210, 100), nose=(205, 125)),
    )

    result = validate_enrollment_image(sharp_face_image(), StaticFaceEngine([detection]))

    assert estimate_yaw_from_landmarks(detection.landmarks) == pytest.approx(0.9)
    assert_rejection(result, EnrollmentRejectionCode.EXTREME_POSE)


def test_invalid_image_shape_rejected_before_detection() -> None:
    with pytest.raises(ValueError, match="BGR uint8 HWC"):
        validate_enrollment_image(np.zeros((100, 100), dtype=np.uint8), StaticFaceEngine([]))


def assert_rejection(result: EnrollmentValidationResult, code: EnrollmentRejectionCode) -> None:
    assert result.passed is False
    assert result.quality is None
    assert result.rejection is not None
    assert result.rejection.code == code
    assert result.rejection.message


def good_detection() -> Detection:
    return Detection(
        bbox=(70, 30, 250, 230),
        det_score=0.92,
        landmarks=landmarks(left_eye=(110, 100), right_eye=(210, 100), nose=(160, 125)),
        blur_var=100.0,
        brightness=128.0,
    )


def landmarks(
    *,
    left_eye: tuple[int, int],
    right_eye: tuple[int, int],
    nose: tuple[int, int],
) -> np.ndarray:
    return np.array(
        [
            left_eye,
            right_eye,
            nose,
            (125, 175),
            (195, 175),
        ],
        dtype=np.float32,
    )


def sharp_face_image(
    *,
    dark: bool = False,
    bright: bool = False,
    width: int = 320,
    height: int = 260,
) -> np.ndarray:
    if dark:
        base, stripe = 20, 35
    elif bright:
        base, stripe = 235, 250
    else:
        base, stripe = 96, 176

    image = np.full((height, width, 3), base, dtype=np.uint8)
    bbox = good_detection().bbox
    for x in range(bbox[0], bbox[2], 8):
        image[bbox[1] : bbox[3], x : x + 4, :] = stripe
    image[90:170, 130:190, :] = 128 if not dark and not bright else base
    return image


def box_blur(image: np.ndarray, *, passes: int) -> np.ndarray:
    blurred = image.astype(np.float32)
    for _ in range(passes):
        padded = np.pad(blurred, ((1, 1), (1, 1), (0, 0)), mode="edge")
        blurred = (
            padded[:-2, :-2]
            + padded[:-2, 1:-1]
            + padded[:-2, 2:]
            + padded[1:-1, :-2]
            + padded[1:-1, 1:-1]
            + padded[1:-1, 2:]
            + padded[2:, :-2]
            + padded[2:, 1:-1]
            + padded[2:, 2:]
        ) / 9.0
    return np.clip(blurred, 0, 255).astype(np.uint8)
