"""Persistent invalidation ledger for the match-score cache (audyt F-28).

The CAS fence from ``0190_match_score_cache_cas`` stamps
``candidate_job_match_scores.invalidated_at`` so a compute that started before a
``mark_stale_*`` cannot resurrect ``stale=False`` on the conflict (row-exists)
write-back. But that fence lives ON the cache row, so the MISS path is unguarded:
when no cache row exists, ``mark_stale_*`` updates zero rows and leaves no trace,
and an in-flight miss-compute then INSERTs ``stale=False`` against stale inputs —
falsely fresh forever.

This adds ``match_score_invalidations`` as the missing durable trace. Every
``mark_stale_*`` UPSERTs a row here to ``now()`` even when no cache row exists,
and the miss/INSERT path reads the newest ``last_invalidated_at`` for the
(candidate, job, profile) keys to decide the ``stale`` verdict.

Keyed by (entity_type, entity_id); one watermark row per touched entity. DDL is
idempotent (``IF NOT EXISTS``) and mirrored in backend/entrypoint.sh (prod
alembic is orphaned at 0152).

Revision ID: 0194_match_score_invalidations
Revises: 0191_contract_lifecycle_invariant
"""

from alembic import op

revision = "0194_match_score_invalidations"
down_revision = "0193_calls_candidate_id_nullable"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS match_score_invalidations (
            entity_type VARCHAR(16) NOT NULL,
            entity_id INTEGER NOT NULL,
            last_invalidated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT pk_match_score_invalidations
                PRIMARY KEY (entity_type, entity_id)
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS match_score_invalidations")
