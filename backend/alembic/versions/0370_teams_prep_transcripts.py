"""Prepy w Teams: spotkanie, transkrypt, ocena prepu (zastępuje Fireflies).

Revision ID: 0370_teams_prep_transcripts
Revises: 0368_contract_termination_reversal

Decyzje Artura 23.09.2026: przed rozmową u klienta są zawsze dwa prepy
(Prep 1 — Delivery Lead, Prep 2 — rekruter), zakładane z NEXUSA w kalendarzu
organizatora przez aplikację; transkrypt z Teams trafia do NEXUSA, a GPT-6
Luna (klucz AI ``prep_review``) ocenia prep. Pełny transkrypt bez limitu czasu,
usuwany kaskadą z kandydatem.

Lustro w ``entrypoint.sh`` (prod alembic bywa osierocony) — pilnuje
``test_prep_meetings_schema.py``.
"""

from alembic import op

revision = "0370_teams_prep_transcripts"
down_revision = "0369_academy"
branch_labels = None
depends_on = None

CREATE_PREP_MEETINGS = """CREATE TABLE IF NOT EXISTS prep_meetings (
    id BIGSERIAL PRIMARY KEY,
    calendar_event_id INTEGER NOT NULL UNIQUE
        REFERENCES calendar_events(id) ON DELETE CASCADE,
    candidate_id INTEGER NOT NULL REFERENCES candidates(id) ON DELETE CASCADE,
    job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    prep_no SMALLINT NOT NULL,
    organizer_user_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    organizer_upn VARCHAR(320) NOT NULL,
    organizer_aad_id VARCHAR(64) NULL,
    scheduled_by_user_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    online_meeting_id VARCHAR(512) NULL,
    transcription_setup VARCHAR(20) NOT NULL DEFAULT 'pending',
    transcript_status VARCHAR(20) NOT NULL DEFAULT 'waiting',
    fetch_attempts INTEGER NOT NULL DEFAULT 0,
    next_fetch_at TIMESTAMPTZ NULL,
    last_error VARCHAR(120) NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_prep_meetings_prep_no CHECK (prep_no IN (1, 2)),
    CONSTRAINT ck_prep_meetings_transcription_setup
        CHECK (transcription_setup IN ('pending','enabled','failed','disabled')),
    CONSTRAINT ck_prep_meetings_transcript_status
        CHECK (transcript_status IN
            ('waiting','fetched','missing','cancelled','forbidden','error'))
)"""
CREATE_PREP_TRANSCRIPTS = """CREATE TABLE IF NOT EXISTS prep_transcripts (
    id BIGSERIAL PRIMARY KEY,
    prep_meeting_id BIGINT NOT NULL UNIQUE
        REFERENCES prep_meetings(id) ON DELETE CASCADE,
    candidate_id INTEGER NOT NULL REFERENCES candidates(id) ON DELETE CASCADE,
    job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    graph_transcript_ids JSONB NOT NULL DEFAULT '[]',
    vtt TEXT NOT NULL,
    plain_text TEXT NOT NULL,
    speakers JSONB NOT NULL DEFAULT '[]',
    candidate_seconds INTEGER NOT NULL DEFAULT 0,
    staff_seconds INTEGER NOT NULL DEFAULT 0,
    unknown_seconds INTEGER NOT NULL DEFAULT 0,
    talk_share NUMERIC(4,3) NULL,
    duration_seconds INTEGER NOT NULL DEFAULT 0,
    summary_note_id INTEGER NULL REFERENCES notes(id) ON DELETE SET NULL,
    fetched_at TIMESTAMPTZ NOT NULL DEFAULT now()
)"""
CREATE_PREP_REVIEWS = """CREATE TABLE IF NOT EXISTS prep_reviews (
    id BIGSERIAL PRIMARY KEY,
    prep_meeting_id BIGINT NOT NULL UNIQUE
        REFERENCES prep_meetings(id) ON DELETE CASCADE,
    candidate_id INTEGER NOT NULL REFERENCES candidates(id) ON DELETE CASCADE,
    job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    status VARCHAR(20) NOT NULL,
    level VARCHAR(10) NULL,
    coverage NUMERIC(4,3) NULL,
    criteria JSONB NOT NULL DEFAULT '{}',
    summary TEXT NULL,
    remaining JSONB NOT NULL DEFAULT '[]',
    model VARCHAR(80) NULL,
    prompt_version VARCHAR(40) NULL,
    input_hash VARCHAR(64) NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_prep_reviews_status CHECK (status IN ('ok','unavailable')),
    CONSTRAINT ck_prep_reviews_level
        CHECK (level IS NULL OR level IN ('weak','ok','good'))
)"""
CREATE_FETCH_QUEUE_INDEX = (
    "CREATE INDEX IF NOT EXISTS ix_prep_meetings_fetch_queue "
    "ON prep_meetings (transcript_status, next_fetch_at)"
)
CREATE_PAIR_INDEX = (
    "CREATE INDEX IF NOT EXISTS ix_prep_meetings_pair "
    "ON prep_meetings (candidate_id, job_id)"
)


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE aifeaturekey ADD VALUE IF NOT EXISTS 'prep_review'")
        op.execute(
            "ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS 'prep_attention'"
        )
    op.execute(
        "INSERT INTO ai_features (feature, enabled, monthly_limit, created_at, updated_at) "
        "SELECT 'prep_review', TRUE, 0, NOW(), NOW() "
        "WHERE NOT EXISTS (SELECT 1 FROM ai_features WHERE feature = 'prep_review')"
    )
    op.execute(CREATE_PREP_MEETINGS)
    op.execute(CREATE_PREP_TRANSCRIPTS)
    op.execute(CREATE_PREP_REVIEWS)
    op.execute(CREATE_FETCH_QUEUE_INDEX)
    op.execute(CREATE_PAIR_INDEX)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS prep_reviews")
    op.execute("DROP TABLE IF EXISTS prep_transcripts")
    op.execute("DROP TABLE IF EXISTS prep_meetings")
    # Wartości enumów zostają — Postgres nie ma `ALTER TYPE … DROP VALUE`.
