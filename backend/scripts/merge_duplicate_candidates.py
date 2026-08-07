"""One-off cleanup: merge duplicate `candidates` rows.

Background
----------
The TalentRadar import (``app.services.talent_radar_importer``) upserts on
``(external_source='talent_radar', external_id)``. The main Traffit import wrote
the *same* people under ``(external_source='traffit', external_id)`` — same
``external_id`` (= Traffit id). Because the unique key is per-source,
``('traffit', 123)`` and ``('talent_radar', 123)`` coexist as two rows. The
TalentRadar rows are almost all email-less, so neither the global
``UNIQUE(email)`` nor ``dedup_service`` caught them → ~1 884 duplicates.

What this script does
---------------------
Merges a duplicate row into a canonical row, then deletes the duplicate:

1. **Port CV fields** dup → canonical, but ONLY where the canonical is empty
   (never overwrites canonical data — purely additive enrichment).
2. **Re-point child rows** (every table with a ``candidate_id`` /
   ``parsed_candidate_id`` FK, discovered from ``information_schema``) from the
   duplicate to the canonical. On a unique-constraint clash (SQLSTATE 23505,
   and only that) the duplicate's redundant child row is dropped instead; any
   other DB error aborts the run loudly rather than silently deleting rows.
   Append-only tables (``_APPEND_ONLY_TRIGGERS``) are re-pointed with their
   immutability trigger disabled for the UPDATE — they carry no FK to
   ``candidates``, so skipping them would leave orphaned PII behind.
3. **DELETE** the now-childless duplicate row.

Tiers (``--tier``)
------------------
* ``1`` — deterministic: ``talent_radar`` rows sharing ``external_id`` with a
  ``traffit`` row. Canonical = the ``traffit`` row. Hard proof of same person.
* ``2`` — corroborated namesake: same ``name+lastname`` AND a hard corroborator
  (same ``linkedin_slug`` or same lower(email)). Conservative auto-merge.
* ``3`` — REPORT ONLY (no deletes): every remaining ``name+lastname`` duplicate
  group, classified, written to a CSV for manual review. Groups whose rows have
  ≥2 distinct emails are flagged as *different people* and left intact.

Safety
------
* Default is dry-run (rolls back, prints what *would* happen). ``--commit``
  persists. ``--dry-run`` / ``--commit`` are mutually exclusive.
* The whole run is a single transaction.

Usage
-----
    python -m scripts.merge_duplicate_candidates --tier 1 --dry-run
    python -m scripts.merge_duplicate_candidates --tier 1 --commit
    python -m scripts.merge_duplicate_candidates --tier 3            # writes review CSV
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import logging
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy import text  # noqa: E402
from sqlalchemy.exc import DBAPIError  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

from app.core.database import AsyncSessionLocal  # noqa: E402

logger = logging.getLogger("merge_duplicate_candidates")

# Identifier guard for table/column names sourced from information_schema —
# defensive, even though the catalog is trusted (no user input reaches here).
_IDENT_RE = re.compile(r"^[a-z_][a-z0-9_]*$")

OUT_DIR = BACKEND_ROOT / "scripts" / "out"

# SQLSTATE 23505 — jedyny błąd, przy którym wolno zejść na kasowanie
# nadmiarowego wiersza-dziecka. Każdy inny (check, FK, trigger) znaczy, że
# repointu NIE da się wykonać, a DELETE zniszczyłby dane zamiast je przenieść.
_UNIQUE_VIOLATION = "23505"

# Tabele z triggerem append-only, który blokuje UPDATE *i* DELETE. Repoint
# wymaga zdjęcia triggera na czas UPDATE-u — pominięcie tabeli nie wchodzi
# w grę, bo `candidate_contact_events` nie ma FK do `candidates`, więc jej
# wiersze przeżyłyby DELETE duplikatu jako osierocone PII wskazujące na
# nieistniejącą osobę. Trigger: migracja 0201.
_APPEND_ONLY_TRIGGERS: dict[str, str] = {
    "candidate_contact_events": "trg_candidate_contact_events_immutable",
}


def _repoint_sql(table: str, col: str) -> str:
    return (
        f"UPDATE {table} t SET {col} = mp.canonical_id "
        f"FROM merge_pairs mp WHERE t.{col} = mp.dup_id"
    )


def _drop_child_sql(table: str, col: str) -> str:
    return f"DELETE FROM {table} t USING merge_pairs mp WHERE t.{col} = mp.dup_id"


def _is_unique_violation(exc: DBAPIError) -> bool:
    """Czy to naprawdę kolizja UNIQUE (asyncpg: `sqlstate`, psycopg: `pgcode`)?

    Trigger append-only podnosi 55000, które asyncpg mapuje na goły
    ``DBAPIError`` — poprzedni ``except IntegrityError`` w ogóle go nie łapał,
    więc wyjątek wysadzał całą (jedną) transakcję runu.
    """

    orig = getattr(exc, "orig", None)
    code = getattr(orig, "sqlstate", None) or getattr(orig, "pgcode", None)
    return code == _UNIQUE_VIOLATION


async def _repoint_append_only(
    db: AsyncSession, table: str, col: str, trigger: str
) -> int:
    """Repoint w tabeli append-only — trigger zdjęty tylko na czas UPDATE-u.

    ``DISABLE TRIGGER`` jest w PostgreSQL transakcyjny (dry-run go wycofuje
    razem z resztą), ale bierze ACCESS EXCLUSIVE na tabeli do końca
    transakcji — akceptowalne dla jednorazowego skryptu konserwacyjnego.
    """

    async with db.begin_nested():
        await db.execute(text(f"ALTER TABLE {table} DISABLE TRIGGER {trigger}"))
        res = await db.execute(text(_repoint_sql(table, col)))
        await db.execute(text(f"ALTER TABLE {table} ENABLE TRIGGER {trigger}"))
    return res.rowcount or 0


# ── CV fields ported dup → canonical (only when canonical is empty) ──────────
# Pairs of (column, "is-empty" SQL predicate template using alias `{a}`).
# Location is intentionally absent. ``city``/``country`` are canonical and the
# legacy ``location`` column must never be copied as an independently authored
# value by this maintenance path.
_TEXT_COLS = ("raw_cv_text", "cv_filename")
# ``languages`` is intentionally absent: candidate_languages is canonical and
# is repointed as a child table by the generic FK pass below. Writing the
# legacy JSONB projection here would create a second language writer.
_JSON_COLS = ("cv_extracted_data", "skills")
_NULLABLE_COLS = ("cv_storage_key", "cv_file_content", "years_it_experience")


def _empty_text(alias: str, col: str) -> str:
    return f"({alias}.{col} IS NULL OR btrim({alias}.{col}::text) = '')"


def _empty_json(alias: str, col: str) -> str:
    return f"({alias}.{col} IS NULL OR {alias}.{col}::text IN ('{{}}', '[]', 'null'))"


def _empty_nullable(alias: str, col: str) -> str:
    return f"({alias}.{col} IS NULL)"


def _build_cv_port_sql() -> str:
    """UPDATE that copies CV fields from the duplicate into the canonical row,
    but only for columns where the canonical is empty and the duplicate has a
    value. The WHERE clause limits writes to genuinely-enriching rows so the
    reported rowcount = number of canonical rows actually enriched."""
    set_parts: list[str] = []
    enrich_parts: list[str] = []

    for col in _TEXT_COLS:
        set_parts.append(
            f"{col} = CASE WHEN {_empty_text('c', col)} THEN d.{col} ELSE c.{col} END"
        )
        enrich_parts.append(
            f"({_empty_text('c', col)} AND NOT {_empty_text('d', col)})"
        )
    for col in _JSON_COLS:
        set_parts.append(
            f"{col} = CASE WHEN {_empty_json('c', col)} THEN d.{col} ELSE c.{col} END"
        )
        enrich_parts.append(
            f"({_empty_json('c', col)} AND NOT {_empty_json('d', col)})"
        )
    for col in _NULLABLE_COLS:
        set_parts.append(f"{col} = COALESCE(c.{col}, d.{col})")
        enrich_parts.append(f"(c.{col} IS NULL AND d.{col} IS NOT NULL)")

    effective_location: dict[str, str] = {}
    for col in ("city", "country"):
        unlocked = (
            "COALESCE(c.cv_extracted_data->>'_manual_override_"
            f"{col}', 'false') <> 'true'"
        )
        should_copy = (
            f"({_empty_text('c', col)} AND NOT {_empty_text('d', col)} AND {unlocked})"
        )
        effective = f"CASE WHEN {should_copy} THEN d.{col} ELSE c.{col} END"
        effective_location[col] = effective
        set_parts.append(f"{col} = {effective}")
        enrich_parts.append(should_copy)

    # ``location`` is a compatibility projection, never an independent merge
    # input. Repeat the effective expressions because PostgreSQL SET clauses
    # all read the pre-update row.
    set_parts.append(
        "location = NULLIF(CONCAT_WS(', ', "
        f"NULLIF(btrim({effective_location['city']}), ''), "
        f"NULLIF(btrim({effective_location['country']}), '')"
        "), '')"
    )

    set_clause = ",\n            ".join(set_parts) + ",\n            updated_at = NOW()"
    enrich_clause = "\n              OR ".join(enrich_parts)
    return f"""
        UPDATE candidates c
        SET {set_clause}
        FROM merge_pairs mp
        JOIN candidates d ON d.id = mp.dup_id
        WHERE c.id = mp.canonical_id
          AND (
              {enrich_clause}
          )
    """


_CV_PORT_SQL = text(_build_cv_port_sql())


@dataclass
class MergeStats:
    pairs: int = 0
    cv_enriched: int = 0
    repointed: dict[str, int] = field(default_factory=dict)
    repoint_conflicts: dict[str, int] = field(default_factory=dict)
    deleted: int = 0

    def log(self, prefix: str) -> None:
        logger.info("%s pairs=%d cv_enriched=%d deleted=%d", prefix, self.pairs,
                    self.cv_enriched, self.deleted)
        for tbl, n in sorted(self.repointed.items()):
            if n:
                logger.info("%s   re-pointed %s: %d rows", prefix, tbl, n)
        for tbl, n in sorted(self.repoint_conflicts.items()):
            if n:
                logger.info("%s   dropped redundant %s (unique clash): %d rows",
                            prefix, tbl, n)


async def _fk_tables(db: AsyncSession) -> list[tuple[str, str]]:
    """All (table, column) pairs referencing a candidate, from the live catalog."""
    rows = (
        await db.execute(
            text(
                """
                SELECT table_name, column_name
                FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND column_name IN ('candidate_id', 'parsed_candidate_id')
                  AND table_name <> 'candidates'
                ORDER BY table_name, column_name
                """
            )
        )
    ).all()
    out: list[tuple[str, str]] = []
    for table_name, column_name in rows:
        if _IDENT_RE.match(table_name) and _IDENT_RE.match(column_name):
            out.append((table_name, column_name))
        else:  # pragma: no cover - catalog never yields bad identifiers
            logger.warning("Skipping suspicious identifier: %s.%s", table_name, column_name)
    return out


async def merge_pairs(db: AsyncSession, pairs: list[tuple[int, int]]) -> MergeStats:
    """Merge each (canonical_id, dup_id) pair. Set-based for speed.

    Builds a ``merge_pairs`` temp table, ports CV fields, re-points every child
    FK, then deletes the duplicates. Runs inside the caller's transaction.
    """
    stats = MergeStats(pairs=len(pairs))
    if not pairs:
        return stats

    await db.execute(
        text(
            "CREATE TEMP TABLE merge_pairs ("
            "dup_id integer PRIMARY KEY, canonical_id integer NOT NULL) "
            "ON COMMIT DROP"
        )
    )
    canon_ids = [c for c, _ in pairs]
    dup_ids = [d for _, d in pairs]
    await db.execute(
        text(
            "INSERT INTO merge_pairs (dup_id, canonical_id) "
            "SELECT * FROM unnest(CAST(:dups AS int[]), CAST(:canons AS int[]))"
        ),
        {"dups": dup_ids, "canons": canon_ids},
    )

    # 1) Port CV fields (additive — only where canonical is empty).
    stats.cv_enriched = (await db.execute(_CV_PORT_SQL)).rowcount or 0

    # 2) Re-point every child FK dup → canonical. On a unique clash, drop the
    #    duplicate's redundant child rows for that table instead.
    for table, col in await _fk_tables(db):
        trigger = _APPEND_ONLY_TRIGGERS.get(table)
        if trigger is not None:
            # Bez fallbacku na DELETE: trigger jest BEFORE UPDATE *OR DELETE*,
            # więc kasowanie padłoby tak samo, a historia append-only ma
            # przeżyć merge pod kandydatem, który został.
            stats.repointed[table] = await _repoint_append_only(db, table, col, trigger)
            continue
        try:
            async with db.begin_nested():
                res = await db.execute(text(_repoint_sql(table, col)))
            stats.repointed[table] = (res.rowcount or 0)
        except DBAPIError as exc:
            if not _is_unique_violation(exc):
                raise RuntimeError(
                    f"re-point {table}.{col} failed with a non-unique DB error "
                    f"— refusing the DELETE fallback, which would destroy rows "
                    f"instead of moving them: {exc.orig!r}"
                ) from exc
            async with db.begin_nested():
                res = await db.execute(text(_drop_child_sql(table, col)))
            stats.repoint_conflicts[table] = (res.rowcount or 0)

    # 3) Delete the duplicates (remaining CASCADE / SET NULL children handled by DB).
    #
    # Capture the ids BEFORE the DELETE — afterwards `merge_pairs` still holds
    # them, but nothing else can tell us which vectors to drop.
    dup_ids = [
        row
        for (row,) in (await db.execute(text("SELECT dup_id FROM merge_pairs"))).all()
    ]

    stats.deleted = (
        await db.execute(
            text(
                "DELETE FROM candidates c USING merge_pairs mp "
                "WHERE c.id = mp.dup_id"
            )
        )
    ).rowcount or 0

    # 4) Drop the duplicates' vectors. The DB has ON DELETE CASCADE for every
    # child table and this script goes further still — re-pointing append-only
    # rows with their immutability trigger disabled, specifically so no orphaned
    # PII is left behind. Qdrant has no foreign keys, so it was the one store
    # the sweep missed: a candidate vector is built from text containing the
    # person's name and up to ~3 000 characters of their CV, and the payload
    # carries `name` outright. The previous run left 1 932 such points behind
    # (measured 2026-08-07); clean them with
    # `reembed_collections --prune-orphans`.
    #
    # Best-effort by design: Qdrant being unreachable must not roll back a
    # completed, consistent merge. The prune tool is the backstop.
    if dup_ids:
        try:
            # One batched delete, not one call per duplicate: a tier-1 run merges
            # ~1 884 rows, and `delete_candidate_embedding` would mean that many
            # sequential Qdrant round-trips (minutes of wall clock inside the
            # merge transaction's tail, for work that Qdrant does in one request).
            from scripts.reembed_collections import _delete_qdrant_points
            from app.services.embedding_service import _collection

            await _delete_qdrant_points(_collection(), [int(i) for i in dup_ids])
            logger.info("Dropped %s duplicate vectors", len(dup_ids))
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Vector cleanup failed (%s) — merge itself is committed. Run "
                "`python -m scripts.reembed_collections --target candidates "
                "--prune-orphans --dry-run` to see what is left.",
                exc,
            )

    return stats


# ── Tier pair collectors ─────────────────────────────────────────────────────


async def collect_tier1_pairs(db: AsyncSession) -> list[tuple[int, int]]:
    """talent_radar rows sharing external_id with a traffit row → (traffit, talent_radar)."""
    rows = (
        await db.execute(
            text(
                """
                SELECT tf.id AS canonical_id, tr.id AS dup_id
                FROM candidates tr
                JOIN candidates tf
                  ON tf.external_source = 'traffit'
                 AND tf.external_id = tr.external_id
                WHERE tr.external_source = 'talent_radar'
                  AND tr.external_id IS NOT NULL
                """
            )
        )
    ).all()
    return [(r.canonical_id, r.dup_id) for r in rows]


async def collect_tier2_pairs(db: AsyncSession) -> list[tuple[int, int]]:
    """Corroborated namesakes: same name+lastname AND same hard corroborator
    (linkedin_slug or lower(email)). Within each corroborator group the canonical
    is the traffit-sourced / oldest row; the rest are duplicates of it.

    Excludes pairs already covered by tier 1 (talent_radar↔traffit external_id).
    """
    rows = (
        await db.execute(
            text(
                """
                WITH cand AS (
                    SELECT id, external_source, external_id,
                           lower(btrim(name)) AS n,
                           lower(btrim(coalesce(lastname, ''))) AS l,
                           nullif(lower(btrim(linkedin_slug)), '') AS slug,
                           nullif(lower(btrim(email)), '') AS em
                    FROM candidates
                    WHERE name IS NOT NULL AND btrim(name) NOT IN ('', '?')
                      AND lastname IS NOT NULL AND btrim(lastname) NOT IN ('', '?')
                ),
                -- corroborator key = name+lastname + (linkedin slug OR email)
                grp AS (
                    SELECT id, external_source, n, l,
                           coalesce(slug, 'email:' || em) AS corr
                    FROM cand
                    WHERE slug IS NOT NULL OR em IS NOT NULL
                ),
                ranked AS (
                    SELECT id, external_source, n, l, corr,
                           first_value(id) OVER (
                               PARTITION BY n, l, corr
                               ORDER BY (external_source = 'traffit') DESC, id ASC
                           ) AS canonical_id,
                           count(*) OVER (PARTITION BY n, l, corr) AS grp_size
                    FROM grp
                )
                SELECT canonical_id, id AS dup_id
                FROM ranked
                WHERE grp_size > 1 AND id <> canonical_id
                """
            )
        )
    ).all()
    return [(r.canonical_id, r.dup_id) for r in rows]


async def write_tier3_report(db: AsyncSession) -> tuple[int, Path]:
    """Write every name+lastname duplicate group to a review CSV. No deletes.

    Each row is annotated with the group's distinct-email / distinct-phone count
    so a human can tell same-person (≤1 email) from real namesakes (≥2 emails).
    """
    rows = (
        await db.execute(
            text(
                """
                WITH grp AS (
                    SELECT lower(btrim(name)) AS n,
                           lower(btrim(coalesce(lastname, ''))) AS l,
                           count(*) AS grp_size,
                           count(DISTINCT lower(btrim(email)))
                               FILTER (WHERE email IS NOT NULL AND btrim(email) <> '')
                               AS distinct_emails,
                           count(DISTINCT nullif(right(regexp_replace(
                               coalesce(phone, ''), '[^0-9]', '', 'g'), 9), ''))
                               FILTER (WHERE phone IS NOT NULL AND btrim(phone) <> '')
                               AS distinct_phones
                    FROM candidates
                    WHERE name IS NOT NULL AND btrim(name) NOT IN ('', '?')
                      AND lastname IS NOT NULL AND btrim(lastname) NOT IN ('', '?')
                    GROUP BY 1, 2
                    HAVING count(*) > 1
                )
                SELECT c.id, c.name, c.lastname, c.email, c.phone,
                       c.external_source, c.source,
                       g.grp_size, g.distinct_emails, g.distinct_phones,
                       CASE WHEN g.distinct_emails >= 2
                            THEN 'different_people'
                            ELSE 'likely_same' END AS verdict
                FROM grp g
                JOIN candidates c
                  ON lower(btrim(c.name)) = g.n
                 AND lower(btrim(coalesce(c.lastname, ''))) = g.l
                ORDER BY g.distinct_emails ASC, g.distinct_phones ASC,
                         c.name, c.lastname, c.id
                """
            )
        )
    ).all()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = OUT_DIR / f"namesake_review_{stamp}.csv"
    with out_path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow([
            "id", "name", "lastname", "email", "phone", "external_source",
            "source", "group_size", "distinct_emails", "distinct_phones", "verdict",
        ])
        for r in rows:
            w.writerow([
                r.id, r.name, r.lastname, r.email, r.phone, r.external_source,
                r.source, r.grp_size, r.distinct_emails, r.distinct_phones, r.verdict,
            ])
    return len(rows), out_path


# ── Orchestration ─────────────────────────────────────────────────────────────


async def _candidate_count(db: AsyncSession) -> int:
    return int((await db.execute(text("SELECT count(*) FROM candidates"))).scalar() or 0)


async def _run(tier: str, commit: bool) -> None:
    async with AsyncSessionLocal() as db:
        before = await _candidate_count(db)
        logger.info("Candidates before: %d (tier=%s, mode=%s)",
                    before, tier, "COMMIT" if commit else "DRY-RUN")

        if tier == "3":
            n_rows, path = await write_tier3_report(db)
            await db.rollback()
            logger.info("Tier 3 review report: %d rows → %s", n_rows, path)
            logger.info("Tier 3 is report-only; no candidates were deleted.")
            return

        if tier == "1":
            pairs = await collect_tier1_pairs(db)
        elif tier == "2":
            pairs = await collect_tier2_pairs(db)
        else:  # "all"
            seen: set[int] = set()
            pairs = []
            for p in (await collect_tier1_pairs(db)) + (await collect_tier2_pairs(db)):
                if p[1] not in seen:  # dedupe by dup_id — never merge a dup twice
                    seen.add(p[1])
                    pairs.append(p)

        stats = await merge_pairs(db, pairs)
        stats.log("DONE" if commit else "DRY-RUN")

        after = await _candidate_count(db)
        logger.info("Candidates after (uncommitted): %d (delta=%d)", after, after - before)

        if commit:
            await db.commit()
            logger.info("COMMITTED: merged %d duplicates, %d enriched with CV.",
                        stats.deleted, stats.cv_enriched)
        else:
            await db.rollback()
            logger.info("DRY-RUN: rolled back. Would merge %d duplicates "
                        "(%d enriched). Re-run with --commit to apply.",
                        stats.deleted, stats.cv_enriched)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Merge duplicate candidate rows (TalentRadar double-import + namesakes)."
    )
    parser.add_argument(
        "--tier", choices=["1", "2", "3", "all"], default="1",
        help="1=talent_radar external_id dups (default); 2=corroborated namesakes; "
             "3=review CSV only; all=tier 1+2.",
    )
    parser.add_argument("--commit", action="store_true", help="Persist changes.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Log only, roll back (default).")
    args = parser.parse_args(argv)
    if args.commit and args.dry_run:
        parser.error("--commit and --dry-run are mutually exclusive")

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    asyncio.run(_run(tier=args.tier, commit=bool(args.commit)))


if __name__ == "__main__":
    main()
    sys.exit(0)
