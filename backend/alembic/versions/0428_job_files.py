"""Pliki rekrutacji (09.10.2026).

Revision ID: 0428_job_files
Revises: 0427_user_email_opt_outs

Delivery Lead dokłada pliki przy zakładaniu rekrutacji (request klienta,
załączniki), a zespół widzi je potem w menu „⋯” rekrutacji. Do tej daty plik
requestu z kroku 1 był czytany i odrzucany — nie było go gdzie zapisać.

SQL ma jedno źródło (``app/services/job_file_schema.py``) — te same instrukcje
stoją dosłownie w ``entrypoint.sh``.
"""

from alembic import op

from app.services import job_file_schema as schema

revision = "0428_job_files"
down_revision = "0427_user_email_opt_outs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for stmt in schema.ALL_DDL:
        op.execute(stmt)


def downgrade() -> None:
    # Pliki na dysku zostają (wolumen `uploads_data`); znikają tylko wiersze.
    bind = op.get_bind()
    if bind.exec_driver_sql("SELECT 1 FROM job_files LIMIT 1").first() is not None:
        raise RuntimeError(
            "job_files zawiera pliki rekrutacji — downgrade skasowałby ich "
            "rejestr. Usuń wiersze świadomie albo zostań przy 0428."
        )
    for stmt in schema.DOWNGRADE_DDL:
        op.execute(stmt)
