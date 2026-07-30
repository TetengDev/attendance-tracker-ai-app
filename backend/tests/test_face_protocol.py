import numpy as np
import pytest

from backend.app.face.protocol import FakeFaceEngine


def test_fake_faceengine_detect_and_embed():
    engine = FakeFaceEngine()
    engine.next_result(person="alice", score=0.95, liveness=0.98)

    img = np.zeros((480, 640, 3), dtype=np.uint8)
    dets = engine.detect(img)
    assert len(dets) == 1
    det = dets[0]
    assert det.bbox[2] > det.bbox[0]

    aligned = engine.align(img, det.landmarks)
    emb = engine.embed(aligned)
    assert emb.vector.shape == (512,)
    norm = np.linalg.norm(emb.vector)
    assert abs(norm - 1.0) < 1e-6
    lv = engine.liveness(img, det.bbox)
    assert isinstance(lv.live_score, float)
    assert isinstance(lv.passed, bool)


def test_queue_and_reset():
    engine = FakeFaceEngine()
    engine.queue_results([
        {"person": "bob", "score": 0.9, "liveness": 0.5, "n_faces": 1},
        {"person": None, "score": 0.0, "liveness": 0.2, "n_faces": 0},
    ])

    img = np.zeros((240, 320, 3), dtype=np.uint8)
    dets1 = engine.detect(img)
    assert len(dets1) == 1

    dets2 = engine.detect(img)
    # second queued item had n_faces == 0 -> no detections
    assert len(dets2) == 0

    engine.reset()
    dets3 = engine.detect(img)
    assert len(dets3) == 0
