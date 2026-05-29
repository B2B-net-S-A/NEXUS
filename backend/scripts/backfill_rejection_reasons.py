"""One-off backfill: fill `candidate_stages.rejection_note` for rejected
Traffit-imported stages from the matching "Zmiana etapu" activity's
`rejection.name` (matched by candidate_id + exact moved_at).

The candidates list ("Powód odrzucenia" column) already renders
`rejection_note`; before this backfill every Traffit rejection only showed a
bare "Odrzucony · job (client)" because the reason lived in `activities`, not
on the stage row. See ``app.services.traffit.rejection_backfill`` for the why.

Idempotent + additive — only fills rows where `rejection_note` is currently
empty, so it is safe to re-run and never overwrites a recruiter-entered reason.

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
    backfill_rejection_notes_from_activities,
)

logger = logging.getLogger("backfill_rejection_reasons")


async def _run(commit: bool) -> int:
    async with AsyncSessionLocal() as db:
        updated = await backfill_rejection_notes_from_activities(db)
        if commit:
            await db.commit()
            logger.info("Committed: %s rejected stages got a rejection_note", updated)
        else:
            await db.rollback()
            logger.info("Dry-run: %s rejected stages would get a rejection_note", updated)
    return updated


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
