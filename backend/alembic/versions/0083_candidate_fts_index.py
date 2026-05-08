"""Candidate full-text search (tsvector + GIN index).

Revision ID: 0083_candidate_fts_index
Revises: 0082_merge_oauth_storage_heads
Create Date: 2026-05-08 10:30:00.000000

Adds postgres FTS support for ``/api/search/candidates`` ranking:

1. ``candidates.fts_doc`` — generated ``tsvector`` column with weighted
   contribution from name/lastname (A), competence_category + ai_summary (B),
   and raw_cv_text (C). Stored generated → no app-side maintenance.

2. ``ix_candidates_fts`` — GIN index built CONCURRENTLY (production has 50K+
   rows; blocking CREATE INDEX would freeze writes for minutes).

Search uses ``websearch_to_tsquery('simple', q)`` + ``ts_rank`` with a recency
tie-breaker (``updated_at`` decay). Postgres ``simple`` config (no stemming) —
candidates' CV text is mixed PL/EN/DE; stemming pollutes results in such cases.

Why generated column (not trigger): stays consistent on UPDATE without app
intervention; trigger would require maintaining function lifecycle.

Why CONCURRENTLY: production has ~50K candidates with raw_cv_text averaging
~5KB. Non-concurrent CREATE INDEX would lock candidates writes for minutes,
breaking the deploy smoke test.
"""

from alembic import op


revision = "0083_candidate_fts_index"
down_revision = "0082_merge_oauth_storage_heads"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE candidates
        ADD COLUMN IF NOT EXISTS fts_doc tsvector
        GENERATED ALWAYS AS (
            setweight(
                to_tsvector(
                    'simple',
                    coalesce(name, '') || ' ' || coalesce(lastname, '')
                ),
                'A'
            ) ||
            setweight(
                to_tsvector('simple', coalesce(competence_category, '')),
                'B'
            ) ||
            setweight(
                to_tsvector('simple', coalesce(ai_summary, '')),
                'B'
            ) ||
            setweight(
                to_tsvector('simple', coalesce(raw_cv_text, '')),
                'C'
            )
        ) STORED;
        """
    )

    # CONCURRENTLY requires running outside a transaction. Alembic wraps
    # upgrades in a transaction by default; we end the implicit transaction
    # before issuing the CONCURRENTLY DDL.
    with op.get_context().autocommit_block():
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
            "ix_candidates_fts ON candidates USING GIN(fts_doc);"
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_candidates_fts;")
    op.execute("ALTER TABLE candidates DROP COLUMN IF EXISTS fts_doc;")
