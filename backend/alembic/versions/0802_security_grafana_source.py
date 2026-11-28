"""Ekran Bezpieczeństwo: źródło ``grafana`` (alerty Grafany Cloud).

Revision ID: 0802_security_grafana_source
Revises: 0801_b2b_krz_check

Zlecenie Artura z 28.11.2026: alerty z Grafany Cloud trafiają do ekranu
Bezpieczeństwo przez ``POST /api/security/ingest/grafana``. Jedyna zmiana
schematu to poszerzony CHECK ``source`` w ``security_findings`` i
``security_events`` — zgodne wstecz. DDL w ``app/services/security_schema.py``,
lustro w ``entrypoint.sh`` (``TABLE_DDL``).
"""

from alembic import op

from app.services import security_schema as schema

revision = "0802_security_grafana_source"
down_revision = "0801_b2b_krz_check"
branch_labels = None
depends_on = None

REFUSE_WITH_GRAFANA_ROWS = """DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM security_findings WHERE source = 'grafana')
       OR EXISTS (SELECT 1 FROM security_events WHERE source = 'grafana') THEN
        RAISE EXCEPTION 'Downgrade 0802 odmawia: są wiersze źródła grafana, których CHECK sprzed tej rewizji nie przepuści.';
    END IF;
END $$"""


def upgrade() -> None:
    for statement in schema.source_check_ddl(schema.SOURCES):
        op.execute(statement)


def downgrade() -> None:
    op.execute(REFUSE_WITH_GRAFANA_ROWS)
    for statement in schema.source_check_ddl(schema.SOURCES_0800):
        op.execute(statement)
