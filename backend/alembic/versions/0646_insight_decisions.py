"""Decyzje z zakładki „Wnioski” w Insights.

Revision ID: 0646_insight_decisions
Revises: 0645_back_office_role

Decyzja Artura 04.11.2026: NEXUS pokazuje, co się powtarza w danych, a człowiek
decyduje. Decyzja nie zmienia działania systemu, tylko zostawia ślad i termin oceny.
DDL w ``app/services/insight_decisions_schema.py``, lustro w ``entrypoint.sh``.
"""

from alembic import op

from app.services.insight_decisions_schema import TABLE_DDL

revision = "0646_insight_decisions"
down_revision = "0645_back_office_role"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for statement in TABLE_DDL:
        op.execute(statement)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS insight_decisions")
