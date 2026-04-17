"""Phase 9 B3: contract_amendments table

Revision ID: 0022
Revises: 0021
Create Date: 2026-04-17 16:00:00.000000

Formal workflow for contract amendments (extensions, rate changes,
scope changes, early terminations). Keeps before/after snapshots as JSONB
so the chronological history is auditable.
"""

from alembic import op
import sqlalchemy as sa


revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()

    amendment_type = sa.Enum(
        "extension",
        "rate_change",
        "scope_change",
        "early_termination",
        name="contractamendmenttype",
    )
    amendment_type.create(bind, checkfirst=True)

    op.execute("""
        CREATE TABLE IF NOT EXISTS contract_amendments (
            id SERIAL PRIMARY KEY,
            contract_id INTEGER NOT NULL
                REFERENCES contracts(id) ON DELETE CASCADE,
            amendment_type contractamendmenttype NOT NULL,
            old_values JSONB,
            new_values JSONB,
            effective_date DATE NOT NULL,
            reason TEXT,
            document_id INTEGER
                REFERENCES contract_documents(id) ON DELETE SET NULL,
            created_by INTEGER REFERENCES users(id),
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_contract_amendments_contract_id "
        "ON contract_amendments(contract_id)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS contract_amendments CASCADE")
    sa.Enum(name="contractamendmenttype").drop(op.get_bind(), checkfirst=True)
