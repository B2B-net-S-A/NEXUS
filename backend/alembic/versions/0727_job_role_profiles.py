"""Profil „Kogo szukamy” rekrutacji w porcji dnia.

Revision ID: 0727_job_role_profiles
Revises: 0726_law_radar_gofin

Decyzja Artura 16.11.2026: „Inna rola” to 28% odrzuceń porcji z 16.11, a 37%
decyzji jest w rekrutacjach, których tytułu ``role_family`` nie rozpoznaje.
Rekrutacja dostaje profil (rola, specjalizacja, technologia, poziom) i listę
„Nie proponujemy”, której silnik „Nowych” pilnuje przy dokładaniu kart.
DDL ma jedno źródło (``app/services/job_role_profile_schema.py``); entrypoint
wykonuje je przy każdym starcie.
"""

from alembic import op

from app.services import job_role_profile_schema as schema

revision = "0727_job_role_profiles"
down_revision = "0726_law_radar_gofin"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for stmt in schema.TABLE_DDL:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in schema.DOWNGRADE_DDL:
        op.execute(stmt)
