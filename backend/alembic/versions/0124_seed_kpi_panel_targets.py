"""seed kpi_role_defaults z targetami panelu „Moje KPI"

Targety KPI dla panelu głównego (verifier-anchored funnel). Logika liczenia
żyje w app/services/kpi_panel.py; tu tylko liczby, żeby admin mógł je zmieniać
w DB bez deploya. Idempotentne — ON CONFLICT (role, kpi_id) DO NOTHING, więc
nie nadpisuje ręcznych zmian admina przy re-runie.

KPI Artura:
  - verifications_daily  = 4/dzień   (sourcer, TAC, recruiter)
  - precision_monthly    = 75 (%)    (sourcer, TAC, recruiter)
  - placements_monthly   = 1/miesiąc (sourcer, TAC, recruiter)
  - cv_added_daily       = 5/dzień   (recruiter, TAC — licencja LinkedIn)

Hit ratio 30% delivery_leadów liczy już /api/reports/delivery-leads, więc tu
go nie seedujemy.

Revision ID: 0124_seed_kpi_panel_targets
Revises: 0123_b2b_contract_generator
"""

from __future__ import annotations

from alembic import op

revision = "0124_seed_kpi_panel_targets"
down_revision = "0123_b2b_contract_generator"
branch_labels = None
depends_on = None


# (role, kpi_id, target_value)
_ROWS: list[tuple[str, str, int]] = [
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

_KPI_IDS = (
    "verifications_daily",
    "precision_monthly",
    "placements_monthly",
    "cv_added_daily",
)


def upgrade() -> None:
    values = ",\n        ".join(
        f"('{role}', '{kpi}', {target}, now(), now())" for role, kpi, target in _ROWS
    )
    op.execute(
        f"""
        INSERT INTO kpi_role_defaults (role, kpi_id, target_value, created_at, updated_at)
        VALUES
        {values}
        ON CONFLICT (role, kpi_id) DO NOTHING
        """
    )


def downgrade() -> None:
    ids = ", ".join(f"'{k}'" for k in _KPI_IDS)
    op.execute(f"DELETE FROM kpi_role_defaults WHERE kpi_id IN ({ids})")
