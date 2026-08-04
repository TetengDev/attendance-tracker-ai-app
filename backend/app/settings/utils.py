"""Settings type parsing and validation helpers."""

from __future__ import annotations


def get_int_setting(settings: dict[str, object], key: str) -> int:
    """Validate and return an integer setting."""
    value = settings[key]
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{key} must be int")
    return value


def get_float_setting(settings: dict[str, object], key: str) -> float:
    """Validate and return a float/numeric setting."""
    value = settings[key]
    if not isinstance(value, int | float):
        raise TypeError(f"{key} must be numeric")
    return float(value)


def get_bool_setting(settings: dict[str, object], key: str) -> bool:
    """Validate and return a boolean setting."""
    value = settings[key]
    if not isinstance(value, bool):
        raise TypeError(f"{key} must be bool")
    return value
