import cv2
import numpy as np
from skimage.transform import SimilarityTransform

# Canonical 112x112 reference landmarks for ArcFace
ARC_FACE_REF = np.array(
    [
        [38.2946, 51.6963],  # Left Eye
        [73.5318, 51.5014],  # Right Eye
        [56.0252, 71.7366],  # Nose
        [41.5493, 92.3655],  # Left Mouth Corner
        [70.7299, 92.2041],  # Right Mouth Corner
    ],
    dtype=np.float32,
)


def align_face(bgr: np.ndarray, landmarks: np.ndarray) -> np.ndarray:
    """Align a face image to canonical 112x112 pixels using 5-point landmarks."""
    if landmarks.shape != (5, 2):
        raise ValueError("landmarks must have shape (5, 2)")

    tform = SimilarityTransform.from_estimate(landmarks, ARC_FACE_REF)
    M = tform.params[0:2, :]

    # Warp image to 112x112 using cv2.warpAffine
    warped = cv2.warpAffine(bgr, M, (112, 112), borderValue=0)
    return warped
