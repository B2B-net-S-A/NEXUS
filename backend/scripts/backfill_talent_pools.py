"""One-off backfill for Talent Pool auto-add (Phase 10 A2).

Two independent phases, controlled by --cc-only / --memberships-only
(default = both):

  Phase A — CC backfill for existing pools
    For every TalentPool with competence_category_id IS NULL:
      - collect distinct source_job_id from its memberships
      - pick the mode() of job.competence_category_id (most common non-NULL)
      - if no source-job CC exists (true for all legacy pools on prod — every
        job currently has CC=NULL), fall back to a deterministic name-based
        classification (services.talent_pool_cc)
      - update pool if a CC was resolved; leave NULL otherwise (e.g. non-role
        buckets like "Targ kandydatów")

  Phase B — Historical membership backfill
    Replay every CandidateStage row with stage = cv_sent (in chronological
    order) by calling `auto_add_on_cv_sent()`. Full idempotency via
    uq_pool_candidate UniqueConstraint. Re-runnable without side effects.

Run:
    python -m scripts.backfill_talent_pools --dry-run
    python -m scripts.backfill_talent_pools --commit
    python -m scripts.backfill_talent_pools --commit --cc-only
    python -m scripts.backfill_talent_pools --commit --memberships-only
    python -m scripts.backfill_talent_pools --commit --since 2026-01-01T00:00:00

On race conditions (backfill vs. live cv_sent moves on the same pool), the
script retries the failing candidate ONCE after IntegrityError; the second
try will see the competing pool row and reuse it.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Optional

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.exc import IntegrityError  # noqa: E402

from app.core.database import AsyncSessionLocal  # noqa: E402
from app.models.competence_category import CompetenceCategory  # noqa: E402
from app.models.job import Job  # noqa: E402
from app.models.recruitment_pipeline import (  # noqa: E402
    CandidateStage,
    PipelineStage,
)
from app.models.talent_pool import TalentPool, TalentPoolMembership  # noqa: E402
from app.services.talent_pool_auto_add import auto_add_on_cv_sent  # noqa: E402
from app.services.talent_pool_cc import (  # noqa: E402
    classify_pool_name_to_cc_slug,
)

logger = logging.getLogger("backfill_talent_pools")

BATCH_COMMIT_SIZE = 500


async def _backfill_cc(commit: bool) -> int:
    """Phase A — populate competence_category_id on pools where it's NULL."""
    updated = 0
    async with AsyncSessionLocal() as db:
        pools = (
            (
                await db.execute(
                    select(TalentPool).where(
                        TalentPool.competence_category_id.is_(None)
                    )
                )
            )
            .scalars()
            .all()
        )
        logger.info("Phase A: %s pools with CC=NULL", len(pools))

        cc_rows = (
            await db.execute(
                select(CompetenceCategory.id, CompetenceCategory.slug)
            )
        ).all()
        slug_to_id = {slug: cid for cid, slug in cc_rows}

        for pool in pools:
            resolved_cc: Optional[int] = None
            source = ""

            # 1) Authoritative path — mode of source-job CCs (when any exist).
            job_ids_result = await db.execute(
                select(TalentPoolMembership.source_job_id)
                .where(TalentPoolMembership.talent_pool_id == pool.id)
                .where(TalentPoolMembership.source_job_id.is_not(None))
            )
            job_ids = [row[0] for row in job_ids_result.all()]
            if job_ids:
                cc_ids_result = await db.execute(
                    select(Job.competence_category_id).where(
                        Job.id.in_(job_ids)
                    )
                )
                cc_ids = [
                    row[0] for row in cc_ids_result.all() if row[0] is not None
                ]
                if cc_ids:
                    resolved_cc, count = Counter(cc_ids).most_common(1)[0]
                    source = f"lineage ({count}/{len(job_ids)} jobs agree)"

            # 2) Fallback — deterministic name-based classification. On prod
            #    every job has CC=NULL, so this is what actually categorises the
            #    legacy pools.
            if resolved_cc is None:
                slug = classify_pool_name_to_cc_slug(pool.name)
                resolved_cc = slug_to_id.get(slug) if slug else None
                source = f"name → {slug}" if slug else "no rule match"

            if resolved_cc is None:
                logger.info(
                    "pool=%s (%r): %s — leave NULL",
                    pool.id,
                    pool.name,
                    source,
                )
                continue

            logger.info(
                "pool=%s (%r): CC=%s via %s",
                pool.id,
                pool.name,
                resolved_cc,
                source,
            )
            if commit:
                pool.competence_category_id = resolved_cc
            updated += 1

        if commit:
            await db.commit()
            logger.info("Phase A: committed %s pool CC updates", updated)
        else:
            logger.info("Phase A: dry-run — %s pools would be updated", updated)

    return updated


async def _backfill_memberships(
    commit: bool, since: Optional[datetime]
) -> tuple[int, int]:
    """Phase B — replay cv_sent stages chronologically.

    Returns (added, already_in_pool) counts.
    """
    added = 0
    already = 0
    skipped = 0
    errors = 0

    async with AsyncSessionLocal() as db:
        stmt = select(CandidateStage).where(
            CandidateStage.stage == PipelineStage.cv_sent
        )
        if since is not None:
            stmt = stmt.where(CandidateStage.moved_at >= since)
        stmt = stmt.order_by(CandidateStage.moved_at.asc())

        rows = (await db.execute(stmt)).scalars().all()
        total = len(rows)
        logger.info("Phase B: %s cv_sent stage rows to replay", total)

        processed = 0
        for row in rows:
            processed += 1
            job = await db.get(Job, row.job_id)
            if job is None:
                logger.warning(
                    "row=%s: job_id=%s missing — skip",
                    row.id,
                    row.job_id,
                )
                skipped += 1
                continue

            try:
                result = await auto_add_on_cv_sent(
                    db=db,
                    candidate_id=row.candidate_id,
                    job=job,
                    user_id=row.moved_by,
                    extra_activity_details={"backfill": True},
                )
            except IntegrityError as e:
                # Race with live cv_sent — rollback this row and retry once
                await db.rollback()
                logger.warning(
                    "row=%s: IntegrityError, retrying once (%s)", row.id, e
                )
                try:
                    job2 = await db.get(Job, row.job_id)
                    if job2 is None:
                        errors += 1
                        continue
                    result = await auto_add_on_cv_sent(
                        db=db,
                        candidate_id=row.candidate_id,
                        job=job2,
                        user_id=row.moved_by,
                        extra_activity_details={"backfill": True, "retry": 1},
                    )
                except Exception as retry_err:  # noqa: BLE001
                    await db.rollback()
                    logger.error(
                        "row=%s: retry failed: %s", row.id, retry_err
                    )
                    errors += 1
                    continue

            if result.status == "added":
                added += 1
            elif result.status == "already_in_pool":
                already += 1
            elif result.status == "skipped_no_category":
                skipped += 1

            # Batch commit
            if commit and processed % BATCH_COMMIT_SIZE == 0:
                await db.commit()
                logger.info(
                    "Phase B: progress %s/%s (added=%s already=%s skipped=%s errors=%s)",
                    processed,
                    total,
                    added,
                    already,
                    skipped,
                    errors,
                )

        if commit:
            await db.commit()
            logger.info(
                "Phase B: committed — total=%s added=%s already=%s skipped=%s errors=%s",
                total,
                added,
                already,
                skipped,
                errors,
            )
        else:
            await db.rollback()
            logger.info(
                "Phase B: dry-run — total=%s would-add=%s already=%s skipped=%s errors=%s",
                total,
                added,
                already,
                skipped,
                errors,
            )

    return added, already


async def _run(
    *,
    commit: bool,
    cc_only: bool,
    memberships_only: bool,
    since: Optional[datetime],
) -> int:
    total = 0

    if not memberships_only:
        total += await _backfill_cc(commit=commit)

    if not cc_only:
        added, _already = await _backfill_memberships(
            commit=commit, since=since
        )
        total += added

    return total


def _parse_since(raw: Optional[str]) -> Optional[datetime]:
    if raw is None:
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"--since must be ISO-8601 datetime, got {raw!r}"
        ) from exc


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Backfill Talent Pool CC + historical cv_sent memberships."
    )
    parser.add_argument(
        "--commit", action="store_true", help="Persist updates to DB."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Log only, no writes.",
    )
    parser.add_argument(
        "--cc-only",
        action="store_true",
        help="Run only Phase A (pool CC population).",
    )
    parser.add_argument(
        "--memberships-only",
        action="store_true",
        help="Run only Phase B (historical membership replay).",
    )
    parser.add_argument(
        "--since",
        type=_parse_since,
        default=None,
        help="ISO-8601 datetime — replay only cv_sent stages on/after this moment.",
    )
    args = parser.parse_args(argv)

    if args.commit and args.dry_run:
        parser.error("--commit and --dry-run are mutually exclusive")
    if args.cc_only and args.memberships_only:
        parser.error(
            "--cc-only and --memberships-only are mutually exclusive"
        )

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    commit = bool(args.commit)
    return asyncio.run(
        _run(
            commit=commit,
            cc_only=bool(args.cc_only),
            memberships_only=bool(args.memberships_only),
            since=args.since,
        )
    )


if __name__ == "__main__":
    sys.exit(0 if main() >= 0 else 1)
