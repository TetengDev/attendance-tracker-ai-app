#!/usr/bin/env python3
"""CLI utility to check the liveness of a face in a single image.

Usage:
    uv run python scripts/liveness_check.py --image path/to/image.jpg
"""

from __future__ import annotations

import argparse
import os
import sys

import cv2

from backend.app.face.engine import ONNXFaceEngine


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify face liveness on a single image.")
    parser.add_argument(
        "--image",
        type=str,
        required=True,
        help="Path to the face image file.",
    )
    parser.add_argument(
        "--model-dir",
        type=str,
        default="models",
        help="Directory containing ONNX models.",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.75,
        help="Liveness threshold (default: 0.75).",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    if not os.path.exists(args.image):
        print(f"Error: Image file not found: {args.image}", file=sys.stderr)
        return 1

    print(f"Loading ONNXFaceEngine from '{args.model_dir}'...")
    try:
        engine = ONNXFaceEngine(
            model_dir=args.model_dir,
            liveness_threshold=args.threshold,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"Error initializing face engine: {exc}", file=sys.stderr)
        return 1

    print(f"Reading image '{args.image}'...")
    img = cv2.imread(args.image)
    if img is None:
        print(f"Error: Failed to load image: {args.image}", file=sys.stderr)
        return 1

    print("Running face detection...")
    # Run detector
    dets = engine.detect(img)
    if not dets:
        print("Result: No face detected in the image.")
        return 1

    print(f"Found {len(dets)} face(s). Running anti-spoofing liveness checks...")

    all_passed = True
    for idx, det in enumerate(dets):
        print(f"\nFace #{idx + 1}:")
        print(f"  Bounding Box: {det.bbox}")
        print(f"  Detection Score: {det.det_score:.4f}")

        # Run liveness
        liveness_res = engine.liveness(img, det.bbox)
        passed_str = "PASSED (REAL)" if liveness_res.passed else "FAILED (SPOOF)"

        print(f"  Liveness Score: {liveness_res.live_score:.4f}")
        print(f"  Per-Model Scores: {liveness_res.per_model}")
        print(f"  Status: {passed_str}")

        if not liveness_res.passed:
            all_passed = False

    print("\n" + "=" * 40)
    if all_passed:
        print("Verdict: All faces verified as LIVE.")
        return 0
    else:
        print("Verdict: Liveness check FAILED (spoof detected).")
        return 1


if __name__ == "__main__":
    sys.exit(main())
