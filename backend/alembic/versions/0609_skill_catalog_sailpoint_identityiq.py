"""Słownik umiejętności: SailPoint IdentityIQ (= „SailPoint IIQ”, „IIQ”).

Revision ID: 0609_skill_catalog_identityiq
Revises: 0608_linkedin_extension

Zgłoszenie z 28.10.2026 (rekrutacja 789171): krytyczne „SailPoint IIQ” ze
słowem wiersza „IIQ” ukryło w nocnym przeglądzie 111 osób, które w CV piszą
„SailPoint IdentityIQ”. Pozycja żyje w ``app/data/skill_catalog_tools.json``;
zasiew jest ten sam co w 0397 (tylko dokłada, niczego nie nadpisuje).
Downgrade usuwa tylko tę pozycję (aliasy kaskadą).
"""

from alembic import op
from sqlalchemy import text

from app.services import skill_catalog_tools as tools

revision = "0609_skill_catalog_identityiq"
down_revision = "0608_linkedin_extension"
branch_labels = None
depends_on = None

NAME = "SailPoint IdentityIQ"


def upgrade() -> None:
    tools.seed(op.get_bind())


def downgrade() -> None:
    op.get_bind().execute(
        text("DELETE FROM skills WHERE canonical_name = :n AND category = 'tools'"),
        {"n": NAME},
    )
