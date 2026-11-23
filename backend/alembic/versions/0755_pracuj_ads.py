"""Ogłoszenia ze strefy Pracuj.pl i aplikacje na nie (parowanie z rekrutacją).

Revision ID: 0755_pracuj_ads
Revises: 0754_b2b_signing_accept_code

SQL i powody: ``app/services/pracuj_ad_schema.py`` (to samo źródło czyta
``entrypoint.sh``).
"""

from alembic import op

from app.services import pracuj_ad_schema as schema

revision = "0755_pracuj_ads"
down_revision = "0754_b2b_signing_accept_code"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for stmt in schema.ALL_DDL:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in schema.DOWNGRADE_DDL:
        op.execute(stmt)
