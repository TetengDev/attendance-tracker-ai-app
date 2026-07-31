from __future__ import annotations

from typing import cast
from uuid import UUID

from sqlalchemy import Table

from backend.app.models.settings import Setting, SettingScope, SettingsVersion

SCOPE_ID = UUID("00000000-0000-0000-0000-000000000001")


def test_settings_models_define_tables() -> None:
    assert Setting.__tablename__ == "settings"
    assert SettingsVersion.__tablename__ == "settings_versions"


def test_setting_model_encodes_scope_and_version_constraints() -> None:
    table = cast(Table, Setting.__table__)
    constraints = {constraint.name for constraint in table.constraints}

    assert "uq_settings_key_scope_scope_id" in constraints
    assert "ck_settings_key_non_empty" in constraints
    assert "ck_settings_scope_valid" in constraints
    assert "ck_settings_non_org_scope_requires_scope_id" in constraints
    assert "ck_settings_version_positive" in constraints


def test_settings_version_model_is_monotonic_namespace_row() -> None:
    table = cast(Table, SettingsVersion.__table__)
    constraints = {constraint.name for constraint in table.constraints}
    version = SettingsVersion(current_version=2)

    assert table.columns["namespace"].primary_key
    assert version.current_version == 2
    assert "ck_settings_versions_current_version_positive" in constraints


def test_setting_row_stamps_value_scope_and_version() -> None:
    setting = Setting(
        key="kiosk.greeting_text",
        scope=SettingScope.DEVICE,
        scope_id=SCOPE_ID,
        value="Good morning",
        version=7,
    )

    assert setting.scope == SettingScope.DEVICE
    assert setting.scope_id == SCOPE_ID
    assert setting.version == 7
