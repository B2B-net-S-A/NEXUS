"""Panel wag rankingu „Dop.” — historia zmian i pomiary (21.10.2026).

Revision ID: 0501_scoring_weight_changes
Revises: 0500_interview_changed_notification

Tabela ``scoring_weight_changes``: kto, kiedy, wagi przed i po, powód
i wynik pomiaru na historii. ``scoring_weight_measurements``: pomiar szkicu
na zamkniętych rekrutacjach (zadanie w tle). Szkic wag i próg nocnych propozycji leżą
w ``app_settings`` (bez zmian schematu). DDL ma jedno źródło z siatką
w ``entrypoint.sh`` (``services/ranking_weights_schema.py``).
"""

from alembic import op

from app.services.ranking_weights_schema import DOWNGRADE_DDL, TABLE_DDL

revision = "0501_scoring_weight_changes"
down_revision = "0500_interview_changed_notification"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for statement in TABLE_DDL:
        op.execute(statement)


def downgrade() -> None:
    for statement in DOWNGRADE_DDL:
        op.execute(statement)
