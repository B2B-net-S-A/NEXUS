"""DDL automatu przydziału requestów (0371) — jedno źródło dla migracji.

``entrypoint.sh`` (``_COLUMN_STATEMENTS``) niesie te same instrukcje dosłownie,
bo alembic na produkcji bywa osierocony; ``test_request_allocation_schema.py``
pilnuje, że żadna nie zginęła po drodze.
"""

from __future__ import annotations

WORK_STATES = ("to_review", "searching", "client_silent", "finished")

COLUMN_STATEMENTS: tuple[str, ...] = (
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS allocation_excluded "
    "BOOLEAN NOT NULL DEFAULT false",
    "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS work_state VARCHAR(20) "
    "NOT NULL DEFAULT 'to_review'",
    "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS work_state_changed_at TIMESTAMPTZ NULL",
    "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS work_state_changed_by INTEGER NULL "
    "REFERENCES users(id) ON DELETE SET NULL",
    """DO $$ BEGIN
    ALTER TABLE jobs ADD CONSTRAINT ck_jobs_work_state
        CHECK (work_state IN ('to_review', 'searching', 'client_silent', 'finished'));
EXCEPTION WHEN duplicate_object THEN NULL; END $$""",
    "CREATE INDEX IF NOT EXISTS ix_jobs_work_state ON jobs (work_state)",
    """CREATE TABLE IF NOT EXISTS job_work_assignments (
    id SERIAL PRIMARY KEY,
    job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role VARCHAR(20) NOT NULL,
    source VARCHAR(20) NOT NULL,
    state VARCHAR(20) NOT NULL,
    assigned_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    assigned_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    released_at TIMESTAMPTZ NULL,
    release_reason VARCHAR(40) NULL,
    CONSTRAINT ck_job_work_assignments_role CHECK (role IN ('recruiter', 'sourcer')),
    CONSTRAINT ck_job_work_assignments_source CHECK (source IN ('auto', 'manual', 'owner')),
    CONSTRAINT ck_job_work_assignments_state
        CHECK (state IN ('proposed', 'active', 'released'))
)""",
    "CREATE INDEX IF NOT EXISTS ix_job_work_assignments_job_id "
    "ON job_work_assignments (job_id)",
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_job_work_assignments_live "
    "ON job_work_assignments (job_id, user_id) WHERE state <> 'released'",
    "CREATE INDEX IF NOT EXISTS ix_job_work_assignments_user_state "
    "ON job_work_assignments (user_id, state)",
    "CREATE INDEX IF NOT EXISTS ix_job_work_assignments_changed "
    "ON job_work_assignments (assigned_at, released_at)",
)

# Stan startowy: rekrutacje przekazane w NEXUSIE do searchu (`is_open`) już
# są w pracy, zamknięte są zakończone. Reszta (setki rekrutacji z Traffita,
# których nikt tam nie zamyka) czeka na decyzję DL w „Porządku w requestach”.
# Warunek na `to_review` sprawia, że ponowny przebieg niczego nie nadpisze.
INITIAL_STATE_STATEMENTS: tuple[str, ...] = (
    "UPDATE jobs SET work_state = 'finished' "
    "WHERE work_state = 'to_review' AND status = 'closed'",
    "UPDATE jobs SET work_state = 'searching' "
    "WHERE work_state = 'to_review' AND status = 'published' AND is_open",
)

ENUM_STATEMENTS: tuple[str, ...] = (
    "ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS 'request_assignment_changed'",
    "ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS 'request_review_needed'",
)

INITIAL_STATE_MARKER = "request_work_state_initial_2026_09"


async def run_initial_work_states(db) -> bool:
    """Jednorazowe ustawienie stanów startowych. ``False`` = już zrobione.

    Wołający commituje. Znacznik w ``app_settings`` — drugi start nic nie robi,
    więc późniejsze decyzje DL nie są nadpisywane regułą startową.
    """
    from sqlalchemy import text  # noqa: PLC0415

    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:k))"),
        {"k": INITIAL_STATE_MARKER},
    )
    done = await db.execute(
        text("SELECT 1 FROM app_settings WHERE key = :k"),
        {"k": INITIAL_STATE_MARKER},
    )
    if done.scalar() is not None:
        return False
    for statement in INITIAL_STATE_STATEMENTS:
        await db.execute(text(statement))
    await db.execute(
        text(
            "INSERT INTO app_settings (key, value, updated_at) "
            "VALUES (:k, CAST('{}' AS jsonb), now()) ON CONFLICT (key) DO NOTHING"
        ),
        {"k": INITIAL_STATE_MARKER},
    )
    return True
