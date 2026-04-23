"""One-off backfill: fill `jobs.tac_id` + `jobs.delivery_lead_id` from
primary TAC + head DL of the job's client.

Only touches OPEN jobs (`status != 'closed' AND status != 'archived'`) and
only populates fields that are currently NULL. Explicit overrides set via
API are preserved — the script is strictly additive.

Usage:
    python -m scripts.backfill_job_owners --dry-run
    python -m scripts.backfill_job_owners --commit
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
from app.services.auto_assign_owners import resolve_default_owners  # noqa: E402

logger = logging.getLogger("backfill_job_owners")


_OPEN_STATUSES = [
    s
    for s in JobStatus
    # closed + archived are terminal; don't rewrite history
    if s.name not in {"closed", "archived"}
]


async def _run(commit: bool) -> dict[str, int]:
    async with AsyncSessionLocal() as db:
        stmt = select(Job).where(
            Job.status.in_(_OPEN_STATUSES),
            or_(Job.tac_id.is_(None), Job.delivery_lead_id.is_(None)),
        )
        jobs = (await db.execute(stmt)).scalars().all()

        logger.info(
            "Candidates: %s open jobs missing tac_id or delivery_lead_id",
            len(jobs),
        )

        counters = {
            "total_candidates": len(jobs),
            "updated": 0,
            "skipped_no_client": 0,
            "skipped_no_assignments": 0,
        }

        for job in jobs:
            if job.client_id is None:
                counters["skipped_no_client"] += 1
                logger.debug("job=%s skipped: no client_id", job.id)
                continue

            resolved = await resolve_default_owners(db, job.client_id)
            if resolved.tac_id is None and resolved.delivery_lead_id is None:
                counters["skipped_no_assignments"] += 1
                logger.debug(
                    "job=%s client=%s skipped: no primary TAC or head DL",
                    job.id,
                    job.client_id,
                )
                continue

            changed = False
            before = {"tac_id": job.tac_id, "delivery_lead_id": job.delivery_lead_id}
            if job.tac_id is None and resolved.tac_id is not None:
                job.tac_id = resolved.tac_id
                changed = True
            if (
                job.delivery_lead_id is None
                and resolved.delivery_lead_id is not None
            ):
                job.delivery_lead_id = resolved.delivery_lead_id
                changed = True

            if changed:
                counters["updated"] += 1
                logger.info(
                    "job=%s client=%s tac %s->%s dl %s->%s",
                    job.id,
                    job.client_id,
                    before["tac_id"],
                    job.tac_id,
                    before["delivery_lead_id"],
                    job.delivery_lead_id,
                )

        if commit:
            await db.commit()
            logger.info("Committed %s job updates", counters["updated"])
        else:
            await db.rollback()
            logger.info(
                "Dry-run — %s jobs would be updated", counters["updated"]
            )

    logger.info(
        "Summary: candidates=%d updated=%d skipped_no_client=%d "
        "skipped_no_assignments=%d",
        counters["total_candidates"],
        counters["updated"],
        counters["skipped_no_client"],
        counters["skipped_no_assignments"],
    )
    return counters


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Backfill tac_id + delivery_lead_id for open jobs."
    )
    parser.add_argument("--commit", action="store_true", help="Persist updates.")
    parser.add_argument(
        "--dry-run", action="store_true", help="Log only, no writes (default)."
    )
    args = parser.parse_args(argv)
    if args.commit and args.dry_run:
        parser.error("--commit and --dry-run are mutually exclusive")

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    commit = bool(args.commit)
    counters = asyncio.run(_run(commit=commit))
    return counters["updated"]


if __name__ == "__main__":
    sys.exit(0 if main() >= 0 else 1)
