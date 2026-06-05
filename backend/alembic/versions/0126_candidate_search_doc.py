"""Candidate substring-search acceleration (search_doc + GIN trigram indexes).

Revision ID: 0126_candidate_search_doc
Revises: 0125_b2b_generated_contracts
Create Date: 2026-06-05 12:00:00.000000

`GET /api/candidates?q=<phrase>` (and the ⌘K command palette that calls it on
every keystroke) was a ~12s full ``Seq Scan`` over 47.6K candidates: the
``single_phrase_filter`` OR'd ``ILIKE '%phrase%'`` across 18 columns — each
wrapped in ``COALESCE`` (which defeats index matching) and mixed with a
non-indexable ``similarity() > threshold`` and a cross-table notes EXISTS — so
the planner could not use *any* of the existing trigram indexes and scanned the
whole table (incl. the 171MB of raw_cv_text).

This migration adds the index support so the rewritten query (see
``app.services.advanced_candidate_search``) becomes a UNION of bitmap index
scans (~100-200ms instead of ~12s):

1. ``candidates.search_doc`` — STORED generated ``text`` column holding the
   space-joined concatenation of every searchable candidate text field EXCEPT
   ``raw_cv_text`` and notes. raw_cv_text keeps its own ``ix_candidates_cv_trgm``
   (still used by ``/api/search/candidates``), so excluding it keeps this column
   tiny (~28MB total / ~617B avg) and — crucially — means the ADD COLUMN table
   rewrite never has to detoast the big CV text, so the ACCESS EXCLUSIVE lock is
   only a few seconds. Generated → no app-side maintenance, stays consistent on
   UPDATE. The ORM never writes it (referenced as a bare column in WHERE only).

2. ``ix_candidates_search_doc_trgm`` — GIN (gin_trgm_ops) on search_doc, so a
   leading-wildcard ``ILIKE`` is an index scan. Built CONCURRENTLY (production
   has 47.6K rows; a blocking CREATE INDEX would freeze writes for the build).

3. ``ix_notes_content_trgm`` — GIN (gin_trgm_ops) on ``notes.content``, so the
   notes branch of the search UNION is an index scan instead of a ~900ms seq
   scan over 46K notes. Also CONCURRENTLY.

Substring scope/semantics match the previous per-column OR (a candidate matches
iff the phrase is a substring of search_doc, raw_cv_text, or a note) — verified
by comparing result sets for known queries before/after.

Why CONCURRENTLY (and the autocommit block): the index builds must not lock
candidates/notes writes during deploy; CREATE INDEX CONCURRENTLY cannot run in a
transaction, and Alembic wraps upgrades in one by default.
"""

from alembic import op


revision = "0126_candidate_search_doc"
down_revision = "0125_b2b_generated_contracts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # pg_trgm already enabled by 0013_search_indexes; idempotent guard for safety.
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    # STORED generated haystack of all searchable candidate text fields except
    # raw_cv_text (own index) and notes (separate table). JSONB blobs are cast to
    # text so the whole payload is searchable, mirroring the previous
    # `cast(col, String)` ILIKE behaviour. name/lastname are adjacent so a
    # "First Last" substring still matches (parity with the old concat_ws line).
    op.execute(
        """
        ALTER TABLE candidates
        ADD COLUMN IF NOT EXISTS search_doc text
        GENERATED ALWAYS AS (
            coalesce(name, '') || ' ' ||
            coalesce(lastname, '') || ' ' ||
            coalesce(email, '') || ' ' ||
            coalesce(phone, '') || ' ' ||
            coalesce(location, '') || ' ' ||
            coalesce(city, '') || ' ' ||
            coalesce(linkedin_current_title, '') || ' ' ||
            coalesce(linkedin_current_company, '') || ' ' ||
            coalesce(ai_summary, '') || ' ' ||
            coalesce(competence_category, '') || ' ' ||
            coalesce(engagement_notes, '') || ' ' ||
            coalesce(experience::text, '') || ' ' ||
            coalesce(skills::text, '') || ' ' ||
            coalesce(tags::text, '') || ' ' ||
            coalesce(education::text, '') || ' ' ||
            coalesce(languages::text, '')
        ) STORED;
        """
    )

    # CONCURRENTLY requires running outside a transaction. Alembic wraps upgrades
    # in a transaction by default; end the implicit transaction before the DDL.
    with op.get_context().autocommit_block():
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_candidates_search_doc_trgm "
            "ON candidates USING GIN (search_doc gin_trgm_ops);"
        )
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_notes_content_trgm "
            "ON notes USING GIN (content gin_trgm_ops);"
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_notes_content_trgm;")
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_candidates_search_doc_trgm;")
    op.execute("ALTER TABLE candidates DROP COLUMN IF EXISTS search_doc;")
