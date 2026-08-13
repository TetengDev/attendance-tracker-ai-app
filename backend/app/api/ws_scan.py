"""WebSocket scan endpoint (TEN-41) for kiosk device connection.

This endpoint handles hello handshake (authenticated by server-signed JWTs),
periodic heartbeats with heartbeat logging, settings pushes on version bump,
and processing frame bursts using the server scan pipeline and combining
frame outputs according to the burst truth table.
"""

from __future__ import annotations

import base64
import binascii
import logging
import secrets
from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

import jwt
from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect, status
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.api.schemas.kiosk import (
    CheckIn,
    ClientMessageType,
    ErrorBody,
    ErrorMessage,
    FrameBurst,
    Heartbeat,
    Hello,
    Person,
    Ready,
    Result,
    ServerMessageType,
    SettingsPush,
)
from backend.app.auth.device import (
    decode_device_jwt,
    get_device_token_key,
    global_revocation_registry,
    hash_device_token,
    is_ip_allowed,
)
from backend.app.config import get_settings
from backend.app.crypto.envelope import EncryptedPayload, decrypt_embedding
from backend.app.db.session import get_session
from backend.app.errors import DomainError, ErrorCode
from backend.app.face.gallery import (
    GalleryEntry,
    GalleryIndex,
    current_gallery_version,
)
from backend.app.face.protocol import FaceEngine
from backend.app.models.attendance import (
    AttendanceEvent,
    AttendanceEventOutcome,
    AttendanceLocationSource,
)
from backend.app.models.biometrics import FaceEmbedding
from backend.app.models.devices import Device, DeviceHeartbeat, DeviceMode
from backend.app.models.settings import Setting, SettingsVersion
from backend.app.scan.cooldown import global_cooldown_checker
from backend.app.scan.pipeline import (
    PersonLookup,
    ScanInput,
    ScanOutput,
    run_scan_pipeline,
)
from backend.app.scan.sessions import (
    ScanSessionError,
    active_scan_session_for_device,
    require_scan_attribution,
)
from backend.app.settings.resolver import (
    ResolvedSettings,
    SettingContext,
    SettingValue,
    resolve_settings,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/kiosk", tags=["kiosk"])


# ---------------------------------------------------------------------------
# Database Helpers
# ---------------------------------------------------------------------------


async def load_active_gallery_entries(
    db: AsyncSession,
    model_name: str,
    model_version: str,
) -> list[GalleryEntry]:
    """Retrieve and decrypt all active face embeddings from the database."""
    result = await db.execute(
        select(FaceEmbedding).where(
            FaceEmbedding.is_active.is_(True),
            FaceEmbedding.model_name == model_name,
            FaceEmbedding.model_version == model_version,
        )
    )
    db_embeddings = result.scalars().all()
    entries = []
    for emb in db_embeddings:
        payload = EncryptedPayload(
            version=emb.envelope_version,
            payload_alg=emb.payload_alg,
            dek_wrap_alg=emb.dek_wrap_alg,
            encryption_key_id=emb.encryption_key_id,
            wrapped_dek=emb.wrapped_dek,
            dek_nonce=emb.dek_nonce,
            payload_nonce=emb.payload_nonce,
            ciphertext=emb.ciphertext,
        )
        try:
            aad = f"face-embedding:{emb.person_id}:{emb.encryption_asset_id}".encode()
            vector = decrypt_embedding(payload, aad=aad)
            entries.append(
                GalleryEntry(
                    person_id=emb.person_id,
                    embedding_id=emb.id,
                    vector=vector,
                )
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to decrypt embedding %s: %s", emb.id, exc)
    return entries


async def resolve_db_settings(
    db: AsyncSession,
    context: SettingContext,
) -> ResolvedSettings:
    """Retrieve all setting values from the database and resolve them for context."""
    result = await db.execute(select(Setting))
    db_settings = result.scalars().all()

    values = [
        SettingValue(
            key=s.key,
            scope=s.scope,
            scope_id=s.scope_id,
            value=s.value,
            version=s.version,
        )
        for s in db_settings
    ]

    settings_ver = await db.execute(
        select(SettingsVersion.current_version).where(SettingsVersion.namespace == "global")
    )
    ver = settings_ver.scalar_one_or_none() or 1

    return resolve_settings(values, context, version=ver)


class DbPersonLookup(PersonLookup):
    """Production person lookup fetching name from database."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    def get_display_name(self, person_id: UUID) -> str | None:
        return None


# ---------------------------------------------------------------------------
# Dependency Helpers
# ---------------------------------------------------------------------------


from backend.app.api.enrollment import get_face_engine, get_gallery_index

# ---------------------------------------------------------------------------
# WebSocket Handler
# ---------------------------------------------------------------------------


def get_client_ip(websocket: WebSocket) -> str:
    """Resolve client IP address, supporting proxy headers securely.

    Checks X-Real-IP first as reverse proxies (e.g. Caddy/Nginx) always overwrite it,
    preventing client-side header spoofing. Falls back to X-Forwarded-For.
    """
    real_ip = websocket.headers.get("x-real-ip")
    if real_ip:
        return real_ip.strip()

    forwarded_for = websocket.headers.get("x-forwarded-for")
    if forwarded_for:
        # X-Forwarded-For can contain a list of proxy IPs; leftmost is original client
        client_ip = forwarded_for.split(",")[0].strip()
        if client_ip:
            return client_ip

    if websocket.client is not None:
        host = websocket.client.host
        if host == "testclient":
            return "127.0.0.1"
        return host
    return "127.0.0.1"


@router.websocket("/ws")
async def kiosk_websocket_endpoint(
    websocket: WebSocket,
    session: Annotated[AsyncSession, Depends(get_session)],
    face_engine: Annotated[FaceEngine, Depends(get_face_engine)],
    gallery_index: Annotated[GalleryIndex, Depends(get_gallery_index)],
) -> None:
    await websocket.accept()

    device: Device | None = None
    settings_ver = 0

    try:
        # 1. Wait for hello message
        payload = await websocket.receive_json()
        try:
            hello = Hello.model_validate(payload)
        except ValidationError as exc:
            await websocket.send_json(
                ErrorMessage(
                    type=ServerMessageType.ERROR,
                    error=ErrorBody(code=ErrorCode.VALIDATION_ERROR, message=str(exc)),
                ).model_dump(mode="json")
            )
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return

        # 2. Authenticate device token from JWT
        settings = get_settings()
        try:
            # Decode the short-lived JWT (uses settings.jwt_secret)
            jwt_secret_val = settings.jwt_secret.get_secret_value()
            claims = decode_device_jwt(hello.device_token_jwt, jwt_secret_val)
            device_id = UUID(claims["sub"])
        except (jwt.InvalidTokenError, KeyError, ValueError) as exc:
            await websocket.send_json(
                ErrorMessage(
                    type=ServerMessageType.ERROR,
                    error=ErrorBody(
                        code=ErrorCode.DEVICE_REVOKED,
                        message=f"Invalid device token JWT: {exc}",
                    ),
                ).model_dump(mode="json")
            )
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return

        # Fetch and verify device
        device = await session.get(Device, device_id)
        if device is None:
            await websocket.send_json(
                ErrorMessage(
                    type=ServerMessageType.ERROR,
                    error=ErrorBody(
                        code=ErrorCode.DEVICE_REVOKED,
                        message="Device not found",
                    ),
                ).model_dump(mode="json")
            )
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return
        # Cache frequently-used attributes to avoid triggering lazy DB loads
        # (which can call await-only SQLAlchemy helpers outside a greenlet)
        cached_device_id = device_id
        cached_allowed_cidrs = device.allowed_cidrs
        cached_device_mode = device.mode
        cached_location_id = device.location_id
        
        # Check revocation status
        if global_revocation_registry.is_revoked(cached_device_id):
            await websocket.send_json(
                ErrorMessage(
                    type=ServerMessageType.ERROR,
                    error=ErrorBody(
                        code=ErrorCode.DEVICE_REVOKED,
                        message="Device revoked",
                    ),
                ).model_dump(mode="json")
            )
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return

        # Check allowed CIDRs
        client_ip = get_client_ip(websocket)
        if not is_ip_allowed(client_ip, cached_allowed_cidrs):
            await websocket.send_json(
                ErrorMessage(
                    type=ServerMessageType.ERROR,
                    error=ErrorBody(
                        code=ErrorCode.DEVICE_REVOKED,
                        message="Client IP address not allowed",
                    ),
                ).model_dump(mode="json")
            )
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return

        # Check location condition for fixed devices
        if cached_device_mode == DeviceMode.FIXED and cached_location_id is None:
            await websocket.send_json(
                ErrorMessage(
                    type=ServerMessageType.ERROR,
                    error=ErrorBody(
                        code=ErrorCode.DEVICE_REVOKED,
                        message="Fixed devices require a configured location",
                    ),
                ).model_dump(mode="json")
            )
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return

        # 3. Synchronize gallery index and get settings context
        async def load_entries_fn() -> list[GalleryEntry]:
            return await load_active_gallery_entries(
                session,
                face_engine.model_name,
                face_engine.model_version,
            )

        await gallery_index.reload_if_stale(session, load_entries_fn)

        context = SettingContext(location_id=device.location_id, device_id=device.id)
        resolved = await resolve_db_settings(session, context)
        settings_ver = resolved.settings_version

        gallery_ver = await current_gallery_version(session)

        # Send ready message
        await websocket.send_json(
            Ready(
                type=ServerMessageType.READY,
                gallery_version=gallery_ver,
                settings_version=settings_ver,
            ).model_dump(mode="json")
        )

        # Push current settings
        await websocket.send_json(
            SettingsPush(
                type=ServerMessageType.SETTINGS_PUSH,
                settings_version=settings_ver,
                payload=resolved.settings,
            ).model_dump(mode="json")
        )

        device_id = device.id
        # 4. Message loop
        while True:
            try:
                payload = await websocket.receive_json()
                # Refresh/bind the device instance to ensure it's not expired from previous commits/rollbacks
                device_db = await session.get(Device, device_id)
                if device_db is None:
                    await websocket.send_json(
                        ErrorMessage(
                            type=ServerMessageType.ERROR,
                            error=ErrorBody(
                                code=ErrorCode.DEVICE_REVOKED,
                                message="Device has been revoked",
                            ),
                        ).model_dump(mode="json")
                    )
                    await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
                    return
                device = device_db

                msg_type = payload.get("type")
                if msg_type == ClientMessageType.HEARTBEAT:
                    heartbeat = Heartbeat.model_validate(payload)
                    
                    # Immediate revocation check on heartbeat
                    if global_revocation_registry.is_revoked(device.id):
                        await websocket.send_json(
                            ErrorMessage(
                                type=ServerMessageType.ERROR,
                                error=ErrorBody(
                                    code=ErrorCode.DEVICE_REVOKED,
                                    message="Device has been revoked",
                                ),
                            ).model_dump(mode="json")
                        )
                        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
                        return

                    # Rotate the long-lived device token
                    new_token = secrets.token_urlsafe(32)
                    key = get_device_token_key(settings.biometric_kek.get_secret_value())
                    device.token_hash = hash_device_token(new_token, key)
                    device.token_display_prefix = new_token[:6]

                    # Log heartbeat durably
                    db_heartbeat = DeviceHeartbeat(
                        device_id=device.id,
                        observed_at=datetime.now(tz=UTC),
                        clock_skew_ms=heartbeat.clock_skew_ms,
                        battery_pct=None,  # Not present in schema currently
                    )
                    session.add(db_heartbeat)
                    await session.commit()

                    # Send token rotation message to client
                    await websocket.send_json({
                        "type": "token_rotation",
                        "device_token": new_token,
                    })

                    # Check for settings version update
                    new_resolved = await resolve_db_settings(session, context)
                    if new_resolved.settings_version > settings_ver:
                        settings_ver = new_resolved.settings_version
                        await websocket.send_json(
                            SettingsPush(
                                type=ServerMessageType.SETTINGS_PUSH,
                                settings_version=settings_ver,
                                payload=new_resolved.settings,
                            ).model_dump(mode="json")
                        )

                elif msg_type == ClientMessageType.CHECK_IN:
                    checkin = CheckIn.model_validate(payload)

                    # Check for existing event with the same idempotency key
                    stmt = select(AttendanceEvent).where(
                        AttendanceEvent.idempotency_key == checkin.idempotency_key
                    )
                    existing_res = await session.execute(stmt)
                    existing = existing_res.scalar_one_or_none()
                    if existing is not None:
                        logger.info(
                            "Found existing event for check-in idempotency key %s",
                            checkin.idempotency_key,
                        )
                        from backend.app.models.people import Person as DbPerson

                        display_name = "Unknown Person"
                        if existing.person_id:
                            db_person = await session.get(DbPerson, existing.person_id)
                            if db_person:
                                display_name = db_person.display_name
                        await websocket.send_json(
                            Result(
                                type=ServerMessageType.RESULT,
                                status=existing.outcome,
                                person=Person(
                                    id=str(existing.person_id) if existing.person_id else "",
                                    display_name=display_name,
                                    photo_url=None,
                                )
                                if existing.person_id
                                else None,
                                direction=existing.direction,
                                occurred_at=existing.occurred_at,
                                record_status=None,
                                committed=True,
                            ).model_dump(mode="json")
                        )
                        continue

                    # Lookup active person by external_id
                    from backend.app.models.people import Person as DbPerson

                    stmt = select(DbPerson).where(
                        DbPerson.external_id == checkin.external_id,
                        DbPerson.is_active == True,
                    )
                    res = await session.execute(stmt)
                    person = res.scalar_one_or_none()

                    if person is None:
                        logger.warning("Check-in failed: invalid external_id=%s", checkin.external_id)
                        await websocket.send_json(
                            ErrorMessage(
                                type=ServerMessageType.ERROR,
                                error=ErrorBody(
                                    code=ErrorCode.UNKNOWN_FACE,
                                    message="Invalid PIN or QR code",
                                ),
                            ).model_dump(mode="json")
                        )
                        continue

                    # Check active scan session
                    scan_session = await active_scan_session_for_device(
                        session, device_id=device.id
                    )
                    resolved_settings = await resolve_db_settings(session, context)

                    if scan_session is None and device.mode == DeviceMode.FIXED:
                        assert device.location_id is not None
                        from backend.app.models.sessions import ScanSessionLocationSource
                        from backend.app.scan.sessions import open_scan_session

                        scan_session = open_scan_session(
                            device,
                            location_id=device.location_id,
                            operator_admin_id=None,
                            location_source=ScanSessionLocationSource.DEVICE_FIXED,
                            started_at=datetime.now(tz=UTC),
                            settings=resolved_settings.settings,
                        )
                        session.add(scan_session)
                        await session.commit()
                        logger.info(
                            "Implicitly created scan session %s for fixed device %s",
                            scan_session.id,
                            device.id,
                        )

                    try:
                        attribution = require_scan_attribution(
                            device,
                            scan_session,
                            now=datetime.now(tz=UTC),
                            settings=resolved_settings.settings,
                        )
                    except ScanSessionError as exc:
                        await websocket.send_json(
                            ErrorMessage(
                                type=ServerMessageType.ERROR,
                                error=ErrorBody(
                                    code=ErrorCode.SCAN_BACKEND_UNAVAILABLE,
                                    message=str(exc),
                                ),
                            ).model_dump(mode="json")
                        )
                        continue

                    # Persist event
                    now = datetime.now(tz=UTC)
                    from backend.app.scan.pipeline import _compute_occurred_at
                    max_backdate = resolved_settings.settings.get("scan.max_offline_backdate_minutes", 240)
                    occurred_at, was_backdated = _compute_occurred_at(
                        now,
                        checkin.monotonic_offset_ms,
                        max_offline_backdate_minutes=int(max_backdate)
                    )
                    event = AttendanceEvent(
                        idempotency_key=checkin.idempotency_key,
                        person_id=person.id,
                        device_id=device.id,
                        session_id=attribution.session_id,
                        location_id=attribution.location_id,
                        direction=checkin.direction,
                        outcome=AttendanceEventOutcome.ACCEPTED,
                        location_source=AttendanceLocationSource(
                            attribution.location_source.value
                        ),
                        client_captured_at=occurred_at,
                        server_received_at=now,
                        occurred_at=occurred_at,
                        monotonic_offset_ms=checkin.monotonic_offset_ms,
                        was_backdated=was_backdated,
                        top1_score=None,
                        top2_other_person_score=None,
                        event_metadata={"method": "pin_or_qr"},
                    )
                    session.add(event)
                    await session.commit()

                    # Send result
                    await websocket.send_json(
                        Result(
                            type=ServerMessageType.RESULT,
                            status="accepted",
                            person=Person(
                                id=str(person.id),
                                display_name=person.display_name,
                                photo_url=None,
                            ),
                            direction=checkin.direction,
                            occurred_at=event.occurred_at,
                            record_status=None,
                            committed=True,
                        ).model_dump(mode="json")
                    )

                elif msg_type == ClientMessageType.FRAME_BURST:
                    burst = FrameBurst.model_validate(payload)

                    # Check for existing success event with the same idempotency key
                    stmt = select(AttendanceEvent).where(
                        AttendanceEvent.idempotency_key == burst.idempotency_key
                    )
                    existing_res = await session.execute(stmt)
                    existing = existing_res.scalar_one_or_none()
                    if existing is not None:
                        logger.info(
                            "Found existing success event for idempotency key %s",
                            burst.idempotency_key,
                        )
                        from backend.app.models.people import Person as DbPerson

                        display_name = "Unknown Person"
                        if existing.person_id:
                            db_person = await session.get(DbPerson, existing.person_id)
                            if db_person:
                                display_name = db_person.display_name
                        await websocket.send_json(
                            Result(
                                type=ServerMessageType.RESULT,
                                status=existing.outcome,
                                person=Person(
                                    id=str(existing.person_id) if existing.person_id else "",
                                    display_name=display_name,
                                    photo_url=None,
                                )
                                if existing.person_id
                                else None,
                                direction=existing.direction,
                                occurred_at=existing.occurred_at,
                                record_status=None,
                                committed=True,
                            ).model_dump(mode="json")
                        )
                        continue

                    # Check for existing failed event (unknown_face, ambiguous, low_confidence)
                    stmt_err = select(AttendanceEvent).where(
                        AttendanceEvent.idempotency_key.like(f"{burst.idempotency_key}-%")
                    )
                    existing_err_res = await session.execute(stmt_err)
                    existing_err = existing_err_res.scalar_one_or_none()
                    if existing_err is not None:
                        logger.info(
                            "Found existing failed event for idempotency key %s",
                            burst.idempotency_key,
                        )
                        err_code = ErrorCode.UNKNOWN_FACE
                        for ec in [
                            ErrorCode.AMBIGUOUS,
                            ErrorCode.LOW_CONFIDENCE,
                            ErrorCode.UNKNOWN_FACE,
                        ]:
                            if ec.value.lower() in existing_err.idempotency_key:
                                err_code = ec
                                break
                        await websocket.send_json(
                            ErrorMessage(
                                type=ServerMessageType.ERROR,
                                error=ErrorBody(
                                    code=err_code,
                                    message=f"Cached scan rejection: {err_code.value}",
                                ),
                            ).model_dump(mode="json")
                        )
                        continue

                    await websocket.send_json({"type": ServerMessageType.DETECTED})
                    await websocket.send_json({"type": ServerMessageType.CHECKING})

                    # Reload gallery if stale
                    await gallery_index.reload_if_stale(session, load_entries_fn)

                    # Get resolved settings for the execution context
                    resolved_settings = await resolve_db_settings(session, context)

                    # Check active scan session
                    scan_session = await active_scan_session_for_device(
                        session, device_id=device.id
                    )
                    if scan_session is None and device.mode == DeviceMode.FIXED:
                        assert device.location_id is not None
                        from backend.app.models.sessions import ScanSessionLocationSource
                        from backend.app.scan.sessions import open_scan_session
                        scan_session = open_scan_session(
                            device,
                            location_id=device.location_id,
                            operator_admin_id=None,
                            location_source=ScanSessionLocationSource.DEVICE_FIXED,
                            started_at=datetime.now(tz=UTC),
                            settings=resolved_settings.settings,
                        )
                        session.add(scan_session)
                        await session.commit()
                        logger.info("Implicitly created scan session %s for fixed device %s", scan_session.id, device.id)

                    try:
                        attribution = require_scan_attribution(
                            device,
                            scan_session,
                            now=datetime.now(tz=UTC),
                            settings=resolved_settings.settings,
                        )
                    except ScanSessionError as exc:
                        logger.warning("Scan attribution failed for device=%s: %s", device.id if device is not None else 'unknown', str(exc))
                        await websocket.send_json(
                            ErrorMessage(
                                type=ServerMessageType.ERROR,
                                error=ErrorBody(
                                    code=ErrorCode.SCAN_BACKEND_UNAVAILABLE,
                                    message=str(exc),
                                ),
                            ).model_dump(mode="json")
                        )
                        continue

                    # Process each frame in the burst
                    outputs: list[tuple[ScanOutput, int]] = []
                    errors: list[DomainError] = []

                    for frame in burst.frames:
                        try:
                            jpeg_bytes = base64.b64decode(frame.jpeg_b64)
                        except binascii.Error:
                            errors.append(
                                DomainError(ErrorCode.LOW_QUALITY, "Invalid base64 JPEG encoding")
                            )
                            continue

                        # Construct scan input
                        scan_input = ScanInput(
                            jpeg_bytes=jpeg_bytes,
                            bbox_hint=frame.bbox,
                            idempotency_key=burst.idempotency_key,
                            device_id=device.id,
                            session_id=attribution.session_id,
                            location_id=attribution.location_id,
                            location_source=attribution.location_source.value,
                            direction="in",  # Default direction
                            client_captured_at=datetime.now(tz=UTC),  # placeholder
                            monotonic_offset_ms=frame.monotonic_offset_ms,
                        )

                        try:
                            out = run_scan_pipeline(
                                scan_input,
                                engine=face_engine,
                                gallery=gallery_index,
                                cooldown=global_cooldown_checker,
                                settings=resolved_settings.settings,
                            )
                            outputs.append((out, frame.monotonic_offset_ms))
                        except DomainError as exc:
                            errors.append(exc)

                    # ── Combine burst results ─────────────────────────────
                    final_output: ScanOutput | None = None
                    final_offset: int = 0
                    final_error: DomainError | None = None

                    # Rule 1: Liveness failure in any frame denies the entire burst (denied_spoof)
                    liveness_fails = [
                        err for err in errors if err.code == ErrorCode.LIVENESS_FAILED
                    ]
                    if liveness_fails:
                        final_error = liveness_fails[0]

                    # Rule 2: If all frames had no face, return NO_FACE
                    elif len(errors) == len(burst.frames) and all(
                        err.code == ErrorCode.NO_FACE for err in errors
                    ):
                        final_error = errors[0]

                    else:
                        # Filter out successful matches
                        successes = [item for item in outputs if item[0].person_id is not None]

                        if len(successes) > 0:
                            # Verify if they all match the same person
                            matched_person_ids = {item[0].person_id for item in successes}
                            if len(matched_person_ids) == 1:
                                # Accept: choose the one with the higher score
                                final_item = max(successes, key=lambda x: x[0].top1_score or 0.0)
                                final_output = final_item[0]
                                final_offset = final_item[1]
                            else:
                                # Ambiguous: multiple people matched in same burst
                                final_error = DomainError(
                                    ErrorCode.AMBIGUOUS,
                                    "Multiple distinct identities matched in same burst",
                                )
                        else:
                            # Choose the most specific error among the frames
                            # AMBIGUOUS > LOW_CONFIDENCE > UNKNOWN_FACE > others
                            priority = [
                                ErrorCode.AMBIGUOUS,
                                ErrorCode.LOW_CONFIDENCE,
                                ErrorCode.UNKNOWN_FACE,
                            ]
                            chosen_err = None
                            for err_code in priority:
                                matches = [err for err in errors if err.code == err_code]
                                if matches:
                                    chosen_err = matches[0]
                                    break
                            final_error = (
                                chosen_err or errors[0]
                                if errors
                                else DomainError(ErrorCode.UNKNOWN_FACE)
                            )

                    # ── Event Persistence & Response ──────────────────────
                    if final_output is not None:
                        # Accept/Location conflict: load display name
                        from backend.app.models.people import Person as DbPerson

                        db_person = await session.get(DbPerson, final_output.person_id)
                        display_name = db_person.display_name if db_person else "Unknown Person"

                        # Persist event durably BEFORE responding (FIX-B3)
                        event = AttendanceEvent(
                            idempotency_key=burst.idempotency_key,
                            person_id=final_output.person_id,
                            device_id=device.id,
                            session_id=attribution.session_id,
                            location_id=attribution.location_id,
                            direction="in",  # Default direction
                            outcome=AttendanceEventOutcome(final_output.outcome),
                            location_source=AttendanceLocationSource(
                                attribution.location_source.value
                            ),
                            client_captured_at=final_output.server_received_at,  # placeholder
                            server_received_at=final_output.server_received_at,
                            occurred_at=final_output.occurred_at,
                            monotonic_offset_ms=final_offset,
                            was_backdated=final_output.was_backdated,
                            top1_score=final_output.top1_score,
                            top2_other_person_score=final_output.top2_other_person_score,
                            event_metadata=final_output.timings.__dict__,
                        )
                        session.add(event)
                        await session.commit()

                        # Send result
                        await websocket.send_json(
                            Result(
                                type=ServerMessageType.RESULT,
                                status=final_output.outcome,
                                person=Person(
                                    id=str(final_output.person_id),
                                    display_name=display_name,
                                    photo_url=None,
                                ),
                                direction=final_output.direction,
                                occurred_at=final_output.occurred_at,
                                record_status=None,
                                committed=True,
                            ).model_dump(mode="json")
                        )
                    else:
                        assert final_error is not None
                        # Persist failed scans as unknown_face events for ROC auditing
                        # Only if it's a valid enum outcome (like unknown_face, ambiguous, low_confidence)
                        mapped_outcome = None
                        if final_error.code == ErrorCode.UNKNOWN_FACE:
                            mapped_outcome = AttendanceEventOutcome.UNKNOWN_FACE
                        elif final_error.code == ErrorCode.AMBIGUOUS:
                            mapped_outcome = AttendanceEventOutcome.AMBIGUOUS
                        elif final_error.code == ErrorCode.LOW_CONFIDENCE:
                            mapped_outcome = AttendanceEventOutcome.LOW_CONFIDENCE

                        if mapped_outcome is not None:
                            # Attempt to write error event
                            # Generate unique key to prevent conflict if client retries
                            err_idem = f"{burst.idempotency_key}-{final_error.code.value.lower()}"
                            event = AttendanceEvent(
                                idempotency_key=err_idem,
                                person_id=None,
                                device_id=device.id,
                                session_id=attribution.session_id,
                                location_id=attribution.location_id,
                                direction="in",
                                outcome=mapped_outcome,
                                location_source=AttendanceLocationSource(
                                    attribution.location_source.value
                                ),
                                client_captured_at=datetime.now(tz=UTC),
                                server_received_at=datetime.now(tz=UTC),
                                occurred_at=datetime.now(tz=UTC),
                                monotonic_offset_ms=0,
                                was_backdated=False,
                                top1_score=None,
                                top2_other_person_score=None,
                                event_metadata={"error": final_error.envelope()},
                            )
                            session.add(event)
                            await session.commit()

                        logger.warning(
                            "Scan burst rejected: code=%s message=%s details=%s",
                            final_error.code.value,
                            final_error.message or final_error.envelope()["error"]["message"],
                            final_error.details,
                        )

                        # Send error message frame
                        await websocket.send_json(
                            ErrorMessage(
                                type=ServerMessageType.ERROR,
                                error=ErrorBody(
                                    code=final_error.code,
                                    message=final_error.message
                                    or final_error.envelope()["error"]["message"],
                                    details=final_error.details,
                                ),
                            ).model_dump(mode="json")
                        )
                else:
                    await websocket.send_json(
                        ErrorMessage(
                            type=ServerMessageType.ERROR,
                            error=ErrorBody(
                                code=ErrorCode.VALIDATION_ERROR,
                                message=f"Unsupported or missing message type: {msg_type}",
                            ),
                        ).model_dump(mode="json")
                    )
            except WebSocketDisconnect:
                raise
            except ValidationError as exc:
                await websocket.send_json(
                    ErrorMessage(
                        type=ServerMessageType.ERROR,
                        error=ErrorBody(code=ErrorCode.VALIDATION_ERROR, message=str(exc)),
                    ).model_dump(mode="json")
                )
            except Exception:
                await session.rollback()
                logger.exception("Unexpected error processing kiosk message")
                await websocket.send_json(
                    ErrorMessage(
                        type=ServerMessageType.ERROR,
                        error=ErrorBody(
                            code=ErrorCode.SCAN_BACKEND_UNAVAILABLE,
                            message="Internal scan backend error",
                        ),
                    ).model_dump(mode="json")
                )
    except WebSocketDisconnect:
        logger.info("Kiosk connection disconnected.")
        return
