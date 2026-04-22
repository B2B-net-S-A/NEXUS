"""Candidate.created_by + composite pool-membership index (Wyszukiwarka phase)

Revision ID: 0030_candidate_created_by
Revises: 0029
Create Date: 2026-04-21 18:00:00.000000

Adds `created_by` FK on `candidates` so the list UI can filter by "added by X".
Backfills from `user_activities` (newer) then `activities` (older), earliest
entry wins. Unbackfillable rows stay NULL — the UI exposes a "System import"
sentinel for them.

Also adds composite btree on `talent_pool_memberships(talent_pool_id,
candidate_id)` so the new EXISTS-subquery filter stays fast.

Idempotent + reversible.
"""

from alembic import op
import sqlalchemy as sa

revision = "0030_candidate_created_by"
down_revision = "0029"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1) Column (+ index) — idempotent via information_schema check.
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name='candidates' AND column_name='created_by'
            ) THEN
                ALTER TABLE candidates
                    ADD COLUMN created_by INTEGER REFERENCES users(id) ON DELETE SET NULL;
            END IF;
        END$$;
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_candidates_created_by "
        "ON candidates(created_by)"
    )

    # 2) Backfill from user_activities — earliest 'candidate_added' per candidate wins.
    op.execute(
        """
        UPDATE candidates c
        SET created_by = sub.user_id
        FROM (
            SELECT DISTINCT ON (entity_id) entity_id, user_id
            FROM user_activities
            WHERE entity_type = 'candidate'
              AND action_type = 'candidate_added'
            ORDER BY entity_id, created_at ASC
        ) sub
        WHERE c.id = sub.entity_id
          AND c.created_by IS NULL
        """
    )

    # 3) Fallback backfill from activities table (older rows, pre-user_activities).
    op.execute(
        """
        UPDATE candidates c
        SET created_by = a.user_id
        FROM (
            SELECT DISTINCT ON (entity_id) entity_id, user_id
            FROM activities
            WHERE entity_type = 'candidate'
              AND action = 'created'
            ORDER BY entity_id, created_at ASC
        ) a
        WHERE c.id = a.entity_id
          AND c.created_by IS NULL
        """
    )

    # 4) Composite index for pool filter EXISTS subquery.
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_tpm_pool_cand "
        "ON talent_pool_memberships(talent_pool_id, candidate_id)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_tpm_pool_cand")
    op.execute("DROP INDEX IF EXISTS ix_candidates_created_by")
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name='candidates' AND column_name='created_by'
            ) THEN
                ALTER TABLE candidates DROP COLUMN created_by;
            END IF;
        END$$;
        """
    )
