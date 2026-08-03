from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from backend.app.audit.export import (
    AuditChainExportError,
    AuditChainExportRecord,
    export_audit_chain_record,
    validate_export_destination,
)

HASH = "abcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890"


def test_export_record_includes_chain_head_fields() -> None:
    record = _record()

    assert record.to_json_dict() == {
        "version": 1,
        "source": "attendance-tracker-ai-app",
        "environment": "test",
        "deployment_id": "deploy-1",
        "exported_at": "2026-08-03T11:40:00+00:00",
        "row_count": 3,
        "last_id": 3,
        "head_hash": HASH,
        "verified_head_hash": HASH,
    }


def test_export_writes_exclusive_read_only_json_snapshot(tmp_path: Path) -> None:
    target = export_audit_chain_record(_record(), destination_dir=tmp_path)

    assert target.exists()
    assert target.stat().st_mode & 0o777 == 0o400
    assert json.loads(target.read_text())["head_hash"] == HASH
    with pytest.raises(FileExistsError):
        export_audit_chain_record(_record(), destination_dir=tmp_path)


def test_export_rejects_relative_destination() -> None:
    with pytest.raises(AuditChainExportError, match="absolute off-box path"):
        validate_export_destination(Path("relative/path"))


def test_export_rejects_repo_destination(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    export_dir = repo / "audit-heads"
    export_dir.mkdir(parents=True)

    with pytest.raises(AuditChainExportError, match="inside the app repo"):
        validate_export_destination(export_dir, repository_root=repo)


def test_export_requires_existing_directory(tmp_path: Path) -> None:
    with pytest.raises(AuditChainExportError, match="does not exist"):
        validate_export_destination(tmp_path / "missing")


def test_export_rejects_file_destination(tmp_path: Path) -> None:
    destination = tmp_path / "not-a-directory"
    destination.write_text("nope")

    with pytest.raises(AuditChainExportError, match="not a directory"):
        validate_export_destination(destination)


def test_export_rejects_non_sha256_hash() -> None:
    with pytest.raises(AuditChainExportError, match="64-character lowercase hex"):
        AuditChainExportRecord(
            exported_at=datetime(2026, 8, 3, 11, 40, tzinfo=UTC),
            row_count=1,
            last_id=1,
            head_hash="ABC",
            verified_head_hash="ABC",
            environment="test",
            deployment_id=None,
        )


def test_export_rejects_latest_and_verified_head_mismatch() -> None:
    with pytest.raises(AuditChainExportError, match="must match"):
        AuditChainExportRecord(
            exported_at=datetime(2026, 8, 3, 11, 40, tzinfo=UTC),
            row_count=1,
            last_id=1,
            head_hash="a" * 64,
            verified_head_hash="b" * 64,
            environment="test",
            deployment_id=None,
        )


def _record() -> AuditChainExportRecord:
    return AuditChainExportRecord(
        exported_at=datetime(2026, 8, 3, 11, 40, tzinfo=UTC),
        row_count=3,
        last_id=3,
        head_hash=HASH,
        verified_head_hash=HASH,
        environment="test",
        deployment_id="deploy-1",
    )
