from __future__ import annotations

from uuid import UUID

import pytest

from backend.app.models.settings import SettingScope
from backend.app.settings.registry import SettingValidationError
from backend.app.settings.resolver import (
    CachedSettingsResolver,
    InMemorySettingsStore,
    RecordingSettingsPublisher,
    SettingContext,
    SettingValue,
    consumer_needs_settings_reload,
    resolve_setting,
    resolve_settings,
    scope_is_allowed,
    setting_precedence,
    setting_row_applies,
    update_setting,
)

LOCATION_ID = UUID("00000000-0000-0000-0000-000000000001")
DEVICE_ID = UUID("00000000-0000-0000-0000-000000000002")
OTHER_LOCATION_ID = UUID("00000000-0000-0000-0000-000000000003")
CONTEXT = SettingContext(location_id=LOCATION_ID, device_id=DEVICE_ID)


def test_resolver_returns_code_default_without_rows() -> None:
    resolved = resolve_setting("kiosk.greeting_text", [], CONTEXT, version=1)

    assert resolved.value == "Welcome"
    assert resolved.source == "default"
    assert resolved.version == 1


def test_resolution_precedence_is_device_location_org_default() -> None:
    rows = [
        setting("kiosk.greeting_text", SettingScope.ORG, None, "Org", version=2),
        setting("kiosk.greeting_text", SettingScope.LOCATION, LOCATION_ID, "Location", version=3),
        setting("kiosk.greeting_text", SettingScope.DEVICE, DEVICE_ID, "Device", version=4),
    ]

    resolved = resolve_setting("kiosk.greeting_text", rows, CONTEXT, version=4)

    assert resolved.value == "Device"
    assert resolved.source == SettingScope.DEVICE
    assert resolved.source_id == DEVICE_ID


def test_location_override_wins_when_device_override_missing() -> None:
    rows = [
        setting("kiosk.greeting_text", SettingScope.ORG, None, "Org", version=2),
        setting("kiosk.greeting_text", SettingScope.LOCATION, LOCATION_ID, "Location", version=3),
    ]

    assert resolve_setting("kiosk.greeting_text", rows, CONTEXT, version=3).value == "Location"


def test_non_matching_scoped_rows_are_ignored() -> None:
    rows = [
        setting("kiosk.greeting_text", SettingScope.ORG, None, "Org", version=2),
        setting(
            "kiosk.greeting_text", SettingScope.LOCATION, OTHER_LOCATION_ID, "Other", version=3
        ),
    ]

    assert resolve_setting("kiosk.greeting_text", rows, CONTEXT, version=3).value == "Org"


def test_invalid_schema_scope_is_rejected() -> None:
    rows = [setting("face.match_threshold", SettingScope.DEVICE, DEVICE_ID, 0.5, version=2)]

    with pytest.raises(SettingValidationError, match="cannot be set at device scope"):
        resolve_setting("face.match_threshold", rows, CONTEXT, version=2)


def test_invalid_setting_value_is_rejected() -> None:
    rows = [setting("scan.rate_per_second", SettingScope.DEVICE, DEVICE_ID, 0, version=2)]

    with pytest.raises(SettingValidationError, match="scan.rate_per_second must be >= 1"):
        resolve_setting("scan.rate_per_second", rows, CONTEXT, version=2)


def test_unknown_setting_key_is_rejected() -> None:
    with pytest.raises(SettingValidationError, match="unknown setting key"):
        resolve_setting("does.not.exist", [], CONTEXT)


def test_resolve_all_rejects_unknown_persisted_setting_rows() -> None:
    rows = [setting("invented.key", SettingScope.ORG, None, "oops", version=2)]

    with pytest.raises(SettingValidationError, match="unknown setting key"):
        resolve_settings(rows, CONTEXT, version=2)


def test_resolve_all_returns_schema_defaults_and_durable_version() -> None:
    rows = [setting("kiosk.greeting_text", SettingScope.ORG, None, "Hello", version=6)]

    resolved = resolve_settings(rows, CONTEXT, version=5)

    assert resolved.settings["kiosk.greeting_text"] == "Hello"
    assert resolved.settings["face.match_threshold"] == 0.45
    assert resolved.settings_version == 6


def test_cached_resolver_polls_version_so_pubsub_is_not_correctness() -> None:
    store = InMemorySettingsStore()
    publisher = RecordingSettingsPublisher()
    resolver = CachedSettingsResolver(store)

    assert resolver.resolve("kiosk.greeting_text", CONTEXT).value == "Welcome"
    update_setting(
        store,
        publisher,
        key="kiosk.greeting_text",
        scope=SettingScope.DEVICE,
        scope_id=DEVICE_ID,
        value="Welcome back",
    )

    assert publisher.published_versions == [2]
    assert resolver.resolve("kiosk.greeting_text", CONTEXT).value == "Welcome back"
    assert resolver.cached_version == 2


def test_scope_helpers_and_stale_consumer_detection() -> None:
    row = setting("kiosk.greeting_text", SettingScope.LOCATION, LOCATION_ID, "Location", version=3)

    assert scope_is_allowed("kiosk.greeting_text", SettingScope.DEVICE)
    assert not scope_is_allowed("face.match_threshold", SettingScope.DEVICE)
    assert setting_row_applies(row, CONTEXT)
    assert setting_precedence(SettingScope.DEVICE) > setting_precedence(SettingScope.ORG)
    assert consumer_needs_settings_reload(loaded_version=4, current_version=5)
    assert not consumer_needs_settings_reload(loaded_version=5, current_version=5)


def setting(
    key: str,
    scope: SettingScope,
    scope_id: UUID | None,
    value: object,
    *,
    version: int,
) -> SettingValue:
    return SettingValue(
        key=key,
        scope=scope,
        scope_id=scope_id,
        value=value,
        version=version,
    )
