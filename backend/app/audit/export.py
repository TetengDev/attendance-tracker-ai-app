from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.audit.service import audit_chain_head, verify_persisted_audit_chain


class AuditChainExportError(ValueError):
    """Raised when the audit chain head cannot be exported safely."""


@dataclass(frozen=True)
class AuditChainExportRecord:
    exported_at: datetime
    row_count: int
    last_id: int | None
    head_hash: str | None
    verified_head_hash: str | None
    environment: str
    deployment_id: str | None
    source: str = "attendance-tracker-ai-app"
    version: int = 1

    def __post_init__(self) -> None:
        _validate_hash(self.head_hash, field_name="head_hash")
        _validate_hash(self.verified_head_hash, field_name="verified_head_hash")
        if self.head_hash != self.verified_head_hash:
            raise AuditChainExportError("head_hash must match verified_head_hash")

    def to_json_dict(self) -> dict[str, object]:
        return {
            "version": self.version,
            "source": self.source,
            "environment": self.environment,
            "deployment_id": self.deployment_id,
            "exported_at": self.exported_at.isoformat(),
            "row_count": self.row_count,
            "last_id": self.last_id,
            "head_hash": self.head_hash,
            "verified_head_hash": self.verified_head_hash,
        }


async def build_audit_chain_export_record(
    session: AsyncSession,
    *,
    environment: str,
    deployment_id: str | None = None,
) -> AuditChainExportRecord:
    verified_head = await verify_persisted_audit_chain(session)
    head = await audit_chain_head(session)
    verified_head_hash = verified_head.hex() if verified_head is not None else None
    if head["head_hash"] != verified_head_hash:
        raise AuditChainExportError("verified audit chain head does not match latest audit row")
    return AuditChainExportRecord(
        exported_at=datetime.now(UTC),
        row_count=_as_int(head["row_count"]),
        last_id=_as_optional_int(head["last_id"]),
        head_hash=_as_optional_str(head["head_hash"]),
        verified_head_hash=verified_head_hash,
        environment=environment,
        deployment_id=deployment_id,
    )


def export_audit_chain_record(
    record: AuditChainExportRecord,
    *,
    destination_dir: Path,
    repository_root: Path | None = None,
) -> Path:
    safe_destination = validate_export_destination(destination_dir, repository_root=repository_root)
    payload = json.dumps(record.to_json_dict(), sort_keys=True, indent=2) + "\n"
    target = safe_destination / _export_filename(record)
    descriptor = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o400)
    with os.fdopen(descriptor, "w", encoding="utf-8") as file:
        file.write(payload)
    return target


def validate_export_destination(
    destination_dir: Path,
    *,
    repository_root: Path | None = None,
) -> Path:
    if not destination_dir.is_absolute():
        raise AuditChainExportError("AUDIT_CHAIN_EXPORT_DIR must be an absolute off-box path")
    resolved_destination = destination_dir.resolve()
    if repository_root is not None:
        resolved_repository = repository_root.resolve()
        if _is_relative_to(resolved_destination, resolved_repository):
            raise AuditChainExportError("audit chain exports must not be written inside the app repo")
    if not resolved_destination.exists():
        raise AuditChainExportError(f"audit chain export directory does not exist: {resolved_destination}")
    if not resolved_destination.is_dir():
        raise AuditChainExportError(f"audit chain export destination is not a directory: {resolved_destination}")
    return resolved_destination


def _export_filename(record: AuditChainExportRecord) -> str:
    timestamp = record.exported_at.strftime("%Y%m%dT%H%M%SZ")
    last_id = "empty" if record.last_id is None else str(record.last_id)
    hash_prefix = "no-head" if record.head_hash is None else record.head_hash[:12]
    return f"audit-chain-head-{timestamp}-row-{last_id}-{hash_prefix}.json"


def _validate_hash(value: str | None, *, field_name: str) -> None:
    if value is None:
        return
    if re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise AuditChainExportError(f"{field_name} must be a 64-character lowercase hex hash")


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def _as_int(value: Any) -> int:
    if isinstance(value, int):
        return value
    raise AuditChainExportError(f"expected integer audit head value, got {value!r}")


def _as_optional_int(value: Any) -> int | None:
    if value is None or isinstance(value, int):
        return value
    raise AuditChainExportError(f"expected optional integer audit head value, got {value!r}")


def _as_optional_str(value: Any) -> str | None:
    if value is None or isinstance(value, str):
        return value
    raise AuditChainExportError(f"expected optional string audit head value, got {value!r}")
