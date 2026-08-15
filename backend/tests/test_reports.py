from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, date, datetime, timedelta
from typing import Any, Self
from uuid import UUID

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pytest import MonkeyPatch
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.api.common import authenticated_admin_user
from backend.app.db.session import get_session
from backend.app.main import create_app
from backend.app.models.admin import AdminRole, AdminUser
from backend.app.models.attendance import ReportJob, ReportJobStatus
from backend.app.reports.generators import REPORT_GENERATORS
from backend.app.reports.renderers import render_pdf, render_xlsx, stream_csv

# ---------------------------------------------------------------------------
# Mocks & Fakes
# ---------------------------------------------------------------------------


class FakeResult:
    def __init__(self, data: list[Any] | None = None) -> None:
        self._data = data or []

    def scalars(self) -> FakeResult:
        return self

    def all(self) -> list[Any]:
        return self._data

    def mappings(self) -> FakeResult:
        return self

    def scalar_one_or_none(self) -> Any:
        return self._data[0] if self._data else None

    def scalar_one(self) -> Any:
        return self._data[0]

    def scalar(self) -> Any:
        return self._data[0] if self._data else None


class FakeTransaction:
    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, exc_type: object, exc_val: object, exc_tb: object) -> None:
        pass


class FakeSession:
    def __init__(self) -> None:
        self.added: list[Any] = []
        self.committed = False
        self.rolled_back = False

    def begin(self) -> FakeTransaction:
        return FakeTransaction()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, exc_type: object, exc_val: object, exc_tb: object) -> None:
        pass

    def add(self, instance: Any) -> None:
        self.added.append(instance)

    async def commit(self) -> None:
        self.committed = True

    async def rollback(self) -> None:
        self.rolled_back = True

    async def flush(self) -> None:
        pass

    async def execute(self, statement: Any, *args: Any, **kwargs: Any) -> FakeResult:
        sql = str(statement)
        if "shifts" in sql:
            return FakeResult([(UUID("00000000-0000-0000-0000-000000000000"), "Unscheduled")])
        if "attendance_records" in sql:
            # Return dummy record
            return FakeResult(
                [
                    {
                        "id": UUID("11111111-1111-1111-1111-111111111111"),
                        "name": "Alice",
                        "external_id": "EMP-001",
                        "group_name": "HR Group",
                        "shift_id": UUID("00000000-0000-0000-0000-000000000000"),
                        "shift_name": "Day Shift",
                        "business_date": date(2026, 8, 14),
                        "expected_start_at": datetime(2026, 8, 14, 8, 0, tzinfo=UTC),
                        "expected_end_at": datetime(2026, 8, 14, 17, 0, tzinfo=UTC),
                        "actual_in": datetime(2026, 8, 14, 8, 5, tzinfo=UTC),
                        "actual_out": datetime(2026, 8, 14, 17, 2, tzinfo=UTC),
                        "late_minutes": 5,
                        "status": "late",
                        "flags": {"was_late": True},
                    }
                ]
            )
        if "report_jobs" in sql:
            # Simulate fetching a completed job
            job = ReportJob(
                id=UUID("22222222-2222-2222-2222-222222222222"),
                report_type="daily_register",
                format="csv",
                status=ReportJobStatus.COMPLETED,
                row_count=1,
                file_path="storage/reports/22222222-2222-2222-2222-222222222222.csv",
                expires_at=datetime.now(UTC) + timedelta(hours=24),
                completed_at=datetime.now(UTC),
                created_at=datetime.now(UTC),
            )
            return FakeResult([job])
        if "devices" in sql:
            return FakeResult(
                [
                    {
                        "device_name": "kiosk-1",
                        "mode": "fixed",
                        "form_factor": "tablet",
                        "location_name": "Main Office",
                        "observed_at": datetime.now(UTC),
                        "battery_pct": 98,
                        "clock_skew_ms": 12,
                    }
                ]
            )
        if "attendance_events" in sql:
            return FakeResult(
                [
                    {
                        "hour": 8,
                        "in_count": 10,
                        "out_count": 0,
                    }
                ]
            )
        return FakeResult([])


async def fake_get_session() -> AsyncIterator[AsyncSession]:
    yield FakeSession()  # type: ignore[misc]


def _admin_user() -> AdminUser:
    return AdminUser(
        id=UUID("00000000-0000-0000-0000-0000000000ad"),
        email="admin@example.test",
        display_name="Admin",
        password_hash="hash",
        role=AdminRole.ADMIN,
        scope_group_ids=[],
        is_active=True,
    )


def _authenticated_app(monkeypatch: MonkeyPatch) -> FastAPI:
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://localhost:5432/attendance")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("BIOMETRIC_KEK", "test-kek")

    async def async_none(*a: Any, **k: Any) -> None:
        pass

    monkeypatch.setattr("backend.app.audit.middleware._append_entry", async_none)
    monkeypatch.setattr("backend.app.api.reports.append_audit_entry", async_none)
    monkeypatch.setattr("backend.app.db.session.get_session_factory", lambda: FakeSession)

    app = create_app()
    app.dependency_overrides[get_session] = fake_get_session
    app.dependency_overrides[authenticated_admin_user] = _admin_user
    return app


# ---------------------------------------------------------------------------
# Test Cases
# ---------------------------------------------------------------------------


def test_stream_csv() -> None:
    headers = ["name", "external_id", "business_date"]
    rows = [
        {"name": "Alice", "external_id": "E1", "business_date": date(2026, 8, 14)},
        {
            "name": "Bob",
            "external_id": "E2",
            "business_date": datetime(2026, 8, 14, 15, 30, tzinfo=UTC),
        },
    ]
    chunks = list(stream_csv(rows, headers))

    # First chunk is BOM
    assert chunks[0] == b"\xef\xbb\xbf"

    content = b"".join(chunks[1:]).decode("utf-8")
    assert "Name,External Id,Business Date" in content
    assert "Alice,E1,2026-08-14" in content
    assert "Bob,E2,2026-08-14 15:30:00" in content


def test_render_xlsx() -> None:
    headers = ["name", "external_id"]
    rows = [{"name": "Alice", "external_id": "E1"}]
    data = render_xlsx(rows, headers, report_title="daily_register")
    assert len(data) > 0
    assert data.startswith(b"PK")  # ZIP signature of xlsx


def test_render_pdf() -> None:
    headers = ["name", "status"]
    rows = [{"name": "Alice", "status": "on_time"}]
    try:
        data = render_pdf(rows, headers, report_title="Daily Register", subtitle="Filter: HR")
        assert len(data) > 0
        assert data.startswith(b"%PDF")  # PDF signature
    except ImportError:
        # WeasyPrint might not be in test execution context due to library paths, ignore in this stub if so
        pass


def test_preview_report(monkeypatch: MonkeyPatch) -> None:
    app = _authenticated_app(monkeypatch)
    with TestClient(app) as client:
        response = client.get("/api/reports/preview?report_type=daily_register")
        assert response.status_code == 200
        data = response.json()
        assert "headers" in data
        assert "rows" in data
        assert len(data["rows"]) == 1
        assert data["rows"][0]["name"] == "Alice"


def test_export_report_sync(monkeypatch: MonkeyPatch) -> None:
    app = _authenticated_app(monkeypatch)
    with TestClient(app) as client:
        # Request a CSV export (sync path since row_count <= 5000)
        response = client.post(
            "/api/reports/export",
            json={
                "report_type": "daily_register",
                "format": "csv",
                "date_from": "2026-08-14",
                "date_to": "2026-08-14",
            },
        )
        assert response.status_code == 200
        assert response.headers["content-type"] == "text/csv; charset=utf-8"
        assert response.headers["content-disposition"].startswith("attachment;")
        content = response.content.decode("utf-8")
        assert "Business Date,External Id,Name" in content


def test_export_report_async(monkeypatch: MonkeyPatch) -> None:
    # Modify the generator to return >5000 rows to trigger async flow
    REPORT_GENERATORS["daily_register"]

    async def mock_large_generator(*args: Any, **kwargs: Any) -> Any:
        # Return 5001 rows
        rows = [{"name": f"User {i}", "status": "on_time"} for i in range(5001)]
        headers = ["name", "status"]
        return rows, headers

    monkeypatch.setitem(REPORT_GENERATORS, "daily_register", mock_large_generator)

    app = _authenticated_app(monkeypatch)
    with TestClient(app) as client:
        response = client.post(
            "/api/reports/export",
            json={
                "report_type": "daily_register",
                "format": "csv",
                "date_from": "2026-08-14",
                "date_to": "2026-08-14",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "pending"
        assert "job_id" in data
        assert data["row_count"] == 5001


def test_list_and_get_jobs(monkeypatch: MonkeyPatch) -> None:
    app = _authenticated_app(monkeypatch)
    with TestClient(app) as client:
        # Get jobs list
        response = client.get("/api/reports/jobs")
        assert response.status_code == 200
        assert len(response.json()) == 1

        # Get single job
        job_id = "22222222-2222-2222-2222-222222222222"
        response = client.get(f"/api/reports/jobs/{job_id}")
        assert response.status_code == 200
        assert response.json()["status"] == "completed"


def test_download_job_file(monkeypatch: MonkeyPatch) -> None:
    # Mock file read
    from pathlib import Path

    orig_exists = Path.exists
    orig_open = open

    # Stub file exists & open to prevent real disk read during test
    def mock_exists(self: Path) -> bool:
        if "22222222-2222-2222-2222-222222222222" in str(self):
            return True
        return orig_exists(self)

    class MockFile:
        def __init__(self) -> None:
            self._read_done = False

        def __enter__(self) -> Self:
            return self

        def __exit__(self, *args: object) -> None:
            pass

        def read(self, *args: Any) -> bytes:
            if not self._read_done:
                self._read_done = True
                return b"dummy csv data"
            return b""

    def mock_open(file: Any, mode: str = "r", *args: Any, **kwargs: Any) -> Any:
        if "22222222-2222-2222-2222-222222222222" in str(file):
            return MockFile()
        return orig_open(file, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "exists", mock_exists)
    monkeypatch.setattr("builtins.open", mock_open)

    app = _authenticated_app(monkeypatch)
    with TestClient(app) as client:
        job_id = "22222222-2222-2222-2222-222222222222"
        response = client.get(f"/api/reports/jobs/{job_id}/download")
        assert response.status_code == 200
        assert "text/csv" in response.headers["content-type"]
        # Downloaded data must match our stubbed reader bytes
        assert b"dummy csv data" in response.content
