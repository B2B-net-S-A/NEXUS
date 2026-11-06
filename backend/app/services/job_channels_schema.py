"""DDL koszyków „Baza” / „LinkedIn” w zespole rekrutacji (0655, 06.11.2026).

Jedno źródło SQL dla migracji ``0655_job_recruiter_channels`` i lustra
w ``entrypoint.sh`` (alembic na produkcji bywa osierocony). Opis reguły:
``docs/claude/rekrutacja-tablica/koszyki-baza-linkedin-w-zespole.md``.

* ``job_recruiter_channels`` — w którym koszyku osoba pracuje przy danej
  rekrutacji. Osobno od trzech źródeł „Rekrutera” (prowadzący, przypisanie,
  dopisany), bo zamiana prowadzącego albo akceptacja propozycji nie może
  zgubić koszyka. Wiersz osoby spoza zespołu nic nie znaczy (ekrany czytają
  koszyk tylko przy osobach z ``job_team.recruiters_for_jobs``).
* ``jobs.channel_plan_base`` / ``channel_plan_linkedin`` — plan Olafa/DL:
  ile osób ma pracować w koszyku. ``NULL`` = bez planu.
"""

TABLES = ("job_recruiter_channels",)

ALL_DDL: tuple[str, ...] = (
    "CREATE TABLE IF NOT EXISTS job_recruiter_channels ("
    " id SERIAL PRIMARY KEY,"
    " job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,"
    " user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,"
    " channel VARCHAR(10) NOT NULL"
    "  CONSTRAINT ck_job_recruiter_channels_channel CHECK (channel IN ('base', 'linkedin')),"
    " set_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,"
    " set_at TIMESTAMPTZ NOT NULL DEFAULT now(),"
    " CONSTRAINT uq_job_recruiter_channels_job_user UNIQUE (job_id, user_id))",
    "CREATE INDEX IF NOT EXISTS ix_job_recruiter_channels_job_id"
    " ON job_recruiter_channels (job_id)",
    "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS channel_plan_base SMALLINT NULL",
    "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS channel_plan_linkedin SMALLINT NULL",
)

DOWNGRADE_DDL: tuple[str, ...] = (
    "ALTER TABLE jobs DROP COLUMN IF EXISTS channel_plan_linkedin",
    "ALTER TABLE jobs DROP COLUMN IF EXISTS channel_plan_base",
)
