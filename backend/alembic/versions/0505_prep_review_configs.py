"""Ustawienia oceny prepów — wersje i wersja przy ocenie (22.10.2026).

Revision ID: 0505_prep_review_configs
Revises: 0504_job_close_neutral

Tabela ``prep_review_configs``: każda publikacja ustawień z Ustawienia →
Ocena prepów (Head of Recruitment, admin) to nowy wiersz; obowiązuje
najnowszy. ``prep_reviews.config_version``: według której wersji powstała
ocena. DDL ma jedno źródło z siatką w ``entrypoint.sh``
(``services/prep_review_config_schema.py``).
"""

from alembic import op

from app.services.prep_review_config_schema import DOWNGRADE_DDL, TABLE_DDL

revision = "0505_prep_review_configs"
down_revision = "0504_job_close_neutral"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for statement in TABLE_DDL:
        op.execute(statement)


def downgrade() -> None:
    for statement in DOWNGRADE_DDL:
        op.execute(statement)
