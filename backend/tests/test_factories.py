import numpy as np

from backend.tests.factories import (
    NON_UTC_TIMEZONES,
    DeviceFactory,
    LocationFactory,
    OrgFactory,
    PersonFactory,
    embedding_with_cosine,
    seeded_unit_embedding,
)


def test_seeded_factories_are_deterministic() -> None:
    assert OrgFactory(key="acme").id == OrgFactory(key="acme").id
    assert LocationFactory().timezone in NON_UTC_TIMEZONES
    assert DeviceFactory().location.id == LocationFactory().id
    assert PersonFactory(key="alice").id == PersonFactory(key="alice").id


def test_seeded_embedding_is_unit_normalized() -> None:
    embedding = seeded_unit_embedding(1)
    assert embedding.shape == (512,)
    assert np.linalg.norm(embedding) == np.float32(1.0)


def test_embedding_pair_hits_requested_cosine() -> None:
    pair = embedding_with_cosine(10, 0.42)
    assert pair.left.shape == (512,)
    assert pair.right.shape == (512,)
    assert abs(pair.actual_cosine - pair.target_cosine) < 1e-6
