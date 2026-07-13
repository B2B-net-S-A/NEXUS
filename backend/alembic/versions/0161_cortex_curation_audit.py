"""Cortex — audyt kuracji taksonomii (kto/kiedy zmapował/zignorował term).

Revision ID: 0161_cortex_curation_audit
Revises: 0160_cortex_trust_foundation
Create Date: 2026-07-13

Etap 1 (Action Layer): domknięcie pętli kuracji — API zyskuje write-path
(map/ignore/create), więc ``cortex_unmatched_terms`` potrzebuje śladu decyzji.
Idempotentne (ADD COLUMN IF NOT EXISTS) — mirror w entrypoint.sh.
"""

from alembic import op

revision = "0161_cortex_curation_audit"
down_revision = "0160_cortex_trust_foundation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE cortex_unmatched_terms "
        "ADD COLUMN IF NOT EXISTS curated_by VARCHAR(120)"
    )
    op.execute(
        "ALTER TABLE cortex_unmatched_terms "
        "ADD COLUMN IF NOT EXISTS curated_at TIMESTAMPTZ"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE cortex_unmatched_terms DROP COLUMN IF EXISTS curated_at")
    op.execute("ALTER TABLE cortex_unmatched_terms DROP COLUMN IF EXISTS curated_by")
