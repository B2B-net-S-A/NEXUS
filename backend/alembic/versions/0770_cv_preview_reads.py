"""Odczyt CV z podglądu „Dodaj kandydata” w bazie zamiast w pamięci procesu.

Revision ID: 0770_cv_preview_reads
Revises: 0769_client_playbook_prep_spec

Przy dwóch procesach web (``NEXUS_WEB_CONCURRENCY=2``, #3857) ``/from-cv``, który
trafił do innego procesu niż ``/cv/preview``, nie miał odczytu: czytał CV modelem
drugi raz i mógł zapisać inny odczyt niż ten, który rekruter widział w formularzu.
Tabela ``cv_preview_reads`` jest wspólna dla procesów. DDL
w ``app/services/cv_preview_reads_schema.py``, lustro w ``entrypoint.sh``.
Samo dodanie — stary kod tabeli nie zna.
"""

from alembic import op

from app.services.cv_preview_reads_schema import TABLE_DDL

revision = "0770_cv_preview_reads"
down_revision = "0769_client_playbook_prep_spec"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for statement in TABLE_DDL:
        op.execute(statement)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS cv_preview_reads")
