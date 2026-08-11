"""Unified image decoding for both enrollment and scan paths.

Every image entering the face pipeline — whether uploaded for enrollment or
captured by a kiosk camera — must go through this single decode function so
that EXIF orientation, colour-space conversion, and array layout are
identical.  Using two different decoders (PIL vs OpenCV) was the root cause
of enrollment → scan recognition failures (TEN-223 / RC-2).
"""

from io import BytesIO

import cv2
import numpy as np
from PIL import Image, ImageOps, UnidentifiedImageError


def decode_image_to_bgr(payload: bytes) -> np.ndarray:
    """Decode raw image bytes to a BGR uint8 HWC ndarray.

    Handles EXIF orientation transparently so that phone-camera portrait
    images are correctly rotated before any face-engine processing.

    Raises ``ValueError`` when the payload is not a decodable image.
    """
    try:
        with Image.open(BytesIO(payload)) as image:
            # Apply EXIF orientation BEFORE converting pixel data.
            # Without this, portrait phone photos are processed sideways
            # and produce unusable face embeddings.
            image_t = ImageOps.exif_transpose(image)
            rgb = np.asarray(image_t.convert("RGB"), dtype=np.uint8)
    except (UnidentifiedImageError, OSError, SyntaxError) as exc:
        raise ValueError("image payload could not be decoded") from exc
    return np.ascontiguousarray(rgb[:, :, ::-1])


def decode_jpeg_to_bgr(jpeg_bytes: bytes) -> np.ndarray:
    """Fast JPEG-only decode via OpenCV, used for kiosk scan frames.

    Kiosk frames are always raw JPEG from ``<canvas>.toBlob()`` and never
    carry EXIF orientation metadata (the browser already renders them
    correctly), so the lighter OpenCV path is safe here.

    Raises ``ValueError`` on decode failure.
    """
    buf = np.frombuffer(jpeg_bytes, dtype=np.uint8)
    img = cv2.imdecode(buf, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("failed to decode JPEG frame")
    return img
