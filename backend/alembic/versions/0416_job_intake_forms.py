"""Niedokończone formularze „Nowa rekrutacja” na koncie autora.

Revision ID: 0416_job_intake_forms
Revises: 0415_job_required_decisions

Od 04.10.2026 rekrutacja nigdy nie jest szkicem (utworzenie = przekazanie =
publikacja). Formularz, którego Delivery Lead nie skończył, zapisuje się na
jego koncie w ``job_intake_forms`` i znika po 30 dniach bez zmian.

SQL ma jedno źródło (``app/services/job_intake_form_schema.py``) — to samo
czyta lustro w ``entrypoint.sh``.
"""

from alembic import op

from app.services import job_intake_form_schema as schema

revision = "0416_job_intake_forms"
down_revision = "0415_job_required_decisions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(schema.TABLE_DDL)
    op.execute(schema.INDEX_DDL)


def downgrade() -> None:
    # Formularz to praca człowieka, której nie ma nigdzie indziej.
    bind = op.get_bind()
    count = bind.exec_driver_sql("SELECT count(*) FROM job_intake_forms").scalar()
    if count:
        raise RuntimeError(
            f"job_intake_forms ma {count} niedokończonych formularzy — "
            "downgrade skasowałby je bez śladu."
        )
    op.execute("DROP TABLE IF EXISTS job_intake_forms")
