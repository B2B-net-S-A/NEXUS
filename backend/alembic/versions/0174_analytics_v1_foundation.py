"""Analytics v1 foundation — indeksy + kanoniczne SQL views (plan PR 2).

Addytywna migracja: żadnych zmian danych, żadnych DROP-ów istniejących
obiektów. Downgrade usuwa wyłącznie obiekty utworzone tutaj.

Views (zwykłe, NIE materialized — plan PR 2 pkt 5: materializacja dopiero
po pomiarze query plan/p95):
- analytics_current_pipeline      — ostatni stage per kandydat × job,
- analytics_first_milestones      — pierwsze osiągnięcie milestone'ów
  (verified/cv_sent/interview/client_interview/hired) per kandydat × job
  wraz z atrybucją (moved_by pierwszego przejścia),
- analytics_candidate_first_sources — pierwszy CandidateSourceEvent per
  kandydat (first-touch; fallback Candidate.source robi warstwa zapytań).

Lustro w backend/entrypoint.sh _COLUMN_STATEMENTS — prod ma chroniczny
multi-head i migracje bywają no-opem (patrz memory
entrypoint-safetynet-new-columns).

Revision ID: 0174_analytics_v1_foundation
Revises: 0173_traffit_bidirectional_persistence
"""

from alembic import op

revision = "0174_analytics_v1_foundation"
down_revision = "0173_traffit_bidirectional_persistence"
branch_labels = None
depends_on = None


_INDEXES = [
    # Ostatni stage per kandydat × job (DISTINCT ON ... ORDER BY moved_at DESC).
    (
        "ix_analytics_cs_cand_job_moved",
        "CREATE INDEX IF NOT EXISTS ix_analytics_cs_cand_job_moved "
        "ON candidate_stages (candidate_id, job_id, moved_at DESC, id DESC)",
    ),
    # Pierwsze milestone'y: partial per stage — window po (stage, cand, job).
    (
        "ix_analytics_cs_stage_first",
        "CREATE INDEX IF NOT EXISTS ix_analytics_cs_stage_first "
        "ON candidate_stages (stage, candidate_id, job_id, moved_at ASC, id ASC) "
        "WHERE stage IN "
        "('verified', 'cv_sent', 'interview', 'client_interview', 'hired')",
    ),
    # Rozmowy: completed po dacie efektywnej COALESCE(started_at, created_at).
    (
        "ix_analytics_calls_user_effective",
        "CREATE INDEX IF NOT EXISTS ix_analytics_calls_user_effective "
        "ON calls (user_id, status, (COALESCE(started_at, created_at)))",
    ),
    # First-touch źródła.
    (
        "ix_analytics_cse_first_touch",
        "CREATE INDEX IF NOT EXISTS ix_analytics_cse_first_touch "
        "ON candidate_source_events (candidate_id, captured_at ASC, id ASC)",
    ),
    # Date-effective kontrakty (aktywny dziś = start <= dziś < end/null).
    (
        "ix_analytics_contracts_dates",
        "CREATE INDEX IF NOT EXISTS ix_analytics_contracts_dates "
        "ON contracts (start_date, end_date)",
    ),
    # Wyniki przetargów.
    (
        "ix_analytics_jobs_close_reason",
        "CREATE INDEX IF NOT EXISTS ix_analytics_jobs_close_reason "
        "ON jobs (close_reason) WHERE close_reason IS NOT NULL",
    ),
]

# UWAGA: te definicje MUSZĄ być zsynchronizowane z entrypoint.sh
# _COLUMN_STATEMENTS (idempotentne CREATE OR REPLACE).
_VIEWS = {
    "analytics_current_pipeline": """
        CREATE OR REPLACE VIEW analytics_current_pipeline AS
        SELECT DISTINCT ON (candidate_id, job_id)
            candidate_id,
            job_id,
            stage,
            moved_at,
            moved_by,
            id AS candidate_stage_id
        FROM candidate_stages
        ORDER BY candidate_id, job_id, moved_at DESC, id DESC
    """,
    "analytics_first_milestones": """
        CREATE OR REPLACE VIEW analytics_first_milestones AS
        SELECT
            candidate_id,
            job_id,
            stage,
            moved_at AS first_reached_at,
            moved_by AS first_moved_by,
            id AS candidate_stage_id
        FROM (
            SELECT
                cs.candidate_id,
                cs.job_id,
                cs.stage,
                cs.moved_at,
                cs.moved_by,
                cs.id,
                ROW_NUMBER() OVER (
                    PARTITION BY cs.candidate_id, cs.job_id, cs.stage
                    ORDER BY cs.moved_at ASC, cs.id ASC
                ) AS rn
            FROM candidate_stages cs
            WHERE cs.stage IN (
                'verified', 'cv_sent', 'interview', 'client_interview', 'hired'
            )
        ) ranked
        WHERE rn = 1
    """,
    "analytics_candidate_first_sources": """
        CREATE OR REPLACE VIEW analytics_candidate_first_sources AS
        SELECT DISTINCT ON (candidate_id)
            candidate_id,
            channel,
            job_id,
            utm_source,
            utm_medium,
            utm_campaign,
            captured_at,
            id AS source_event_id
        FROM candidate_source_events
        ORDER BY candidate_id, captured_at ASC, id ASC
    """,
}


def upgrade() -> None:
    for _name, stmt in _INDEXES:
        op.execute(stmt)
    for _name, stmt in _VIEWS.items():
        op.execute(stmt)


def downgrade() -> None:
    for name in _VIEWS:
        op.execute(f"DROP VIEW IF EXISTS {name}")
    for name, _stmt in _INDEXES:
        op.execute(f"DROP INDEX IF EXISTS {name}")
