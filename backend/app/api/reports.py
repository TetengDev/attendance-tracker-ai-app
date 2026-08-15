from __future__ import annotations

import logging
from collections.abc import Generator
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.api.common import SessionDep
from backend.app.audit.chain import AuditEntry
from backend.app.audit.service import append_audit_entry
from backend.app.models.attendance import ReportJob, ReportJobStatus
from backend.app.models.audit import AuditActorKind
from backend.app.reports.generators import REPORT_GENERATORS
from backend.app.reports.renderers import render_pdf, render_xlsx, stream_csv

logger = logging.getLogger("attendance_tracker")
router = APIRouter(prefix="/api/reports", tags=["reports"])


class ReportExportRequest(BaseModel):
    report_type: str
    format: str  # csv, xlsx, pdf
    date_from: date | None = None
    date_to: date | None = None
    group_id: UUID | None = None
    person_id: UUID | None = None
    min_absences: int = 3


class ReportJobResponse(BaseModel):
    id: UUID
    report_type: str
    format: str
    status: str
    row_count: int | None = None
    error_message: str | None = None
    expires_at: datetime | None = None
    created_at: datetime


async def audit_report_export(
    session: AsyncSession,
    report_type: str,
    format_type: str,
    row_count: int,
    request: Request,
    async_job_id: UUID | None = None,
) -> None:
    """Manually records an audit row for report extraction/export operations."""
    actor_kind = AuditActorKind.SYSTEM
    actor_id = None

    raw_kind = request.headers.get("x-actor-kind")
    if raw_kind:
        try:
            actor_kind = AuditActorKind(raw_kind)
        except ValueError:
            pass

    raw_actor_id = request.headers.get("x-actor-id")
    if raw_actor_id:
        try:
            actor_id = UUID(raw_actor_id)
        except ValueError:
            pass

    request_id = getattr(request.state, "request_id", "N/A")
    ip_address = request.client.host if request.client else None

    entry = AuditEntry(
        actor_kind=actor_kind,
        actor_id=actor_id,
        action="EXPORT_REPORT",
        entity_type="report",
        entity_id=report_type,
        before=None,
        after={
            "report_type": report_type,
            "format": format_type,
            "row_count": row_count,
            "async_job_id": str(async_job_id) if async_job_id else None,
        },
        ip_address=ip_address,
        request_id=request_id,
        occurred_at=datetime.now(UTC),
    )
    await append_audit_entry(session, entry)


async def run_async_export(
    job_id: UUID,
    report_type: str,
    format_type: str,
    params: dict[str, Any],
) -> None:
    """Background task to query data, format it, and write it to storage."""
    from backend.app.db.session import get_session_factory

    logger.info("Starting async report export for job %s", job_id)
    try:
        # Resolve parameters
        date_from = params.get("date_from")
        date_to = params.get("date_to")
        if isinstance(date_from, str):
            date_from = date.fromisoformat(date_from)
        if isinstance(date_to, str):
            date_to = date.fromisoformat(date_to)

        if not date_from:
            date_from = datetime.now(UTC).date()
        if not date_to:
            date_to = datetime.now(UTC).date()

        group_id = params.get("group_id")
        if group_id and isinstance(group_id, str):
            group_id = UUID(group_id)

        person_id = params.get("person_id")
        if person_id and isinstance(person_id, str):
            person_id = UUID(person_id)

        min_absences = params.get("min_absences", 3)

        # Run query within a new session
        async with get_session_factory()() as session, session.begin():
            generator = REPORT_GENERATORS.get(report_type)
            if not generator:
                raise ValueError(f"Unknown report type: {report_type}")

            if report_type == "truancy":
                rows, headers = await generator(session, date_from, date_to, group_id, min_absences)
            elif report_type in ["muster_roll", "device_health"]:
                rows, headers = await generator(session)
            elif report_type == "timesheet":
                rows, headers = await generator(session, date_from, date_to, person_id, group_id)
            else:
                rows, headers = await generator(session, date_from, date_to, group_id)

            # Ensure output folder exists
            reports_dir = Path("storage/reports")
            reports_dir.mkdir(parents=True, exist_ok=True)
            file_path = reports_dir / f"{job_id}.{format_type}"

            # Render report payload
            if format_type == "csv":
                with open(file_path, "wb") as f:  # noqa: ASYNC230
                    f.writelines(stream_csv(rows, headers))
            elif format_type == "xlsx":
                data = render_xlsx(rows, headers, report_title=report_type)
                with open(file_path, "wb") as f:  # noqa: ASYNC230
                    f.write(data)
            elif format_type == "pdf":
                data = render_pdf(rows, headers, report_title=report_type.replace("_", " ").title())
                with open(file_path, "wb") as f:  # noqa: ASYNC230
                    f.write(data)
            else:
                raise ValueError(f"Unsupported format: {format_type}")

            # Update job state in db
            stmt = select(ReportJob).where(ReportJob.id == job_id).with_for_update()
            job = (await session.execute(stmt)).scalar_one()
            job.status = ReportJobStatus.COMPLETED
            job.row_count = len(rows)
            job.file_path = str(file_path)
            job.completed_at = datetime.now(UTC)
            job.expires_at = datetime.now(UTC) + timedelta(hours=24)
            session.add(job)

        logger.info("Completed async report export for job %s", job_id)

    except Exception as exc:
        logger.exception("Async export task failed for job %s", job_id)
        try:
            async with get_session_factory()() as session, session.begin():
                stmt = select(ReportJob).where(ReportJob.id == job_id).with_for_update()
                job = (await session.execute(stmt)).scalar_one()
                job.status = ReportJobStatus.FAILED
                job.error_message = str(exc)
                job.completed_at = datetime.now(UTC)
                session.add(job)
        except Exception:
            logger.exception("Failed to write failure state to db for job %s", job_id)


@router.get("/preview")
async def preview_report(
    session: SessionDep,
    report_type: str,
    date_from: date | None = None,
    date_to: date | None = None,
    group_id: UUID | None = None,
    person_id: UUID | None = None,
    min_absences: int = 3,
) -> dict[str, Any]:
    """Retrieve raw JSON preview list of report rows (for immediate rendering in admin UI)."""
    generator = REPORT_GENERATORS.get(report_type)
    if not generator:
        raise HTTPException(status_code=400, detail=f"Unknown report type: {report_type}")

    if not date_from:
        date_from = datetime.now(UTC).date()
    if not date_to:
        date_to = datetime.now(UTC).date()

    if report_type == "truancy":
        rows, headers = await generator(session, date_from, date_to, group_id, min_absences)
    elif report_type in ["muster_roll", "device_health"]:
        rows, headers = await generator(session)
    elif report_type == "timesheet":
        rows, headers = await generator(session, date_from, date_to, person_id, group_id)
    else:
        rows, headers = await generator(session, date_from, date_to, group_id)

    return {
        "headers": headers,
        "rows": rows[:500],  # cap preview size
        "total_count": len(rows),
    }


@router.post("/export")
async def export_report(
    request_data: ReportExportRequest,
    background_tasks: BackgroundTasks,
    request: Request,
    session: SessionDep,
) -> Any:
    """Start report extract. Returns streaming download or starts an async job if rows > 5000."""
    report_type = request_data.report_type
    format_type = request_data.format.lower()
    generator = REPORT_GENERATORS.get(report_type)
    if not generator:
        raise HTTPException(status_code=400, detail=f"Unknown report type: {report_type}")

    if format_type not in ["csv", "xlsx", "pdf"]:
        raise HTTPException(status_code=400, detail=f"Unsupported format: {format_type}")

    date_from = request_data.date_from or datetime.now(UTC).date()
    date_to = request_data.date_to or datetime.now(UTC).date()

    # Query matching rows to check limit count
    if report_type == "truancy":
        rows, headers = await generator(
            session, date_from, date_to, request_data.group_id, request_data.min_absences
        )
    elif report_type in ["muster_roll", "device_health"]:
        rows, headers = await generator(session)
    elif report_type == "timesheet":
        rows, headers = await generator(
            session, date_from, date_to, request_data.person_id, request_data.group_id
        )
    else:
        rows, headers = await generator(session, date_from, date_to, request_data.group_id)

    # 1. Sync path: <= 5,000 rows
    if len(rows) <= 5000:
        await audit_report_export(session, report_type, format_type, len(rows), request)

        filename = f"{report_type}_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}.{format_type}"

        if format_type == "csv":
            return StreamingResponse(
                stream_csv(rows, headers),
                media_type="text/csv",
                headers={"Content-Disposition": f"attachment; filename={filename}"},
            )
        elif format_type == "xlsx":
            data = render_xlsx(rows, headers, report_title=report_type)
            return Response(
                content=data,
                media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                headers={"Content-Disposition": f"attachment; filename={filename}"},
            )
        elif format_type == "pdf":
            try:
                data = render_pdf(rows, headers, report_title=report_type.replace("_", " ").title())
                return Response(
                    content=data,
                    media_type="application/pdf",
                    headers={"Content-Disposition": f"attachment; filename={filename}"},
                )
            except Exception as e:
                logger.exception("PDF rendering failed")
                raise HTTPException(status_code=500, detail=f"PDF generation failed: {e}")

    # 2. Async path: > 5,000 rows
    job_id = uuid4()
    params = {
        "date_from": date_from.isoformat(),
        "date_to": date_to.isoformat(),
        "group_id": str(request_data.group_id) if request_data.group_id else None,
        "person_id": str(request_data.person_id) if request_data.person_id else None,
        "min_absences": request_data.min_absences,
    }

    job = ReportJob(
        id=job_id,
        report_type=report_type,
        format=format_type,
        parameters=params,
        status=ReportJobStatus.PENDING,
    )
    session.add(job)
    await session.commit()

    # Manual audit row
    await audit_report_export(
        session, report_type, format_type, len(rows), request, async_job_id=job_id
    )

    # Queue background processing
    background_tasks.add_task(
        run_async_export,
        job_id,
        report_type,
        format_type,
        params,
    )

    return {
        "job_id": job_id,
        "status": "pending",
        "row_count": len(rows),
        "message": "Export contains over 5,000 rows and will be processed asynchronously.",
    }


@router.get("/jobs")
async def list_report_jobs(session: SessionDep) -> list[ReportJobResponse]:
    """Retrieve list of recent background report jobs."""
    stmt = select(ReportJob).order_by(ReportJob.created_at.desc()).limit(50)
    result = await session.execute(stmt)
    jobs = result.scalars().all()
    return [
        ReportJobResponse(
            id=job.id,
            report_type=job.report_type,
            format=job.format,
            status=job.status,
            row_count=job.row_count,
            error_message=job.error_message,
            expires_at=job.expires_at,
            created_at=job.created_at,
        )
        for job in jobs
    ]


@router.get("/jobs/{job_id}")
async def get_report_job(job_id: UUID, session: SessionDep) -> ReportJobResponse:
    """Check the status of a specific background report job."""
    stmt = select(ReportJob).where(ReportJob.id == job_id)
    job = (await session.execute(stmt)).scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Export job not found")

    return ReportJobResponse(
        id=job.id,
        report_type=job.report_type,
        format=job.format,
        status=job.status,
        row_count=job.row_count,
        error_message=job.error_message,
        expires_at=job.expires_at,
        created_at=job.created_at,
    )


@router.get("/jobs/{job_id}/download")
async def download_report_job(
    job_id: UUID,
    request: Request,
    session: SessionDep,
) -> StreamingResponse:
    """Download the output file of a completed background export job."""
    stmt = select(ReportJob).where(ReportJob.id == job_id)
    job = (await session.execute(stmt)).scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Export job not found")

    if job.status != ReportJobStatus.COMPLETED:
        raise HTTPException(status_code=400, detail=f"Export job is in status: {job.status}")

    if not job.file_path or not Path(job.file_path).exists():
        raise HTTPException(status_code=404, detail="Exported file not found on disk")

    if job.expires_at and datetime.now(UTC) > job.expires_at:
        raise HTTPException(status_code=410, detail="Export download URL has expired")

    # Audit download row
    await audit_report_export(
        session, job.report_type, job.format, job.row_count or 0, request, async_job_id=job.id
    )

    filename = f"{job.report_type}_{job_id}.{job.format}"
    path = Path(job.file_path)

    def file_iterator() -> Generator[bytes]:
        with open(path, "rb") as f:
            while chunk := f.read(8192):
                yield chunk

    media_types = {
        "csv": "text/csv",
        "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "pdf": "application/pdf",
    }
    media_type = media_types.get(job.format, "application/octet-stream")

    return StreamingResponse(
        file_iterator(),
        media_type=media_type,
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
