"""One-off backfill for rejected Traffit-imported stages, from the matching
"Zmiana etapu" activity (matched by candidate_id + exact moved_at). Two passes:

1. `rejection.name` → `candidate_stages.rejection_note` (the bucket, e.g. "Po CV").
2. `content.description` → `candidate_stages.notes` (the recruiter's free-text
   comment, e.g. "niezainteresowany") — so the "Powód odrzucenia" column shows
   "Po CV — niezainteresowany", not a bare bucket.

The candidates list ("Powód odrzucenia" column) renders both (kategoria +
notatka). See ``app.services.traffit.rejection_backfill`` for the why.

Idempotent + additive — only fills rows where the target column is currently
empty, so it is safe to re-run and never overwrites recruiter-entered values.

Usage:
    python -m scripts.backfill_rejection_reasons --dry-run
    python -m scripts.backfill_rejection_reasons --commit
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

from app.core.database import AsyncSessionLocal  # noqa: E402
from app.services.traffit.rejection_backfill import (  # noqa: E402
    backfill_rejection_descriptions_from_activities,
    backfill_rejection_notes_from_activities,
)

logger = logging.getLogger("backfill_rejection_reasons")


async def _run(commit: bool) -> int:
    async with AsyncSessionLocal() as db:
        reasons = await backfill_rejection_notes_from_activities(db)
        descriptions = await backfill_rejection_descriptions_from_activities(db)
        if commit:
            await db.commit()
            logger.info(
                "Committed: %s rejection_note + %s rejection notes (description)",
                reasons,
                descriptions,
            )
        else:
            await db.rollback()
            logger.info(
                "Dry-run: %s rejection_note + %s rejection notes (description) would be set",
                reasons,
                descriptions,
            )
    return reasons + descriptions


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Backfill candidate_stages.rejection_note from Traffit activities."
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
    updated = asyncio.run(_run(commit=bool(args.commit)))
    return updated


if __name__ == "__main__":
    # Exit 0 on success regardless of row count (0 updated is still success).
    main()
    sys.exit(0)
