"""Sesje zdalnego podpisu przez API CSC (0759) — SQL migracji i lustra w ``entrypoint.sh``.

JEDNO źródło instrukcji dla ``alembic/versions/0759_b2b_esign_remote_sessions.py``
i ``entrypoint.sh`` (alembic na prodzie bywa osierocony). Model:
``app.models.b2b_esign_remote_session``. Same dodania: stary kod tabeli nie zna.
"""

from __future__ import annotations

SESSION_PARTIES = ("contractor", "company")
SESSION_STATES = ("waiting_for_user", "signing", "done", "failed", "cancelled")
SESSION_METHODS = ("own_certificate", "one_time")

TABLE = (
    "CREATE TABLE IF NOT EXISTS b2b_esign_remote_sessions ("
    "id SERIAL PRIMARY KEY, "
    "public_id VARCHAR(43) NOT NULL UNIQUE, "
    "party VARCHAR(16) NOT NULL, "
    "request_ids JSONB NOT NULL DEFAULT '[]'::jsonb, "
    "document_ids JSONB NOT NULL DEFAULT '[]'::jsonb, "
    "method VARCHAR(16) NULL, "
    "user_id INTEGER NULL REFERENCES users(id) ON DELETE CASCADE, "
    "state_hash VARCHAR(64) NOT NULL UNIQUE, "
    "code_verifier VARCHAR(128) NULL, "
    "sealed_token TEXT NULL, "
    "status VARCHAR(24) NOT NULL DEFAULT 'waiting_for_user', "
    "message TEXT NULL, "
    "done_request_ids JSONB NOT NULL DEFAULT '[]'::jsonb, "
    "evidence JSONB NULL, "
    "expires_at TIMESTAMPTZ NOT NULL, "
    "callback_at TIMESTAMPTZ NULL, "
    "finished_at TIMESTAMPTZ NULL, "
    "created_at TIMESTAMPTZ NOT NULL DEFAULT now(), "
    "updated_at TIMESTAMPTZ NOT NULL DEFAULT now(), "
    "CONSTRAINT ck_b2b_esign_remote_sessions_party "
    "CHECK (party IN ('contractor', 'company')), "
    "CONSTRAINT ck_b2b_esign_remote_sessions_status "
    "CHECK (status IN ('waiting_for_user', 'signing', 'done', 'failed', 'cancelled'))"
    ")"
)
INDEX = (
    "CREATE INDEX IF NOT EXISTS ix_b2b_esign_remote_sessions_open "
    "ON b2b_esign_remote_sessions (status, expires_at) "
    "WHERE status IN ('waiting_for_user', 'signing')"
)

TABLE_DDL: tuple[str, ...] = (TABLE, INDEX)
