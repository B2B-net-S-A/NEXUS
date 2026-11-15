"""Szczegół powodu odrzucenia z porcji i powód „Porządki” (runda 5).

Revision ID: 0717_autofill_detail_cleanup
Revises: 0716_premium_skill_claims

Decyzja Artura 16.11.2026 po feedbacku porcji z 13.11: „Inna rola” mówi,
co nie pasuje (95 z 98 odrzuceń bez słowa), „Nie szuka” zapisuje okres
wypowiedzenia albo datę, a porządki tablicy mają własny powód, który nie
uczy systemu. DDL ma jedno źródło (``app/services/autofill_feedback_schema.py``);
entrypoint wykonuje je przy każdym starcie.
"""

from alembic import op

from app.services import autofill_feedback_schema as schema

revision = "0717_autofill_detail_cleanup"
down_revision = "0716_premium_skill_claims"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for stmt in schema.DETAIL_DDL:
        op.execute(stmt)


def downgrade() -> None:
    # Więz zostaje szerszy, a kolumna zostaje — nowe wiersze nie tracą danych.
    pass
