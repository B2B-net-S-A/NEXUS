"""Powody „co generator zrobił źle” przy pobraniu oryginału CV.

Revision ID: 0630_cv_generator_feedback
Revises: 0629_company_results_permission

Decyzja Artura 02.11.2026: osoba z samą rolą rekrutera pobiera oryginał CV tylko
po złym wyniku generatora i podaje powód. SQL tabeli ma jedno źródło
(``app/services/cv_generator_feedback_schema.py``); entrypoint wykonuje
``TABLE_DDL`` przy każdym starcie.
"""

from alembic import op

from app.services import cv_generator_feedback_schema as schema

revision = "0630_cv_generator_feedback"
down_revision = "0629_company_results_permission"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for stmt in schema.TABLE_DDL:
        op.execute(stmt)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS cv_generator_feedback")
