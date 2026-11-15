"""DDL zespołu dla klienta (0709) — jedno źródło dla migracji i ``entrypoint.sh``.

Zespół to pojemnik na kilka zwykłych rekrutacji jednego klienta i jeden link
dla klienta na cały skład (``docs/claude/klienci/zespol-dla-klienta.md``).
Nie jest typem rekrutacji. Link domyślnie wyłączony.

- ``job_teams``: zespół; w bazie tylko skrót tokenu linku.
- ``jobs.team_id``: rekrutacja należy najwyżej do jednego zespołu.
- ``job_team_selections``: skład wybrany przez klienta pod linkiem. Autor jest
  niezweryfikowany, IP tylko jako skrót z solą dnia.
"""

TABLE_DDL = (
    """CREATE TABLE IF NOT EXISTS job_teams (
        id SERIAL PRIMARY KEY,
        client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
        name VARCHAR(160) NOT NULL,
        panel_enabled BOOLEAN NOT NULL DEFAULT FALSE,
        panel_show_rate BOOLEAN NOT NULL DEFAULT TRUE,
        panel_expires_at TIMESTAMPTZ NULL,
        panel_token_nonce VARCHAR(32) NULL,
        panel_token_sha256 VARCHAR(64) NULL,
        created_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )""",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_job_teams_panel_token "
    "ON job_teams (panel_token_sha256) WHERE panel_token_sha256 IS NOT NULL",
    "CREATE INDEX IF NOT EXISTS ix_job_teams_client_id ON job_teams (client_id)",
    # ORM czyta tę kolumnę przy KAŻDYM zapytaniu o rekrutację: lustro
    # w entrypoincie jest tu wdrożeniem, nie dodatkiem.
    "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS team_id INTEGER NULL "
    "REFERENCES job_teams(id) ON DELETE SET NULL",
    "CREATE INDEX IF NOT EXISTS ix_jobs_team_id ON jobs (team_id)",
    """CREATE TABLE IF NOT EXISTS job_team_selections (
        id SERIAL PRIMARY KEY,
        team_id INTEGER NOT NULL REFERENCES job_teams(id) ON DELETE CASCADE,
        picks JSONB NOT NULL DEFAULT '[]'::jsonb,
        author_name VARCHAR(120) NOT NULL,
        author_email VARCHAR(255) NOT NULL,
        note VARCHAR(2000) NULL,
        ip_hash VARCHAR(64) NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )""",
    "CREATE INDEX IF NOT EXISTS ix_job_team_selections_team_created "
    "ON job_team_selections (team_id, created_at)",
)

DOWNGRADE_DDL = (
    "DROP TABLE IF EXISTS job_team_selections",
    "DROP INDEX IF EXISTS ix_jobs_team_id",
    "ALTER TABLE jobs DROP COLUMN IF EXISTS team_id",
    "DROP TABLE IF EXISTS job_teams",
)
