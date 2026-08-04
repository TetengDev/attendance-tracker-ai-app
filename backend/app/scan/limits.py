"""Redis-backed cooldown, rate-limit, and impossible-travel checker for production."""

from __future__ import annotations

import time
from datetime import UTC, datetime
from uuid import UUID, uuid4

import redis

from backend.app.config import get_settings
from backend.app.scan.pipeline import CooldownChecker


class RedisCooldownChecker(CooldownChecker):
    """Redis-backed cooldown, rate-limit, and impossible-travel checker."""

    def __init__(self, redis_url: str | None = None) -> None:
        url = redis_url or get_settings().redis_url
        self.client = redis.from_url(url, decode_responses=True)

        # Register Lua script for rate limiting
        self._rate_limit_script = self.client.register_script("""
            local key = KEYS[1]
            local now = tonumber(ARGV[1])
            local limit = tonumber(ARGV[2])
            local member = ARGV[3]

            redis.call('ZREMRANGEBYSCORE', key, 0, now - 1.0)
            local count = redis.call('ZCARD', key)
            if count >= limit then
                return 1
            else
                redis.call('ZADD', key, now, member)
                redis.call('EXPIRE', key, 2)
                return 0
            end
        """)

        # Register Lua script for unknown-face lockout rate limiting
        self._unknown_rate_script = self.client.register_script("""
            local unknown_key = KEYS[1]
            local lockout_key = KEYS[2]
            local now = tonumber(ARGV[1])
            local limit = tonumber(ARGV[2])
            local lockout_window = tonumber(ARGV[3])
            local member = ARGV[4]

            -- Check if currently locked out
            if redis.call('EXISTS', lockout_key) == 1 then
                return 1
            end

            -- Clean up old entries in the sliding window (60 seconds)
            redis.call('ZREMRANGEBYSCORE', unknown_key, 0, now - 60.0)

            -- Count recent unknown scans
            local recent = redis.call('ZCARD', unknown_key)
            if recent >= limit then
                -- Trigger lockout: set lockout key and clear unknown scans
                redis.call('SET', lockout_key, 1, 'EX', lockout_window)
                redis.call('DEL', unknown_key)
                return 1
            else
                -- Add current scan and set TTL on the sliding window key
                redis.call('ZADD', unknown_key, now, member)
                redis.call('EXPIRE', unknown_key, 62)
                return 0
            end
        """)

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
        val = self.client.get(key)
        if not isinstance(val, str):
            return None
        try:
            return datetime.fromisoformat(val)
        except (ValueError, TypeError):
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

        pipe = self.client.pipeline()
        for scope in scopes:
            key = self._cooldown_key(person_id, location_id, scope, device_id)
            pipe.set(key, occurred_at.isoformat(), ex=cooldown_seconds)

        # Update last-scan for impossible-travel (location_id|ts|location_source)
        last_scan_key = f"scan:last:{person_id}"
        val = f"{location_id}|{occurred_at.isoformat()}|{location_source}"
        pipe.set(last_scan_key, val, ex=86400)  # expires in 24 hours to prevent leak

        pipe.execute()

    def check_impossible_travel(
        self,
        person_id: UUID,
        location_id: UUID,
        location_source: str,
        *,
        min_inter_location_seconds: int,
    ) -> bool:
        # Only check when the current event has location_source = device_fixed
        if location_source != "device_fixed":
            return False

        last_scan_key = f"scan:last:{person_id}"
        val = self.client.get(last_scan_key)
        if not isinstance(val, str):
            return False

        parts = val.split("|", maxsplit=2)
        if len(parts) < 2:
            return False

        last_location = UUID(parts[0])
        last_ts = datetime.fromisoformat(parts[1])
        last_source = parts[2] if len(parts) > 2 else "device_fixed"

        # Only check when the last event also has location_source = device_fixed
        if last_source != "device_fixed":
            return False

        # No travel check if scan is at the same location
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
        key = f"scan:rate:{device_id}"
        now = time.time()
        member = f"{now}:{uuid4()}"
        res = self._rate_limit_script(keys=[key], args=[now, rate_per_second, member])
        return bool(res)

    def check_unknown_rate(
        self,
        device_id: UUID,
        *,
        unknown_rate_per_minute: int,
        unknown_lockout_seconds: int,
    ) -> bool:
        unknown_key = f"scan:unknown:{device_id}"
        lockout_key = f"scan:lockout:{device_id}"
        now = time.time()
        member = f"{now}:{uuid4()}"
        res = self._unknown_rate_script(
            keys=[unknown_key, lockout_key],
            args=[now, unknown_rate_per_minute, unknown_lockout_seconds, member]
        )
        return bool(res)

    def reset(self) -> None:
        """Delete all keys matching scan:* from Redis."""
        keys = self.client.keys("scan:*")
        if keys:
            self.client.delete(*keys)
