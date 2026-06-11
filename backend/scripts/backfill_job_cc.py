"""One-off backfill: jobs.competence_category_id (the /jobs "Kategoria" filter).

On production every job had ``competence_category_id = NULL`` (3919/3919 as of
2026-06-11) — the UI filter and the API param existed but always returned 0
results. This script classifies every NULL job:

  Tier 1 — deterministic title rules (``services.job_cc``), pure/offline,
  Tier 2 — hybrid keyword+embedding classifier (Qdrant centroids), accepted
           only when confident (no tie, score ≥ 0.30). Skipped with
           ``--title-only``.

Jobs matching neither tier (non-role buckets like "Opportunity") stay NULL.
Idempotent and re-runnable — only touches rows where the CC is still NULL.

Run (inside the backend container):
    python -m scripts.backfill_job_cc --dry-run
    python -m scripts.backfill_job_cc --commit
    python -m scripts.backfill_job_cc --commit --title-only
    python -m scripts.backfill_job_cc --dry-run --limit 200
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from collections import Counter
from pathlib import Path
from typing import Optional

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy import select  # noqa: E402

from app.core.database import AsyncSessionLocal  # noqa: E402
from app.models.competence_category import CompetenceCategory  # noqa: E402
from app.models.job import Job  # noqa: E402
from app.services.cc_classifier import classify_job_to_cc  # noqa: E402
from app.services.job_cc import (  # noqa: E402
    HYBRID_MIN_SCORE,
    classify_job_title_to_cc_slug,
)

logger = logging.getLogger("backfill_job_cc")

BATCH_COMMIT_SIZE = 500


async def run(
    commit: bool, title_only: bool, limit: Optional[int]
) -> None:
    updated_by_slug: Counter[str] = Counter()
    tier_counts: Counter[str] = Counter()

    async with AsyncSessionLocal() as db:
        slug_to_id: dict[str, int] = {
            slug: cc_id
            for cc_id, slug in (
                await db.execute(
                    select(CompetenceCategory.id, CompetenceCategory.slug).where(
                        CompetenceCategory.is_active.is_(True)
                    )
                )
            ).all()
        }
        id_to_slug = {v: k for k, v in slug_to_id.items()}

        query = (
            select(Job)
            .where(Job.competence_category_id.is_(None))
            .order_by(Job.id.asc())
        )
        if limit:
            query = query.limit(limit)
        jobs = (await db.execute(query)).scalars().all()
        logger.info("Jobs with NULL competence_category_id: %d", len(jobs))

        pending = 0
        for job in jobs:
            cc_id: Optional[int] = None
            tier = "unmatched"

            slug = classify_job_title_to_cc_slug(job.title)
            if slug is not None and slug in slug_to_id:
                cc_id = slug_to_id[slug]
                tier = "title"
            elif not title_only:
                result = await classify_job_to_cc(job, db)
                if (
                    result.top
                    and not result.tie
                    and result.top.score >= HYBRID_MIN_SCORE
                ):
                    cc_id = result.top.cc_id
                    tier = "hybrid"

            tier_counts[tier] += 1
            if cc_id is None:
                continue

            updated_by_slug[id_to_slug.get(cc_id, str(cc_id))] += 1
            if commit:
                job.competence_category_id = cc_id
                pending += 1
                if pending >= BATCH_COMMIT_SIZE:
                    await db.commit()
                    logger.info(
                        "Committed batch (%d assigned so far)",
                        sum(updated_by_slug.values()),
                    )
                    pending = 0

        if commit and pending:
            await db.commit()

    total_assigned = sum(updated_by_slug.values())
    logger.info(
        "%s %d/%d jobs (tiers: %s)",
        "Assigned" if commit else "[DRY-RUN] Would assign",
        total_assigned,
        sum(tier_counts.values()),
        dict(tier_counts),
    )
    for slug, count in updated_by_slug.most_common():
        logger.info("  %-28s %d", slug, count)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="classify, no writes")
    mode.add_argument("--commit", action="store_true", help="write assignments")
    parser.add_argument(
        "--title-only",
        action="store_true",
        help="skip the hybrid (Qdrant) fallback tier",
    )
    parser.add_argument("--limit", type=int, default=None, help="max jobs to process")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    asyncio.run(run(commit=args.commit, title_only=args.title_only, limit=args.limit))


if __name__ == "__main__":
    main()
