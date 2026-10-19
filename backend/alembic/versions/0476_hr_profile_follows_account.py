"""„Ludzie w NEXUSIE” — kartoteka idzie za kontem (forma i przełożony „do uzupełnienia”).

Revision ID: 0476_hr_profile_follows_account
Revises: 0475_client_structure_proposals

Dwie kolumny ``employee_profiles``: ``employment_type_pending`` i
``created_from_account``. SQL ma jedno źródło
(``app/services/hr_account_profile_schema.py``) — ten sam moduł czyta
``entrypoint.sh`` przez ``hr_schema_bundle``.
"""

from alembic import op

from app.services import hr_account_profile_schema as schema

revision = "0476_hr_profile_follows_account"
down_revision = "0475_client_structure_proposals"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for stmt in schema.ALL_DDL:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in schema.DOWNGRADE_DDL:
        op.execute(stmt)
