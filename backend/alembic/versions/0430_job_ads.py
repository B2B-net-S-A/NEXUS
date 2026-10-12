"""Ogłoszenie rekrutacji do wklejenia na portale (12.10.2026).

Revision ID: 0430_job_ads
Revises: 0429_recruiter_member_backfill

Rekruter generuje treść ogłoszenia z Profilu Championa i kopiuje ją do
Pracuj.pl oraz JustJoin.IT. Do tej daty „Szkic ogłoszenia” był szablonem
bez modelu i niczego nie zapisywał.

SQL ma jedno źródło (``app/services/job_ad_schema.py``) — te same instrukcje
stoją dosłownie w ``entrypoint.sh``.
"""

from alembic import op

from app.services import job_ad_schema as schema

revision = "0430_job_ads"
down_revision = "0429_recruiter_member_backfill"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for stmt in schema.ALL_DDL:
        op.execute(stmt)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.exec_driver_sql("SELECT 1 FROM job_ads LIMIT 1").first() is not None:
        raise RuntimeError(
            "job_ads zawiera przygotowane ogłoszenia — downgrade by je skasował. "
            "Usuń wiersze świadomie albo zostań przy 0430."
        )
    for stmt in schema.DOWNGRADE_DDL:
        op.execute(stmt)
