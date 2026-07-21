"""Pending public-apply submissions (application_submissions) — P0-CAND-01.

Closes the public ``POST /api/public/apply/{token}`` candidate-poisoning hole:
a duplicate e-mail no longer OVERWRITES a canonical candidate. The applicant
payload + CV are parked in this table (``status='pending_review'``) for
recruiter triage instead.

New empty table — no existing data to migrate. Mirrored idempotently in
backend/entrypoint.sh (prod alembic is orphaned; every schema change must be
reflected there too), matching this DDL 1:1.

Revision ID: 0189_application_submissions
Revises: 0188_contract_alert_dedup
"""

from alembic import op

revision = "0189_application_submissions"
down_revision = "0188_contract_alert_dedup"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS application_submissions (
            id SERIAL PRIMARY KEY,
            invite_link_token_sha256 VARCHAR(64),
            job_id INTEGER REFERENCES jobs(id) ON DELETE SET NULL,
            status VARCHAR(20) NOT NULL DEFAULT 'pending_review',
            submitted_first_name VARCHAR(100) NOT NULL,
            submitted_last_name VARCHAR(100) NOT NULL,
            submitted_email VARCHAR(255) NOT NULL,
            submitted_phone VARCHAR(30),
            submitted_linkedin VARCHAR(500),
            submitted_message TEXT,
            matched_candidate_id INTEGER REFERENCES candidates(id) ON DELETE SET NULL,
            cv_object_key VARCHAR(500),
            cv_filename VARCHAR(500),
            cv_content_type VARCHAR(100),
            cv_size_bytes INTEGER,
            cv_file_content BYTEA,
            raw_cv_text TEXT,
            raw_payload JSONB,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            reviewed_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
            reviewed_at TIMESTAMPTZ,
            CONSTRAINT ck_application_submissions_status CHECK (
                status IN ('pending_review','linked','merged','created','rejected')
            )
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_application_submissions_status "
        "ON application_submissions (status)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_application_submissions_matched_candidate_id "
        "ON application_submissions (matched_candidate_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_application_submissions_link "
        "ON application_submissions (invite_link_token_sha256)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_application_submissions_submitted_email "
        "ON application_submissions (submitted_email)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_application_submissions_job_id "
        "ON application_submissions (job_id)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS application_submissions")
