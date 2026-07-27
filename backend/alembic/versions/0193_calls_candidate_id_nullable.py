"""Allow calls.candidate_id NULL — unassigned inbound CloudTalk calls (F-12).

An inbound CloudTalk webhook whose phone matches MORE than one candidate (same
trailing-9 digits) must NOT auto-attach the recording/transcript to an arbitrary
candidate — that would leak one person's call onto another candidate's profile.
Instead the Call row is still upserted (by ``cloudtalk_call_id``) so the event
isn't lost, but with ``candidate_id`` NULL (unassigned) for later manual
attribution. That requires relaxing the historical ``NOT NULL`` on the column.

Dropping ``NOT NULL`` is instant on Postgres (catalog-only, no table rewrite,
no scan). Idempotent: ``DROP NOT NULL`` on an already-nullable column is a
no-op. Mirrored in backend/entrypoint.sh (prod alembic is orphaned; every
schema change must be reflected there too), matching this DDL 1:1.

Revision ID: 0193_calls_candidate_id_nullable
Revises: 0191_contract_lifecycle_invariant
"""

from alembic import op

revision = "0193_calls_candidate_id_nullable"
down_revision = "0192_user_tokens_valid_after"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE calls ALTER COLUMN candidate_id DROP NOT NULL")


def downgrade() -> None:
    # Only safe if no unassigned rows exist; existing NULLs would block this.
    op.execute("ALTER TABLE calls ALTER COLUMN candidate_id SET NOT NULL")
