"""Jeden katalog KPI + próg Wyścigu Placementów w konfiguracji (22.09.2026).

Audyt ról, uprawnień i targetów (T1/T4, decyzje Artura 22.09.2026):

1. `kpi_role_defaults` / `user_kpi_targets` — stare id panelu „Moje KPI"
   (`verifications_daily`, `cv_added_daily`, `placements_monthly`,
   `precision_monthly`) przepisane na kanoniczne id katalogu KPI, martwe id
   z 0034 skasowane, a wiersze równe domyślnym z katalogu usunięte — katalog
   (`app/services/kpi_catalog.py`) jest odtąd jedynym źródłem liczb, tabela
   ról trzyma wyłącznie świadome odstępstwa. SQL ma JEDNO źródło:
   `app/services/kpi_target_normalization.py` (bez importów aplikacji);
   ten sam blok biegnie w `entrypoint.sh`. Jednorazowy: marker w
   `app_settings` + advisory lock.
2. `insights_scoring_config.monthly_race_min_placements = 2` — minimum
   placementów Wyścigu Placementów (1 500 PLN) z konfiguracji, a nie ze stałej
   w kodzie. `ON CONFLICT DO NOTHING`, więc strojenie admina zostaje.

Revision ID: 0343_kpi_catalog_unification
Revises: 0342_email_send_state
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from app.services.kpi_target_normalization import (
    KPI_TARGET_NORMALIZATION_MARKER,
    KPI_TARGET_NORMALIZATION_SQL,
)

revision = "0343_kpi_catalog_unification"
down_revision = "0342_email_send_state"
branch_labels = None
depends_on = None


# LUSTRO `SCORING_DEFAULTS` dla nowego klucza — strażnikiem zgodności jest
# `test_insights_scoring_config.py::test_migration_seed_matches_code_defaults`.
_RACE_DEFAULTS: list[tuple[str, int]] = [
    ("monthly_race_min_placements", 2),
]

# Downgrade przywraca DOKŁADNIE seed 0124 (panel „Moje KPI" sprzed 0343).
_SEED_0124: list[tuple[str, str, int]] = [
    ("sourcer", "verifications_daily", 4),
    ("tac", "verifications_daily", 4),
    ("recruiter", "verifications_daily", 4),
    ("sourcer", "precision_monthly", 75),
    ("tac", "precision_monthly", 75),
    ("recruiter", "precision_monthly", 75),
    ("sourcer", "placements_monthly", 1),
    ("tac", "placements_monthly", 1),
    ("recruiter", "placements_monthly", 1),
    ("recruiter", "cv_added_daily", 5),
    ("tac", "cv_added_daily", 5),
]


def upgrade() -> None:
    conn = op.get_bind()
    op.execute(KPI_TARGET_NORMALIZATION_SQL)
    for key, value in _RACE_DEFAULTS:
        conn.execute(
            sa.text(
                "INSERT INTO insights_scoring_config (key, value) "
                "VALUES (:key, :value) ON CONFLICT (key) DO NOTHING"
            ),
            {"key": key, "value": value},
        )


def downgrade() -> None:
    """Przywraca seed 0124 pod starymi id i zdejmuje marker.

    Wiersze pod kanonicznymi id zostają — kod sprzed 0343 i tak czytał je
    w widgecie KPI Coach (id widgetu się nie zmieniły).
    """
    conn = op.get_bind()
    conn.execute(
        sa.text("DELETE FROM insights_scoring_config WHERE key = :key"),
        {"key": "monthly_race_min_placements"},
    )
    for role, kpi_id, value in _SEED_0124:
        conn.execute(
            sa.text(
                "INSERT INTO kpi_role_defaults "
                "(role, kpi_id, target_value, created_at, updated_at) "
                "VALUES (CAST(:role AS userrole), :kpi, :value, now(), now()) "
                "ON CONFLICT (role, kpi_id) DO NOTHING"
            ),
            {"role": role, "kpi": kpi_id, "value": value},
        )
    conn.execute(
        sa.text("DELETE FROM app_settings WHERE key = :key"),
        {"key": KPI_TARGET_NORMALIZATION_MARKER},
    )
