"""Jobs full-text search (tsvector + GIN index).

Revision ID: 0086_jobs_fts_index
Revises: 0085_embedding_cache
Create Date: 2026-05-08 14:55:00.000000

Mirrors `0083_candidate_fts_index` for the `jobs` table — enables BM25 search
needed by the hybrid retrieval orchestrator (Item 7 of AI modernization).

Weights:
  A — title (highest signal)
  B — requirements + must_skills (decisive for matching)
  C — description (long, lower signal-to-noise)

Why `simple` config: candidates' CV text is mixed PL/EN/DE; stemming pollutes
results. Same applies to job descriptions written in mixed languages.

Why STORED generated column + GIN: stays consistent on UPDATE without app-side
maintenance; GIN gives sub-50ms `ts_rank` lookups on 4K rows + room to grow.
"""

from alembic import op


revision = "0086_jobs_fts_index"
down_revision = "0085_embedding_cache"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # must_skills/nice_skills are JSONB arrays of {name, level, years}.
    # We pull just the names via a CASE guard (prod has scalar values too —
    # see eval_matching bugfix). text() avoids jsonb_array_length on scalars.
    op.execute(
        """
        ALTER TABLE jobs
        ADD COLUMN IF NOT EXISTS fts_doc tsvector
        GENERATED ALWAYS AS (
            setweight(
                to_tsvector('simple', coalesce(title, '')),
                'A'
            ) ||
            setweight(
                to_tsvector('simple', coalesce(requirements, '')),
                'B'
            ) ||
            setweight(
                to_tsvector(
                    'simple',
                    CASE
                        WHEN jsonb_typeof(must_skills) = 'array'
                        THEN coalesce(
                            (SELECT string_agg(
                                CASE
                                    WHEN jsonb_typeof(elem) = 'object'
                                    THEN coalesce(elem->>'name', '')
                                    ELSE coalesce(elem #>> '{}', '')
                                END,
                                ' '
                            )
                            FROM jsonb_array_elements(must_skills) AS elem),
                            ''
                        )
                        ELSE ''
                    END
                ),
                'B'
            ) ||
            setweight(
                to_tsvector('simple', coalesce(description, '')),
                'C'
            )
        ) STORED;
        """
    )

    with op.get_context().autocommit_block():
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
            "ix_jobs_fts ON jobs USING GIN(fts_doc);"
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_jobs_fts;")
    op.execute("ALTER TABLE jobs DROP COLUMN IF EXISTS fts_doc;")
