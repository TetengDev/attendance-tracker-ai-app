"""Session copy of backend/app/settings/registry.py: SETTINGS_SCHEMA + helpers

Saved to session-state due to repository filesystem permissions. Move into the
repo at backend/app/settings/registry.py once permissions allow.
"""
from typing import Any, Dict, List

SETTINGS_SCHEMA: Dict[str, Dict[str, Any]] = {
    "face.match_threshold": {"type": "float", "default": 0.45, "range": (0.20, 0.80), "scope": "O"},
    "face.match_margin": {"type": "float", "default": 0.05, "range": (0.0, 0.30), "scope": "O"},
    # ... truncated in-session copy; full file lives in session-state for now
}


def validate_setting(key: str, value: Any) -> Any:
    if key not in SETTINGS_SCHEMA:
        raise ValueError("unknown key")
    meta = SETTINGS_SCHEMA[key]
    t = meta.get("type")
    if t == "float":
        return float(value)
    if t == "int":
        return int(value)
    return value


def default_settings() -> Dict[str, Any]:
    return {k: m.get("default") for k, m in SETTINGS_SCHEMA.items()}
