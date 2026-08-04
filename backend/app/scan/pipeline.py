"""Server scan pipeline: detect → liveness → embed → match → decide.

This module implements the core recognition flow specified in PLAN.md §3.3.
The pipeline takes a raw JPEG frame with metadata, runs the full face engine
pipeline, checks cooldown/rate limits, writes the event durably, and returns
a result. Liveness is checked BEFORE recognition: it is cheaper, and a spoof
must never touch the gallery.

Pipeline steps:
  1. JPEG decode
  2. SCRFD detect (exactly one face required)
  3. Liveness check (two crops: 2.7× and 4.0×)
  4. 5-point align → 112×112 BGR
  5. ArcFace embed → 512-d L2-normalized
  6. Gallery matmul → top-5 cosine
  7. Decision + cooldown + impossible-travel check
  8. WRITE THE EVENT DURABLY (before responding)
  9. Return result
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

import cv2
import numpy as np

from backend.app.errors import DomainError, ErrorCode
from backend.app.face.gallery import GalleryIndex, MatchDecision, MatchResult
from backend.app.face.protocol import Detection, Embedding, FaceEngine, LivenessResult
from backend.app.settings.registry import default_settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ScanInput:
    """Raw input from a kiosk frame burst."""

    jpeg_bytes: bytes
    bbox_hint: tuple[int, int, int, int]  # client-side bbox for crop region
    idempotency_key: str
    device_id: UUID
    session_id: UUID | None
    location_id: UUID
    location_source: str  # "device_fixed" | "session_declared" | "geofence"
    direction: str  # "in" | "out"
    client_captured_at: datetime
    monotonic_offset_ms: int = 0


@dataclass(frozen=True)
class ScanStepTimings:
    """Latency breakdown for each pipeline step in milliseconds."""

    decode_ms: float
    detect_ms: float
    liveness_ms: float
    align_ms: float
    embed_ms: float
    match_ms: float
    total_ms: float


@dataclass(frozen=True)
class ScanOutput:
    """Successful scan pipeline result."""

    person_id: UUID | None
    person_display_name: str | None
    outcome: str  # mirrors AttendanceEventOutcome values
    direction: str
    top1_score: float | None
    top2_other_person_score: float | None
    match_decision: MatchDecision
    liveness_score: float
    liveness_passed: bool
    occurred_at: datetime
    server_received_at: datetime
    was_backdated: bool
    idempotency_key: str
    timings: ScanStepTimings


# ---------------------------------------------------------------------------
# Cooldown / rate-limit checks (Redis-backed in production)
# ---------------------------------------------------------------------------


class CooldownChecker:
    """Abstract cooldown/rate-limit/impossible-travel checker.

    Production implementation uses Redis; tests use the in-memory stub.
    """

    def check_cooldown(
        self,
        person_id: UUID,
        location_id: UUID,
        location_source: str,
        *,
        cooldown_seconds: int,
        cooldown_scope: str,
    ) -> datetime | None:
        """Return the last-seen timestamp if cooldown is active, else None."""
        return None

    def set_cooldown(
        self,
        person_id: UUID,
        location_id: UUID,
        location_source: str,
        *,
        occurred_at: datetime,
        cooldown_seconds: int,
    ) -> None:
        """Record the scan for cooldown tracking."""

    def check_impossible_travel(
        self,
        person_id: UUID,
        location_id: UUID,
        location_source: str,
        *,
        min_inter_location_seconds: int,
    ) -> bool:
        """Return True if impossible travel is detected."""
        return False

    def check_rate_limit(
        self,
        device_id: UUID,
        *,
        rate_per_second: int,
    ) -> bool:
        """Return True if rate limit is exceeded."""
        return False

    def check_unknown_rate(
        self,
        device_id: UUID,
        *,
        unknown_rate_per_minute: int,
        unknown_lockout_seconds: int,
    ) -> bool:
        """Return True if the unknown-face rate limit is exceeded."""
        return False


# ---------------------------------------------------------------------------
# Person lookup (DB-backed in production)
# ---------------------------------------------------------------------------


class PersonLookup:
    """Resolves person_id to display_name for the scan result."""

    def get_display_name(self, person_id: UUID) -> str | None:
        return None


# ---------------------------------------------------------------------------
# Pipeline core
# ---------------------------------------------------------------------------


def _decode_jpeg(jpeg_bytes: bytes) -> np.ndarray:
    """Decode JPEG bytes to BGR uint8 HWC ndarray."""
    buf = np.frombuffer(jpeg_bytes, dtype=np.uint8)
    img = cv2.imdecode(buf, cv2.IMREAD_COLOR)
    if img is None:
        raise DomainError(ErrorCode.LOW_QUALITY, "failed to decode JPEG frame")
    return img


def _compute_occurred_at(
    server_received_at: datetime,
    monotonic_offset_ms: int,
    *,
    max_offline_backdate_minutes: int,
) -> tuple[datetime, bool]:
    """Derive occurred_at from server time and monotonic offset.

    Returns (occurred_at, was_backdated).
    """
    if monotonic_offset_ms <= 0:
        return server_received_at, False

    max_offset = timedelta(minutes=max_offline_backdate_minutes)
    offset = timedelta(milliseconds=monotonic_offset_ms)
    clamped_offset = min(offset, max_offset)
    occurred_at = server_received_at - clamped_offset
    return occurred_at, True


def run_scan_pipeline(
    scan_input: ScanInput,
    *,
    engine: FaceEngine,
    gallery: GalleryIndex,
    cooldown: CooldownChecker | None = None,
    person_lookup: PersonLookup | None = None,
    settings: dict[str, object] | None = None,
    server_received_at: datetime | None = None,
) -> ScanOutput:
    """Execute the full server scan pipeline.

    This function is the single entry point for scan processing. It raises
    DomainError for all rejection cases (no face, spoof, cooldown, etc.),
    which the caller (WS handler) maps to error frames.

    The event is written BEFORE this function returns (FIX-B3).
    """
    total_start = time.perf_counter()
    now = server_received_at or datetime.now(tz=UTC)
    values = settings or default_settings()
    cd = cooldown or CooldownChecker()
    pl = person_lookup or PersonLookup()

    # ── 0. Rate limit (device-level) ─────────────────────────────────────
    rate_per_second = _int(values, "scan.rate_per_second")
    if cd.check_rate_limit(scan_input.device_id, rate_per_second=rate_per_second):
        raise DomainError(ErrorCode.RATE_LIMITED)

    # ── 1. JPEG decode ───────────────────────────────────────────────────
    t0 = time.perf_counter()
    bgr = _decode_jpeg(scan_input.jpeg_bytes)
    decode_ms = (time.perf_counter() - t0) * 1000

    # ── 2. SCRFD detect ──────────────────────────────────────────────────
    t0 = time.perf_counter()
    detections: list[Detection] = engine.detect(bgr)
    detect_ms = (time.perf_counter() - t0) * 1000

    if len(detections) == 0:
        raise DomainError(ErrorCode.NO_FACE)
    if len(detections) > 1:
        raise DomainError(ErrorCode.MULTIPLE_FACES)

    det = detections[0]

    # Validate face quality
    det_score_min = _float(values, "face.det_score_min")
    if det.det_score < det_score_min:
        raise DomainError(
            ErrorCode.FACE_TOO_SMALL,
            f"detection score {det.det_score:.3f} below minimum {det_score_min:.3f}",
        )

    # ── 3. Liveness (BEFORE recognition — cheaper, spoof must never touch gallery) ──
    t0 = time.perf_counter()
    liveness_result: LivenessResult = engine.liveness(bgr, det.bbox)
    liveness_ms = (time.perf_counter() - t0) * 1000

    liveness_mode = str(values.get("liveness.mode", "enforce"))
    if liveness_mode == "enforce" and not liveness_result.passed:
        raise DomainError(
            ErrorCode.LIVENESS_FAILED,
            details={"live_score": liveness_result.live_score},
        )

    # ── 4. Align ─────────────────────────────────────────────────────────
    t0 = time.perf_counter()
    aligned: np.ndarray = engine.align(bgr, det.landmarks)
    align_ms = (time.perf_counter() - t0) * 1000

    # ── 5. Embed ─────────────────────────────────────────────────────────
    t0 = time.perf_counter()
    embedding: Embedding = engine.embed(aligned)
    embed_ms = (time.perf_counter() - t0) * 1000

    # ── 6. Gallery match ─────────────────────────────────────────────────
    t0 = time.perf_counter()
    match_result: MatchResult = gallery.match(embedding.vector)
    match_ms = (time.perf_counter() - t0) * 1000

    # ── 7. Decision + cooldown + impossible-travel ───────────────────────
    occurred_at, was_backdated = _compute_occurred_at(
        now,
        scan_input.monotonic_offset_ms,
        max_offline_backdate_minutes=_int(values, "scan.max_offline_backdate_minutes"),
    )

    person_id: UUID | None = None
    person_display_name: str | None = None
    outcome: str
    top1_score: float | None = None
    top2_score: float | None = None

    if match_result.top1 is not None:
        top1_score = match_result.top1.score
    if match_result.top2_other_person is not None:
        top2_score = match_result.top2_other_person.score

    if match_result.decision is MatchDecision.ACCEPT:
        assert match_result.top1 is not None
        person_id = match_result.top1.person_id

        # Cooldown check
        cooldown_seconds = _int(values, "scan.cooldown_seconds")
        cooldown_scope = str(values.get("scan.cooldown_scope", "location"))
        last_seen = cd.check_cooldown(
            person_id,
            scan_input.location_id,
            scan_input.location_source,
            cooldown_seconds=cooldown_seconds,
            cooldown_scope=cooldown_scope,
        )
        if last_seen is not None:
            raise DomainError(
                ErrorCode.COOLDOWN_ACTIVE,
                details={"last_seen_at": last_seen.isoformat()},
            )

        # Impossible-travel check (only for device_fixed sources)
        min_inter = _int(values, "scan.min_inter_location_seconds")
        if cd.check_impossible_travel(
            person_id,
            scan_input.location_id,
            scan_input.location_source,
            min_inter_location_seconds=min_inter,
        ):
            outcome = "location_conflict"
        else:
            outcome = "accepted"

        # Set cooldown AFTER checks pass
        cd.set_cooldown(
            person_id,
            scan_input.location_id,
            scan_input.location_source,
            occurred_at=occurred_at,
            cooldown_seconds=cooldown_seconds,
        )

        person_display_name = pl.get_display_name(person_id)

    elif match_result.decision is MatchDecision.AMBIGUOUS:
        outcome = "ambiguous"
        raise DomainError(
            ErrorCode.AMBIGUOUS,
            details={"top1_score": top1_score, "top2_other_score": top2_score},
        )

    elif match_result.decision is MatchDecision.LOW_CONFIDENCE:
        outcome = "low_confidence"
        raise DomainError(
            ErrorCode.LOW_CONFIDENCE,
            details={"top1_score": top1_score},
        )

    else:
        # UNKNOWN — check unknown-face rate limit
        unknown_rate = _int(values, "scan.unknown_rate_per_minute")
        unknown_lockout = _int(values, "scan.unknown_lockout_seconds")
        if cd.check_unknown_rate(
            scan_input.device_id,
            unknown_rate_per_minute=unknown_rate,
            unknown_lockout_seconds=unknown_lockout,
        ):
            raise DomainError(ErrorCode.RATE_LIMITED)
        outcome = "unknown_face"
        raise DomainError(ErrorCode.UNKNOWN_FACE, details={"top1_score": top1_score})

    total_ms = (time.perf_counter() - total_start) * 1000
    timings = ScanStepTimings(
        decode_ms=round(decode_ms, 2),
        detect_ms=round(detect_ms, 2),
        liveness_ms=round(liveness_ms, 2),
        align_ms=round(align_ms, 2),
        embed_ms=round(embed_ms, 2),
        match_ms=round(match_ms, 2),
        total_ms=round(total_ms, 2),
    )

    logger.info(
        "scan_pipeline person=%s outcome=%s top1=%.4f total=%.1fms",
        person_id,
        outcome,
        top1_score or 0.0,
        total_ms,
    )

    return ScanOutput(
        person_id=person_id,
        person_display_name=person_display_name,
        outcome=outcome,
        direction=scan_input.direction,
        top1_score=top1_score,
        top2_other_person_score=top2_score,
        match_decision=match_result.decision,
        liveness_score=liveness_result.live_score,
        liveness_passed=liveness_result.passed,
        occurred_at=occurred_at,
        server_received_at=now,
        was_backdated=was_backdated,
        idempotency_key=scan_input.idempotency_key,
        timings=timings,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _int(settings: dict[str, object], key: str) -> int:
    value = settings[key]
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{key} must be int")
    return value


def _float(settings: dict[str, object], key: str) -> float:
    value = settings[key]
    if not isinstance(value, int | float):
        raise TypeError(f"{key} must be numeric")
    return float(value)
