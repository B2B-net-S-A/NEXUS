"""One-off re-embed: regenerate Qdrant vectors for candidates and jobs.

Used after switching `VOYAGE_MODEL` (e.g. voyage-3 -> voyage-3-large) — old
embeddings live in a different semantic space, so retrieval against the new
query embeddings degrades until we re-embed.

Run:
    # candidates only, dry run (counts what would be processed)
    python -m scripts.reembed_collections --target candidates --dry-run

    # jobs only, with commit
    python -m scripts.reembed_collections --target jobs --commit

    # both, commit, batch size 50, max 200 (testing)
    python -m scripts.reembed_collections --target all --commit --batch 50 --limit 200

    # progress logging every 100 entities
    python -m scripts.reembed_collections --target all --commit --log-every 100
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path
from typing import Optional

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy import select  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.core.database import AsyncSessionLocal  # noqa: E402
from app.models.candidate import Candidate  # noqa: E402
from app.models.job import Job  # noqa: E402
from app.services.embedding_service import embed_candidate, embed_job  # noqa: E402

logger = logging.getLogger("reembed_collections")


async def _reembed_candidates(
    *, commit: bool, batch: int, limit: Optional[int], log_every: int
) -> tuple[int, int, int]:
    """Returns (processed, succeeded, failed)."""
    processed = succeeded = failed = 0
    async with AsyncSessionLocal() as db:
        # Pull only IDs to keep memory bounded; we re-fetch row inside embed_candidate.
        stmt = select(Candidate.id).order_by(Candidate.id.asc())
        if limit is not None:
            stmt = stmt.limit(limit)
        rows = (await db.execute(stmt)).scalars().all()

    total = len(rows)
    logger.info(
        "Found %s candidates to re-embed (model=%s, commit=%s)",
        total,
        settings.VOYAGE_MODEL,
        commit,
    )
    if not commit:
        return total, 0, 0

    for i in range(0, total, batch):
        chunk = rows[i : i + batch]
        async with AsyncSessionLocal() as db:
            for cid in chunk:
                processed += 1
                try:
                    ok = await embed_candidate(cid, db)
                    succeeded += 1 if ok else 0
                    failed += 0 if ok else 1
                except Exception as e:  # noqa: BLE001 — surface any error
                    failed += 1
                    logger.warning("[reembed] candidate %s failed: %s", cid, e)
                if processed % log_every == 0:
                    logger.info(
                        "[reembed candidates] %s/%s (ok=%s, fail=%s)",
                        processed,
                        total,
                        succeeded,
                        failed,
                    )
    logger.info(
        "[reembed candidates] DONE %s/%s (ok=%s, fail=%s)",
        processed,
        total,
        succeeded,
        failed,
    )
    return processed, succeeded, failed


async def _reembed_jobs(
    *, commit: bool, batch: int, limit: Optional[int], log_every: int
) -> tuple[int, int, int]:
    processed = succeeded = failed = 0
    async with AsyncSessionLocal() as db:
        stmt = select(Job.id).order_by(Job.id.asc())
        if limit is not None:
            stmt = stmt.limit(limit)
        rows = (await db.execute(stmt)).scalars().all()

    total = len(rows)
    logger.info(
        "Found %s jobs to re-embed (model=%s, commit=%s)",
        total,
        settings.VOYAGE_MODEL,
        commit,
    )
    if not commit:
        return total, 0, 0

    for i in range(0, total, batch):
        chunk = rows[i : i + batch]
        async with AsyncSessionLocal() as db:
            for jid in chunk:
                processed += 1
                try:
                    ok = await embed_job(jid, db)
                    succeeded += 1 if ok else 0
                    failed += 0 if ok else 1
                except Exception as e:  # noqa: BLE001
                    failed += 1
                    logger.warning("[reembed] job %s failed: %s", jid, e)
                if processed % log_every == 0:
                    logger.info(
                        "[reembed jobs] %s/%s (ok=%s, fail=%s)",
                        processed,
                        total,
                        succeeded,
                        failed,
                    )
    logger.info(
        "[reembed jobs] DONE %s/%s (ok=%s, fail=%s)",
        processed,
        total,
        succeeded,
        failed,
    )
    return processed, succeeded, failed


def _parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--target", choices=["candidates", "jobs", "all"], default="all")
    p.add_argument("--commit", action="store_true", help="actually call Voyage + upsert Qdrant")
    p.add_argument("--dry-run", action="store_true", help="count only, no API calls")
    p.add_argument("--batch", type=int, default=50, help="DB session batch size (default 50)")
    p.add_argument("--limit", type=int, default=None, help="cap number of entities (testing)")
    p.add_argument("--log-every", type=int, default=100, help="progress log every N entities")
    args = p.parse_args(argv)
    if not args.commit and not args.dry_run:
        p.error("must pass --commit or --dry-run")
    if args.commit and args.dry_run:
        p.error("--commit and --dry-run are mutually exclusive")
    return args


async def _main(args: argparse.Namespace) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    if args.target in ("candidates", "all"):
        await _reembed_candidates(
            commit=args.commit,
            batch=args.batch,
            limit=args.limit,
            log_every=args.log_every,
        )
    if args.target in ("jobs", "all"):
        await _reembed_jobs(
            commit=args.commit,
            batch=args.batch,
            limit=args.limit,
            log_every=args.log_every,
        )
    return 0


def main() -> int:
    return asyncio.run(_main(_parse_args()))


if __name__ == "__main__":
    sys.exit(main())
