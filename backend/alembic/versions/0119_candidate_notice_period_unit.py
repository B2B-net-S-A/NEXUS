"""Add notice_period_unit to candidates (days/weeks/months).

Revision ID: 0119_candidate_notice_period_unit
Revises: 0118_candidate_pins
Create Date: 2026-05-25 12:00:00.000000

The existing `notice_period` column stores an integer that historically meant
"days" (used by Polish B2B contracts). For UoP contracts notice periods are
defined in months/weeks by law (2 weeks / 1 month / 3 months depending on
tenure), and converting "3 months" to "90 days" loses the original intent —
the actual calendar duration depends on the day the notice is filed.

This migration adds `notice_period_unit` so the UI can capture the
qualitative period (value + unit) without ambiguity. Existing rows keep
`notice_period_unit = NULL`, which the application treats as "days" for
backward compatibility. Search filters normalize unit→days via CASE.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0119_candidate_notice_period_unit"
down_revision: str | Sequence[str] | None = "0118_candidate_pins"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "candidates",
        sa.Column("notice_period_unit", sa.String(length=20), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("candidates", "notice_period_unit")
