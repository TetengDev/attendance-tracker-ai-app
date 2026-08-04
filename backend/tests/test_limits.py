"""Unit and integration tests for RedisCooldownChecker limits."""

from __future__ import annotations

import time
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
import redis

from backend.app.config import get_settings
from backend.app.scan.cooldown import InMemoryCooldownChecker
from backend.app.scan.limits import RedisCooldownChecker
from backend.app.scan.pipeline import CooldownChecker


@pytest.fixture
def redis_client() -> Iterator[redis.Redis]:
    url = get_settings().redis_url
    client = redis.from_url(url, decode_responses=True)
    # Clear scan keys before test
    keys = client.keys("scan:*")
    if keys:
        client.delete(*keys)
    yield client
    # Clear scan keys after test
    keys = client.keys("scan:*")
    if keys:
        client.delete(*keys)


@pytest.fixture(params=["in_memory", "redis"])
def checker(request: pytest.FixtureRequest) -> Iterator[CooldownChecker]:
    if request.param == "in_memory":
        chk: CooldownChecker = InMemoryCooldownChecker()
    else:
        chk = RedisCooldownChecker()
    chk.reset()
    yield chk
    chk.reset()


# ── Cooldown Tests ────────────────────────────────────────────────────────────

def test_check_cooldown_location_scope(checker: CooldownChecker) -> None:
    person_id = uuid4()
    location_id = uuid4()
    device_id = uuid4()
    now = datetime.now(tz=UTC)

    # 1. Initially no cooldown
    assert checker.check_cooldown(
        person_id,
        location_id,
        "device_fixed",
        cooldown_seconds=10,
        cooldown_scope="location",
        device_id=device_id,
    ) is None

    # 2. Set location cooldown
    checker.set_cooldown(
        person_id,
        location_id,
        "device_fixed",
        occurred_at=now,
        cooldown_seconds=10,
        cooldown_scope="location",
        device_id=device_id,
    )

    # 3. Cooldown should be active for same location
    last_seen = checker.check_cooldown(
        person_id,
        location_id,
        "device_fixed",
        cooldown_seconds=10,
        cooldown_scope="location",
        device_id=device_id,
    )
    assert last_seen is not None
    assert abs((last_seen - now).total_seconds()) < 0.1

    # 4. Different location should NOT trigger cooldown under "location" scope
    other_location = uuid4()
    assert checker.check_cooldown(
        person_id,
        other_location,
        "device_fixed",
        cooldown_seconds=10,
        cooldown_scope="location",
        device_id=device_id,
    ) is None


def test_check_cooldown_global_scope(checker: CooldownChecker) -> None:
    person_id = uuid4()
    location_id = uuid4()
    other_location = uuid4()
    device_id = uuid4()
    now = datetime.now(tz=UTC)

    # Set cooldown
    checker.set_cooldown(
        person_id,
        location_id,
        "device_fixed",
        occurred_at=now,
        cooldown_seconds=10,
        cooldown_scope="global",
        device_id=device_id,
    )

    # Global cooldown active even at another location
    assert checker.check_cooldown(
        person_id,
        other_location,
        "device_fixed",
        cooldown_seconds=10,
        cooldown_scope="global",
        device_id=device_id,
    ) is not None


def test_check_cooldown_device_scope(checker: CooldownChecker) -> None:
    person_id = uuid4()
    location_id = uuid4()
    device_id = uuid4()
    other_device = uuid4()
    now = datetime.now(tz=UTC)

    # Set cooldown
    checker.set_cooldown(
        person_id,
        location_id,
        "device_fixed",
        occurred_at=now,
        cooldown_seconds=10,
        cooldown_scope="device",
        device_id=device_id,
    )

    # Cooldown active on same device
    assert checker.check_cooldown(
        person_id,
        location_id,
        "device_fixed",
        cooldown_seconds=10,
        cooldown_scope="device",
        device_id=device_id,
    ) is not None

    # Cooldown NOT active on different device
    assert checker.check_cooldown(
        person_id,
        location_id,
        "device_fixed",
        cooldown_seconds=10,
        cooldown_scope="device",
        device_id=other_device,
    ) is None


# ── Impossible Travel Tests ────────────────────────────────────────────────────

def test_check_impossible_travel_both_fixed(checker: CooldownChecker) -> None:
    person_id = uuid4()
    location_a = uuid4()
    location_b = uuid4()
    now = datetime.now(tz=UTC)

    # First scan: device_fixed
    checker.set_cooldown(
        person_id,
        location_a,
        "device_fixed",
        occurred_at=now,
        cooldown_seconds=10,
        cooldown_scope="location",
    )

    # Second scan: device_fixed, different location, within 120s -> True (conflict)
    assert checker.check_impossible_travel(
        person_id,
        location_b,
        "device_fixed",
        min_inter_location_seconds=120,
    ) is True

    # Second scan: outside window -> False
    checker.set_cooldown(
        person_id,
        location_a,
        "device_fixed",
        occurred_at=now - timedelta(seconds=130),
        cooldown_seconds=10,
        cooldown_scope="location",
    )
    assert checker.check_impossible_travel(
        person_id,
        location_b,
        "device_fixed",
        min_inter_location_seconds=120,
    ) is False


def test_check_impossible_travel_roaming_ignored(checker: CooldownChecker) -> None:
    person_id = uuid4()
    location_a = uuid4()
    location_b = uuid4()
    now = datetime.now(tz=UTC)

    # 1. First scan roaming, second fixed -> should ignore
    checker.set_cooldown(
        person_id,
        location_a,
        "session_declared",  # roaming
        occurred_at=now,
        cooldown_seconds=10,
        cooldown_scope="location",
    )
    assert checker.check_impossible_travel(
        person_id,
        location_b,
        "device_fixed",
        min_inter_location_seconds=120,
    ) is False

    # 2. First scan fixed, second roaming -> should ignore
    checker.set_cooldown(
        person_id,
        location_a,
        "device_fixed",
        occurred_at=now,
        cooldown_seconds=10,
        cooldown_scope="location",
    )
    assert checker.check_impossible_travel(
        person_id,
        location_b,
        "geofence",  # roaming
        min_inter_location_seconds=120,
    ) is False


def test_check_impossible_travel_same_location(checker: CooldownChecker) -> None:
    person_id = uuid4()
    location_a = uuid4()
    now = datetime.now(tz=UTC)

    checker.set_cooldown(
        person_id,
        location_a,
        "device_fixed",
        occurred_at=now,
        cooldown_seconds=10,
        cooldown_scope="location",
    )
    # Same location -> no conflict
    assert checker.check_impossible_travel(
        person_id,
        location_a,
        "device_fixed",
        min_inter_location_seconds=120,
    ) is False


# ── Rate Limiting Tests ────────────────────────────────────────────────────────

def test_check_rate_limit(checker: CooldownChecker) -> None:
    device_id = uuid4()

    # Rate limit: 2 per second
    assert checker.check_rate_limit(device_id, rate_per_second=2) is False
    assert checker.check_rate_limit(device_id, rate_per_second=2) is False

    # Third scan within 1 second -> True (blocked)
    assert checker.check_rate_limit(device_id, rate_per_second=2) is True

    # Blocked requests are NOT counted. Check again immediately -> still blocked
    assert checker.check_rate_limit(device_id, rate_per_second=2) is True

    # Wait for rate window to slide
    time.sleep(1.1)

    # Allowed again
    assert checker.check_rate_limit(device_id, rate_per_second=2) is False


# ── Unknown Face Lockout Tests ───────────────────────────────────────────────

def test_check_unknown_rate_lockout(checker: CooldownChecker) -> None:
    device_id = uuid4()

    # Lockout threshold: 3 per minute (lowered for test efficiency)
    limit = 3
    lockout_seconds = 2

    # Send 3 unknown faces
    for _ in range(limit):
        assert checker.check_unknown_rate(
            device_id,
            unknown_rate_per_minute=limit,
            unknown_lockout_seconds=lockout_seconds,
        ) is False

    # 4th unknown face -> True (locked out!)
    assert checker.check_unknown_rate(
        device_id,
        unknown_rate_per_minute=limit,
        unknown_lockout_seconds=lockout_seconds,
    ) is True

    # Lockout blocks further tries
    assert checker.check_unknown_rate(
        device_id,
        unknown_rate_per_minute=limit,
        unknown_lockout_seconds=lockout_seconds,
    ) is True

    # Wait for lockout window (2 seconds) to expire
    time.sleep(2.1)

    # Allowed again
    assert checker.check_unknown_rate(
        device_id,
        unknown_rate_per_minute=limit,
        unknown_lockout_seconds=lockout_seconds,
    ) is False


def test_check_unknown_rate_lockout_extended(checker: CooldownChecker) -> None:
    from unittest.mock import patch
    device_id = uuid4()
    limit = 3
    lockout_seconds = 120  # 2 minutes

    start_time = 1700000000.0

    with patch("time.time") as mock_time, patch("time.monotonic") as mock_mono:
        # Initial time
        current_time = start_time
        mock_time.return_value = current_time
        mock_mono.return_value = current_time

        # Send 3 unknown faces
        for _ in range(limit):
            assert checker.check_unknown_rate(
                device_id,
                unknown_rate_per_minute=limit,
                unknown_lockout_seconds=lockout_seconds,
            ) is False
            # Increment time slightly
            current_time += 1.0
            mock_time.return_value = current_time
            mock_mono.return_value = current_time

        # 4th unknown face -> locked out
        assert checker.check_unknown_rate(
            device_id,
            unknown_rate_per_minute=limit,
            unknown_lockout_seconds=lockout_seconds,
        ) is True

        # Fast forward time by 65 seconds (total elapsed = 68 seconds)
        # This is more than 60 seconds (rate window), but less than 120 seconds (lockout window)
        current_time += 65.0
        mock_time.return_value = current_time
        mock_mono.return_value = current_time

        # Should STILL be locked out!
        assert checker.check_unknown_rate(
            device_id,
            unknown_rate_per_minute=limit,
            unknown_lockout_seconds=lockout_seconds,
        ) is True

        # Fast forward past lockout window (total elapsed = 125 seconds)
        current_time += 55.0
        mock_time.return_value = current_time
        mock_mono.return_value = current_time

        # Simulating TTL expiration in Redis (which has its own clock)
        if hasattr(checker, "client"):
            checker.client.delete(f"scan:lockout:{device_id}")

        # Lockout expired -> should be allowed now
        assert checker.check_unknown_rate(
            device_id,
            unknown_rate_per_minute=limit,
            unknown_lockout_seconds=lockout_seconds,
        ) is False


