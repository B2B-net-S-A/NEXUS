"""Decyzje z zakładki „Wnioski” w Insights.

Revision ID: 0647_insight_decisions
Revises: 0646_frequent_rejection_reasons

Decyzja Artura 04.11.2026: NEXUS pokazuje, co się powtarza w danych, a człowiek
decyduje. Decyzja nie zmienia działania systemu, tylko zostawia ślad i termin oceny.
DDL w ``app/services/insight_decisions_schema.py``, lustro w ``entrypoint.sh``.
"""

from alembic import op

from app.services.insight_decisions_schema import TABLE_DDL

revision = "0647_insight_decisions"
down_revision = "0646_frequent_rejection_reasons"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for statement in TABLE_DDL:
        op.execute(statement)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS insight_decisions")
