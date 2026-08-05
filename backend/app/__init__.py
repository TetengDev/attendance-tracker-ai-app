"""Application package."""

import os
import sys
from pathlib import Path

# Load .env file manually into os.environ if it exists and not running tests
if "pytest" not in sys.modules and "PYTEST_CURRENT_TEST" not in os.environ:
    env_path = Path(__file__).resolve().parents[2] / ".env"
    if env_path.exists():
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    key, val = line.split("=", 1)
                    os.environ.setdefault(key.strip(), val.strip())
