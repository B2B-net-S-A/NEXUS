"""Add composite index on dr_placement_details + TIMESTAMPTZ for dr_user_seniority.

Revision ID: 0115_dr_perf_indexes
Revises: 0114_dr_user_seniority
Create Date: 2026-05-19 12:00:00.000000

Quality check findings fixup (review of PR #242-252):

HIGH #1: dr_placement_details miał single-column indexes na `user_id` i
`placement_date` osobno, ale brak composite `(user_id, placement_date)`.
Endpoint `/acceleration-path` robił 4 correlated subqueries per row z
range scan po placement_date — przy 44 użytkownikach na ścieżce to 176
subquery na request, każdy musiał intersect 2 single-column indexy.

Fix: dodaj composite index. Wzorzec NON-CONCURRENT bo migracja w
deployment lifecycle (Coolify auto-upgrade head, dr_placement_details
ma ~90 wierszy obecnie — instant operation).

HIGH #5: dr_user_seniority.updated_at używał `TIMESTAMP` (no TZ) co jest
niezgodne z resztą schema nexus (wszystkie inne tabele mają TIMESTAMPTZ).
Tabela jest obecnie pusta (35 wpisów ale dane testowe) — można ALTER
bezpiecznie.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0115_dr_perf_indexes"
down_revision = "0114_dr_user_seniority"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # HIGH #1: composite index na dr_placement_details
    op.create_index(
        "idx_dr_placement_details_user_date",
        "dr_placement_details",
        ["user_id", "placement_date"],
    )

    # HIGH #5: TIMESTAMPTZ dla dr_user_seniority.updated_at
    # Zachowujemy obecne dane jako UTC (CURRENT_TIMESTAMP bez TZ zakładamy UTC
    # dla server-side defaults).
    op.alter_column(
        "dr_user_seniority",
        "updated_at",
        type_=sa.DateTime(timezone=True),
        postgresql_using="updated_at AT TIME ZONE 'UTC'",
        server_default=sa.func.current_timestamp(),
        nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "dr_user_seniority",
        "updated_at",
        type_=sa.DateTime(timezone=False),
        postgresql_using="updated_at AT TIME ZONE 'UTC'",
        server_default=sa.func.current_timestamp(),
        nullable=False,
    )
    op.drop_index(
        "idx_dr_placement_details_user_date",
        table_name="dr_placement_details",
    )
