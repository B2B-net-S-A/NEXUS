"""Ekran Bezpieczeństwo: źródło ``defender`` (incydenty Microsoft Defendera).

Revision ID: 0808_security_defender_source
Revises: 0807_market_trainer_portal

Zlecenie Artura z 28.11.2026: incydent High z Defendera wisiał tydzień
nieprzypisany, bo nikt nie zagląda do portalu Microsoftu. NEXUS czyta
incydenty i Secure Score z Microsoft Graph co 15 min
(``services/security_defender.py``). Schemat: poszerzony CHECK ``source``
w ``security_findings`` i ``security_events`` oraz typ dzwonka
``security_defender_incident`` (tylko admini, mail od razu). Same dodania —
zgodne wstecz. DDL w ``app/services/security_schema.py``, lustro
w ``entrypoint.sh`` (``TABLE_DDL`` i ``_ENUM_STATEMENTS``).
"""

from alembic import op

from app.services import security_schema as schema

revision = "0808_security_defender_source"
down_revision = "0807_market_trainer_portal"
branch_labels = None
depends_on = None

ENUM_DDL = (
    "ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS 'security_defender_incident'"
)

# Kod sprzed tej rewizji nie zna źródła ani typu dzwonka, a Postgres nie ma
# `ALTER TYPE … DROP VALUE` — downgrade odmawia przy żywych wierszach.
REFUSE_WITH_DEFENDER_ROWS = """DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM security_findings WHERE source = 'defender')
       OR EXISTS (SELECT 1 FROM security_events WHERE source = 'defender')
       OR EXISTS (
           SELECT 1 FROM notifications
           WHERE notification_type::text = 'security_defender_incident'
       ) THEN
        RAISE EXCEPTION 'Downgrade 0808 odmawia: są wiersze źródła defender albo dzwonki security_defender_incident, których kod sprzed tej rewizji nie odczyta.';
    END IF;
END $$"""


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(ENUM_DDL)
    for statement in schema.source_check_ddl(schema.SOURCES):
        op.execute(statement)


def downgrade() -> None:
    op.execute(REFUSE_WITH_DEFENDER_ROWS)
    for statement in schema.source_check_ddl(schema.SOURCES_0802):
        op.execute(statement)
