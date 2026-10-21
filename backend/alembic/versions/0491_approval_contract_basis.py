"""„Ludzie w NEXUSIE” — podstawa w umowie przy premii poza umową (decyzja Artura 21.10.2026).

Revision ID: 0491_approval_contract_basis
Revises: 0490_board_role

Kolumna ``approval_requests.contract_basis`` (punkt umowy albo numer aneksu)
i CHECK, że podstawa jest tylko przy premii. SQL ma jedno źródło
(``app/services/hr_approval_basis_schema.py``) — ten sam moduł czyta
``entrypoint.sh`` przez ``hr_schema_bundle``.
"""

from alembic import op

from app.services import hr_approval_basis_schema as schema

revision = "0491_approval_contract_basis"
down_revision = "0490_board_role"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for stmt in schema.ALL_DDL:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in schema.DOWNGRADE_DDL:
        op.execute(stmt)
