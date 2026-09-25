"""Teams follow-up meetings and candidate-owned transcripts.

Revision ID: 0379_followup_teams_meetings
Revises: 0378_archive_jobs_before_nexus_start
"""

from alembic import op

revision = "0379_followup_teams_meetings"
down_revision = "0378_archive_jobs_before_nexus_start"
branch_labels = None
depends_on = None

CREATE = """CREATE TABLE IF NOT EXISTS followup_meetings (
    id BIGSERIAL PRIMARY KEY,
    candidate_id INTEGER NOT NULL REFERENCES candidates(id) ON DELETE CASCADE,
    calendar_event_id INTEGER NOT NULL UNIQUE REFERENCES calendar_events(id) ON DELETE CASCADE,
    organizer_user_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    organizer_upn VARCHAR(320) NOT NULL,
    organizer_aad_id VARCHAR(64) NULL,
    online_meeting_id VARCHAR(512) NULL,
    client_request_id VARCHAR(80) NOT NULL UNIQUE,
    transcription_setup VARCHAR(20) NOT NULL DEFAULT 'pending',
    transcript_status VARCHAR(20) NOT NULL DEFAULT 'waiting',
    fetch_attempts INTEGER NOT NULL DEFAULT 0,
    next_fetch_at TIMESTAMPTZ NULL,
    last_error VARCHAR(120) NULL,
    transcript_vtt TEXT NULL,
    transcript_text TEXT NULL,
    transcript_fetched_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
)"""


def upgrade() -> None:
    op.execute(CREATE)
    op.execute("CREATE INDEX IF NOT EXISTS ix_followup_meetings_candidate ON followup_meetings (candidate_id, created_at)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_followup_meetings_queue ON followup_meetings (transcript_status, next_fetch_at)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS followup_meetings")
