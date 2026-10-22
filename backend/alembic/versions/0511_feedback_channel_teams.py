"""„Ludzie w NEXUSIE” — forma „Teams” rozmowy z menedżerem u klienta.

Revision ID: 0511_feedback_channel_teams
Revises: 0510_teams_prep_scope_alert

Okno „Rozmowa z menedżerem” (opinia i popyt do sprawdzenia, makieta R4
z 22.10.2026) ma formę „Teams” obok telefonu, spotkania i maila. Poszerza
CHECK ``ck_client_feedback_sessions_channel``. SQL ma jedno źródło
(``app/services/contract_care_schema.py``); entrypoint wykonuje ten sam blok
przez ``hr_schema_bundle``.
"""

from alembic import op

from app.services import contract_care_schema as schema

revision = "0511_feedback_channel_teams"
down_revision = "0510_teams_prep_scope_alert"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for stmt in schema.FEEDBACK_TEAMS_DDL:
        op.execute(stmt)


def downgrade() -> None:
    op.execute(
        "UPDATE client_feedback_sessions SET channel = 'meeting' WHERE channel = 'teams'"
    )
    op.execute(
        "ALTER TABLE client_feedback_sessions "
        "DROP CONSTRAINT IF EXISTS ck_client_feedback_sessions_channel"
    )
    op.execute(
        "ALTER TABLE client_feedback_sessions ADD CONSTRAINT "
        "ck_client_feedback_sessions_channel "
        "CHECK (channel IN ('phone', 'meeting', 'email'))"
    )
