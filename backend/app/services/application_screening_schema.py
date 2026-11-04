"""DDL oceny zgłoszeń z linku rekrutacji — JEDNO źródło dla migracji 0404
i ``entrypoint.sh``.

Produkcyjny alembic bywa osierocony, więc siatka w ``entrypoint.sh`` jest
wdrożeniem równorzędnym z migracją. Obie strony importują listy stąd.
Wartość enumu AI (``application_screening``), jej wiersz w ``ai_features``
i typ powiadomienia (``application_screening_digest``) stoją w entrypoincie
literalnie — pilnują ich ``test_ai_feature_enum_entrypoint_mirror`` oraz
``test_application_screening_migration_mirror``.
"""

from __future__ import annotations

STATUSES = ("pending", "done", "failed")
VERDICTS = ("fits", "unclear", "not_fit")
OUTCOMES = (
    "pending",
    "added",
    "screened_out",
    "blocked",
    "already_in_job",
    "job_closed",
)


def _in(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


TABLE_DDL: list[str] = [
    f"""CREATE TABLE IF NOT EXISTS application_screenings (
           id BIGSERIAL PRIMARY KEY,
           submission_id INTEGER NULL
               REFERENCES application_submissions(id) ON DELETE CASCADE,
           candidate_id INTEGER NOT NULL REFERENCES candidates(id) ON DELETE CASCADE,
           job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
           status VARCHAR(16) NOT NULL DEFAULT 'pending',
           verdict VARCHAR(16) NULL,
           outcome VARCHAR(20) NOT NULL DEFAULT 'pending',
           must_found INTEGER NULL,
           must_total INTEGER NULL,
           reasons JSONB NULL,
           model VARCHAR(80) NULL,
           error VARCHAR(120) NULL,
           attempts INTEGER NOT NULL DEFAULT 0,
           claimed_until TIMESTAMPTZ NULL,
           cv_text TEXT NULL,
           context JSONB NOT NULL DEFAULT '{{}}'::jsonb,
           created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
           decided_at TIMESTAMPTZ NULL,
           digested_at TIMESTAMPTZ NULL,
           overridden_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
           overridden_at TIMESTAMPTZ NULL,
           CONSTRAINT ck_application_screenings_status
               CHECK (status IN ({_in(STATUSES)})),
           CONSTRAINT ck_application_screenings_verdict
               CHECK (verdict IS NULL OR verdict IN ({_in(VERDICTS)})),
           CONSTRAINT ck_application_screenings_outcome
               CHECK (outcome IN ({_in(OUTCOMES)}))
       )""",
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_application_screenings_submission "
    "ON application_screenings (submission_id) WHERE submission_id IS NOT NULL",
    "CREATE INDEX IF NOT EXISTS ix_application_screenings_job_outcome "
    "ON application_screenings (job_id, outcome)",
    "CREATE INDEX IF NOT EXISTS ix_application_screenings_candidate "
    "ON application_screenings (candidate_id)",
    "CREATE INDEX IF NOT EXISTS ix_application_screenings_pending "
    "ON application_screenings (created_at) WHERE status = 'pending'",
]

DROP_DDL: list[str] = ["DROP TABLE IF EXISTS application_screenings"]
