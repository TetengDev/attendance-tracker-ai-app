from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID

from backend.app.models.settings import SettingScope
from backend.app.settings.registry import (
    SETTINGS_SCHEMA,
    SettingSpec,
    SettingValidationError,
    validate_setting,
)

SCOPE_PRECEDENCE: tuple[SettingScope, ...] = (
    SettingScope.DEVICE,
    SettingScope.LOCATION,
    SettingScope.ORG,
)
SETTINGS_VERSION_NAMESPACE = "global"

SCHEMA_SCOPE_TO_SETTING_SCOPES: dict[str, tuple[SettingScope, ...]] = {
    "O": (SettingScope.ORG,),
    "O·L": (SettingScope.ORG, SettingScope.LOCATION),
    "O·D": (SettingScope.ORG, SettingScope.DEVICE),
    "O·L·D": (SettingScope.ORG, SettingScope.LOCATION, SettingScope.DEVICE),
}


@dataclass(frozen=True)
class SettingContext:
    location_id: UUID | None = None
    device_id: UUID | None = None


@dataclass(frozen=True)
class SettingValue:
    key: str
    scope: SettingScope
    scope_id: UUID | None
    value: Any
    version: int


@dataclass(frozen=True)
class ResolvedSetting:
    key: str
    value: Any
    source: SettingScope | str
    source_id: UUID | None
    version: int


@dataclass(frozen=True)
class ResolvedSettings:
    settings: dict[str, Any]
    settings_version: int


class SettingsStore(Protocol):
    def current_version(self) -> int: ...

    def list_values(self) -> Iterable[SettingValue]: ...

    def upsert_value(
        self,
        *,
        key: str,
        scope: SettingScope,
        scope_id: UUID | None,
        value: Any,
    ) -> SettingValue: ...


class SettingsPublisher(Protocol):
    def publish_invalidation(self, version: int) -> None: ...


class NoopSettingsPublisher:
    def publish_invalidation(self, version: int) -> None:
        _ = version


class InMemorySettingsStore:
    def __init__(self, values: Iterable[SettingValue] = ()) -> None:
        self._values: dict[tuple[str, SettingScope, UUID | None], SettingValue] = {}
        self._version = 1
        for value in values:
            self._values[_value_key(value.key, value.scope, value.scope_id)] = value
            self._version = max(self._version, value.version)

    def current_version(self) -> int:
        return self._version

    def list_values(self) -> Iterable[SettingValue]:
        return tuple(self._values.values())

    def upsert_value(
        self,
        *,
        key: str,
        scope: SettingScope,
        scope_id: UUID | None,
        value: Any,
    ) -> SettingValue:
        validated_value = validate_setting_for_scope(key, value, scope, scope_id)
        self._version += 1
        setting = SettingValue(
            key=key,
            scope=scope,
            scope_id=scope_id,
            value=validated_value,
            version=self._version,
        )
        self._values[_value_key(key, scope, scope_id)] = setting
        return setting


class RecordingSettingsPublisher:
    def __init__(self) -> None:
        self.published_versions: list[int] = []

    def publish_invalidation(self, version: int) -> None:
        self.published_versions.append(version)


class CachedSettingsResolver:
    def __init__(self, store: SettingsStore) -> None:
        self._store = store
        self._cached_version = 0
        self._values: tuple[SettingValue, ...] = ()

    @property
    def cached_version(self) -> int:
        return self._cached_version

    def invalidate(self, version: int) -> None:
        if version > self._cached_version:
            self._cached_version = 0

    def refresh_if_stale(self) -> None:
        store_version = self._store.current_version()
        if store_version == self._cached_version:
            return
        self._values = tuple(self._store.list_values())
        self._cached_version = store_version

    def resolve(self, key: str, context: SettingContext) -> ResolvedSetting:
        self.refresh_if_stale()
        return resolve_setting(
            key,
            self._values,
            context,
            version=self._cached_version,
        )

    def resolve_all(self, context: SettingContext) -> ResolvedSettings:
        self.refresh_if_stale()
        return resolve_settings(self._values, context, version=self._cached_version)


def update_setting(
    store: SettingsStore,
    publisher: SettingsPublisher,
    *,
    key: str,
    scope: SettingScope,
    scope_id: UUID | None,
    value: Any,
) -> SettingValue:
    setting = store.upsert_value(key=key, scope=scope, scope_id=scope_id, value=value)
    publisher.publish_invalidation(setting.version)
    return setting


def resolve_setting(
    key: str,
    values: Iterable[SettingValue],
    context: SettingContext,
    *,
    version: int = 1,
) -> ResolvedSetting:
    rows = tuple(values)
    spec = _schema_spec(key)
    allowed_scopes = SCHEMA_SCOPE_TO_SETTING_SCOPES[spec.scope]
    _validate_rows_for_key(key, rows)
    by_scope = {
        _value_key(value.key, value.scope, value.scope_id): value
        for value in rows
        if value.key == key
    }

    for scope in SCOPE_PRECEDENCE:
        scope_id = _scope_id_for_context(scope, context)
        if scope not in allowed_scopes or (scope != SettingScope.ORG and scope_id is None):
            continue
        scoped_value = by_scope.get(_value_key(key, scope, scope_id))
        if scoped_value is not None:
            return ResolvedSetting(
                key=key,
                value=validate_setting(key, scoped_value.value),
                source=scoped_value.scope,
                source_id=scoped_value.scope_id,
                version=max(version, scoped_value.version),
            )

    return ResolvedSetting(
        key=key,
        value=spec.default,
        source="default",
        source_id=None,
        version=version,
    )


def resolve_settings(
    values: Iterable[SettingValue],
    context: SettingContext,
    *,
    version: int = 1,
) -> ResolvedSettings:
    rows = tuple(values)
    _validate_rows(rows)
    resolved = {
        key: resolve_setting(key, rows, context, version=version).value for key in SETTINGS_SCHEMA
    }
    row_version = max((row.version for row in rows), default=version)
    return ResolvedSettings(settings=resolved, settings_version=max(version, row_version))


def validate_setting_for_scope(
    key: str,
    value: Any,
    scope: SettingScope,
    scope_id: UUID | None,
) -> Any:
    spec = _schema_spec(key)
    allowed_scopes = SCHEMA_SCOPE_TO_SETTING_SCOPES[spec.scope]
    if scope not in allowed_scopes:
        raise SettingValidationError(f"{key} cannot be set at {scope.value} scope")
    if scope == SettingScope.ORG and scope_id is not None:
        raise SettingValidationError("org-scoped settings must not include scope_id")
    if scope != SettingScope.ORG and scope_id is None:
        raise SettingValidationError(f"{scope.value}-scoped settings require scope_id")
    return validate_setting(key, value)


def scope_is_allowed(key: str, scope: SettingScope) -> bool:
    spec = _schema_spec(key)
    return scope in SCHEMA_SCOPE_TO_SETTING_SCOPES[spec.scope]


def setting_row_applies(row: SettingValue, context: SettingContext) -> bool:
    return _scope_id_for_context(row.scope, context) == row.scope_id


def setting_precedence(scope: SettingScope) -> int:
    return len(SCOPE_PRECEDENCE) - SCOPE_PRECEDENCE.index(scope)


def consumer_needs_settings_reload(loaded_version: int, current_version: int) -> bool:
    return loaded_version < current_version


def settings_version_for_health(store: SettingsStore) -> int:
    return store.current_version()


DEFAULT_SETTINGS_STORE = InMemorySettingsStore()


def _scope_id_for_context(scope: SettingScope, context: SettingContext) -> UUID | None:
    if scope == SettingScope.DEVICE:
        return context.device_id
    if scope == SettingScope.LOCATION:
        return context.location_id
    return None


def _value_key(
    key: str,
    scope: SettingScope,
    scope_id: UUID | None,
) -> tuple[str, SettingScope, UUID | None]:
    return (key, scope, scope_id)


def _schema_spec(key: str) -> SettingSpec:
    try:
        return SETTINGS_SCHEMA[key]
    except KeyError as exc:
        raise SettingValidationError(f"unknown setting key: {key}") from exc


def _validate_rows_for_key(key: str, values: Iterable[SettingValue]) -> None:
    for value in values:
        if value.key == key:
            validate_setting_for_scope(value.key, value.value, value.scope, value.scope_id)


def _validate_rows(values: Iterable[SettingValue]) -> None:
    for value in values:
        validate_setting_for_scope(value.key, value.value, value.scope, value.scope_id)
