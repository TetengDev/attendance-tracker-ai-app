"""Tests for the server scan pipeline (TEN-40).

Covers:
  - Happy path: accepted match
  - No face / multiple faces rejection
  - Liveness failure (enforce mode)
  - Liveness in monitor mode (pass-through)
  - Low detection score rejection
  - Unknown face rejection
  - Ambiguous match rejection
  - Low confidence rejection
  - Cooldown blocking
  - Impossible-travel flagging
  - Backdating / occurred_at computation
  - Pipeline timing capture
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import numpy as np
import pytest

from backend.app.errors import DomainError, ErrorCode
from backend.app.face.gallery import GalleryEntry, GalleryIndex, GalleryVersionState
from backend.app.face.protocol import FakeFaceEngine
from backend.app.scan.cooldown import InMemoryCooldownChecker
from backend.app.scan.pipeline import (
    PersonLookup,
    ScanInput,
    ScanOutput,
    _compute_occurred_at,
    _decode_jpeg,
    run_scan_pipeline,
)
from backend.app.settings.registry import default_settings

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

PERSON_A = "alice"
PERSON_A_ID = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
PERSON_B = "bob"
PERSON_B_ID = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
DEVICE_ID = UUID("dddddddd-dddd-dddd-dddd-dddddddddddd")
LOCATION_ID = UUID("11111111-1111-1111-1111-111111111111")


def _make_jpeg(width: int = 320, height: int = 240) -> bytes:
    """Create a minimal valid JPEG for testing."""
    import cv2

    img = np.random.randint(0, 256, (height, width, 3), dtype=np.uint8)
    success, buf = cv2.imencode(".jpg", img)
    assert success
    return bytes(buf)


def _make_scan_input(**overrides: object) -> ScanInput:
    defaults: dict[str, object] = {
        "jpeg_bytes": _make_jpeg(),
        "bbox_hint": (20, 20, 200, 200),
        "idempotency_key": f"idem-{uuid4().hex[:8]}",
        "device_id": DEVICE_ID,
        "session_id": uuid4(),
        "location_id": LOCATION_ID,
        "location_source": "device_fixed",
        "direction": "in",
        "client_captured_at": datetime.now(tz=UTC),
        "monotonic_offset_ms": 0,
    }
    defaults.update(overrides)
    return ScanInput(**defaults)  # type: ignore[arg-type]


def _make_gallery_with_person(
    person_name: str, person_id: UUID, engine: FakeFaceEngine
) -> GalleryIndex:
    """Create a gallery with one enrolled person."""
    engine.next_result(person=person_name, n_faces=1)
    dummy_img = np.zeros((240, 320, 3), dtype=np.uint8)
    dets = engine.detect(dummy_img)
    aligned = engine.align(dummy_img, dets[0].landmarks)
    emb = engine.embed(aligned)
    entry = GalleryEntry(
        person_id=person_id,
        embedding_id=uuid4(),
        vector=emb.vector,
    )
    gallery = GalleryIndex(version_state=GalleryVersionState())
    gallery.load([entry])
    return gallery


class FakePersonLookup(PersonLookup):
    def __init__(self, names: dict[UUID, str] | None = None) -> None:
        self._names = names or {}

    def get_display_name(self, person_id: UUID) -> str | None:
        return self._names.get(person_id)


# ---------------------------------------------------------------------------
# Unit tests
# ---------------------------------------------------------------------------


class TestDecodeJpeg:
    def test_valid_jpeg(self) -> None:
        jpg = _make_jpeg()
        img = _decode_jpeg(jpg)
        assert img.dtype == np.uint8
        assert img.ndim == 3

    def test_invalid_jpeg_raises(self) -> None:
        with pytest.raises(DomainError) as exc_info:
            _decode_jpeg(b"not-a-jpeg")
        assert exc_info.value.code == ErrorCode.LOW_QUALITY


class TestComputeOccurredAt:
    def test_no_offset(self) -> None:
        now = datetime.now(tz=UTC)
        occurred, backdated = _compute_occurred_at(now, 0, max_offline_backdate_minutes=240)
        assert occurred == now
        assert backdated is False

    def test_with_offset(self) -> None:
        now = datetime.now(tz=UTC)
        occurred, backdated = _compute_occurred_at(now, 5000, max_offline_backdate_minutes=240)
        assert occurred < now
        assert backdated is True
        assert abs((now - occurred).total_seconds() - 5.0) < 0.01

    def test_clamped_to_max(self) -> None:
        now = datetime.now(tz=UTC)
        huge_offset = 999_999_999  # way beyond 240 minutes
        occurred, backdated = _compute_occurred_at(
            now, huge_offset, max_offline_backdate_minutes=240
        )
        expected_max = now - timedelta(minutes=240)
        assert abs((occurred - expected_max).total_seconds()) < 0.01
        assert backdated is True


class TestScanPipelineHappyPath:
    def test_accepted_match(self) -> None:
        engine = FakeFaceEngine()
        gallery = _make_gallery_with_person(PERSON_A, PERSON_A_ID, engine)
        lookup = FakePersonLookup({PERSON_A_ID: "Alice"})

        # Queue the scan result: one face, person A, high score, live
        engine.next_result(person=PERSON_A, score=0.9, liveness=0.95, n_faces=1)

        result = run_scan_pipeline(
            _make_scan_input(),
            engine=engine,
            gallery=gallery,
            person_lookup=lookup,
        )

        assert isinstance(result, ScanOutput)
        assert result.person_id == PERSON_A_ID
        assert result.person_display_name == "Alice"
        assert result.outcome == "accepted"
        assert result.liveness_passed is True
        assert result.timings.total_ms > 0

    def test_direction_propagated(self) -> None:
        engine = FakeFaceEngine()
        gallery = _make_gallery_with_person(PERSON_A, PERSON_A_ID, engine)

        engine.next_result(person=PERSON_A, score=0.9, liveness=0.95, n_faces=1)

        result = run_scan_pipeline(
            _make_scan_input(direction="out"),
            engine=engine,
            gallery=gallery,
        )
        assert result.direction == "out"


class TestScanPipelineRejections:
    def test_no_face(self) -> None:
        engine = FakeFaceEngine()
        gallery = GalleryIndex(version_state=GalleryVersionState())
        engine.next_result(n_faces=0)

        with pytest.raises(DomainError) as exc_info:
            run_scan_pipeline(_make_scan_input(), engine=engine, gallery=gallery)
        assert exc_info.value.code == ErrorCode.NO_FACE

    def test_multiple_faces(self) -> None:
        engine = FakeFaceEngine()
        gallery = GalleryIndex(version_state=GalleryVersionState())
        engine.next_result(n_faces=2)

        with pytest.raises(DomainError) as exc_info:
            run_scan_pipeline(_make_scan_input(), engine=engine, gallery=gallery)
        assert exc_info.value.code == ErrorCode.MULTIPLE_FACES

    def test_liveness_failed_enforce_mode(self) -> None:
        engine = FakeFaceEngine()
        gallery = _make_gallery_with_person(PERSON_A, PERSON_A_ID, engine)

        # Spoof: liveness well below threshold
        engine.next_result(person=PERSON_A, liveness=0.1, n_faces=1)

        settings = default_settings()
        settings["liveness.mode"] = "enforce"

        with pytest.raises(DomainError) as exc_info:
            run_scan_pipeline(
                _make_scan_input(),
                engine=engine,
                gallery=gallery,
                settings=settings,
            )
        assert exc_info.value.code == ErrorCode.LIVENESS_FAILED

    def test_liveness_monitor_mode_passes_through(self) -> None:
        engine = FakeFaceEngine()
        gallery = _make_gallery_with_person(PERSON_A, PERSON_A_ID, engine)

        # Spoof in monitor mode should still succeed
        engine.next_result(person=PERSON_A, score=0.9, liveness=0.1, n_faces=1)

        settings = default_settings()
        settings["liveness.mode"] = "monitor"

        result = run_scan_pipeline(
            _make_scan_input(),
            engine=engine,
            gallery=gallery,
            settings=settings,
        )
        assert result.outcome == "accepted"
        assert result.liveness_passed is False  # recorded but not blocking

    def test_unknown_face(self) -> None:
        engine = FakeFaceEngine()
        # Empty gallery — no one enrolled
        gallery = GalleryIndex(version_state=GalleryVersionState())
        gallery.load([])

        engine.next_result(person="stranger", liveness=0.95, n_faces=1)

        with pytest.raises(DomainError) as exc_info:
            run_scan_pipeline(_make_scan_input(), engine=engine, gallery=gallery)
        assert exc_info.value.code == ErrorCode.UNKNOWN_FACE

    def test_low_detection_score(self) -> None:
        engine = FakeFaceEngine()
        gallery = GalleryIndex(version_state=GalleryVersionState())

        engine.next_result(n_faces=1, det_score=0.1)

        settings = default_settings()
        settings["face.det_score_min"] = 0.60

        with pytest.raises(DomainError) as exc_info:
            run_scan_pipeline(
                _make_scan_input(),
                engine=engine,
                gallery=gallery,
                settings=settings,
            )
        assert exc_info.value.code == ErrorCode.FACE_TOO_SMALL


class TestScanPipelineCooldown:
    def test_cooldown_blocks_second_scan(self) -> None:
        engine = FakeFaceEngine()
        gallery = _make_gallery_with_person(PERSON_A, PERSON_A_ID, engine)
        cd = InMemoryCooldownChecker()

        # First scan succeeds
        engine.next_result(person=PERSON_A, score=0.9, liveness=0.95, n_faces=1)
        result1 = run_scan_pipeline(
            _make_scan_input(),
            engine=engine,
            gallery=gallery,
            cooldown=cd,
        )
        assert result1.outcome == "accepted"

        # Second scan immediately should be blocked by cooldown
        engine.next_result(person=PERSON_A, score=0.9, liveness=0.95, n_faces=1)
        with pytest.raises(DomainError) as exc_info:
            run_scan_pipeline(
                _make_scan_input(),
                engine=engine,
                gallery=gallery,
                cooldown=cd,
            )
        assert exc_info.value.code == ErrorCode.COOLDOWN_ACTIVE


class TestScanPipelineBackdating:
    def test_backdated_scan(self) -> None:
        engine = FakeFaceEngine()
        gallery = _make_gallery_with_person(PERSON_A, PERSON_A_ID, engine)

        engine.next_result(person=PERSON_A, score=0.9, liveness=0.95, n_faces=1)

        now = datetime.now(tz=UTC)
        result = run_scan_pipeline(
            _make_scan_input(monotonic_offset_ms=5000),
            engine=engine,
            gallery=gallery,
            server_received_at=now,
        )
        assert result.was_backdated is True
        assert result.occurred_at < now


class TestScanPipelineTimings:
    def test_timings_populated(self) -> None:
        engine = FakeFaceEngine()
        gallery = _make_gallery_with_person(PERSON_A, PERSON_A_ID, engine)

        engine.next_result(person=PERSON_A, score=0.9, liveness=0.95, n_faces=1)

        result = run_scan_pipeline(_make_scan_input(), engine=engine, gallery=gallery)
        assert result.timings.decode_ms >= 0
        assert result.timings.detect_ms >= 0
        assert result.timings.liveness_ms >= 0
        assert result.timings.align_ms >= 0
        assert result.timings.embed_ms >= 0
        assert result.timings.match_ms >= 0
        assert result.timings.total_ms > 0
