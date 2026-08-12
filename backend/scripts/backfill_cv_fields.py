"""Masowe uzupełnianie pól kandydata z CV — CLI (Fala 3).

    # pomiar scope'u: zero LLM, zero zapisów
    python -m scripts.backfill_cv_fields --dry-run

    # kalibracja: 200 CV, surowe wyniki+usage do JSONL (ocena jakości Haiku)
    python -m scripts.backfill_cv_fields --commit --limit 200 \
        --calibration-log /tmp/cv-calibration.jsonl

    # pełny bieg / wznowienie
    python -m scripts.backfill_cv_fields --commit
    python -m scripts.backfill_cv_fields --commit --after-id 20000

    # shard równoległy: rozłączny zakres id (górna granica WŁĄCZNIE)
    python -m scripts.backfill_cv_fields --commit --after-id 20000 --until-id 40000

Prod używa endpointów admin (POST /api/admin/candidates/backfill-cv-fields);
ten plik to ta sama logika dla środowisk z dostępem do CLI.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.database import AsyncSessionLocal  # noqa: E402
from app.services.cv_field_backfill import backfill_cv_fields, count_scope  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("backfill_cv_fields")


async def _main(args: argparse.Namespace) -> None:
    async with AsyncSessionLocal() as db:
        if not args.commit:
            scope = await count_scope(db, after_id=args.after_id)
            logger.info("=== POMIAR SCOPE (nic nie zapisano, zero LLM) ===")
            for key, value in scope.items():
                logger.info("%-16s: %s", key, f"{value:,}")
            return

        stats = await backfill_cv_fields(
            db,
            limit=args.limit,
            after_id=args.after_id,
            until_id=args.until_id,
            calibration_log_path=args.calibration_log,
        )
        logger.info("=== KONIEC BIEGU ===")
        logger.info("%s", json.dumps(stats, ensure_ascii=False, indent=1))
        logger.info("wznowienie: --after-id %s", stats.get("last_id"))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--dry-run", action="store_true", help="Domyślne: pomiar scope'u."
    )
    mode.add_argument(
        "--commit", action="store_true", help="Bieg płatny (LLM + zapisy)."
    )
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--after-id", type=int, default=0)
    parser.add_argument("--until-id", type=int, default=None)
    parser.add_argument("--calibration-log", type=str, default=None)
    asyncio.run(_main(parser.parse_args()))


if __name__ == "__main__":
    main()
