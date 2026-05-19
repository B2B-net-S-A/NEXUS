"""DynaReporter Acceleration Path — seniority tracking per user.

Revision ID: 0114_dr_user_seniority
Revises: 0113_dynareporter_schema
Create Date: 2026-05-19 11:00:00.000000

Dodaje tabelę ``dr_user_seniority`` do trackingu Acceleration Path
(Junior → Senior → Expert) z oryginalnego DynaReportera.

Tabela 1:1 z `users` (PRIMARY KEY = user_id, FOREIGN KEY) — opcjonalne
rozszerzenie, nie zaśmieca głównej tabeli ``users`` (która ma już
allowed_sections, dynareporter_legacy_id, roles, aad_group_ids).

Kolumny:
- seniority_level VARCHAR(20) DEFAULT 'junior' — junior | senior | expert
- acceleration_start_date DATE — od kiedy user jest na ścieżce awansu
- senior_since DATE — kiedy awansował na seniora (NULL jeśli wciąż junior)
- expert_since DATE — kiedy awansował na experta (NULL jeśli wciąż senior)
- updated_at TIMESTAMP

ETL: po migracji wypełnić z DynaReporter Render dump (44 sourcer/tac/recruiter
z `acceleration_start_date`, 4 z `senior_since`). Mapping przez
`users.dynareporter_legacy_id` ↔ `dr_users.id`.

Acceleration Path logika (computed na podstawie dr_placement_details):
- Junior → Senior: 6 placement w 6mc OR 12 placement w 12mc
- Senior → Expert: 12 placement w 6mc OR 24 placement w 12mc
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0114_dr_user_seniority"
down_revision = "0113_dynareporter_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "dr_user_seniority",
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "seniority_level",
            sa.String(length=20),
            nullable=False,
            server_default="junior",
        ),
        sa.Column("acceleration_start_date", sa.Date(), nullable=True),
        sa.Column("senior_since", sa.Date(), nullable=True),
        sa.Column("expert_since", sa.Date(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=False),
            server_default=sa.func.current_timestamp(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "seniority_level IN ('junior','senior','expert')",
            name="dr_user_seniority_level_check",
        ),
    )
    op.create_index(
        "idx_dr_user_seniority_level",
        "dr_user_seniority",
        ["seniority_level"],
    )


def downgrade() -> None:
    op.drop_index("idx_dr_user_seniority_level", table_name="dr_user_seniority")
    op.drop_table("dr_user_seniority")
