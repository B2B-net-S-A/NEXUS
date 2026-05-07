"""Round 2: migrate candidates.cv_file_content (BYTEA) → Hetzner Object Storage.

Round 1 (scripts/migrate_cvs_to_object_storage.py) zmigrowała
`candidate_documents` (13 GB). Round 2 zmigruje `candidates.cv_file_content`
(11 GB, ~41k records) — single primary CV per kandydat, używany przez
Traffit/Talent Radar importerów + bulk-cv-download endpoint fallback.

2-fazowe podejście (jak round 1):
    1. COPY:    BYTEA → S3 → save cv_storage_key.
    2. VERIFY:  smoke test bulk-cv-download.
    3. DELETE:  --finalize-delete-bytea zeruje cv_file_content.
    4. VACUUM:  VACUUM FULL candidates → uwolni ~11 GB.

Idempotent: pomija rekordy które już mają cv_storage_key.

Usage:
    python -m scripts.migrate_candidates_cv_to_object_storage --dry-run
    python -m scripts.migrate_candidates_cv_to_object_storage --commit --batch 200
    python -m scripts.migrate_candidates_cv_to_object_storage --finalize-delete-bytea
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

from sqlalchemy import func, select, update  # noqa: E402

from app.core.database import AsyncSessionLocal  # noqa: E402
from app.models.candidate import Candidate  # noqa: E402
from app.services.object_storage import is_available, upload_cv  # noqa: E402

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s | %(message)s"
)
log = logging.getLogger(__name__)


async def _count_remaining(session) -> int:
    return (
        await session.scalar(
            select(func.count(Candidate.id))
            .where(Candidate.cv_storage_key.is_(None))
            .where(Candidate.cv_file_content.isnot(None))
        )
        or 0
    )


async def copy_phase(commit: bool, batch: int) -> int:
    if commit and not is_available():
        log.error(
            "Object storage env not configured. Set OBJECT_STORAGE_ENDPOINT, "
            "OBJECT_STORAGE_ACCESS_KEY, OBJECT_STORAGE_SECRET_KEY."
        )
        return 0

    inserted = 0
    async with AsyncSessionLocal() as session:
        total = await _count_remaining(session)
        log.info("Candidates pending migration: %d", total)
        if not commit:
            log.info("Dry-run: would migrate %d candidates", total)
            return 0

        while True:
            stmt = (
                select(Candidate)
                .where(Candidate.cv_storage_key.is_(None))
                .where(Candidate.cv_file_content.isnot(None))
                .order_by(Candidate.id)
                .limit(batch)
            )
            rows = (await session.execute(stmt)).scalars().all()
            if not rows:
                break
            for cand in rows:
                try:
                    # Filename może być pusty/None — fallback po id.
                    filename = cand.cv_filename or f"candidate-{cand.id}-cv.pdf"
                    key = upload_cv(
                        content=cand.cv_file_content,
                        filename=filename,
                        content_type=None,  # candidates nie ma osobnego content_type
                    )
                    cand.cv_storage_key = key
                    inserted += 1
                except Exception as e:
                    log.exception("Failed to upload candidate %s: %s", cand.id, e)
                    await session.rollback()
                    return inserted
            await session.commit()
            log.info("Committed batch: %d uploaded so far", inserted)

    log.info("Copy phase done: %d candidates migrated", inserted)
    return inserted


async def finalize_delete_bytea() -> int:
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            update(Candidate)
            .where(Candidate.cv_storage_key.isnot(None))
            .where(Candidate.cv_file_content.isnot(None))
            .values(cv_file_content=None)
        )
        await session.commit()
        n = result.rowcount or 0
        log.info("Cleared cv_file_content for %d candidates", n)
        log.info("NEXT: VACUUM FULL candidates; (~10-15 min, exclusive lock)")
        return n


async def main() -> None:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--dry-run", action="store_true")
    group.add_argument("--commit", action="store_true")
    group.add_argument("--finalize-delete-bytea", action="store_true")
    parser.add_argument("--batch", type=int, default=200)
    args = parser.parse_args()

    if args.finalize_delete_bytea:
        await finalize_delete_bytea()
    else:
        await copy_phase(commit=args.commit, batch=args.batch)


if __name__ == "__main__":
    asyncio.run(main())
