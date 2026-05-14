"""candidates.linkedin_slug GENERATED + index for fast dedup.

Revision ID: 0106_candidate_linkedin_slug
Revises: 0105_user_email_templates
Create Date: 2026-05-14 17:30:00.000000

Why a generated column instead of app-maintained
-------------------------------------------------
The Chrome extension (`POST /api/candidates/from-linkedin`) does dedup via
`find_candidate_duplicates(linkedin=...)`, which today scans every candidate
with `linkedin.ilike('%<slug>%')`. That's a sequential scan over the whole
table (~12k rows on prod, climbing). A normalized slug column with an index
makes dedup O(log n).

PostgreSQL 16 (which NEXUS runs on prod, verified) supports STORED generated
columns; we extract the LinkedIn slug deterministically via the same logic
the app uses in `_normalize_phone`/`_linkedin_slug` helpers.

Why NOT a unique constraint (yet)
----------------------------------
Prod audit (2026-05-14, this commit author's session) found 54 real duplicate
groups (max 4 rows / group, total ~113 rows) plus ~1900 rows with broken
short slugs (e.g. `linkedin.com/in/jakub` — single first name from a bad
CV import, not an identifying URL). Adding a unique constraint now would
require manual merge UI which we don't have yet. Phase 2 follow-up: build
candidate-merge UI, then add `WHERE LENGTH(linkedin_slug) >= 10` partial
unique index.

What this migration changes
---------------------------
- Adds `candidates.linkedin_slug` as a STORED generated column from
  `linkedin` (lowercased last path segment, trailing slash + query stripped).
- Creates a non-unique B-tree index `ix_candidates_linkedin_slug`.
- The endpoint switches from `linkedin.ilike('%<slug>%')` to
  `linkedin_slug = :slug` (covered by the index).

Rollback: drop the index + column. No data migration; the column is
generated, so no app changes needed at rollback time.
"""

from __future__ import annotations

from alembic import op

revision = "0106_candidate_linkedin_slug"
down_revision = "0105_user_email_templates"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE candidates
        ADD COLUMN linkedin_slug VARCHAR(150)
        GENERATED ALWAYS AS (
            LOWER(
                REGEXP_REPLACE(
                    SPLIT_PART(SPLIT_PART(linkedin, '/in/', 2), '?', 1),
                    '/+$', ''
                )
            )
        ) STORED
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_candidates_linkedin_slug "
        "ON candidates (linkedin_slug) WHERE linkedin_slug IS NOT NULL AND linkedin_slug != ''"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_candidates_linkedin_slug")
    op.execute("ALTER TABLE candidates DROP COLUMN IF EXISTS linkedin_slug")
