"""Pytest configuration and global fixtures.

Sets up default environment variables for KEK and databases at initialization time
to prevent import-time key configuration failures.
"""

from __future__ import annotations

import base64
import os

# Set valid default environment variables before any modules are imported
if not os.environ.get("BIOMETRIC_KEK"):
    os.environ["BIOMETRIC_KEK"] = "kek.v1:-ry91V2agNGowleP-YgCe5Vpbyhy2yXDAvZFMcegjl8"

if not os.environ.get("DATABASE_URL"):
    os.environ["DATABASE_URL"] = "postgresql+asyncpg://localhost:5432/attendance"

if not os.environ.get("REDIS_URL"):
    os.environ["REDIS_URL"] = "redis://localhost:6379/0"
