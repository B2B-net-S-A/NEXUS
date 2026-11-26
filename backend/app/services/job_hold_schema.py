"""DDL stanu „Wstrzymana” (0796) — jedno źródło dla migracji i ``entrypoint.sh``.

``entrypoint.sh`` niesie te same instrukcje dosłownie (alembic na produkcji
bywa osierocony, entrypoint jest wtedy wdrożeniem); pilnuje
``tests/test_job_hold.py``. CHECK ``ck_jobs_work_state`` z 0371 nie znał
``on_hold`` — zapis stanu dałby ``IntegrityError``. Wymiana tylko wtedy, gdy
CHECK jeszcze go nie zna, więc kolejny start nie blokuje tabeli ``jobs``.
"""

from __future__ import annotations

WORK_STATES_0793 = ("to_review", "searching", "client_silent", "on_hold", "finished")

ENUM_STATEMENTS: tuple[str, ...] = (
    "ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS 'job_hold_changed'",
    "ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS 'job_hold_check'",
)

COLUMN_STATEMENTS: tuple[str, ...] = (
    "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS hold_reason TEXT NULL",
    "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS hold_review_on DATE NULL",
    "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS hold_ended_at TIMESTAMPTZ NULL",
    """DO $$ BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM pg_constraint
            WHERE conname = 'ck_jobs_work_state'
              AND pg_get_constraintdef(oid) LIKE '%on_hold%'
        ) THEN
            ALTER TABLE jobs DROP CONSTRAINT IF EXISTS ck_jobs_work_state;
            ALTER TABLE jobs ADD CONSTRAINT ck_jobs_work_state CHECK (work_state IN ('to_review', 'searching', 'client_silent', 'on_hold', 'finished'));
        END IF;
    END $$""",
)
