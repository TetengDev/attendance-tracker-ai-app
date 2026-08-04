from __future__ import annotations

from sqlalchemy import Select, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.audit.chain import AuditEntry, make_audit_log, verify_audit_chain
from backend.app.models.audit import AuditLog

AUDIT_CHAIN_LOCK_KEY = 29_2026


async def append_audit_entry(session: AsyncSession, entry: AuditEntry) -> AuditLog:
    """Append one audit row under a transaction-scoped Postgres advisory lock."""

    await session.execute(
        text("SELECT pg_advisory_xact_lock(:lock_key)"), {"lock_key": AUDIT_CHAIN_LOCK_KEY}
    )
    prev_hash = await latest_audit_hash(session)
    row = make_audit_log(entry, prev_hash=prev_hash)
    session.add(row)
    await session.flush()
    return row


async def latest_audit_hash(session: AsyncSession) -> bytes | None:
    result = await session.execute(select(AuditLog.hash).order_by(AuditLog.id.desc()).limit(1))
    return result.scalar_one_or_none()


async def verify_persisted_audit_chain(session: AsyncSession) -> bytes | None:
    result = await session.execute(_audit_rows_in_chain_order())
    return verify_audit_chain(list(result.scalars()))


async def audit_chain_head(session: AsyncSession) -> dict[str, object]:
    count_result = await session.execute(select(func.count(AuditLog.id)))
    row_count = count_result.scalar_one()
    latest_result = await session.execute(
        select(AuditLog.id, AuditLog.hash).order_by(AuditLog.id.desc()).limit(1)
    )
    latest = latest_result.one_or_none()
    if latest is None:
        return {"row_count": 0, "last_id": None, "head_hash": None}
    return {
        "row_count": row_count,
        "last_id": latest[0],
        "head_hash": latest[1].hex(),
    }


def _audit_rows_in_chain_order() -> Select[tuple[AuditLog]]:
    return select(AuditLog).order_by(AuditLog.id.asc())
