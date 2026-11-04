"""Rekrutacje sprzed startu NEXUSA do archiwum (decyzja Artura 25.09.2026).

Revision ID: 0378_archive_jobs_before_nexus_start
Revises: 0377_traffit_jobs_archive

Jednorazowo zamyka („Zakończona”) każdą rekrutację założoną przed 25.09.2026,
także założoną ręcznie w NEXUSIE — od tego dnia otwarte są tylko rekrutacje
zakładane przez Delivery Leadów w NEXUSIE. `closed_at` się nie zmienia.
SQL: `services/job_archive_cutover.py`, lustro w `entrypoint.sh` (znacznik
w `app_settings` — drugi przebieg nic nie robi).

Bez zmiany schematu.
"""

from alembic import op

from app.services.job_archive_cutover import ARCHIVE_JOBS_BEFORE_NEXUS_START_SQL

revision = "0378_archive_jobs_before_nexus_start"
down_revision = "0377_traffit_jobs_archive"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(ARCHIVE_JOBS_BEFORE_NEXUS_START_SQL)


def downgrade() -> None:
    # Świadomie bez cofania: rekrutację otwiera się z powrotem w aplikacji
    # („Opublikuj”); lista zamkniętych jest w `activities` (action='archived').
    pass
