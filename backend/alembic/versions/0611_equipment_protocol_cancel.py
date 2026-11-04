"""Sprzęt — anulowanie protokołu: kto, kiedy i dlaczego.

Revision ID: 0611_equipment_protocol_cancel
Revises: 0610_job_p0_request

Decyzja Artura 28.10.2026: „Popraw protokół” przed podpisem i „Anuluj
protokół” niepotwierdzony. SQL ma jedno źródło
(``app/services/equipment_protocol_cancel_schema.py``) — ten sam moduł czyta
``entrypoint.sh`` przez ``hr_schema_bundle``.
"""

from alembic import op

from app.services import equipment_protocol_cancel_schema as schema

revision = "0611_equipment_protocol_cancel"
down_revision = "0610_job_p0_request"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for stmt in schema.ALL_DDL:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in schema.DOWNGRADE_DDL:
        op.execute(stmt)
