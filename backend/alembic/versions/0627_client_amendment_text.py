"""Treść aneksów do umów ramowych dla Jarvisa (30.10.2026).

Revision ID: 0627_client_amendment_text
Revises: 0626_client_cover_sheet_templates

Umowa bywa przedłużona samym aneksem, a Jarvis czytał tylko umowy. Fragment
aneksu leży w ``client_framework_contract_chunks`` (``amendment_id``), a kolumny
``client_contract_amendments.text_*`` trzymają stan odczytu pliku.

SQL ma jedno źródło (``app/services/framework_contract_text_schema.py``) — ten
sam moduł importuje ``entrypoint.sh``.
"""

from alembic import op

from app.services import framework_contract_text_schema as schema

revision = "0627_client_amendment_text"
down_revision = "0626_client_cover_sheet_templates"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for stmt in schema.AMENDMENT_ALL_DDL:
        op.execute(stmt)


def downgrade() -> None:
    # Fragmenty są danymi pochodnymi — odbudowuje je odczyt pliku.
    for stmt in schema.AMENDMENT_DOWNGRADE_DDL:
        op.execute(stmt)
