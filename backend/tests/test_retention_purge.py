from __future__ import annotations

import base64
import os

os.environ.setdefault(
    "BIOMETRIC_KEK",
    "kek.test:" + base64.urlsafe_b64encode(bytes([9]) * 32).decode().rstrip("="),
)

from datetime import UTC, datetime
from typing import Any, cast
from unittest.mock import MagicMock

import pytest

from backend.app.models.audit import AuditActorKind, AuditLog
from backend.app.retention.service import run_purge_job
from backend.app.settings.resolver import ResolvedSettings, SettingContext


class MockResult:
    def __init__(self, value: Any, rowcount: int = 0) -> None:
        self._value = value
        self.rowcount = rowcount

    def scalars(self) -> MockResult:
        return self

    def all(self) -> list[Any]:
        if isinstance(self._value, list):
            return self._value
        return [self._value] if self._value is not None else []

    def scalar_one_or_none(self) -> Any | None:
        if isinstance(self._value, list):
            return self._value[0] if self._value else None
        return self._value


class PurgeMockSession:
    def __init__(self) -> None:
        self.added: list[Any] = []
        self.executed_statements: list[Any] = []

    async def execute(self, statement: Any, *args: Any, **kwargs: Any) -> MockResult:
        self.executed_statements.append(statement)
        sql = str(statement)
        
        rowcount = 0
        if "DELETE" in sql:
            if "device_heartbeats" in sql:
                rowcount = 10
            elif "attendance_events" in sql:
                if "outcome" in sql:
                    rowcount = 20
                else:
                    rowcount = 30
            elif "face_embeddings" in sql:
                rowcount = 40
            elif "enrollment_assets" in sql:
                rowcount = 50
            elif "attendance_records" in sql:
                rowcount = 60
            elif "audit_log" in sql:
                rowcount = 70

        return MockResult([], rowcount=rowcount)

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        pass


@pytest.mark.anyio
async def test_run_purge_job(monkeypatch: pytest.MonkeyPatch) -> None:
    # Mock resolve_db_settings to return our specific test thresholds
    async def mock_resolve_settings(session: Any, context: SettingContext) -> ResolvedSettings:
        s = {
            "retention.embeddings_days_after_inactive": 100,
            "retention.enrollment_images_days": 200,
            "retention.unknown_face_hours": 24,
            "retention.events_days": 300,
            "retention.records_days": 400,
            "retention.audit_days": 500,
        }
        return ResolvedSettings(settings=s, settings_version=1)

    import backend.app.retention.service as service_mod
    monkeypatch.setattr(service_mod, "resolve_db_settings", mock_resolve_settings)

    # We also mock latest_audit_hash in audit.service to return dummy hash
    import backend.app.audit.service as audit_service
    async def mock_latest_hash(session: Any) -> bytes | None:
        return b"a" * 32
    monkeypatch.setattr(audit_service, "latest_audit_hash", mock_latest_hash)

    now = datetime(2026, 8, 18, 12, 0, 0, tzinfo=UTC)
    session = PurgeMockSession()

    stats = await run_purge_job(cast(Any, session), now=now)

    # Verify return counts match our mock rowcount logic
    assert stats["device_heartbeats"] == 10
    assert stats["unknown_face_events"] == 20
    assert stats["inactive_face_embeddings"] == 40
    assert stats["enrollment_assets"] == 50
    assert stats["attendance_events"] == 30
    assert stats["attendance_records"] == 60
    assert stats["audit_logs"] == 70

    # Assert that an AuditLog was added
    assert len(session.added) == 1
    audit_row = session.added[0]
    assert isinstance(audit_row, AuditLog)
    assert audit_row.action == "retention_purge"
    assert audit_row.entity_type == "system"
    assert audit_row.entity_id == "retention_service"
    assert audit_row.actor_kind == AuditActorKind.JOB
    assert audit_row.before is not None
    assert audit_row.after is not None
    before_dict = cast(dict[str, Any], audit_row.before)
    after_dict = cast(dict[str, Any], audit_row.after)
    assert before_dict["thresholds"]["embeddings_days"] == 100
    assert after_dict["deleted_counts"]["device_heartbeats"] == 10


@pytest.mark.anyio
async def test_cli_purge_main(monkeypatch: pytest.MonkeyPatch) -> None:
    called = False

    async def mock_run_purge_job(session: Any, *, now: Any = None) -> dict[str, int]:
        nonlocal called
        called = True
        return {"device_heartbeats": 5}

    import backend.app.cli.purge as cli_mod
    monkeypatch.setattr(cli_mod, "run_purge_job", mock_run_purge_job)

    class AsyncContextManager:
        def __init__(self, value: Any = None) -> None:
            self._value = value
        async def __aenter__(self) -> Any:
            return self._value
        async def __aexit__(
            self,
            exc_type: type[BaseException] | None,
            exc_val: BaseException | None,
            exc_tb: object,
        ) -> None:
            pass

    mock_session = MagicMock()
    mock_session.begin = MagicMock(return_value=AsyncContextManager())

    # calling factory() returns AsyncContextManager(mock_session)
    mock_factory = MagicMock(return_value=AsyncContextManager(mock_session))
    # calling get_session_factory() returns factory
    monkeypatch.setattr(cli_mod, "get_session_factory", MagicMock(return_value=mock_factory))

    await cli_mod.main()
    assert called

