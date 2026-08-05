from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select

from backend.app.auth.device import get_device_token_key, hash_device_token
from backend.app.auth.passwords import hash_admin_password
from backend.app.auth.totp import generate_totp_secret
from backend.app.config import get_settings
from backend.app.db.session import get_session_factory
from backend.app.models.admin import AdminRole, AdminUser
from backend.app.models.devices import (
    Device,
    DeviceDirection,
    DeviceFormFactor,
    DeviceMode,
    Location,
)

SEED_ADMIN_EMAIL = "admin@example.test"
SEED_ADMIN_PASSWORD = "change-me-now"
SEED_LOCATION_NAME = "Main Campus"
SEED_DEVICE_PREFIX = "dev_seed"


async def seed() -> None:
    async with get_session_factory()() as session, session.begin():
        admin = (
            await session.execute(select(AdminUser).where(AdminUser.email == SEED_ADMIN_EMAIL))
        ).scalar_one_or_none()
        if admin is None:
            session.add(
                AdminUser(
                    email=SEED_ADMIN_EMAIL,
                    display_name="Seed Admin",
                    password_hash=hash_admin_password(SEED_ADMIN_PASSWORD),
                    role=AdminRole.OWNER,
                    totp_secret=generate_totp_secret(),
                    password_changed_at=datetime.now(UTC),
                )
            )

        location = (
            await session.execute(select(Location).where(Location.name == SEED_LOCATION_NAME))
        ).scalar_one_or_none()
        if location is None:
            location = Location(name=SEED_LOCATION_NAME, timezone="Asia/Manila")
            session.add(location)
            await session.flush()

        settings = get_settings()
        key = get_device_token_key(settings.biometric_kek.get_secret_value())
        token_hash = hash_device_token("seed-device-token", key)

        device = (
            await session.execute(
                select(Device).where(Device.token_display_prefix == SEED_DEVICE_PREFIX)
            )
        ).scalar_one_or_none()
        if device is None:
            session.add(
                Device(
                    location_id=location.id or UUID(int=0),
                    mode=DeviceMode.FIXED,
                    form_factor=DeviceFormFactor.TABLET,
                    direction=DeviceDirection.BIDIRECTIONAL,
                    token_hash=token_hash,
                    token_display_prefix=SEED_DEVICE_PREFIX,
                    allowed_cidrs=["127.0.0.1/32"],
                    settings_override={},
                )
            )
        else:
            device.token_hash = token_hash


def main() -> None:
    asyncio.run(seed())


if __name__ == "__main__":
    main()
