"""DDL „Kto już to robił” — JEDNO źródło dla migracji 0678 i siatki
w ``entrypoint.sh`` (produkcyjny alembic bywa osierocony).

``duty_search_runs``: jedno wyszukiwanie po celu projektu albo obowiązkach
(decyzja Artura 09.11.2026, reguła
``docs/claude/kandydaci-wyszukiwanie/kto-juz-to-robil-wyszukiwanie-po-celu.md``).
``plan`` to rozbicie celu przez AI (zdolności, sygnały, przykładowe akapity CV),
``metrics`` liczniki i czasy. ``error_code`` to kod przyczyny, nigdy treść
odpowiedzi modelu.

``duty_search_results``: osoba oceniona w przebiegu. Osobna tabela z FK do
kandydata (``ON DELETE CASCADE``), bo wynik niesie cytaty z CV — twarde
usunięcie osoby (RODO) usuwa je razem z nią, czego JSON w przebiegu by nie dał.
"""

from __future__ import annotations

TABLE_DDL: list[str] = [
    """CREATE TABLE IF NOT EXISTS duty_search_runs (
           id VARCHAR(36) PRIMARY KEY,
           created_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
           client_id INTEGER NULL REFERENCES clients(id) ON DELETE SET NULL,
           job_id INTEGER NULL REFERENCES jobs(id) ON DELETE SET NULL,
           goal_title VARCHAR(300) NULL,
           goal_text TEXT NOT NULL,
           state VARCHAR(20) NOT NULL DEFAULT 'queued',
           plan JSONB NULL,
           metrics JSONB NOT NULL DEFAULT '{}'::jsonb,
           error_code VARCHAR(60) NULL,
           lease_expires_at TIMESTAMPTZ NULL,
           started_at TIMESTAMPTZ NULL,
           completed_at TIMESTAMPTZ NULL,
           created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
           updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
           CONSTRAINT ck_duty_search_runs_state
               CHECK (state IN ('queued', 'running', 'complete', 'failed'))
       )""",
    """CREATE INDEX IF NOT EXISTS ix_duty_search_runs_user_day
           ON duty_search_runs (created_by, created_at)""",
    """CREATE INDEX IF NOT EXISTS ix_duty_search_runs_job
           ON duty_search_runs (job_id, created_at DESC)""",
    """CREATE INDEX IF NOT EXISTS ix_duty_search_runs_active
           ON duty_search_runs (created_at) WHERE state IN ('queued', 'running')""",
    """CREATE TABLE IF NOT EXISTS duty_search_results (
           run_id VARCHAR(36) NOT NULL REFERENCES duty_search_runs(id) ON DELETE CASCADE,
           candidate_id INTEGER NOT NULL REFERENCES candidates(id) ON DELETE CASCADE,
           position INTEGER NOT NULL,
           tier VARCHAR(20) NOT NULL,
           confidence SMALLINT NULL,
           fit_score REAL NULL,
           from_goal_only BOOLEAN NOT NULL DEFAULT FALSE,
           assessment JSONB NOT NULL DEFAULT '{}'::jsonb,
           feedback VARCHAR(8) NULL,
           feedback_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
           feedback_at TIMESTAMPTZ NULL,
           PRIMARY KEY (run_id, candidate_id),
           CONSTRAINT ck_duty_search_results_tier
               CHECK (tier IN ('zrobil_to', 'bardzo_blisko', 'ma_klocki', 'brak')),
           CONSTRAINT ck_duty_search_results_feedback
               CHECK (feedback IS NULL OR feedback IN ('up', 'down'))
       )""",
    """CREATE INDEX IF NOT EXISTS ix_duty_search_results_candidate
           ON duty_search_results (candidate_id)""",
]

DOWNGRADE_DDL: list[str] = [
    "DROP TABLE IF EXISTS duty_search_results",
    "DROP TABLE IF EXISTS duty_search_runs",
]
