"""Ogłoszenia ze strefy Pracuj.pl i aplikacje na nie (parowanie z rekrutacją).

Revision ID: 0754_pracuj_ads
Revises: 0753_cv_layout

SQL i powody: ``app/services/pracuj_ad_schema.py`` (to samo źródło czyta
``entrypoint.sh``).
"""

from alembic import op

from app.services import pracuj_ad_schema as schema

revision = "0754_pracuj_ads"
down_revision = "0753_cv_layout"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for stmt in schema.ALL_DDL:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in schema.DOWNGRADE_DDL:
        op.execute(stmt)
