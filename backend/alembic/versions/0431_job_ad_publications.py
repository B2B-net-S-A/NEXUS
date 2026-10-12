"""Oznaczenie „ogłoszenie opublikowane” na Pracuj.pl i JustJoin.IT (13.10.2026).

Revision ID: 0431_job_ad_publications
Revises: 0430_job_ads

Etap 2 ogłoszeń na portale: rekruter po wklejeniu treści oznacza, że
ogłoszenie wisi (z linkiem), a lista rekrutacji pokazuje to w kolumnie
„Ogłoszenia”.

SQL ma jedno źródło (``app/services/job_ad_publication_schema.py``) — te same
instrukcje stoją dosłownie w ``entrypoint.sh``.
"""

from alembic import op

from app.services import job_ad_publication_schema as schema

revision = "0431_job_ad_publications"
down_revision = "0430_job_ads"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for stmt in schema.ALL_DDL:
        op.execute(stmt)


def downgrade() -> None:
    bind = op.get_bind()
    if (
        bind.exec_driver_sql("SELECT 1 FROM job_ad_publications LIMIT 1").first()
        is not None
    ):
        raise RuntimeError(
            "job_ad_publications zawiera oznaczone publikacje — downgrade by je "
            "skasował. Usuń wiersze świadomie albo zostań przy 0431."
        )
    for stmt in schema.DOWNGRADE_DDL:
        op.execute(stmt)
