from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.attendance.resolver import resolve_db_settings
from backend.app.audit.chain import AuditEntry
from backend.app.audit.service import append_audit_entry
from backend.app.models.attendance import AttendanceEvent, AttendanceEventOutcome, AttendanceRecord
from backend.app.models.audit import AuditActorKind, AuditLog
from backend.app.models.biometrics import EnrollmentAsset, FaceEmbedding
from backend.app.models.devices import DeviceHeartbeat
from backend.app.models.people import Person
from backend.app.settings.resolver import SettingContext

logger = logging.getLogger("attendance_tracker")


async def run_purge_job(session: AsyncSession, *, now: datetime | None = None) -> dict[str, int]:
    """Runs retention policies to delete expired records and logs stats."""
    if now is None:
        now = datetime.now(UTC)

    # 1. Fetch global settings
    settings = await resolve_db_settings(session, SettingContext())

    # Extract thresholds
    embeddings_days = settings.settings.get("retention.embeddings_days_after_inactive", 1095)
    enrollment_images_days = settings.settings.get("retention.enrollment_images_days", 1095)
    unknown_face_hours = settings.settings.get("retention.unknown_face_hours", 72)
    events_days = settings.settings.get("retention.events_days", 2555)
    records_days = settings.settings.get("retention.records_days", 2555)
    audit_days = settings.settings.get("retention.audit_days", 2555)

    stats = {}

    logger.info("Starting retention purge job at %s", now.isoformat())

    # 2. Executing Purge Statements
    # a. Device Heartbeats (7 days hardcoded constant)
    heartbeat_cutoff = now - timedelta(days=7)
    hb_stmt = delete(DeviceHeartbeat).where(DeviceHeartbeat.observed_at < heartbeat_cutoff)
    hb_res = await session.execute(hb_stmt)
    stats["device_heartbeats"] = cast(Any, hb_res).rowcount

    # b. Unknown Face Events (unknown_face_hours)
    unknown_cutoff = now - timedelta(hours=unknown_face_hours)
    unknown_stmt = delete(AttendanceEvent).where(
        AttendanceEvent.outcome == AttendanceEventOutcome.UNKNOWN_FACE,
        AttendanceEvent.occurred_at < unknown_cutoff,
    )
    unknown_res = await session.execute(unknown_stmt)
    stats["unknown_face_events"] = cast(Any, unknown_res).rowcount

    # c. Face Embeddings for Inactive People (embeddings_days)
    inactive_cutoff = now - timedelta(days=embeddings_days)
    subq = select(Person.id).where(
        Person.is_active.is_(False),
        Person.updated_at < inactive_cutoff,
    )
    embed_stmt = delete(FaceEmbedding).where(FaceEmbedding.person_id.in_(subq))
    embed_res = await session.execute(embed_stmt)
    stats["inactive_face_embeddings"] = cast(Any, embed_res).rowcount

    # d. Enrollment Images (enrollment_images_days)
    enrollment_cutoff = now - timedelta(days=enrollment_images_days)
    enrollment_stmt = delete(EnrollmentAsset).where(EnrollmentAsset.created_at < enrollment_cutoff)
    enrollment_res = await session.execute(enrollment_stmt)
    stats["enrollment_assets"] = cast(Any, enrollment_res).rowcount

    # e. Events (events_days)
    events_cutoff = now - timedelta(days=events_days)
    events_stmt = delete(AttendanceEvent).where(AttendanceEvent.occurred_at < events_cutoff)
    events_res = await session.execute(events_stmt)
    stats["attendance_events"] = cast(Any, events_res).rowcount

    # f. Attendance Records (records_days)
    records_cutoff_date = (now - timedelta(days=records_days)).date()
    records_stmt = delete(AttendanceRecord).where(AttendanceRecord.business_date < records_cutoff_date)
    records_res = await session.execute(records_stmt)
    stats["attendance_records"] = cast(Any, records_res).rowcount

    # g. Audit Logs (audit_days)
    audit_cutoff = now - timedelta(days=audit_days)
    audit_stmt = delete(AuditLog).where(AuditLog.occurred_at < audit_cutoff)
    audit_res = await session.execute(audit_stmt)
    stats["audit_logs"] = cast(Any, audit_res).rowcount

    # 3. Log audit entry for the purge job action
    before_state: dict[str, Any] = {
        "thresholds": {
            "embeddings_days": embeddings_days,
            "enrollment_images_days": enrollment_images_days,
            "unknown_face_hours": unknown_face_hours,
            "events_days": events_days,
            "records_days": records_days,
            "audit_days": audit_days,
        }
    }
    after_state: dict[str, Any] = {
        "deleted_counts": stats
    }

    audit_entry = AuditEntry(
        actor_kind=AuditActorKind.JOB,
        actor_id=None,
        action="retention_purge",
        entity_type="system",
        entity_id="retention_service",
        before=before_state,
        after=after_state,
        ip_address=None,
        request_id="nightly-purge-job",
        occurred_at=now,
    )
    await append_audit_entry(session, audit_entry)

    logger.info("Completed retention purge job. Stats: %s", stats)
    return stats
