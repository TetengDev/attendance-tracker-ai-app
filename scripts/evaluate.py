#!/usr/bin/env python3
"""CLI utility to sweep and evaluate face recognition threshold parameters.

Computes False Match Rate (FMR), False Non-Match Rate (FNMR/FRR), and False Acceptance Rate
extrapolated to a gallery size of N=5000. Draws a recommendation for the optimal threshold.
"""

from __future__ import annotations

import argparse
import os
import sys

import cv2
import numpy as np

from backend.app.face.engine import ONNXFaceEngine


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Sweep face recognition thresholds and generate ROC statistics."
    )
    parser.add_argument(
        "--model-dir",
        type=str,
        default="models",
        help="Directory containing ONNX models.",
    )
    parser.add_argument(
        "--eval-dir",
        type=str,
        default="fixtures/faces/sfhq",
        help="Directory containing SFHQ synthetic evaluation images.",
    )
    parser.add_argument(
        "--num-images",
        type=int,
        default=100,
        help="Number of synthetic images to evaluate (default: 100).",
    )
    parser.add_argument(
        "--gallery-size",
        type=int,
        default=5000,
        help="Gallery size N for FAR extrapolation (default: 5000).",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    if not os.path.exists(args.eval_dir):
        print(f"Error: Evaluation directory does not exist: {args.eval_dir}", file=sys.stderr)
        return 1

    # Load images
    image_extensions = (".jpg", ".jpeg", ".png")
    all_files = sorted(
        [
            os.path.join(args.eval_dir, f)
            for f in os.listdir(args.eval_dir)
            if f.lower().endswith(image_extensions)
        ]
    )

    if not all_files:
        print(f"Error: No images found in {args.eval_dir}", file=sys.stderr)
        return 1

    selected_files = all_files[: args.num_images]
    print(f"Selected {len(selected_files)} images for evaluation sweep.")

    print(f"Initializing ONNXFaceEngine from '{args.model_dir}'...")
    try:
        engine = ONNXFaceEngine(model_dir=args.model_dir)
    except Exception as exc:  # noqa: BLE001
        print(f"Error initializing face engine: {exc}", file=sys.stderr)
        return 1

    print("\nExtracting embeddings for genuine and impostor sets...")
    embeddings: list[np.ndarray] = []
    shifted_embeddings: list[np.ndarray] = []

    processed_count = 0
    for idx, filepath in enumerate(selected_files):
        img = cv2.imread(filepath)
        if img is None:
            continue

        # Detect
        dets = engine.detect(img)
        if not dets:
            # Skip if no face detected
            continue

        det = dets[0]

        # Extract genuine embedding (original image)
        aligned = engine.align(img, det.landmarks)
        emb = engine.embed(aligned)

        # Generate genuine pair by applying a realistic minor 2-pixel shift
        shifted_img = np.roll(img, shift=2, axis=0)
        dets_shift = engine.detect(shifted_img)
        if not dets_shift:
            continue

        aligned_shift = engine.align(shifted_img, dets_shift[0].landmarks)
        emb_shift = engine.embed(aligned_shift)

        # Normalize vectors to ensure correct cosine similarity dot products
        vec = emb.vector / np.linalg.norm(emb.vector)
        vec_shift = emb_shift.vector / np.linalg.norm(emb_shift.vector)

        embeddings.append(vec)
        shifted_embeddings.append(vec_shift)
        processed_count += 1

        if processed_count % 10 == 0:
            print(f"  Processed {processed_count}/{len(selected_files)} images...")

    M = len(embeddings)
    if M < 10:
        print(
            f"Error: Only processed {M} face images successfully. Need at least 10.",
            file=sys.stderr,
        )
        return 1

    print(f"\nSuccessfully extracted embeddings for {M} identities.")

    # ── Impostor similarities (similarities between different identities) ──
    # Matrix shape: M x M
    emb_matrix = np.array(embeddings)
    sim_matrix = np.dot(emb_matrix, emb_matrix.T)
    # Extract only upper-triangle (excluding diagonal) to prevent self-matching comparisons
    impostor_sims = sim_matrix[np.triu_indices(M, k=1)]

    # ── Genuine similarities (similarities between same identity, slightly perturbed) ──
    genuine_sims = np.array(
        [np.dot(emb, emb_shift) for emb, emb_shift in zip(embeddings, shifted_embeddings)]
    )

    print(f"Total Impostor pairs evaluated: {len(impostor_sims)}")
    print(f"Total Genuine pairs evaluated: {len(genuine_sims)}")
    print(f"Genuine Similarity Mean: {np.mean(genuine_sims):.4f} (std={np.std(genuine_sims):.4f})")
    print(
        f"Impostor Similarity Mean: {np.mean(impostor_sims):.4f} (std={np.std(impostor_sims):.4f})"
    )

    # ── Threshold Sweep ──
    print("\n" + "=" * 90)
    print("ROC Threshold Sweep & Scale Extrapolation:")
    print("-" * 90)
    print(
        f"{'Threshold (T)':<15} | {'FMR (1:1)':>12} | {'FAR (1:N=' + str(args.gallery_size) + ')':>16} | {'FRR/FNMR (1:1)':>15}"
    )
    print("-" * 90)

    best_t = 0.45
    min_diff = 1.0

    # Sweep in steps of 0.01 internally for recommendation, but print every 0.05
    for t in np.arange(0.20, 0.81, 0.01):
        fmr = np.mean(impostor_sims >= t)
        far_n = 1.0 - (1.0 - fmr) ** args.gallery_size
        frr = np.mean(genuine_sims < t)

        # Look for Equal Error Rate (EER) where FAR(N) is closest to FRR
        diff = abs(far_n - frr)
        if diff < min_diff:
            min_diff = diff
            best_t = t

        # Print rows on 0.05 bounds
        if abs(t * 100 % 5) < 1e-5:
            print(f"{t:<15.2f} | {fmr:>12.6f} | {far_n:>16.6f} | {frr:>15.6f}")

    print("-" * 90)

    # Calculate metrics for the recommended threshold
    rec_fmr = np.mean(impostor_sims >= best_t)
    rec_far = 1.0 - (1.0 - rec_fmr) ** args.gallery_size
    rec_frr = np.mean(genuine_sims < best_t)

    print("Equal Error Rate (EER) Threshold Recommendation (FAR(N) ≈ FRR):")
    print(f"  Recommended Threshold: {best_t:.2f}")
    print(f"  FMR (1:1) at {best_t:.2f}: {rec_fmr:.6f}")
    print(f"  FAR (1:N={args.gallery_size}) at {best_t:.2f}: {rec_far:.6f}")
    print(f"  FRR (1:1) at {best_t:.2f}: {rec_frr:.6f}")

    # Check if threshold conforms to PLAN.md expectations
    print("\nVerification Gate:")
    if best_t >= 0.45:
        print(
            f"  [PASS] Recommended threshold {best_t:.2f} is >= 0.45 (conforming to PLAN.md §0 #9)."
        )
        print("=" * 90)
        return 0
    else:
        print(
            f"  [FAIL] Recommended threshold {best_t:.2f} is below 0.45. Consider increasing sample size."
        )
        print("=" * 90)
        return 1


if __name__ == "__main__":
    sys.exit(main())
