"""Trzy nazwy rekrutacji: numer u klienta i tytuł dla rekrutera (25.09.2026).

Revision ID: 0380_job_client_reference_working_title
Revises: 0379_followup_teams_meetings

``jobs.title`` zostaje nazwą od klienta — idzie do klienta (CV, plik, Cpro)
i do wektora oferty, więc jego znaczenie się nie zmienia. Dochodzą:

* ``client_reference`` — numer zapytania klienta (ZOB, SAP, numer w Cpro);
  do 25.09 generator CV wyciągał go regexem z tytułu;
* ``working_title`` + ``working_title_auto`` — tytuł dla rekrutera
  („Java Developer · Java, Kafka · 5+ lat · Payments”) składany przez
  ``job_working_title`` z Championa; ręczna zmiana wyłącza automat.

Wartości istniejących rekrutacji uzupełnia jednorazowy krok w ``entrypoint.sh``
(``job_working_title.fill_missing_job_names``, marker w ``app_settings``) —
reguła składania jest w Pythonie. Lustro DDL w ``entrypoint.sh`` (prod
alembic bywa osierocony) — pilnuje ``test_job_working_title.py``.
"""

from alembic import op

revision = "0380_job_client_reference_working_title"
down_revision = "0379_followup_teams_meetings"
branch_labels = None
depends_on = None

ADD_COLUMNS = (
    "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS client_reference VARCHAR(120)",
    "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS working_title VARCHAR(255)",
    "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS working_title_auto "
    "BOOLEAN NOT NULL DEFAULT true",
)


def upgrade() -> None:
    for statement in ADD_COLUMNS:
        op.execute(statement)


def downgrade() -> None:
    for column in ("working_title_auto", "working_title", "client_reference"):
        op.execute(f"ALTER TABLE jobs DROP COLUMN IF EXISTS {column}")
    op.execute("DELETE FROM app_settings WHERE key = 'job_names_backfill_0380'")
