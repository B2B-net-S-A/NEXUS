"""Bulk backfill: classify candidates into the 5 competence categories.

The CC subsystem (models, classifier, filter, badges) shipped, but historical
profiles were only classified when a CV was (re)uploaded — so most of the
~49k candidates have ``competence_category_id = NULL`` and appear in no CC
filter. This script runs the existing hybrid classifier
(``services.cc_classifier.classify_candidate_to_cc``) over every candidate and
writes 1 primary + up to 2 secondary categories via the shared writer
(``services.candidate_cc_assignment.apply_candidate_cc_scores``), keeping the
legacy slug + FK in sync. Manually-curated profiles are never touched.

Idempotent and resumable (commits per assigned candidate). ``--only-missing``
(default) targets just ``competence_category_id IS NULL``; ``--all`` re-runs
the classifier over everyone.

Run (inside the backend container — for prod use the admin endpoint instead:
``POST /api/admin/candidates/backfill-cc``):
    python -m scripts.backfill_candidate_cc --dry-run
    python -m scripts.backfill_candidate_cc --dry-run --limit 500
    python -m scripts.backfill_candidate_cc --commit
    python -m scripts.backfill_candidate_cc --commit --all
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

from app.core.database import AsyncSessionLocal  # noqa: E402
from app.services.candidate_cc_assignment import backfill_candidate_ccs  # noqa: E402


async def run(commit: bool, only_missing: bool, limit: Optional[int]) -> None:
    async with AsyncSessionLocal() as db:
        stats = await backfill_candidate_ccs(
            db,
            limit=limit,
            only_missing=only_missing,
            dry_run=not commit,
        )

    prefix = "Assigned" if commit else "[DRY-RUN] Would assign"
    logging.info(
        "%s %d/%d candidates (skipped=%d errors=%d)",
        prefix,
        stats["assigned"],
        stats["total"],
        stats["skipped"],
        stats["errors"],
    )
    for slug, count in sorted(
        stats["by_primary"].items(), key=lambda kv: kv[1], reverse=True
    ):
        logging.info("  %-28s %d", slug, count)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="classify, no writes")
    mode.add_argument("--commit", action="store_true", help="write assignments")
    scope = parser.add_mutually_exclusive_group()
    scope.add_argument(
        "--only-missing",
        dest="only_missing",
        action="store_true",
        default=True,
        help="classify only candidates with no primary CC (default)",
    )
    scope.add_argument(
        "--all",
        dest="only_missing",
        action="store_false",
        help="re-classify every candidate (skips manual assignments)",
    )
    parser.add_argument(
        "--limit", type=int, default=None, help="max candidates to process"
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    asyncio.run(
        run(commit=args.commit, only_missing=args.only_missing, limit=args.limit)
    )


if __name__ == "__main__":
    main()
