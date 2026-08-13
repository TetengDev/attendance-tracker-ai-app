from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from backend.app.api.common import AdminUserDep, SessionDep, StrictSchema, require_org_admin
from backend.app.settings.registry import SETTINGS_SCHEMA, default_settings

router = APIRouter(prefix="/api/settings", tags=["settings"])


class SettingInfo(StrictSchema):
    key: str
    type: str
    default: Any
    value: Any
    scope: str
    min: int | float | None = None
    max: int | float | None = None
    enum: list[str] | None = None
    max_length: int | None = None
    format: str | None = None
    note: str | None = None
    category: str


class SettingsResponse(StrictSchema):
    settings: list[SettingInfo]


@router.get("", response_model=SettingsResponse)
async def get_settings_schema(
    session: SessionDep,
    admin_user: AdminUserDep,
) -> SettingsResponse:
    require_org_admin(admin_user)
    defaults = default_settings()

    settings_list = []
    for key, spec in SETTINGS_SCHEMA.items():
        category = key.split(".")[0]
        settings_list.append(
            SettingInfo(
                key=key,
                type=spec.type,
                default=spec.default,
                value=defaults.get(key, spec.default),
                scope=spec.scope,
                min=spec.min,
                max=spec.max,
                enum=list(spec.enum) if spec.enum else None,
                max_length=spec.max_length,
                format=spec.format,
                note=spec.note,
                category=category,
            )
        )

    return SettingsResponse(settings=settings_list)
