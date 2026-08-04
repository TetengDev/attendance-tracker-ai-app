#!/usr/bin/env python3
"""CLI utility to benchmark face recognition engine latency.

Measures latency statistics for SCRFD detection, face alignment, ArcFace embedding,
MiniFASNet liveness, and the end-to-end processing pipeline.
"""

from __future__ import annotations

import argparse
import os
import platform
import sys
import time

import cv2
import numpy as np

from backend.app.face.engine import ONNXFaceEngine


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Benchmark face recognition engine latency.")
    parser.add_argument(
        "--image",
        type=str,
        default="fixtures/faces/Lester Bryan Ilao - 1.JPG",
        help="Path to the test image file.",
    )
    parser.add_argument(
        "--model-dir",
        type=str,
        default="models",
        help="Directory containing ONNX models.",
    )
    parser.add_argument(
        "--runs",
        type=int,
        default=30,
        help="Number of iterations for benchmarking (default: 30).",
    )
    parser.add_argument(
        "--warmup",
        type=int,
        default=5,
        help="Number of warm-up runs (default: 5).",
    )
    return parser.parse_args()


def get_cpu_info() -> str:
    """Retrieve basic CPU model details for reporting."""
    system = platform.system()
    if system == "Darwin":
        # macOS CPU info
        import subprocess

        try:
            return (
                subprocess.check_output(["sysctl", "-n", "machdep.cpu.brand_string"])
                .decode()
                .strip()
            )
        except (subprocess.SubprocessError, OSError):
            try:
                return subprocess.check_output(["sysctl", "-n", "hw.model"]).decode().strip()
            except (subprocess.SubprocessError, OSError):
                return "Apple Silicon / Mac CPU"
    elif system == "Linux":
        try:
            with open("/proc/cpuinfo") as f:
                for line in f:
                    if "model name" in line:
                        return line.split(":")[1].strip()
        except OSError:
            pass
    return platform.processor() or "Unknown CPU"


def print_stats_row(name: str, times: list[float]) -> None:
    # Convert seconds to milliseconds
    times_ms = [t * 1000.0 for t in times]
    mean_val = np.mean(times_ms)
    median_val = np.median(times_ms)
    min_val = np.min(times_ms)
    max_val = np.max(times_ms)
    p90 = np.percentile(times_ms, 90)
    p95 = np.percentile(times_ms, 95)
    p99 = np.percentile(times_ms, 99)

    print(
        f"{name:<15} | {mean_val:>8.2f} | {median_val:>8.2f} | {min_val:>8.2f} | {max_val:>8.2f} | {p90:>8.2f} | {p95:>8.2f} | {p99:>8.2f}"
    )


def main() -> int:
    args = parse_args()

    if not os.path.exists(args.image):
        print(f"Error: Test image not found: {args.image}", file=sys.stderr)
        return 1

    print("System Information:")
    print(f"  OS: {platform.system()} {platform.release()}")
    print(f"  CPU: {get_cpu_info()}")
    print(f"  Python: {platform.python_version()}")
    print("-" * 50)

    print(f"Initializing ONNXFaceEngine from '{args.model_dir}'...")
    try:
        engine = ONNXFaceEngine(model_dir=args.model_dir)
    except Exception as exc:  # noqa: BLE001
        print(f"Error initializing face engine: {exc}", file=sys.stderr)
        return 1

    img = cv2.imread(args.image)
    if img is None:
        print(f"Error: Failed to read image '{args.image}'", file=sys.stderr)
        return 1

    # Print image dimensions
    h, w, c = img.shape
    print(f"Test Image Dimensions: {w}x{h} ({c} channels)")

    # 1. Warm-up
    print(f"\nRunning {args.warmup} warm-up iterations to initialize ORM execution plans...")
    for _ in range(args.warmup):
        # Full flow
        dets = engine.detector.detect(img, det_thresh=engine.det_score_min)
        if dets:
            aligned = engine.align(img, dets[0].landmarks)
            _ = engine.embed(aligned)
            _ = engine.liveness_detector.check_liveness(img, dets[0].bbox)

    print("Warm-up complete.")

    # 2. Benchmarking loops
    print(f"\nBenchmarking over {args.runs} iterations...")

    detect_times: list[float] = []
    align_times: list[float] = []
    embed_times: list[float] = []
    liveness_times: list[float] = []
    total_times: list[float] = []

    for run_idx in range(args.runs):
        t_start = time.perf_counter()

        # Step 1: Detect
        t0 = time.perf_counter()
        dets = engine.detector.detect(img, det_thresh=engine.det_score_min)
        t_detect = time.perf_counter() - t0
        detect_times.append(t_detect)

        if not dets:
            print(f"Warning: No face detected in run {run_idx + 1}. Aborting benchmark.")
            return 1

        det = dets[0]

        # Step 2: Align
        t0 = time.perf_counter()
        aligned = engine.align(img, det.landmarks)
        t_align = time.perf_counter() - t0
        align_times.append(t_align)

        # Step 3: Embed
        t0 = time.perf_counter()
        _ = engine.embed(aligned)
        t_embed = time.perf_counter() - t0
        embed_times.append(t_embed)

        # Step 4: Liveness
        t0 = time.perf_counter()
        _ = engine.liveness_detector.check_liveness(img, det.bbox)
        t_liveness = time.perf_counter() - t0
        liveness_times.append(t_liveness)

        t_total = time.perf_counter() - t_start
        total_times.append(t_total)

    # 3. Report Results
    print("\n" + "=" * 90)
    print("Latency Statistics (in milliseconds):")
    print("-" * 90)
    print(
        f"{'Pipeline Stage':<15} | {'Mean':>8} | {'Median':>8} | {'Min':>8} | {'Max':>8} | {'p90':>8} | {'p95':>8} | {'p99':>8}"
    )
    print("-" * 90)
    print_stats_row("Detection (SCRFD)", detect_times)
    print_stats_row("Alignment", align_times)
    print_stats_row("Embedding (ArcFace)", embed_times)
    print_stats_row("Liveness (AntiSpoof)", liveness_times)
    print("-" * 90)
    print_stats_row("Total Pipeline", total_times)
    print("=" * 90)

    return 0


if __name__ == "__main__":
    sys.exit(main())
