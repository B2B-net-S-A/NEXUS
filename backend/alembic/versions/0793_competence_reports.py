"""Raporty kompetencji w 24 godziny i lista opiekunów.

Revision ID: 0793_competence_reports
Revises: 0792_cv_page1_highlight_ai

Decyzje Artura 25.11.2026: osoba, która wyśle z nowej strony CV razem
z warunkami (``report=1``), dostaje w 24 godziny raport e-mailem. Tabela
``competence_reports`` trzyma stan raportu, warunki, snapshot, termin wysyłki,
opiekuna i skrót tokenu; ``competence_report_owners`` to lista rekruterów,
między których raporty idą po kolei. DDL ma jedno źródło
(``app/services/competence_report_ddl.py``); entrypoint wykonuje je przy
każdym starcie.
"""

from alembic import op

from app.services import competence_report_ddl as schema

revision = "0793_competence_reports"
down_revision = "0792_cv_page1_highlight_ai"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for stmt in schema.TABLE_DDL:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in schema.DOWNGRADE_DDL:
        op.execute(stmt)
