"""Device pairing and JWT exchange endpoints."""

from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from backend.app.api.common import (
    ActorDep,
    AdminUserDep,
    RequestActor,
    SessionDep,
    StrictSchema,
    audited_mutation,
    commit_or_422,
    require_org_admin,
    snapshot,
)
from backend.app.auth.device import (
    generate_pairing_code,
    get_device_token_key,
    global_revocation_registry,
    hash_device_token,
    hash_pairing_code,
    issue_device_jwt,
    verify_device_token,
)
from backend.app.config import get_settings
from backend.app.errors import ErrorCode, make_error
from backend.app.models.devices import Device

router = APIRouter(tags=["devices"])

# Fields we audit for changes
DEVICE_PAIRED_FIELDS = ("id", "token_display_prefix", "pairing_code_expires_at")


# ── Schemas ─────────────────────────────────────────────────────────────────

class PairRequest(StrictSchema):
    pairing_code: str


class PairResponse(StrictSchema):
    device_id: UUID
    device_token: str


class TokenRequest(StrictSchema):
    device_id: UUID
    device_token: str


class TokenResponse(StrictSchema):
    device_token_jwt: str


class PairingCodeResponse(StrictSchema):
    pairing_code: str
    expires_at: datetime


# ── Admin Routes ────────────────────────────────────────────────────────────

@router.post(
    "/api/devices/{device_id}/pairing-code",
    response_model=PairingCodeResponse,
    status_code=201,
)
async def generate_device_pairing_code(
    device_id: UUID,
    session: SessionDep,
    admin_user: AdminUserDep,
    actor: ActorDep,
) -> PairingCodeResponse:
    """Generate a temporary 8-character pairing code for a device."""
    require_org_admin(admin_user)

    device = await session.get(Device, device_id)
    if device is None:
        raise HTTPException(status_code=404, detail="Device not found")

    before = snapshot(device, DEVICE_PAIRED_FIELDS)

    # Generate new pairing code
    code = generate_pairing_code()
    expires_at = datetime.now(tz=UTC) + timedelta(minutes=15)

    device.pairing_code_hash = hash_pairing_code(code)
    device.pairing_code_expires_at = expires_at

    actor_admin = RequestActor(admin_user.id, actor.request_id, actor.ip_address)
    await audited_mutation(
        session,
        actor_admin,
        action="device.generate_pairing_code",
        entity_type="device",
        entity_id=str(device.id),
        before=before,
        after=snapshot(device, DEVICE_PAIRED_FIELDS),
    )
    await commit_or_422(session)

    return PairingCodeResponse(pairing_code=code, expires_at=expires_at)


# ── Kiosk Routes ────────────────────────────────────────────────────────────

@router.post("/api/kiosk/pair", response_model=PairResponse)
async def pair_device(
    payload: PairRequest,
    session: SessionDep,
    actor: ActorDep,
) -> PairResponse:
    """Exchange an 8-character pairing code for a long-lived device token."""
    # Find the device with this active pairing code
    code_hash = hash_pairing_code(payload.pairing_code)
    now = datetime.now(tz=UTC)

    result = await session.execute(
        select(Device)
        .where(Device.pairing_code_hash == code_hash)
        .where(Device.pairing_code_expires_at > now)
    )
    device = result.scalar_one_or_none()

    if device is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=make_error(ErrorCode.DEVICE_REVOKED, "Invalid or expired pairing code"),
        )

    before = snapshot(device, DEVICE_PAIRED_FIELDS)

    # Generate long-lived opaque 32-byte device token
    raw_token = secrets.token_urlsafe(32)

    # Compute server-side HMAC representation
    settings = get_settings()
    key = get_device_token_key(settings.biometric_kek.get_secret_value())
    device.token_hash = hash_device_token(raw_token, key)
    device.token_display_prefix = raw_token[:6]

    # Clear pairing code (single-use)
    device.pairing_code_hash = None
    device.pairing_code_expires_at = None

    actor_kiosk = RequestActor(None, actor.request_id, actor.ip_address)
    await audited_mutation(
        session,
        actor_kiosk,
        action="device.pair",
        entity_type="device",
        entity_id=str(device.id),
        before=before,
        after=snapshot(device, DEVICE_PAIRED_FIELDS),
    )
    await commit_or_422(session)

    return PairResponse(device_id=device.id, device_token=raw_token)


@router.post("/api/kiosk/token", response_model=TokenResponse)
async def refresh_device_token(
    payload: TokenRequest,
    session: SessionDep,
) -> TokenResponse:
    """Exchange a long-lived device token for a short-lived 15-minute scan JWT."""
    device = await session.get(Device, payload.device_id)
    if device is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=make_error(ErrorCode.DEVICE_REVOKED, "Device not found"),
        )

    # Check if device is in the revocation set
    if global_revocation_registry.is_revoked(payload.device_id):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=make_error(ErrorCode.DEVICE_REVOKED, "Device is revoked"),
        )

    # Verify device token HMAC
    settings = get_settings()
    key = get_device_token_key(settings.biometric_kek.get_secret_value())
    if not verify_device_token(payload.device_token, device.token_hash, key):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=make_error(ErrorCode.DEVICE_REVOKED, "Invalid device credentials"),
        )

    # Issue short-lived JWT (uses KEK SecretStr string value as the secret)
    jwt_secret_val = settings.jwt_secret.get_secret_value()
    token_jwt = issue_device_jwt(device.id, payload.device_token, jwt_secret_val)

    return TokenResponse(device_token_jwt=token_jwt)
