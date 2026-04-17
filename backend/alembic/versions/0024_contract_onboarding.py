"""Phase 9 B6: contract_onboarding_items table

Revision ID: 0024
Revises: 0023
Create Date: 2026-04-17 17:00:00.000000

Simple flat onboarding checklist per contract — one row per item.
No templates (yet); defaults seeded client-side. Supports done/pending/na
status plus optional assigned_to and due_date.
"""

from alembic import op
import sqlalchemy as sa


revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()

    status_enum = sa.Enum(
        "pending", "done", "na", name="onboardingitemstatus"
    )
    status_enum.create(bind, checkfirst=True)

    op.execute("""
        CREATE TABLE IF NOT EXISTS contract_onboarding_items (
            id SERIAL PRIMARY KEY,
            contract_id INTEGER NOT NULL
                REFERENCES contracts(id) ON DELETE CASCADE,
            label VARCHAR(255) NOT NULL,
            status onboardingitemstatus NOT NULL DEFAULT 'pending',
            assigned_to INTEGER REFERENCES users(id) ON DELETE SET NULL,
            due_date DATE,
            notes TEXT,
            "order" INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_contract_onboarding_contract "
        "ON contract_onboarding_items(contract_id)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS contract_onboarding_items CASCADE")
    sa.Enum(name="onboardingitemstatus").drop(op.get_bind(), checkfirst=True)
