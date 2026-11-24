"""Sprzedaż: przetargi z BZP i TED (decyzja Artura 24.11.2026, wariant B).

Revision ID: 0770_sales_tenders
Revises: 0769_client_playbook_prep_spec

NEXUS codziennie czyta ogłoszenia z BZP i TED, bramka z regułami Kingi zakłada
szansę w lejku Przetargi albo odsiewa ogłoszenie z regułą. Tabela trzyma
ogłoszenia, które przeszły frazy albo kody CPV usług IT. DDL w
``app/services/sales_schema.py``; ``entrypoint.sh`` wpina tę samą listę.
"""

from alembic import op

from app.services import sales_schema as schema

revision = "0770_sales_tenders"
down_revision = "0769_client_playbook_prep_spec"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for stmt in schema.TENDERS_DDL:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in schema.TENDERS_DOWNGRADE_DDL:
        op.execute(stmt)
