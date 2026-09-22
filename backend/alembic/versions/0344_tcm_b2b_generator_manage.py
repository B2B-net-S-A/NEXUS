"""TCM: pełny generator B2B także na świeżej bazie (22.09.2026).

Decyzja Artura z audytu ról (22.09.2026): Talent Community Manager ma pełny
generator umów B2B (``manage``). Produkcja ma to od 03–04.09 (zmiana w panelu
RBAC), ale seed 0273 zakłada ``view`` — świeża baza (CI, odtworzenie) dawała
TCM mniej niż produkcja i niż ``DEFAULT_ROLE_ACTION_ACCESS``.

Zmieniamy WYŁĄCZNIE wiersz z seeda (``updated_by IS NULL`` i ``view``): decyzja
administratora zapisana w panelu RBAC zostaje nietknięta. Na produkcji to
no-op (wiersz ma autora i już ``manage``).

Revision ID: 0344_tcm_b2b_generator_manage
Revises: 0343_kpi_catalog_unification
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0344_tcm_b2b_generator_manage"
down_revision = "0343_kpi_catalog_unification"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE rbac_role_action_permissions SET access = 'manage' "
            "WHERE role = 'talent_community_manager' "
            "AND action = 'b2b_contract_generator' "
            "AND access = 'view' AND updated_by IS NULL"
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE rbac_role_action_permissions SET access = 'view' "
            "WHERE role = 'talent_community_manager' "
            "AND action = 'b2b_contract_generator' "
            "AND access = 'manage' AND updated_by IS NULL"
        )
    )
