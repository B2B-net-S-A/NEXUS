"""Append-only matching telemetry — impressions + outcomes (plan PR2).

Revision ID: 0169_match_telemetry
Revises: 0168_cortex_curation_audit
Create Date: 2026-07-15

Two immutable analytics logs (no FKs — decoupled from operational deletes,
purged by a separate retention/DSAR job). Idempotent (CREATE TABLE/INDEX IF
NOT EXISTS) and mirrored 1:1 in entrypoint.sh because prod's chronic alembic
multi-head drift means ``alembic upgrade heads`` may not land these.
"""

from alembic import op

revision = "0169_match_telemetry"
down_revision = "0168_cortex_curation_audit"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS match_impressions (
            id BIGSERIAL PRIMARY KEY,
            run_id VARCHAR(64) NOT NULL,
            surface VARCHAR(64) NOT NULL,
            job_id INTEGER,
            request_id INTEGER,
            user_ref VARCHAR(64),
            client_ref VARCHAR(64),
            candidate_id INTEGER NOT NULL,
            rank INTEGER NOT NULL,
            eligible BOOLEAN NOT NULL DEFAULT true,
            retrieval_sources JSONB,
            retrieval_score DOUBLE PRECISION,
            rerank_score DOUBLE PRECISION,
            fit_score DOUBLE PRECISION,
            fit_breakdown JSONB,
            ranker_version VARCHAR(64) NOT NULL DEFAULT 'scoring-v1-legacy',
            index_version VARCHAR(64) NOT NULL DEFAULT 'index-legacy-v1',
            text_schema_version VARCHAR(64) NOT NULL DEFAULT 'text-v1-legacy',
            taxonomy_version VARCHAR(64) NOT NULL DEFAULT 'taxonomy-legacy-v1',
            degraded BOOLEAN NOT NULL DEFAULT false,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_match_impression_run_cand UNIQUE (run_id, candidate_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_match_impressions_run_id "
        "ON match_impressions (run_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_match_impressions_job_id "
        "ON match_impressions (job_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_match_impressions_candidate_id "
        "ON match_impressions (candidate_id)"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS match_outcomes (
            id BIGSERIAL PRIMARY KEY,
            event_id VARCHAR(128) NOT NULL,
            run_id VARCHAR(64),
            candidate_id INTEGER,
            job_id INTEGER,
            event_type VARCHAR(32) NOT NULL,
            reason_code VARCHAR(64),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_match_outcome_event_id UNIQUE (event_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_match_outcomes_run_id "
        "ON match_outcomes (run_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_match_outcomes_candidate_id "
        "ON match_outcomes (candidate_id)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS match_outcomes")
    op.execute("DROP TABLE IF EXISTS match_impressions")
