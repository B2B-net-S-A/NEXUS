"""Zastępca do Cpro we wniosku urlopowym osoby od Cpro.

Revision ID: 0622_leave_cpro_substitute
Revises: 0621_pair_departure_care

Decyzja Artura 29.10.2026: osoba od Cpro wskazuje we wniosku, kto w tym
czasie wrzuca kandydatów Nordei do Cpro. SQL ma jedno źródło
(``app/services/hr_leave_cpro_schema.py``) — ten sam moduł czyta
``entrypoint.sh`` przez ``hr_schema_bundle``.
"""

from alembic import op

from app.services import hr_leave_cpro_schema as schema

revision = "0622_leave_cpro_substitute"
down_revision = "0621_pair_departure_care"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for stmt in schema.ALL_DDL:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in schema.DOWNGRADE_DDL:
        op.execute(stmt)
