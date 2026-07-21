"""Atomic dedup for Fireflies meeting notes: partial UNIQUE index on source_ref.

``services/fireflies_sync.py`` deduped imported transcripts with a non-atomic
SELECT-then-INSERT on the non-unique ``notes.source_ref`` (``fireflies:<id>``).
Two overlapping syncs (concurrent POST /api/fireflies/sync, or a manual trigger
racing a scheduled one) both saw "no existing row" and both inserted → duplicate
meeting notes. The code now uses ``INSERT ... ON CONFLICT DO NOTHING`` which
needs a unique arbiter index to be race-proof.

The index is partial (``WHERE source_ref LIKE 'fireflies:%'``) so it only
constrains Fireflies notes and leaves every other ``source_ref`` writer
(Traffit ``traffit:activity:<id>``, and NULL for user/bulk notes) completely
untouched. Fireflies ``source_ref`` is 1:1 with a transcript, so no legitimate
row is lost — but the buggy code may already have produced duplicates, so we
dedupe (keep the lowest id per source_ref) before creating the unique index,
or the CREATE would fail.

Mirrored idempotently in backend/entrypoint.sh (prod alembic is orphaned).

Revision ID: 0186_notes_fireflies_source_ref_unique
Revises: 0185_widen_scoring_algorithm_version
"""

from alembic import op

revision = "0187_notes_fireflies_source_ref_unique"
down_revision = "0186_bgtask_restart_safety_markers"
branch_labels = None
depends_on = None

_INDEX_NAME = "ux_notes_source_ref_fireflies"


def upgrade() -> None:
    # Dedupe first: keep the lowest id per fireflies source_ref, delete the
    # rest. note_mentions.note_id is ON DELETE CASCADE, so any (rare) child
    # rows on a duplicate system note go with it.
    op.execute(
        """
        DELETE FROM notes a
        USING notes b
        WHERE a.source_ref LIKE 'fireflies:%'
          AND b.source_ref = a.source_ref
          AND b.id < a.id
        """
    )
    op.execute(
        f"CREATE UNIQUE INDEX IF NOT EXISTS {_INDEX_NAME} "
        "ON notes (source_ref) WHERE source_ref LIKE 'fireflies:%'"
    )


def downgrade() -> None:
    op.execute(f"DROP INDEX IF EXISTS {_INDEX_NAME}")
