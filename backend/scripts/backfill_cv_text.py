"""Extract ``raw_cv_text`` for candidates whose CV file is in object storage
but whose text was never read.

Closes a retrieval blind spot: 14 509 candidates (prod, 2026-08-10) hold a
`cv_storage_key` pointing at a PDF/DOCX while `raw_cv_text` is empty — so the
richest signal we have about them never reaches the embedding, the field parse
or the search index.

The logic lives in ``app.services.cv_text_backfill`` so an API layer can reuse
it; this file is the CLI. Safe to interrupt: a row that gains text drops out of
the scope, and a file that can never yield text is marked so reruns skip it
instead of re-burning OCR on it.

Run:
    python -m scripts.backfill_cv_text --dry-run --limit 50   # classify only
    python -m scripts.backfill_cv_text --commit --limit 50    # smoke test
    python -m scripts.backfill_cv_text --commit               # full run
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

from app.services.cv_text_backfill import run_backfill  # noqa: E402

logger = logging.getLogger("backfill_cv_text")


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--commit", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--batch-size", type=int, default=8)
    p.add_argument("--log-every", type=int, default=200)
    p.add_argument(
        "--random-sample",
        action="store_true",
        help=(
            "Draw the --limit rows at random instead of by ascending id. Use for "
            "ESTIMATES: id order clusters the oldest imports first, so a small "
            "id-ordered sample badly misrepresents the backlog."
        ),
    )
    p.add_argument(
        "--no-reindex",
        action="store_true",
        help=(
            "Skip enqueueing recovered candidates for re-embedding. Only for a "
            "run whose vectors you intend to rebuild wholesale afterwards — "
            "otherwise the recovered text stays invisible to search."
        ),
    )
    args = p.parse_args()
    if not args.commit and not args.dry_run:
        p.error("must pass --commit or --dry-run")
    if args.commit and args.dry_run:
        p.error("--commit and --dry-run are mutually exclusive")
    return args


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    args = _parse_args()
    stats = asyncio.run(
        run_backfill(
            commit=args.commit,
            limit=args.limit,
            batch_size=args.batch_size,
            log_every=args.log_every,
            enqueue_reindex=not args.no_reindex,
            random_sample=args.random_sample,
        )
    )
    return 0 if stats.scanned == 0 or stats.error < stats.scanned else 1


if __name__ == "__main__":
    sys.exit(main())
