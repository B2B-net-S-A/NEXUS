"""One-off backfill: populate must/nice_skills for jobs that lack them.

Uses the existing `_fallback_criteria_from_text` heuristic (regex over
title+description+requirements) so the scoring engine has something to compare
candidate skills against. When Ollama is configured, prefers its output.

Run:
    python -m scripts.backfill_job_criteria --dry-run
    python -m scripts.backfill_job_criteria --commit
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy import case, func, or_, select  # noqa: E402

from app.api.recommendations import (  # noqa: E402
    _fallback_criteria_from_text,
    _generate_criteria_with_ollama,
)
from app.core.database import AsyncSessionLocal  # noqa: E402
from app.models.job import Job  # noqa: E402

logger = logging.getLogger("backfill_job_criteria")


async def _run(commit: bool, use_ollama: bool) -> int:
    async with AsyncSessionLocal() as db:
        # "Missing" = NULL, scalar value, or empty JSONB array. Postgres does
        # not short-circuit AND in WHERE — same fix as eval_matching.py: gate
        # jsonb_array_length with CASE WHEN jsonb_typeof = 'array'.
        must_len = case(
            (
                func.jsonb_typeof(Job.must_skills) == "array",
                func.jsonb_array_length(Job.must_skills),
            ),
            else_=0,
        )
        jobs = (
            await db.execute(
                select(Job).where(or_(Job.must_skills.is_(None), must_len == 0))
            )
        ).scalars().all()

        logger.info("Found %s jobs without must_skills", len(jobs))
        updates: list[tuple[int, dict]] = []

        for job in jobs:
            criteria = None
            if use_ollama:
                criteria = await _generate_criteria_with_ollama(job)
            if not criteria:
                criteria = _fallback_criteria_from_text(job)

            must = criteria.get("must_skills") or []
            nice = criteria.get("nice_skills") or []
            if not must and not nice:
                logger.warning("job=%s (%r): no criteria could be derived", job.id, job.title)
                continue

            updates.append((job.id, {"must": must, "nice": nice}))
            logger.info(
                "job=%s (%r): must=%s nice=%s",
                job.id,
                job.title,
                [m.get("name") for m in must],
                [n.get("name") for n in nice],
            )

            if commit:
                job.must_skills = must
                job.nice_skills = nice
                job.criteria_generated_at = datetime.now(timezone.utc)

        if commit:
            await db.commit()
            logger.info("Committed %s job updates", len(updates))
        else:
            logger.info("Dry-run — %s jobs would be updated", len(updates))

    return len(updates)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Backfill must/nice skills for jobs.")
    parser.add_argument("--commit", action="store_true", help="Persist updates.")
    parser.add_argument("--dry-run", action="store_true", help="Log only, no writes.")
    parser.add_argument(
        "--no-ollama",
        action="store_true",
        help="Skip LLM and use the regex heuristic only (faster, no network).",
    )
    args = parser.parse_args(argv)
    if args.commit and args.dry_run:
        parser.error("--commit and --dry-run are mutually exclusive")

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    commit = bool(args.commit)
    use_ollama = not args.no_ollama
    return asyncio.run(_run(commit=commit, use_ollama=use_ollama))


if __name__ == "__main__":
    sys.exit(0 if main() >= 0 else 1)
