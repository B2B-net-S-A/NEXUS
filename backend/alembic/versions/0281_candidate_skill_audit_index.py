"""Index historical manual candidate edits used by skill provenance.

Revision ID: 0281_candidate_skill_audit_index
Revises: 0280_ai_metering_and_leases
"""

from alembic import op

revision = "0281_candidate_skill_audit_index"
down_revision = "0280_ai_metering_and_leases"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # A full composite index also supports prepared/generic query plans: the
    # ORM binds its predicate values, so a partial index is not always usable.
    # Build without blocking writes to the production audit log.
    with op.get_context().autocommit_block():
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
            "ix_activities_candidate_manual_edit "
            "ON activities (entity_type, entity_id, action, external_source)"
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(
            "DROP INDEX CONCURRENTLY IF EXISTS ix_activities_candidate_manual_edit"
        )
