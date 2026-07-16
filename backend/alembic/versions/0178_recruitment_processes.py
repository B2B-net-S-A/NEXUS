"""RecruitmentProcess — kanoniczny agregat w shadow mode (M4 audyt P0.1, PR-06).

Additive: nowa tabela + enum. Runtime nie czyta ani nie pisze (backfill +
komparator przez admin API). Inwarianty DB: partial unique jeden otwarty
proces pary + unique (candidate, job, attempt_no).

Mirror w ``backend/entrypoint.sh`` (prod alembic orphaned).

Revision ID: 0178_recruitment_processes
Revises: 0177_workflow_revisions
"""

from alembic import op

revision = "0178_recruitment_processes"
down_revision = "0177_workflow_revisions"
branch_labels = None
depends_on = None

STATEMENTS = [
    """DO $$
    BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM pg_type WHERE typname = 'processstatus'
        ) THEN
            CREATE TYPE processstatus AS ENUM ('open', 'closed', 'voided');
        END IF;
    END $$""",
    """CREATE TABLE IF NOT EXISTS recruitment_processes (
        id SERIAL PRIMARY KEY,
        candidate_id INTEGER NOT NULL
            REFERENCES candidates(id) ON DELETE CASCADE,
        job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
        client_id INTEGER NULL REFERENCES clients(id) ON DELETE SET NULL,
        attempt_no INTEGER NOT NULL DEFAULT 1,
        previous_process_id INTEGER NULL
            REFERENCES recruitment_processes(id) ON DELETE SET NULL,
        workflow_revision_id INTEGER NULL
            REFERENCES workflow_revisions(id) ON DELETE SET NULL,
        current_stage_revision_id INTEGER NULL
            REFERENCES stage_revisions(id) ON DELETE SET NULL,
        current_semantic_state VARCHAR(50) NULL,
        legacy_current_candidate_stage_id INTEGER NULL
            REFERENCES candidate_stages(id) ON DELETE SET NULL,
        state_version INTEGER NOT NULL DEFAULT 1,
        status processstatus NOT NULL DEFAULT 'open',
        owner_user_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
        source_authority VARCHAR(30) NOT NULL DEFAULT 'backfill',
        opened_at TIMESTAMPTZ NULL,
        closed_at TIMESTAMPTZ NULL,
        voided_at TIMESTAMPTZ NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        CONSTRAINT uq_process_attempt UNIQUE (candidate_id, job_id, attempt_no)
    )""",
    "CREATE INDEX IF NOT EXISTS ix_processes_candidate "
    "ON recruitment_processes (candidate_id)",
    "CREATE INDEX IF NOT EXISTS ix_processes_job ON recruitment_processes (job_id)",
    "CREATE INDEX IF NOT EXISTS ix_processes_client "
    "ON recruitment_processes (client_id)",
    "CREATE INDEX IF NOT EXISTS ix_processes_status ON recruitment_processes (status)",
    "CREATE INDEX IF NOT EXISTS ix_processes_semantic "
    "ON recruitment_processes (current_semantic_state)",
    "CREATE INDEX IF NOT EXISTS ix_processes_job_status "
    "ON recruitment_processes (job_id, status)",
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_process_one_open "
    "ON recruitment_processes (candidate_id, job_id) WHERE status = 'open'",
]


def upgrade() -> None:
    for stmt in STATEMENTS:
        op.execute(stmt)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS recruitment_processes")
    op.execute("DROP TYPE IF EXISTS processstatus")
