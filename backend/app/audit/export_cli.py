from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path

from backend.app.audit.export import (
    AuditChainExportError,
    build_audit_chain_export_record,
    export_audit_chain_record,
    validate_export_destination,
)
from backend.app.db.session import get_session_factory


def main() -> None:
    parser = argparse.ArgumentParser(description="Export the verified audit chain head off-box.")
    parser.add_argument(
        "--destination-dir",
        help="Absolute off-box export directory. Defaults to AUDIT_CHAIN_EXPORT_DIR.",
    )
    args = parser.parse_args()
    destination_dir = args.destination_dir or os.getenv("AUDIT_CHAIN_EXPORT_DIR")
    if not destination_dir:
        parser.error("--destination-dir or AUDIT_CHAIN_EXPORT_DIR is required")
    try:
        safe_destination = validate_export_destination(Path(destination_dir), repository_root=Path.cwd())
        exported_path = asyncio.run(
            _export(
                safe_destination,
                environment=os.getenv("AUDIT_CHAIN_EXPORT_ENVIRONMENT", "production"),
                deployment_id=os.getenv("AUDIT_CHAIN_EXPORT_DEPLOYMENT_ID"),
            )
        )
    except AuditChainExportError as exc:
        parser.error(str(exc))
    print(json.dumps({"status": "ok", "exported_path": str(exported_path)}, sort_keys=True))


async def _export(
    destination_dir: Path,
    *,
    environment: str,
    deployment_id: str | None,
) -> Path:
    async with get_session_factory()() as session:
        record = await build_audit_chain_export_record(
            session,
            environment=environment,
            deployment_id=deployment_id,
        )
    return export_audit_chain_record(record, destination_dir=destination_dir)


if __name__ == "__main__":
    main()
