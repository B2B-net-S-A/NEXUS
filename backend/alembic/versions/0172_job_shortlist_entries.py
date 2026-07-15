"""Job shortlist — pre-pipeline evaluation list (SEARCH-P1-05).

``job_shortlist_entries`` — one row per (job, candidate) on a job's shortlist,
with orthogonal ``evaluation_status`` / ``outreach_status``, an owner, a
decision reason, a next action and an optimistic-locking ``version``. Only
*approved* entries get promoted into the pipeline (``candidate_stages``).

Idempotent CREATE TABLE / INDEX with IF NOT EXISTS — plays nicely with the
entrypoint ``alembic upgrade heads`` and the ``Base.metadata.create_all``
safety-net (new TABLES land on prod even under multi-head; see app/main.py).
Statuses are plain VARCHAR (validated in the Pydantic layer), so there is no
native enum type to create.
"""

from alembic import op

revision = "0172_job_shortlist_entries"
down_revision = "0171_index_outbox"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS job_shortlist_entries (
            id                       SERIAL PRIMARY KEY,
            job_id                   INTEGER NOT NULL
                                         REFERENCES jobs(id) ON DELETE CASCADE,
            candidate_id             INTEGER NOT NULL
                                         REFERENCES candidates(id) ON DELETE CASCADE,
            evaluation_status        VARCHAR(32) NOT NULL DEFAULT 'do_oceny',
            outreach_status          VARCHAR(32) NOT NULL DEFAULT 'nie_kontaktowano',
            owner_id                 INTEGER NULL
                                         REFERENCES users(id) ON DELETE SET NULL,
            decision_reason_code     VARCHAR(64) NULL,
            note                     TEXT NULL,
            next_action_at           TIMESTAMP WITH TIME ZONE NULL,
            score_snapshot           INTEGER NULL,
            version                  INTEGER NOT NULL DEFAULT 1,
            promoted_to_pipeline_at  TIMESTAMP WITH TIME ZONE NULL,
            created_by               INTEGER NULL
                                         REFERENCES users(id) ON DELETE SET NULL,
            updated_by               INTEGER NULL
                                         REFERENCES users(id) ON DELETE SET NULL,
            created_at               TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
            updated_at               TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_job_shortlist_job_candidate UNIQUE (job_id, candidate_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_job_shortlist_entries_job_id "
        "ON job_shortlist_entries (job_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_job_shortlist_entries_candidate_id "
        "ON job_shortlist_entries (candidate_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_job_shortlist_entries_owner_id "
        "ON job_shortlist_entries (owner_id)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS job_shortlist_entries")
