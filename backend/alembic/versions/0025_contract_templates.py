"""Phase 9 B1: contract_templates table

Revision ID: 0025
Revises: 0024
Create Date: 2026-04-17 17:30:00.000000

Reusable Jinja2 templates for generating contract / annex documents.
"""

from alembic import op


revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS contract_templates (
            id SERIAL PRIMARY KEY,
            name VARCHAR(255) NOT NULL,
            contract_type VARCHAR(32) NOT NULL,
            content_jinja TEXT NOT NULL,
            is_default BOOLEAN NOT NULL DEFAULT FALSE,
            created_by INTEGER REFERENCES users(id),
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_contract_templates_type "
        "ON contract_templates(contract_type)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS contract_templates CASCADE")
