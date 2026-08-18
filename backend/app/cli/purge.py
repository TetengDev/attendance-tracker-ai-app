from __future__ import annotations

import asyncio
import logging
import sys

from backend.app.db.session import get_session_factory
from backend.app.retention.service import run_purge_job

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("retention_cli")


async def main() -> None:
    logger.info("Initializing nightly retention purge job...")
    try:
        async with get_session_factory()() as session, session.begin():
            stats = await run_purge_job(session)
            logger.info("Purge job succeeded. Stats: %s", stats)
    except Exception:
        logger.exception("Retention purge job failed")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
