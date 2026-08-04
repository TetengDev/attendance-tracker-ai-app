import argparse
import os
import sys

import cv2
import numpy as np

from backend.app.face.engine import ONNXFaceEngine


def generate_spoof_image(real_img_path: str, spoof_img_path: str) -> None:
    img = cv2.imread(real_img_path)
    if img is None:
        raise ValueError(f"Could not load image from {real_img_path}")

    h, w, _ = img.shape
    # Downscale significantly to simulate a screen display replay
    spoof = cv2.resize(img, (w // 4, h // 4))
    spoof = cv2.resize(spoof, (w, h))

    # Add a moire pattern grid
    grid = np.zeros_like(spoof)
    grid[::4, :, :] = 40
    grid[:, ::4, :] = 40
    spoof = cv2.addWeighted(spoof, 0.7, grid, 0.3, 0)

    os.makedirs(os.path.dirname(spoof_img_path), exist_ok=True)
    cv2.imwrite(spoof_img_path, spoof)
    print(f"Generated synthetic spoof image from {real_img_path} at {spoof_img_path}")


def run_smoke_test(generate_golden: bool = False) -> bool:
    real_1_path = "fixtures/faces/Lester Bryan Ilao - 1.JPG"
    real_2_path = "fixtures/faces/Lester Bryan Ilao - 2.JPG"
    spoof_path = "fixtures/faces/Lester Bryan Ilao - Spoof.JPG"
    golden_path = "backend/tests/fixtures/goldens/tester-zero.npy"

    if not os.path.exists(real_1_path) or not os.path.exists(real_2_path):
        print("Error: Tester-Zero images not found in fixtures/faces/")
        return False

    if not os.path.exists(spoof_path):
        generate_spoof_image(real_2_path, spoof_path)

    # Initialize ONNX Face Engine
    print("Initializing ONNX Face Engine...")
    engine = ONNXFaceEngine()

    # 1. Process Image 1 (Enrollment)
    print("\n--- Processing Image 1 (Enrollment) ---")
    img1 = cv2.imread(real_1_path)
    assert img1 is not None, f"Failed to load image from {real_1_path}"

    dets1 = engine.detect(img1)
    if not dets1:
        print("Error: No face detected in Image 1")
        return False
    det1 = dets1[0]
    print(f"Face detected: bbox={det1.bbox}, score={det1.det_score:.4f}")

    # Compute Liveness for Image 1
    liveness_1 = engine.liveness(img1, det1.bbox)
    print(f"Liveness: score={liveness_1.live_score:.4f}, passed={liveness_1.passed}")
    if not liveness_1.passed:
        print("Error: Image 1 failed liveness check (expected to pass)")
        return False

    # Align and Extract Embedding for Image 1
    aligned1 = engine.align(img1, det1.landmarks)
    emb1 = engine.embed(aligned1)
    print(f"Extracted 512-d embedding. Norm={np.linalg.norm(emb1.vector):.4f}")

    # Generate/Verify Golden Embedding
    if generate_golden:
        os.makedirs(os.path.dirname(golden_path), exist_ok=True)
        np.save(golden_path, emb1.vector)
        print(f"Saved golden embedding to {golden_path}")
        return True

    if not os.path.exists(golden_path):
        print(
            f"Warning: Golden embedding not found at {golden_path}. Running golden generation first..."
        )
        os.makedirs(os.path.dirname(golden_path), exist_ok=True)
        np.save(golden_path, emb1.vector)
        print(f"Saved golden embedding to {golden_path}")

    golden_vector = np.load(golden_path)

    # Verify drift (Image 1 embedding vs Golden)
    drift_similarity = np.dot(emb1.vector, golden_vector)
    print(f"Similarity against golden: {drift_similarity:.6f}")
    if not np.allclose(emb1.vector, golden_vector, atol=1e-5):
        print(
            "Error: PREPROCESSING DRIFT DETECTED! Newly extracted embedding does not match golden."
        )
        return False
    print("Preprocessing drift check: PASS")

    # 2. Process Image 2 (Probe)
    print("\n--- Processing Image 2 (Probe) ---")
    img2 = cv2.imread(real_2_path)
    assert img2 is not None, f"Failed to load image from {real_2_path}"

    dets2 = engine.detect(img2)
    if not dets2:
        print("Error: No face detected in Image 2")
        return False
    det2 = dets2[0]
    print(f"Face detected: bbox={det2.bbox}, score={det2.det_score:.4f}")

    # Compute Liveness for Image 2
    liveness_2 = engine.liveness(img2, det2.bbox)
    print(f"Liveness: score={liveness_2.live_score:.4f}, passed={liveness_2.passed}")
    if not liveness_2.passed:
        print("Error: Image 2 failed liveness check (expected to pass)")
        return False

    # Align and Extract Embedding for Image 2
    aligned2 = engine.align(img2, det2.landmarks)
    emb2 = engine.embed(aligned2)

    # Compute Cosine Similarity between Image 2 and Golden
    probe_similarity = np.dot(emb2.vector, golden_vector)
    print(f"Cosine similarity between Probe and Enrollment: {probe_similarity:.4f}")
    if probe_similarity < 0.60:
        print("Error: Cosine similarity too low (expected >= 0.60 for same identity)")
        return False
    print("Identity matching check: PASS")

    # 3. Process Spoof Image
    print("\n--- Processing Spoof Image ---")
    img_spoof = cv2.imread(spoof_path)
    assert img_spoof is not None, f"Failed to load image from {spoof_path}"

    dets_spoof = engine.detect(img_spoof)
    if not dets_spoof:
        print("Error: No face detected in Spoof Image")
        return False
    det_spoof = dets_spoof[0]
    print(f"Face detected in Spoof: bbox={det_spoof.bbox}, score={det_spoof.det_score:.4f}")

    # Check Liveness for Spoof
    liveness_spoof = engine.liveness(img_spoof, det_spoof.bbox)
    print(f"Spoof Liveness: score={liveness_spoof.live_score:.4f}, passed={liveness_spoof.passed}")
    if liveness_spoof.passed:
        print("Error: Spoof image passed liveness check (expected to fail)")
        return False
    if liveness_spoof.live_score >= 0.70:
        print("Error: Spoof liveness score too high (expected < 0.70)")
        return False
    print("Liveness rejection check: PASS")

    print("\n==============================")
    print("ALL SMOKE TEST ASSERTS PASSED!")
    print("==============================")
    return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Tester-Zero face engine smoke test.")
    parser.add_argument(
        "--generate-golden",
        action="store_true",
        help="Generate the golden embedding for Tester-Zero",
    )
    args = parser.parse_args()

    success = run_smoke_test(generate_golden=args.generate_golden)
    sys.exit(0 if success else 1)
