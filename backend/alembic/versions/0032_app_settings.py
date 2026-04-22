"""app_settings key/value store (Wyszukiwarka phase)

Revision ID: 0032_app_settings
Revises: 0031_candidate_invite_links
Create Date: 2026-04-21 18:10:00.000000

Single-row-per-key JSONB store for organization-wide UI/product defaults
(candidates-columns config, future SLA thresholds, etc.). Per-user overrides
stay on the frontend — this table only holds the *default everyone starts from*.

Idempotent + reversible.
"""

from alembic import op
import sqlalchemy as sa

revision = "0032_app_settings"
down_revision = "0031_candidate_invite_links"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS app_settings (
            key         VARCHAR(100) PRIMARY KEY,
            value       JSONB        NOT NULL,
            updated_by  INTEGER      REFERENCES users(id) ON DELETE SET NULL,
            updated_at  TIMESTAMPTZ  NOT NULL DEFAULT now()
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS app_settings")
