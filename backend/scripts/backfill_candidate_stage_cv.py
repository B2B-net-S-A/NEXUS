"""Standalone backfill candidate_stage_cvs (alternatywa dla migracji 0070).

Użycie:
  python scripts/backfill_candidate_stage_cv.py --dry-run
  python scripts/backfill_candidate_stage_cv.py --batch-size=500

Po co osobny skrypt obok migracji Alembic? Na produkcji można:
* Uruchomić `--dry-run` i obejrzeć COUNT bez zmian.
* Tunować `--batch-size` jeśli IO wąskie.
* Wznawiać po crashu — INSERT pomija już-istniejące.
* Logować progres co batch — żeby widzieć czy nie utknął.

Migracja 0070 robi to samo automatycznie przy `alembic upgrade head`. Ten
skrypt to bezpieczna ścieżka manualna jeśli chcesz mieć kontrolę.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys

import asyncpg

logger = logging.getLogger("backfill_csv")


COUNT_TOTAL_SQL = "SELECT count(*) FROM candidate_stages"
COUNT_DONE_SQL = (
    "SELECT count(*) FROM candidate_stages cs "
    "JOIN candidate_stage_cvs csv ON csv.candidate_stage_id = cs.id"
)


async def _backfill(dsn: str, batch_size: int, dry_run: bool) -> None:
    conn = await asyncpg.connect(dsn)
    try:
        total = await conn.fetchval(COUNT_TOTAL_SQL)
        done = await conn.fetchval(COUNT_DONE_SQL)
        missing = total - done
        logger.info(
            "candidate_stages total=%d, with_csv=%d, missing=%d",
            total,
            done,
            missing,
        )
        if dry_run:
            logger.info("--dry-run: nic nie zostanie zmienione.")
            return

        inserted_total = 0
        batch_no = 0
        while True:
            batch_no += 1
            inserted = await conn.execute(
                f"""
                INSERT INTO candidate_stage_cvs (
                    candidate_stage_id, candidate_id, job_id,
                    original_cv_filename, original_cv_content, original_cv_language,
                    original_snapshot_at, original_snapshot_source,
                    branded_status, created_at, updated_at
                )
                SELECT cs.id, cs.candidate_id, cs.job_id,
                       c.cv_filename, c.cv_file_content, c.cv_language,
                       CASE WHEN c.cv_file_content IS NOT NULL THEN now() ELSE NULL END,
                       CASE WHEN c.cv_file_content IS NOT NULL THEN 'backfill_0070' ELSE NULL END,
                       'none', now(), now()
                FROM candidate_stages cs
                JOIN candidates c ON cs.candidate_id = c.id
                LEFT JOIN candidate_stage_cvs csv ON csv.candidate_stage_id = cs.id
                WHERE csv.id IS NULL
                ORDER BY cs.id
                LIMIT $1
                """,
                batch_size,
            )
            # asyncpg.execute zwraca string typu "INSERT 0 N" — parsujemy ostatni
            # token jako liczbę.
            try:
                count = int(inserted.split()[-1])
            except (ValueError, IndexError):
                count = 0
            inserted_total += count
            logger.info(
                "[batch %d] inserted=%d total=%d/%d",
                batch_no,
                count,
                inserted_total,
                missing,
            )
            if count < batch_size:
                break

        # Final sanity:
        final_done = await conn.fetchval(COUNT_DONE_SQL)
        logger.info(
            "DONE. inserted_total=%d final candidate_stage_cvs=%d "
            "(should equal candidate_stages=%d)",
            inserted_total,
            final_done,
            total,
        )
    finally:
        await conn.close()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--batch-size",
        type=int,
        default=500,
        help="Liczba wierszy w pojedynczym INSERT (default 500).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Pokaż liczniki bez modyfikacji bazy.",
    )
    return parser.parse_args()


def _resolve_dsn() -> str:
    raw = os.environ.get(
        "DATABASE_URL", "postgresql+asyncpg://nexus:nexus@postgres:5432/nexus"
    )
    return raw.replace("postgresql+asyncpg://", "postgresql://")


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    args = _parse_args()
    dsn = _resolve_dsn()
    asyncio.run(_backfill(dsn, args.batch_size, args.dry_run))


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
