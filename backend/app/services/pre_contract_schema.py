"""Prośby o umowę przedwstępną — SQL migracji 0505 i lustra w ``entrypoint.sh``.

JEDNO źródło instrukcji dla ``alembic/versions/0505_pre_contract_requests.py``
i ``entrypoint.sh`` (alembic na prodzie bywa osierocony); test
``test_pre_contract_schema_mirror.py`` sprawdza, że każda stoi w entrypoincie
dosłownie — po tabeli ``b2b_contract_documents``, na którą wskazuje klucz obcy.
Model: ``app.models.pre_contract``.
"""

from __future__ import annotations

REQUESTS_DDL = (
    "CREATE TABLE IF NOT EXISTS pre_contract_requests ("
    "id SERIAL PRIMARY KEY, "
    "candidate_id INTEGER NOT NULL REFERENCES candidates(id) ON DELETE CASCADE, "
    "job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE, "
    "client_id INTEGER NULL REFERENCES clients(id) ON DELETE SET NULL, "
    "needed_before VARCHAR(24) NOT NULL, "
    "needed_by DATE NULL, "
    "reason TEXT NULL, "
    "requested_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL, "
    "requested_at TIMESTAMPTZ NOT NULL DEFAULT now(), "
    "assignee_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL, "
    "document_id INTEGER NULL REFERENCES b2b_contract_documents(id) ON DELETE SET NULL, "
    "issued_at TIMESTAMPTZ NULL, "
    "sent_at TIMESTAMPTZ NULL, "
    "candidate_signed_at TIMESTAMPTZ NULL, "
    "candidate_signature_form VARCHAR(24) NULL, "
    "candidate_file_path VARCHAR(512) NULL, "
    "candidate_file_name VARCHAR(255) NULL, "
    "company_signed_at TIMESTAMPTZ NULL, "
    "company_file_path VARCHAR(512) NULL, "
    "company_file_name VARCHAR(255) NULL, "
    "valid_until DATE NULL, "
    "b2b_deadline DATE NULL, "
    "closed_at TIMESTAMPTZ NULL, "
    "close_reason VARCHAR(24) NULL, "
    "closed_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL, "
    "withdrawal JSONB NULL, "
    "last_reminder_at TIMESTAMPTZ NULL, "
    "created_at TIMESTAMPTZ NOT NULL DEFAULT now(), "
    "updated_at TIMESTAMPTZ NOT NULL DEFAULT now(), "
    "CONSTRAINT ck_pre_contract_needed_before CHECK "
    "(needed_before IN ('cv_sent', 'client_interview', 'b2b_contract', 'date')), "
    "CONSTRAINT ck_pre_contract_signature_form CHECK "
    "(candidate_signature_form IS NULL OR candidate_signature_form IN "
    "('trusted_profile', 'personal_signature', 'qualified', 'handwritten_scan', 'other')), "
    "CONSTRAINT ck_pre_contract_close_reason CHECK "
    "(close_reason IS NULL OR close_reason IN ('fulfilled', 'expired', 'cancelled', "
    "'withdrawn', 'candidate_refused', 'candidate_withdrew')))"
)

WATCHERS_DDL = (
    "CREATE TABLE IF NOT EXISTS pre_contract_watchers ("
    "request_id INTEGER NOT NULL REFERENCES pre_contract_requests(id) ON DELETE CASCADE, "
    "user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, "
    "created_at TIMESTAMPTZ NOT NULL DEFAULT now(), "
    "PRIMARY KEY (request_id, user_id))"
)

EVENTS_DDL = (
    "CREATE TABLE IF NOT EXISTS pre_contract_events ("
    "id SERIAL PRIMARY KEY, "
    "request_id INTEGER NOT NULL REFERENCES pre_contract_requests(id) ON DELETE CASCADE, "
    "kind VARCHAR(40) NOT NULL, "
    "actor_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL, "
    "at TIMESTAMPTZ NOT NULL DEFAULT now(), "
    "payload JSONB NULL)"
)

INDEX_DDL = (
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_pre_contract_open_per_pair "
    "ON pre_contract_requests (candidate_id, job_id) WHERE closed_at IS NULL",
    "CREATE INDEX IF NOT EXISTS ix_pre_contract_requests_candidate_id "
    "ON pre_contract_requests (candidate_id)",
    "CREATE INDEX IF NOT EXISTS ix_pre_contract_requests_job_id "
    "ON pre_contract_requests (job_id)",
    "CREATE INDEX IF NOT EXISTS ix_pre_contract_requests_client_id "
    "ON pre_contract_requests (client_id)",
    "CREATE INDEX IF NOT EXISTS ix_pre_contract_requests_requested_by "
    "ON pre_contract_requests (requested_by)",
    "CREATE INDEX IF NOT EXISTS ix_pre_contract_requests_assignee_id "
    "ON pre_contract_requests (assignee_id)",
    "CREATE INDEX IF NOT EXISTS ix_pre_contract_watchers_user_id "
    "ON pre_contract_watchers (user_id)",
    "CREATE INDEX IF NOT EXISTS ix_pre_contract_events_request_id "
    "ON pre_contract_events (request_id)",
)

ENUM_DDL = "ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS 'pre_contract'"

ALL_DDL = (REQUESTS_DDL, WATCHERS_DDL, EVENTS_DDL, *INDEX_DDL)

DOWNGRADE_DDL = (
    "DROP TABLE IF EXISTS pre_contract_events",
    "DROP TABLE IF EXISTS pre_contract_watchers",
    "DROP TABLE IF EXISTS pre_contract_requests",
)
