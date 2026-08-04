"""In-memory cooldown, rate-limit, and impossible-travel checker.

Keys mirror the Redis key layout for production:
  scan:cooldown:{scope}:{person_id}[:{location_id}]  — last scan timestamp
  scan:last:{person_id}                                — (location_id, ts) for impossible-travel
  scan:rate:{device_id}                                — token bucket counter
  scan:unknown:{device_id}                             — unknown-face rate counter
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from uuid import UUID

from backend.app.scan.pipeline import CooldownChecker


class InMemoryCooldownChecker(CooldownChecker):
    """In-memory cooldown checker for tests and single-process dev mode.

    Not suitable for multi-process production deployment — use RedisCooldownChecker.
    """

    def __init__(self) -> None:
        # cooldown: key -> occurred_at
        self._cooldowns: dict[str, datetime] = {}
        # impossible travel: person_id -> (location_id, ts, location_source)
        self._last_scan: dict[UUID, tuple[UUID, datetime, str]] = {}
        # rate limit: device_id -> list of monotonic timestamps
        self._rate_log: dict[UUID, list[float]] = {}
        # unknown rate: device_id -> list of monotonic timestamps
        self._unknown_log: dict[UUID, list[float]] = {}
        # unknown lockout: device_id -> lockout_expires_at
        self._lockouts: dict[UUID, float] = {}

    def _cooldown_key(
        self,
        person_id: UUID,
        location_id: UUID,
        cooldown_scope: str,
        device_id: UUID | None = None,
    ) -> str:
        if cooldown_scope == "location":
            return f"scan:cooldown:location:{person_id}:{location_id}"
        if cooldown_scope == "device":
            if device_id is None:
                raise ValueError("device_id is required for device-scoped cooldown")
            return f"scan:cooldown:device:{person_id}:{device_id}"
        return f"scan:cooldown:{cooldown_scope}:{person_id}"

    def check_cooldown(
        self,
        person_id: UUID,
        location_id: UUID,
        location_source: str,
        *,
        cooldown_seconds: int,
        cooldown_scope: str,
        device_id: UUID | None = None,
    ) -> datetime | None:
        key = self._cooldown_key(person_id, location_id, cooldown_scope, device_id)
        last = self._cooldowns.get(key)
        if last is None:
            return None
        now = datetime.now(tz=UTC)
        elapsed = (now - last).total_seconds()
        if elapsed < cooldown_seconds:
            return last
        return None

    def set_cooldown(
        self,
        person_id: UUID,
        location_id: UUID,
        location_source: str,
        *,
        occurred_at: datetime,
        cooldown_seconds: int,
        cooldown_scope: str,
        device_id: UUID | None = None,
    ) -> None:
        # Set all possible scopes (global, location, device)
        scopes = ["location", "global"]
        if device_id is not None:
            scopes.append("device")
        for scope in scopes:
            key = self._cooldown_key(person_id, location_id, scope, device_id)
            self._cooldowns[key] = occurred_at

        # Update last-scan for impossible-travel
        self._last_scan[person_id] = (location_id, occurred_at, location_source)

    def check_impossible_travel(
        self,
        person_id: UUID,
        location_id: UUID,
        location_source: str,
        *,
        min_inter_location_seconds: int,
    ) -> bool:
        # Only check when both events are device_fixed
        if location_source != "device_fixed":
            return False

        last = self._last_scan.get(person_id)
        if last is None:
            return False

        last_location, last_ts, last_source = last
        # Only check when the last event also has location_source = device_fixed
        if last_source != "device_fixed":
            return False
        if last_location == location_id:
            return False

        now = datetime.now(tz=UTC)
        elapsed = (now - last_ts).total_seconds()
        return elapsed < min_inter_location_seconds

    def check_rate_limit(
        self,
        device_id: UUID,
        *,
        rate_per_second: int,
    ) -> bool:
        now = time.monotonic()
        log = self._rate_log.setdefault(device_id, [])
        # Trim old entries
        cutoff = now - 1.0
        self._rate_log[device_id] = [t for t in log if t > cutoff]
        log = self._rate_log[device_id]

        if len(log) >= rate_per_second:
            return True
        log.append(now)
        return False

    def check_unknown_rate(
        self,
        device_id: UUID,
        *,
        unknown_rate_per_minute: int,
        unknown_lockout_seconds: int,
    ) -> bool:
        now = time.monotonic()

        # Check if currently locked out
        lockout_expiry = self._lockouts.get(device_id)
        if lockout_expiry is not None:
            if now < lockout_expiry:
                return True
            else:
                del self._lockouts[device_id]

        log = self._unknown_log.setdefault(device_id, [])
        # Trim entries older than 60 seconds
        cutoff = now - 60.0
        self._unknown_log[device_id] = [t for t in log if t > cutoff]
        log = self._unknown_log[device_id]

        if len(log) >= unknown_rate_per_minute:
            # Trigger lockout
            self._lockouts[device_id] = now + unknown_lockout_seconds
            self._unknown_log[device_id] = []
            return True

        log.append(now)
        return False

    def reset(self) -> None:
        """Clear all state — useful between tests."""
        self._cooldowns.clear()
        self._last_scan.clear()
        self._rate_log.clear()
        self._unknown_log.clear()
        self._lockouts.clear()


class CooldownCheckerProxy(CooldownChecker):
    """Proxy that delegates to RedisCooldownChecker in production, or InMemory in tests."""

    def __init__(self) -> None:
        self._delegate: CooldownChecker | None = None

    @property
    def delegate(self) -> CooldownChecker:
        if self._delegate is None:
            import sys
            if "pytest" in sys.modules:
                self._delegate = InMemoryCooldownChecker()
            else:
                from backend.app.scan.limits import RedisCooldownChecker
                self._delegate = RedisCooldownChecker()
        return self._delegate

    def check_cooldown(
        self,
        person_id: UUID,
        location_id: UUID,
        location_source: str,
        *,
        cooldown_seconds: int,
        cooldown_scope: str,
        device_id: UUID | None = None,
    ) -> datetime | None:
        return self.delegate.check_cooldown(
            person_id,
            location_id,
            location_source,
            cooldown_seconds=cooldown_seconds,
            cooldown_scope=cooldown_scope,
            device_id=device_id,
        )

    def set_cooldown(
        self,
        person_id: UUID,
        location_id: UUID,
        location_source: str,
        *,
        occurred_at: datetime,
        cooldown_seconds: int,
        cooldown_scope: str,
        device_id: UUID | None = None,
    ) -> None:
        self.delegate.set_cooldown(
            person_id,
            location_id,
            location_source,
            occurred_at=occurred_at,
            cooldown_seconds=cooldown_seconds,
            cooldown_scope=cooldown_scope,
            device_id=device_id,
        )

    def check_impossible_travel(
        self,
        person_id: UUID,
        location_id: UUID,
        location_source: str,
        *,
        min_inter_location_seconds: int,
    ) -> bool:
        return self.delegate.check_impossible_travel(
            person_id,
            location_id,
            location_source,
            min_inter_location_seconds=min_inter_location_seconds,
        )

    def check_rate_limit(self, device_id: UUID, *, rate_per_second: int) -> bool:
        return self.delegate.check_rate_limit(device_id, rate_per_second=rate_per_second)

    def check_unknown_rate(
        self,
        device_id: UUID,
        *,
        unknown_rate_per_minute: int,
        unknown_lockout_seconds: int,
    ) -> bool:
        return self.delegate.check_unknown_rate(
            device_id,
            unknown_rate_per_minute=unknown_rate_per_minute,
            unknown_lockout_seconds=unknown_lockout_seconds,
        )

    def reset(self) -> None:
        self.delegate.reset()


global_cooldown_checker = CooldownCheckerProxy()
