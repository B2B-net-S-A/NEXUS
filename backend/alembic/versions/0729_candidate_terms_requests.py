"""Prośby o warunki kandydata po aplikacji z ogłoszenia.

Revision ID: 0729_candidate_terms_requests
Revises: 0728_job_role_profiles

Decyzje Artura 16–17.11.2026: po aplikacji z portalu albo strony kariery
kandydat dostaje mail z podziękowaniem, a osoba z brakami w profilu (stawka,
tryb, biuro, start) także link do formularza warunków. Tabela trzyma kolejkę
wysyłki, skrót tokenu i ostatnią odpowiedź. DDL ma jedno źródło
(``app/services/candidate_terms_schema.py``); entrypoint wykonuje je przy
każdym starcie.
"""

from alembic import op

from app.services import candidate_terms_schema as schema

revision = "0729_candidate_terms_requests"
down_revision = "0728_job_role_profiles"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for stmt in schema.TABLE_DDL:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in schema.DOWNGRADE_DDL:
        op.execute(stmt)
