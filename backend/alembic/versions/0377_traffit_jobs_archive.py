"""Rekrutacje z Traffita są w NEXUSIE archiwum (decyzja Artura 24.09.2026).

Revision ID: 0377_traffit_jobs_archive
Revises: 0376_job_delivery_lead_auto_filled

Od 25.09.2026 Delivery Leadzi zakładają rekrutacje w NEXUSIE. Każda rekrutacja
z Traffita (poza przełączonymi „Prowadzona w NEXUSIE”) zostaje zamknięta
i „Zakończona” — nie ma jej w otwartych listach i automatach, ale zostaje
źródłem podobnych rekrutacji, przepięć i profili Championa. Ten sam SQL
(`services/traffit_job_archive.ARCHIVE_TRAFFIT_JOBS_SQL`) wykonuje nocny import
po każdej fazie rekrutacji, więc migracja jest tylko pierwszym przebiegiem.
`closed_at` się nie zmienia — hit ratio liczy daty zamknięcia z Traffita.

Bez zmiany schematu. Lustro w `entrypoint.sh` pilnuje
`test_traffit_job_archive.py`.
"""

from alembic import op

from app.services.traffit_job_archive import ARCHIVE_TRAFFIT_JOBS_SQL

revision = "0377_traffit_jobs_archive"
down_revision = "0376_job_delivery_lead_auto_filled"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(ARCHIVE_TRAFFIT_JOBS_SQL)


def downgrade() -> None:
    # Świadomie bez cofania: nie wiadomo, które rekrutacje były otwarte przed
    # archiwizacją (stan z Traffita jest w `custom_fields.traffit_status`
    # dopiero od kolejnego importu).
    pass
