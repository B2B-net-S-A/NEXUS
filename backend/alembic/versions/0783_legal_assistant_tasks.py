"""Zadania asystenta prawnego — stan „załatwione / odrzucone” (część F, 25.11.2026).

Revision ID: 0783_legal_assistant_tasks
Revises: 0782_contract_document_chunks

Tabela ``legal_assistant_tasks``: zadania z paska asystenta (lista kontraktów,
strona kontraktu), które ktoś zamknął — zatwierdzonym pismem albo „Pomiń”.
Same zadania liczą dostawcy przy odczycie. Same dodania — stary kod działa
na nowym schemacie. DDL ma jedno źródło z siatką w ``entrypoint.sh``
(``services/legal/tasks_schema.py``).
"""

from alembic import op

from app.services.legal.tasks_schema import ALL_DDL, DOWNGRADE_DDL

revision = "0783_legal_assistant_tasks"
down_revision = "0782_contract_document_chunks"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for statement in ALL_DDL:
        op.execute(statement)


def downgrade() -> None:
    for statement in DOWNGRADE_DDL:
        op.execute(statement)
