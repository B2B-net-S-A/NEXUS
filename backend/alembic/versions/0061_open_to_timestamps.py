"""Timestamps for open_to_* engagement flags (TTL/freshness of declarations).

Revision ID: 0061_open_to_timestamps
Revises: 0060_client_tac_assignments
Create Date: 2026-04-24 14:00:00.000000

Dodaje 3 nullable `timestamptz` kolumny na `candidates`:

  open_to_side_projects_updated_at
  open_to_sales_support_updated_at
  open_to_expert_consult_updated_at

NULL = deklaracja nigdy nie była aktualizowana (backfill zostawiamy NULL,
żeby UI pokazywał generic „nie wiadomo kiedy" zamiast fałszywej daty).

Motywacja: zakładka „Otwartość na dodatkowe projekty" pokazuje rekruterowi
świeżość deklaracji — po 90 dniach renderuje się nudge „potwierdź lub
odśwież". Bez timestampa per flagę ta feature nie wyróżnia, która z
trzech flag jest stara.
"""

from alembic import op
import sqlalchemy as sa


revision = "0061_open_to_timestamps"
down_revision = "0060_client_tac_assignments"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "candidates",
        sa.Column(
            "open_to_side_projects_updated_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "candidates",
        sa.Column(
            "open_to_sales_support_updated_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "candidates",
        sa.Column(
            "open_to_expert_consult_updated_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("candidates", "open_to_expert_consult_updated_at")
    op.drop_column("candidates", "open_to_sales_support_updated_at")
    op.drop_column("candidates", "open_to_side_projects_updated_at")
