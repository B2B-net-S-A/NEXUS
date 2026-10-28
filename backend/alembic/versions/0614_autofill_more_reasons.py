"""Trzy nowe powody odrzucenia osoby od systemu.

Revision ID: 0614_autofill_more_reasons
Revises: 0613_timesheets_permission

Decyzja Artura 28.10.2026 po analizie 44 odrzuceń (runda 3): 6 z 10 „Inne”
to „overqualified”, błędny numer telefonu i „zgłoszony do klienta przez inną
firmę”. Więz powodów ma jedno źródło (``REASON_CHECK_DDL``
w ``app/services/autofill_feedback_schema.py``); entrypoint wykonuje go przy
każdym starcie.
"""

from alembic import op

from app.services import autofill_feedback_schema as schema

revision = "0614_autofill_more_reasons"
down_revision = "0613_timesheets_permission"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for stmt in schema.REASON_CHECK_DDL:
        op.execute(stmt)


def downgrade() -> None:
    # Więz zostaje szerszy — nowe powody w wierszach nie znikają.
    pass
