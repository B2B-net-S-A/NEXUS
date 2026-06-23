"""Candidate full-text search (tsvector + GIN) for fast keyword filtering.

Revision ID: 0143_candidate_search_fts
Revises: 0142_contracts_framework_rate_line_manager
Create Date: 2026-06-23 12:00:00.000000

Why this exists
---------------
``GET /api/candidates?q_all=java|selenium`` (and any keyword bucket hitting a
common term) was 3-27s on the 50K-row production base. Migration 0126 added the
``search_doc`` trigram column and got the *non-CV* fields fast, but the keyword
filter still has a separate ``raw_cv_text ILIKE '%phrase%'`` branch. pg_trgm GIN
is **lossy for substring LIKE**, so Postgres must re-read and **detoast every
candidate row the index flags** to confirm the match. A common keyword flags
thousands of rows (``java`` ≈ 17K = 34% of the table), so it's thousands of
multi-KB CV detoasts per request (the ~171MB of ``raw_cv_text``). Measured cold:
``kubernetes`` 7.6s, ``java`` page-50 26.9s. Zero-match and unfiltered loads stay
<0.8s precisely because they never run that per-row recheck.

The fix
-------
A ``tsvector`` GIN index evaluates ``@@`` against the **compact stored
tsvector**, never detoasting the raw CV — so it is strictly cheaper per row than
the trigram-substring path regardless of the plan the planner picks (index
bitmap, lossy-bitmap recheck on the small tsvector, or even a seq scan over the
tsvector column). The query layer
(``app.services.advanced_candidate_search``) routes plain alphanumeric words
(``java``, ``selenium``, ``python``) through a word-PREFIX FTS match
(``to_tsquery('simple', 'java:*')``) and keeps the existing trigram-substring
path for short/special-char fragments (``c++``, ``.net``, ``c#``). Word-prefix
keeps ``jav`` → ``java`` (incremental ⌘K typing) and ``java`` → ``javascript``
(word-prefix) while dropping only rare mid-word substring matches.

Zero-downtime shape (NOT a generated column)
--------------------------------------------
A ``GENERATED ALWAYS AS (...) STORED`` column would have to detoast all 171MB of
CV text during the ``ADD COLUMN`` table rewrite, holding ``ACCESS EXCLUSIVE``
(blocking candidate reads AND writes) for ~a minute on prod. Instead:

1. ``ADD COLUMN search_fts tsvector`` — nullable, no default → instant metadata
   change, no rewrite.
2. A ``BEFORE INSERT OR UPDATE`` trigger keeps it fresh (same maintenance
   semantics a generated column would have, just without the rewrite lock).
3. Batched backfill (autocommit, 2000 rows/batch, resumable via
   ``WHERE search_fts IS NULL``) — short row locks, autovacuum keeps up.
4. ``CREATE INDEX CONCURRENTLY`` GIN — never blocks writes during the build.

Scope mirrors ``search_doc`` (migration 0126) field-for-field, PLUS
``raw_cv_text`` capped at 200KB (``left(...)``) — far beyond any real CV's
extracted text, and a hard guard against the 1MB tsvector limit so one
pathological row can never break inserts/updates. The ``'simple'`` config
(no stemming, no stopwords) keeps tech tokens predictable: ``java`` → ``java``.

The trigram ``search_doc`` / ``raw_cv_text`` indexes from 0013/0126 STAY — the
substring fallback path still uses them.
"""

from alembic import op

revision = "0143_candidate_search_fts"
down_revision = "0142_contracts_framework_rate_line_manager"
branch_labels = None
depends_on = None


# Single source of truth for the FTS document. Mirrors the search_doc field list
# (migration 0126) in the same order, then appends raw_cv_text capped at 200KB.
# `prefix` is "NEW." inside the trigger and "" for the backfill UPDATE.
_TEXT_COLS = (
    "name",
    "lastname",
    "email",
    "phone",
    "location",
    "city",
    "linkedin_current_title",
    "linkedin_current_company",
    "ai_summary",
    "competence_category",
    "engagement_notes",
)
_JSON_COLS = ("experience", "skills", "tags", "education", "languages")
_CV_CAP = 200_000


def _fts_expr(prefix: str) -> str:
    parts = [f"coalesce({prefix}{c}, '')" for c in _TEXT_COLS]
    parts += [f"coalesce({prefix}{c}::text, '')" for c in _JSON_COLS]
    parts.append(f"coalesce(left({prefix}raw_cv_text, {_CV_CAP}), '')")
    inner = " || ' ' || ".join(parts)
    return f"to_tsvector('simple', {inner})"


def upgrade() -> None:
    # 1. Nullable column — instant, no table rewrite (PG adds a NULL column as a
    #    metadata-only change).
    op.execute("ALTER TABLE candidates ADD COLUMN IF NOT EXISTS search_fts tsvector")

    # 2. Trigger keeps search_fts in sync on every insert/update. A generated
    #    column would recompute on the same events; the trigger only differs in
    #    avoiding the ADD-COLUMN rewrite lock.
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION candidates_search_fts_refresh()
        RETURNS trigger AS $$
        BEGIN
            NEW.search_fts := {_fts_expr("NEW.")};
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    # CREATE OR REPLACE TRIGGER is PG14+ (prod is PG16). Idempotent on re-run.
    op.execute(
        """
        CREATE OR REPLACE TRIGGER trg_candidates_search_fts
        BEFORE INSERT OR UPDATE ON candidates
        FOR EACH ROW EXECUTE FUNCTION candidates_search_fts_refresh();
        """
    )

    # 3. Batched backfill + 4. concurrent index — both need to run outside the
    #    migration's transaction (autocommit) so batches commit individually and
    #    CREATE INDEX CONCURRENTLY is legal. Resumable: only NULL rows are
    #    touched, so an interrupted deploy re-runs cleanly.
    with op.get_context().autocommit_block():
        conn = op.get_bind()
        backfill = (
            f"UPDATE candidates SET search_fts = {_fts_expr('')} "
            "WHERE id IN ("
            "  SELECT id FROM candidates WHERE search_fts IS NULL ORDER BY id LIMIT 2000"
            ")"
        )
        while True:
            result = conn.exec_driver_sql(backfill)
            if not result.rowcount:
                break

        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_candidates_search_fts "
            "ON candidates USING GIN (search_fts);"
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_candidates_search_fts;")
    op.execute("DROP TRIGGER IF EXISTS trg_candidates_search_fts ON candidates;")
    op.execute("DROP FUNCTION IF EXISTS candidates_search_fts_refresh();")
    op.execute("ALTER TABLE candidates DROP COLUMN IF EXISTS search_fts;")
