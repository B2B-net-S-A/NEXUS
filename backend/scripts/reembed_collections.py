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
from app.services.embedding_service import (  # noqa: E402
    _build_candidate_text,
    _build_job_text,
    _collection,
    _jobs_collection,
    _voyage_embed_batch,
)

logger = logging.getLogger("reembed_collections")


async def _bulk_upsert_qdrant(collection: str, points: list[dict]) -> int:
    """Bulk upsert points into Qdrant. Returns number upserted."""
    if not points:
        return 0
    from qdrant_client.models import PointStruct  # noqa: PLC0415
    from app.services.qdrant_factory import get_qdrant_client  # noqa: PLC0415

    def _upsert():
        client = get_qdrant_client()
        client.upsert(
            collection_name=collection,
            points=[PointStruct(**p) for p in points],
        )

    await asyncio.to_thread(_upsert)
    return len(points)


async def _reembed_candidates(
    *, commit: bool, batch: int, limit: Optional[int], log_every: int
) -> tuple[int, int, int]:
    """Returns (processed, succeeded, failed). Batches Voyage calls (up to 128/req)."""
    processed = succeeded = failed = 0
    async with AsyncSessionLocal() as db:
        stmt = select(Candidate).order_by(Candidate.id.asc())
        if limit is not None:
            stmt = stmt.limit(limit)
        rows = (await db.execute(stmt)).scalars().all()

    total = len(rows)
    logger.info(
        "Found %s candidates to re-embed (model=%s, batch=%s, commit=%s)",
        total,
        settings.VOYAGE_MODEL,
        batch,
        commit,
    )
    if not commit:
        return total, 0, 0

    for i in range(0, total, batch):
        chunk = rows[i : i + batch]
        texts = [_build_candidate_text(c) for c in chunk]
        # Filter out blanks to align with embedding response.
        keep_idx = [j for j, t in enumerate(texts) if t and t.strip()]
        if not keep_idx:
            processed += len(chunk)
            failed += len(chunk)
            continue

        keep_texts = [texts[j] for j in keep_idx]
        embeddings = await _voyage_embed_batch(keep_texts, input_type="document")
        if embeddings is None:
            processed += len(chunk)
            failed += len(chunk)
            logger.warning(
                "[reembed candidates] batch %s-%s failed entirely", i, i + len(chunk)
            )
            continue

        points: list[dict] = []
        for k, j in enumerate(keep_idx):
            emb = embeddings[k] if k < len(embeddings) else None
            c = chunk[j]
            if emb is None:
                failed += 1
                continue
            points.append(
                dict(
                    id=int(c.id),
                    vector=emb,
                    payload={
                        "candidate_id": int(c.id),
                        "name": f"{c.name or ''} {c.lastname or ''}".strip(),
                        "competence_category": c.competence_category or "",
                    },
                )
            )

        try:
            await _bulk_upsert_qdrant(_collection(), points)
            succeeded += len(points)
        except Exception as e:  # noqa: BLE001
            logger.warning("[reembed candidates] qdrant upsert failed: %s", e)
            failed += len(points)

        processed += len(chunk)
        if processed // log_every > (processed - len(chunk)) // log_every:
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
    """Same batched pattern as candidates."""
    processed = succeeded = failed = 0
    async with AsyncSessionLocal() as db:
        stmt = select(Job).order_by(Job.id.asc())
        if limit is not None:
            stmt = stmt.limit(limit)
        rows = (await db.execute(stmt)).scalars().all()

    total = len(rows)
    logger.info(
        "Found %s jobs to re-embed (model=%s, batch=%s, commit=%s)",
        total,
        settings.VOYAGE_MODEL,
        batch,
        commit,
    )
    if not commit:
        return total, 0, 0

    for i in range(0, total, batch):
        chunk = rows[i : i + batch]
        texts = [_build_job_text(j) for j in chunk]
        keep_idx = [k for k, t in enumerate(texts) if t and t.strip()]
        if not keep_idx:
            processed += len(chunk)
            failed += len(chunk)
            continue

        keep_texts = [texts[k] for k in keep_idx]
        embeddings = await _voyage_embed_batch(keep_texts, input_type="document")
        if embeddings is None:
            processed += len(chunk)
            failed += len(chunk)
            logger.warning(
                "[reembed jobs] batch %s-%s failed entirely", i, i + len(chunk)
            )
            continue

        points: list[dict] = []
        for k, j in enumerate(keep_idx):
            emb = embeddings[k] if k < len(embeddings) else None
            job = chunk[j]
            if emb is None:
                failed += 1
                continue
            payload = {
                "job_id": int(job.id),
                "title": job.title or "",
                "client_id": job.client_id,
                "industry": job.industry or "",
            }
            train_name = getattr(job, "train_name", None)
            if train_name:
                payload["train_name"] = train_name
            points.append(dict(id=int(job.id), vector=emb, payload=payload))

        try:
            await _bulk_upsert_qdrant(_jobs_collection(), points)
            succeeded += len(points)
        except Exception as e:  # noqa: BLE001
            logger.warning("[reembed jobs] qdrant upsert failed: %s", e)
            failed += len(points)

        processed += len(chunk)
        if processed // log_every > (processed - len(chunk)) // log_every:
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
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--target", choices=["candidates", "jobs", "all"], default="all")
    p.add_argument(
        "--commit", action="store_true", help="actually call Voyage + upsert Qdrant"
    )
    p.add_argument("--dry-run", action="store_true", help="count only, no API calls")
    p.add_argument(
        "--batch",
        type=int,
        default=128,
        help="Voyage batch size (max 128, default 128 for ~390 calls / 50K candidates)",
    )
    p.add_argument(
        "--limit", type=int, default=None, help="cap number of entities (testing)"
    )
    p.add_argument(
        "--log-every", type=int, default=100, help="progress log every N entities"
    )
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
