"""One-off cleanup: close obvious test data widoczne na prod (audit-2026-05-07).

Identyfikuje:
1. Oferty z tytułem dokładnie "POLL" (placeholder z jakiegoś migration step)
2. Oferty z tytułem zaczynającym się od "SMOKE TEST" (testowe oferty
   wstrzyknięte podczas QA)

Działanie: zmiana `status='closed'`, **bez DELETE** — zachowujemy audit trail
(klient `__traffit_orphans` jest już `inactive`, więc go nie ruszamy).

Usage:
    python -m scripts.cleanup_test_data --dry-run
    python -m scripts.cleanup_test_data --commit
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy import or_, select  # noqa: E402

from app.core.database import AsyncSessionLocal  # noqa: E402
from app.models.job import Job, JobStatus  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
log = logging.getLogger(__name__)


async def cleanup(commit: bool) -> int:
    """Return number of jobs that were (or would be) closed."""
    closed = 0
    async with AsyncSessionLocal() as session:
        # Pattern: tytuły "POLL", "SMOKE TEST*"
        stmt = select(Job).where(
            or_(
                Job.title == "POLL",
                Job.title.like("SMOKE TEST%"),
            ),
            Job.status != JobStatus.closed,
        )
        result = await session.execute(stmt)
        candidates = list(result.scalars().all())
        log.info("Found %d test-data jobs to close:", len(candidates))
        for j in candidates:
            log.info(
                "  - id=%s title=%r status=%s client_id=%s",
                j.id,
                j.title,
                j.status.value if hasattr(j.status, "value") else j.status,
                j.client_id,
            )
            if commit:
                j.status = JobStatus.closed
                closed += 1
        if commit:
            await session.commit()
            log.info("Committed: closed %d jobs", closed)
        else:
            log.info("Dry-run: would close %d jobs", len(candidates))
    return closed


async def main() -> None:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--dry-run", action="store_true", help="Preview without DB writes"
    )
    group.add_argument("--commit", action="store_true", help="Apply changes")
    args = parser.parse_args()
    await cleanup(commit=args.commit)


if __name__ == "__main__":
    asyncio.run(main())
