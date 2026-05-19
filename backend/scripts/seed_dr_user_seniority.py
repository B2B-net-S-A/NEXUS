"""DynaReporter Acceleration Path — one-shot ETL seed.

Czyta seniority data z DynaReporter standalone postgres (Coolify
container `postgres-wpal3b75siiiu8lzw8ccg7ad`) i populuje
`dr_user_seniority` w nexus DB, mapując po `users.dynareporter_legacy_id`
↔ `dr.users.id`.

Użycie (z backend container w prod):
    python /app/scripts/seed_dr_user_seniority.py --apply

Wymaga:
- migrate 0114 zaaplikowana (`alembic upgrade head`)
- `DR_LEGACY_DB_URL` env var (lub `--source-url`) wskazujący na DR postgres
- `DATABASE_URL` env var (nexus postgres)
"""

from __future__ import annotations

import argparse
import logging
import os
import sys

import psycopg2
import psycopg2.extras

logger = logging.getLogger("seed_dr_seniority")


def _connect(url: str) -> psycopg2.extensions.connection:
    return psycopg2.connect(url)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source-url",
        default=os.environ.get("DR_LEGACY_DB_URL"),
        help="DynaReporter standalone DB connection URL",
    )
    parser.add_argument(
        "--target-url",
        default=os.environ.get("DATABASE_URL", "").replace(
            "postgresql+asyncpg://", "postgresql://"
        ),
        help="Nexus DB URL (psycopg2 sync flavor)",
    )
    parser.add_argument(
        "--apply", action="store_true", help="Bez tej flagi: dry-run (zero writes)"
    )
    parser.add_argument(
        "--verbose", action="store_true", help="Wypisuj kazdy wiersz INSERT/UPDATE"
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    if not args.source_url:
        logger.error("Brak --source-url lub DR_LEGACY_DB_URL env var")
        sys.exit(2)
    if not args.target_url:
        logger.error("Brak --target-url lub DATABASE_URL env var")
        sys.exit(2)

    if args.apply:
        logger.info("APPLY mode — wprowadzam zmiany do nexus DB")
    else:
        logger.info("DRY-RUN — zero writes (use --apply żeby zapisać)")

    # Read seniority from DR
    src_conn = _connect(args.source_url)
    src_cur = src_conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    src_cur.execute(
        """
        SELECT id, seniority_level, acceleration_start_date,
               senior_since, expert_since
        FROM users
        WHERE acceleration_start_date IS NOT NULL
        """
    )
    src_rows = src_cur.fetchall()
    logger.info("DR users z acceleration_start_date: %d", len(src_rows))

    # Build map legacy_id → seniority
    legacy_to_seniority = {}
    for r in src_rows:
        # Per-legacy_id pick the most populated record (senior > junior)
        existing = legacy_to_seniority.get(r["id"])
        if existing and existing["seniority_level"] == "senior":
            continue  # don't downgrade
        legacy_to_seniority[r["id"]] = dict(r)
    logger.info("Unique DR legacy_ids: %d", len(legacy_to_seniority))

    src_cur.close()
    src_conn.close()

    # Insert into nexus.dr_user_seniority
    tgt_conn = _connect(args.target_url)
    tgt_cur = tgt_conn.cursor()
    tgt_cur.execute(
        """
        SELECT id, dynareporter_legacy_id FROM users
        WHERE dynareporter_legacy_id IS NOT NULL
        """
    )
    nexus_user_map = {row[1]: row[0] for row in tgt_cur.fetchall()}
    logger.info("Nexus users z dynareporter_legacy_id: %d", len(nexus_user_map))

    matched = 0
    skipped = 0
    for legacy_id, data in legacy_to_seniority.items():
        nexus_user_id = nexus_user_map.get(legacy_id)
        if nexus_user_id is None:
            skipped += 1
            if args.verbose:
                logger.debug("  SKIP legacy_id=%d (brak w nexus.users)", legacy_id)
            continue
        matched += 1
        if args.apply:
            tgt_cur.execute(
                """
                INSERT INTO dr_user_seniority (
                    user_id, seniority_level, acceleration_start_date,
                    senior_since, expert_since, updated_at
                ) VALUES (%s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
                ON CONFLICT (user_id) DO UPDATE SET
                    seniority_level = EXCLUDED.seniority_level,
                    acceleration_start_date = EXCLUDED.acceleration_start_date,
                    senior_since = EXCLUDED.senior_since,
                    expert_since = EXCLUDED.expert_since,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    nexus_user_id,
                    data["seniority_level"] or "junior",
                    data["acceleration_start_date"],
                    data["senior_since"],
                    data["expert_since"],
                ),
            )
        if args.verbose:
            logger.debug(
                "  %s legacy=%d → nexus=%d level=%s start=%s senior_since=%s",
                "INSERT" if args.apply else "DRY",
                legacy_id,
                nexus_user_id,
                data["seniority_level"],
                data["acceleration_start_date"],
                data["senior_since"],
            )

    if args.apply:
        tgt_conn.commit()
        logger.info("Committed: matched=%d skipped=%d", matched, skipped)
    else:
        logger.info("DRY summary: would match=%d skip=%d", matched, skipped)

    tgt_cur.close()
    tgt_conn.close()


if __name__ == "__main__":
    main()
