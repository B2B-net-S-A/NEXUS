"""Konto wybiera, czy dostaje ruchy cudzych kandydatów w rekrutacjach, które prowadzi.

Revision ID: 0679_stage_moves_all_led_jobs
Revises: 0678_duty_search

Reguła ``docs/claude/powiadomienia/ruch-etapu-do-rekrutera-kandydata.md``.
Lustro w ``entrypoint.sh``.
"""

from alembic import op

revision = "0679_stage_moves_all_led_jobs"
down_revision = "0678_duty_search"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS stage_moves_all_led_jobs BOOLEAN NOT NULL DEFAULT false"  # noqa: E501
    )


def downgrade() -> None:
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS stage_moves_all_led_jobs")
