"""Taxonomy-driven backfill of must_skills for jobs with empty criteria.

Replacement for the regex-only `backfill_job_criteria.py` whose narrow
TECH_PATTERN missed Polish role titles ("Tester Manualny", "Analityk
Biznesowy", "Programista Java"). This variant scans job text against the
full skill_aliases taxonomy (194 canonical + 433 aliases as of 2026-05-08,
including Polish business roles seeded in PR #129).

Source priority (per job):
    title + description + requirements + reference_number  →  union regex
    on every alias → canonical name lookup → must_skills.

Idempotent — only touches jobs where must_skills is currently empty.

Run:
    python -m scripts.backfill_job_criteria_taxonomy --dry-run
    python -m scripts.backfill_job_criteria_taxonomy --commit --limit 100
    python -m scripts.backfill_job_criteria_taxonomy --commit
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy import case, func, or_, select  # noqa: E402

from app.core.database import AsyncSessionLocal  # noqa: E402
from app.models.job import Job  # noqa: E402
from app.models.skill import Skill, SkillAlias  # noqa: E402

logger = logging.getLogger("backfill_job_criteria_taxonomy")


async def _build_alias_pattern() -> tuple[re.Pattern | None, dict[str, str]]:
    """Load alias→canonical from DB, build a single union regex.

    Word boundaries via lookarounds on non-word chars so 'java' doesn't match
    inside 'javascript' but 'C#' is matched (the # isn't a word char).
    """
    async with AsyncSessionLocal() as db:
        rows = (
            await db.execute(
                select(SkillAlias.alias, Skill.canonical_name)
                .join(Skill, Skill.id == SkillAlias.skill_id)
            )
        ).all()
        canonical_rows = (await db.execute(select(Skill.canonical_name))).scalars().all()

    alias_map: dict[str, str] = {}
    for alias, canonical in rows:
        alias_map[alias.lower().strip()] = canonical
    # Add canonical names as their own aliases (case-insensitive self-match).
    for c in canonical_rows:
        alias_map.setdefault(c.lower().strip(), c)

    if not alias_map:
        return None, {}

    sorted_aliases = sorted(alias_map.keys(), key=len, reverse=True)
    pattern = (
        r"(?<![A-Za-z0-9_])("
        + "|".join(re.escape(a) for a in sorted_aliases)
        + r")(?![A-Za-z0-9_])"
    )
    return re.compile(pattern, re.IGNORECASE), alias_map


def _extract_canonicals(
    text: str, pattern: re.Pattern, alias_map: dict[str, str]
) -> list[str]:
    if not text or not text.strip():
        return []
    found: dict[str, int] = {}
    for match in pattern.finditer(text):
        canonical = alias_map.get(match.group(1).lower())
        if not canonical:
            continue
        found[canonical] = found.get(canonical, 0) + 1
    # Order by frequency desc, stable secondary by name.
    return [c for c, _ in sorted(found.items(), key=lambda kv: (-kv[1], kv[0]))]


async def _run(*, commit: bool, limit: int | None, log_every: int, max_must: int) -> int:
    pattern, alias_map = await _build_alias_pattern()
    if pattern is None:
        logger.error("Empty alias map — run scripts.seed_skill_aliases --commit first")
        return 1
    logger.info("Loaded %s alias entries", len(alias_map))

    must_len = case(
        (
            func.jsonb_typeof(Job.must_skills) == "array",
            func.jsonb_array_length(Job.must_skills),
        ),
        else_=0,
    )
    async with AsyncSessionLocal() as db:
        stmt = select(Job).where(or_(Job.must_skills.is_(None), must_len == 0))
        if limit is not None:
            stmt = stmt.limit(limit)
        jobs = (await db.execute(stmt)).scalars().all()

    total = len(jobs)
    logger.info("Found %s jobs without must_skills (commit=%s, max_must=%s)", total, commit, max_must)

    updated = empty = 0
    sample: list[tuple[int, str, list[str]]] = []
    for i, job in enumerate(jobs):
        text = " ".join(
            filter(
                None,
                [
                    job.title or "",
                    getattr(job, "reference_number", None) or "",
                    (job.description or "")[:4000],
                    (job.requirements or "")[:4000],
                ],
            )
        )
        canonicals = _extract_canonicals(text, pattern, alias_map)
        if not canonicals:
            empty += 1
            continue

        must = [{"name": c, "level": None} for c in canonicals[:max_must]]
        if commit:
            async with AsyncSessionLocal() as db:
                fresh = await db.scalar(select(Job).where(Job.id == job.id))
                if fresh is None:
                    continue
                fresh.must_skills = must
                fresh.criteria_generated_at = datetime.now(timezone.utc)
                await db.commit()
        updated += 1
        if len(sample) < 10:
            sample.append((job.id, job.title or "", [m["name"] for m in must]))
        if (i + 1) % log_every == 0:
            logger.info(
                "[%s/%s] updated=%s empty=%s",
                i + 1,
                total,
                updated,
                empty,
            )

    logger.info("DONE total=%s updated=%s empty=%s", total, updated, empty)
    logger.info("Sample updates:")
    for jid, title, must in sample:
        logger.info("  job=%s title=%r → %s", jid, title[:80], must)
    return 0


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--commit", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--log-every", type=int, default=200)
    p.add_argument("--max-must", type=int, default=8)
    args = p.parse_args()
    if not args.commit and not args.dry_run:
        p.error("must pass --commit or --dry-run")
    if args.commit and args.dry_run:
        p.error("--commit and --dry-run are mutually exclusive")
    return args


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    args = _parse_args()
    return asyncio.run(
        _run(
            commit=args.commit,
            limit=args.limit,
            log_every=args.log_every,
            max_must=args.max_must,
        )
    )


if __name__ == "__main__":
    sys.exit(main())
