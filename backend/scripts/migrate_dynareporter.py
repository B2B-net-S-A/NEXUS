"""DynaReporter B.0 — ETL: dump.sql → nexus postgres.

Faza B.0 z planu (.claude/plans/zaplanuj-migracje-pelna-nie-parallel-acorn.md).

Dwa stadia:

1. **Users** (`--users-only` lub `--all`):
   - Parsuje COPY block `public.users` z dumpa
   - Dla każdego DynaReporter usera (74 sztuk):
     - Email-match z nexus ``users``
     - Match → UPDATE allowed_sections + dynareporter_legacy_id
     - No match → INSERT nowy nexus user (rola mapowana, password_hash
       transfer z DynaReportera)
   - Budowa remap dict: ``legacy_user_id -> nexus_user_id``

2. **Data** (`--data-only` lub `--all`):
   - Wymaga: kolumna ``dynareporter_legacy_id`` w nexus ``users``
     wypełniona przez krok 1 (lub manualnie)
   - Parsuje 57 COPY blocks (dr_* tabel) z dumpa
   - Dla każdej tabeli: remapuje ``user_id`` i pokrewne kolumny
   - INSERT do `dr_*` z odpowiednio przemapowanymi user references
   - Fix sequences: ``SELECT setval('public.dr_X_id_seq', max(id))``

Użycie:
    # Dry-run (default — zero writes, tylko raport)
    python scripts/migrate_dynareporter.py --source-dump /tmp/render-dump.sql

    # Apply (PRODUCTION)
    python scripts/migrate_dynareporter.py \\
        --source-dump /tmp/render-dump.sql \\
        --apply \\
        --target-db "postgresql://nexus:...@postgres:5432/nexus"

    # Tylko users (etap 1)
    python scripts/migrate_dynareporter.py --source-dump dump.sql --users-only --apply

    # Tylko data (etap 2 — po sukcesie etap 1)
    python scripts/migrate_dynareporter.py --source-dump dump.sql --data-only --apply

Idempotency:
    - Users: WHERE dynareporter_legacy_id IS NULL — bezpieczne re-run.
    - Data: ``--reset`` (NIE default) TRUNCATEs dr_* przed re-loadem;
      bez tego INSERT ON CONFLICT DO NOTHING.
"""

from __future__ import annotations

import argparse
import logging
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Optional

import psycopg2
from psycopg2.extras import execute_values

logger = logging.getLogger("dr_etl")


# DynaReporter → nexus role mapping.
ROLE_MAP: dict[str, str] = {
    "admin": "admin",
    "delivery_lead": "delivery_lead",
    "delivery_lead_manager": "delivery_lead",
    "recruiter": "recruiter",
    "sourcer": "sourcer",
    "sales": "tac",
    "sales_manager": "tac",
    "sales_director": "tac",
    "board": "user",
    "rozliczenia": "user",
    "recruitment_team": "user",
    "recruitment_team_viewer": "user",
    "viewer": "user",
}

DEFAULT_SECTIONS_BY_ROLE: dict[str, list[str]] = {
    "admin": [
        "body-leasing",
        "sales",
        "delivery-lead",
        "placements",
        "clients-mrr",
        "competitions",
        "przetargi",
        "board",
        "sales-mgmt",
        "mindy",
        "admin",
    ],
    "delivery_lead": ["delivery-lead", "placements", "clients-mrr", "competitions"],
    "recruiter": ["body-leasing", "competitions"],
    "sourcer": ["body-leasing", "competitions"],
    "sales": ["sales", "sales-mgmt", "clients-mrr"],
    "sales_manager": ["sales", "sales-mgmt", "clients-mrr", "board"],
    "sales_director": ["sales", "sales-mgmt", "clients-mrr", "board"],
    "board": ["board", "clients-mrr"],
    "rozliczenia": ["clients-mrr", "przetargi"],
    "recruitment_team": ["body-leasing", "delivery-lead"],
    "recruitment_team_viewer": ["body-leasing"],
    "viewer": [],
}


@dataclass(frozen=True)
class CopyBlock:
    table: str
    columns: list[str]
    rows: list[list[Optional[str]]]


def parse_dump_copy_blocks(
    dump_path: Path, only_tables: Optional[set[str]] = None
) -> Iterator[CopyBlock]:
    copy_re = re.compile(r"^COPY public\.(\w+) \(([^)]+)\) FROM stdin;$")
    with dump_path.open("r", encoding="utf-8") as f:
        line = f.readline()
        while line:
            m = copy_re.match(line.rstrip("\n"))
            if m:
                table, cols_raw = m.group(1), m.group(2)
                # Strip pg_dump's quoting on reserved-word columns (e.g. "position")
                # so downstream SQL builders re-quote with their own logic.
                columns = [c.strip().strip('"') for c in cols_raw.split(",")]
                if only_tables and table not in only_tables:
                    while True:
                        line = f.readline()
                        if not line or line.rstrip("\n") == "\\.":
                            break
                    line = f.readline()
                    continue
                rows: list[list[Optional[str]]] = []
                while True:
                    row_line = f.readline()
                    if not row_line:
                        break
                    stripped = row_line.rstrip("\n")
                    if stripped == "\\.":
                        break
                    fields = [
                        None if v == "\\N" else _unescape_pg_copy(v)
                        for v in stripped.split("\t")
                    ]
                    rows.append(fields)
                yield CopyBlock(table=table, columns=columns, rows=rows)
            line = f.readline()


def _unescape_pg_copy(s: str) -> str:
    """Unescape PostgreSQL COPY text format."""
    return (
        s.replace("\\\\", "\x00")
        .replace("\\t", "\t")
        .replace("\\n", "\n")
        .replace("\\r", "\r")
        .replace("\x00", "\\")
    )


def migrate_users(conn, dump_path: Path, dry_run: bool) -> dict[int, int]:
    """Etap 1: email-match + INSERT/UPDATE nexus.users z dump DynaReportera."""
    logger.info("Stage 1: USERS — email-match + transfer")

    blocks = list(parse_dump_copy_blocks(dump_path, only_tables={"users"}))
    if not blocks:
        logger.error("No `public.users` COPY block found in dump — aborting")
        sys.exit(1)
    users_block = blocks[0]
    logger.info(
        "  Found %d users in dump (columns: %s)",
        len(users_block.rows),
        users_block.columns,
    )

    remap: dict[int, int] = {}
    matched = new = conflict = 0

    col_idx = {c: i for i, c in enumerate(users_block.columns)}
    needed = {"id", "email", "password_hash", "first_name", "last_name", "role"}
    missing = needed - set(col_idx.keys())
    if missing:
        logger.error("Dump users columns missing: %s", missing)
        sys.exit(1)

    cur = conn.cursor()
    for row in users_block.rows:
        legacy_id = int(row[col_idx["id"]])
        email = (row[col_idx["email"]] or "").strip().lower()
        legacy_role = row[col_idx["role"]] or "user"
        nexus_role = ROLE_MAP.get(legacy_role, "user")
        first_name = row[col_idx["first_name"]] or ""
        last_name = row[col_idx["last_name"]] or ""
        full_name = f"{first_name} {last_name}".strip() or email
        password_hash = row[col_idx["password_hash"]]
        sections = DEFAULT_SECTIONS_BY_ROLE.get(legacy_role, [])

        if not email:
            logger.warning("Legacy user id=%d has empty email — skipping", legacy_id)
            conflict += 1
            continue

        cur.execute("SELECT id FROM users WHERE lower(email) = %s", (email,))
        existing = cur.fetchone()

        if existing:
            nexus_id = existing[0]
            remap[legacy_id] = nexus_id
            matched += 1
            if dry_run:
                logger.info(
                    "  [DRY] MATCH legacy.id=%d → nexus.id=%d (email=%s)",
                    legacy_id,
                    nexus_id,
                    email,
                )
            else:
                cur.execute(
                    """
                    UPDATE users
                       SET dynareporter_legacy_id = %s,
                           allowed_sections = (
                               SELECT COALESCE(jsonb_agg(DISTINCT s), '[]'::jsonb)
                                 FROM jsonb_array_elements_text(
                                          allowed_sections || %s::jsonb
                                      ) AS s
                           )
                     WHERE id = %s
                       AND dynareporter_legacy_id IS NULL
                    """,
                    (legacy_id, str(sections).replace("'", '"'), nexus_id),
                )
        else:
            new += 1
            if dry_run:
                logger.info(
                    "  [DRY] NEW legacy.id=%d → nexus.INSERT (email=%s, role=%s)",
                    legacy_id,
                    email,
                    nexus_role,
                )
            else:
                cur.execute(
                    """
                    INSERT INTO users (
                        email, name, role, password_hash,
                        profile_completed, is_active,
                        dynareporter_legacy_id, allowed_sections,
                        aad_group_ids, roles
                    )
                    VALUES (%s, %s, %s, %s, true, true, %s, %s::jsonb,
                            '[]'::jsonb, %s::jsonb)
                    RETURNING id
                    """,
                    (
                        email,
                        full_name,
                        nexus_role,
                        password_hash,
                        legacy_id,
                        str(sections).replace("'", '"'),
                        f'["{nexus_role}"]',
                    ),
                )
                nexus_id = cur.fetchone()[0]
                remap[legacy_id] = nexus_id

    if not dry_run:
        conn.commit()

    logger.info(
        "Stage 1 done: matched=%d, new=%d, conflicts=%d, total=%d",
        matched,
        new,
        conflict,
        matched + new + conflict,
    )
    return remap


def migrate_data(
    conn, dump_path: Path, remap: dict[int, int], dry_run: bool, reset: bool
) -> dict[str, int]:
    """Etap 2: kopia 57 dr_* tabel z remappingiem user_id przez ``remap``."""
    logger.info("Stage 2: DATA — kopia 57 tabel z remappingiem user_id")

    dr_tables = {
        "about_calendar",
        "about_career_paths",
        "about_clients_partners",
        "about_contacts",
        "about_faq",
        "about_feedback",
        "about_glossary",
        "about_links",
        "about_org_chart",
        "about_positions",
        "about_procedures",
        "about_templates",
        "about_training",
        "about_values",
        "alerts",
        "api_key_audit_log",
        "api_keys",
        "applied_migrations",
        "board_monthly_report",
        "board_placement_clients",
        "client_mrr",
        "clients",
        "competence_categories",
        "competition_notifications",
        "competition_winners",
        "consultant_group_assignments",
        "consultant_rate_history",
        "consultants",
        "data_audit_log",
        "delivery_lead_client_assignments",
        "finances",
        "group_monthly_costs",
        "kpi_body_leasing",
        "kpi_delivery_lead",
        "kpi_sales",
        "monthly_mrr_data",
        "mrr_import_history",
        "placement_details",
        "project_cost_groups",
        "project_monthly_costs",
        "project_other_cost_items",
        "przetargi_allocations",
        "przetargi_consultants",
        "przetargi_mrr",
        "przetargi_mrr_backup",
        "przetargi_project_costs",
        "przetargi_projects",
        "sales_leads",
        "sales_offers",
        "sales_people",
        "sales_projects",
        "sourcer_category_assignments",
        "system_config",
        "tac_delivery_lead_assignments",
        "tac_linkedin_farming",
        "upload_history",
        "weekly_sales_activity",
    }

    USER_FK_COLUMN_NAMES = {
        "user_id",
        "uploaded_by",
        "created_by",
        "updated_by",
        "approved_by",
        "proposed_by",
        "resolved_by",
        "tac_user_id",
        "delivery_lead_user_id",
        "bdm_id",
    }

    cur = conn.cursor()
    # Defer FK constraints — dr_* tables are inserted alphabetically,
    # not in parent-first order (e.g. dr_api_key_audit_log before dr_api_keys).
    cur.execute("SET session_replication_role = replica;")

    if reset:
        for tbl in dr_tables:
            cmd = f"TRUNCATE TABLE public.dr_{tbl} CASCADE"
            if dry_run:
                logger.info("  [DRY] %s", cmd)
            else:
                cur.execute(cmd)
        if not dry_run:
            conn.commit()

    counts: dict[str, int] = {}
    for block in parse_dump_copy_blocks(dump_path, only_tables=dr_tables):
        target_table = f"dr_{block.table}"
        col_idx_map = {c: i for i, c in enumerate(block.columns)}
        fk_cols = [c for c in block.columns if c in USER_FK_COLUMN_NAMES]

        remapped_rows = []
        skipped = 0
        for row in block.rows:
            new_row = list(row)
            valid = True
            for fk_col in fk_cols:
                idx = col_idx_map[fk_col]
                val = row[idx]
                if val is None:
                    continue
                legacy_uid = int(val)
                if legacy_uid in remap:
                    new_row[idx] = str(remap[legacy_uid])
                else:
                    logger.warning(
                        "  %s.row legacy %s=%d nie znaleziono w remap; pomijam wiersz",
                        target_table,
                        fk_col,
                        legacy_uid,
                    )
                    valid = False
                    break
            if valid:
                remapped_rows.append(tuple(new_row))
            else:
                skipped += 1

        counts[target_table] = len(remapped_rows)

        if dry_run:
            logger.info(
                "  [DRY] %s: %d rows ready (skipped %d w/ unmapped FK)",
                target_table,
                len(remapped_rows),
                skipped,
            )
        else:
            if remapped_rows:
                cols_sql = ", ".join(f'"{c}"' for c in block.columns)
                placeholder = "(" + ", ".join(["%s"] * len(block.columns)) + ")"
                sql = (
                    f"INSERT INTO public.{target_table} ({cols_sql}) "
                    f"VALUES %s "
                    f"ON CONFLICT DO NOTHING"
                )
                execute_values(cur, sql, remapped_rows, template=placeholder)
            logger.info(
                "  %s: inserted %d rows (skipped %d)",
                target_table,
                len(remapped_rows),
                skipped,
            )

    if not dry_run:
        # Commit all INSERTs BEFORE setval loop — otherwise a single sequence
        # failure (e.g. table without an id column) rolls back the entire
        # transaction including every row we just inserted.
        conn.commit()
        for tbl in dr_tables:
            try:
                cur.execute(
                    f"SELECT setval('public.dr_{tbl}_id_seq', "
                    f"COALESCE((SELECT MAX(id) FROM public.dr_{tbl}), 1), true)"
                )
                conn.commit()
            except psycopg2.Error:
                conn.rollback()
                cur = conn.cursor()
                continue

        # Restore FK enforcement after bulk loads
        try:
            cur.execute("SET session_replication_role = origin;")
            conn.commit()
        except psycopg2.Error:
            conn.rollback()

    return counts


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--source-dump",
        type=Path,
        required=True,
        help="Path do render-dump.sql (bez --clean preferowany)",
    )
    parser.add_argument(
        "--target-db",
        type=str,
        default=os.environ.get("DATABASE_URL"),
        help="Nexus DB URL (default: $DATABASE_URL)",
    )
    parser.add_argument(
        "--users-only", action="store_true", help="Tylko etap 1 (users email-match)"
    )
    parser.add_argument(
        "--data-only", action="store_true", help="Tylko etap 2 (data load)"
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="TRUNCATE dr_* CASCADE przed loadem (dla data stage)",
    )
    parser.add_argument(
        "--apply", action="store_true", help="Apply changes (default: dry-run)"
    )
    parser.add_argument("--verbose", "-v", action="count", default=0)
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    if not args.target_db:
        logger.error("--target-db (or DATABASE_URL env) required")
        sys.exit(1)
    if not args.source_dump.exists():
        logger.error("--source-dump not found: %s", args.source_dump)
        sys.exit(1)

    dry_run = not args.apply
    mode = "DRY-RUN" if dry_run else "APPLY"
    logger.info("DynaReporter ETL — %s mode", mode)
    logger.info(
        "  Source dump: %s (%d bytes)",
        args.source_dump,
        args.source_dump.stat().st_size,
    )

    conn = psycopg2.connect(args.target_db)
    try:
        remap: dict[int, int] = {}

        if not args.data_only:
            remap = migrate_users(conn, args.source_dump, dry_run=dry_run)

        if not args.users_only:
            if not remap:
                cur = conn.cursor()
                cur.execute(
                    "SELECT dynareporter_legacy_id, id FROM users "
                    "WHERE dynareporter_legacy_id IS NOT NULL"
                )
                remap = {legacy: nexus for legacy, nexus in cur.fetchall()}
                logger.info("Loaded remap from DB: %d users", len(remap))

            if remap:
                migrate_data(
                    conn, args.source_dump, remap, dry_run=dry_run, reset=args.reset
                )
            else:
                logger.warning(
                    "Empty remap dict — stage 2 will fail. Run --users-only first."
                )

    finally:
        conn.close()


if __name__ == "__main__":
    main()
