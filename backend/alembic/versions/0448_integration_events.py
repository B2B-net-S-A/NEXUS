"""API integracyjne v1: kanał zdarzeń i webhooki kont serwisowych.

Revision ID: 0448_integration_events
Revises: 0447_job_previous_recruiters

Decyzja Artura 15.10.2026 („rób wszystko”): automatyzacje dowiadują się
o zmianach z kanału ``GET /api/integrations/v1/events`` albo z webhooka.

* ``integration_event_outbox`` — zdarzenia dopisywane przez listener ORM
  w transakcji zmiany (bez kursora).
* ``integration_events`` — kanał; ``id`` = kursor nadawany przy publikacji
  przez pętlę w tle (szeregowane partie = kursor bez dziur „na później”).
  Retencja 30 dni.
* ``integration_webhooks`` — adres, sekret podpisu (Fernet), kursor
  dostarczenia, ponowienia i wyłączenie po serii porażek.

Lustro w ``entrypoint.sh`` — pilnuje ``test_integration_events_migration_mirror.py``.
"""

from alembic import op

revision = "0448_integration_events"
down_revision = "0447_job_previous_recruiters"
branch_labels = None
depends_on = None

CREATE_OUTBOX = """CREATE TABLE IF NOT EXISTS integration_event_outbox (
    id BIGSERIAL PRIMARY KEY,
    type VARCHAR(64) NOT NULL,
    scope VARCHAR(64) NOT NULL,
    refs JSONB NOT NULL DEFAULT '{}'::jsonb,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT now()
)"""
CREATE_EVENTS = """CREATE TABLE IF NOT EXISTS integration_events (
    id BIGSERIAL PRIMARY KEY,
    type VARCHAR(64) NOT NULL,
    scope VARCHAR(64) NOT NULL,
    refs JSONB NOT NULL DEFAULT '{}'::jsonb,
    occurred_at TIMESTAMPTZ NOT NULL,
    published_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_integration_events_refs_object
        CHECK (jsonb_typeof(refs) = 'object')
)"""
CREATE_WEBHOOKS = """CREATE TABLE IF NOT EXISTS integration_webhooks (
    id SERIAL PRIMARY KEY,
    service_account_id INTEGER NOT NULL
        REFERENCES service_accounts(id) ON DELETE CASCADE,
    url VARCHAR(2048) NOT NULL,
    secret_ct TEXT NOT NULL,
    event_types JSONB NOT NULL DEFAULT '[]'::jsonb,
    is_active BOOLEAN NOT NULL DEFAULT true,
    last_event_id BIGINT NOT NULL DEFAULT 0,
    failure_count INTEGER NOT NULL DEFAULT 0,
    next_attempt_at TIMESTAMPTZ NULL,
    lease_until TIMESTAMPTZ NULL,
    test_requested_at TIMESTAMPTZ NULL,
    disabled_reason VARCHAR(255) NULL,
    disabled_at TIMESTAMPTZ NULL,
    last_delivery_at TIMESTAMPTZ NULL,
    last_status INTEGER NULL,
    last_error VARCHAR(120) NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_integration_webhooks_event_types_array
        CHECK (jsonb_typeof(event_types) = 'array')
)"""
INDEXES = [
    "CREATE INDEX IF NOT EXISTS ix_integration_events_type_id "
    "ON integration_events (type, id)",
    "CREATE INDEX IF NOT EXISTS ix_integration_webhooks_account "
    "ON integration_webhooks (service_account_id)",
]


def upgrade() -> None:
    op.execute(CREATE_OUTBOX)
    op.execute(CREATE_EVENTS)
    op.execute(CREATE_WEBHOOKS)
    for statement in INDEXES:
        op.execute(statement)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS integration_webhooks")
    op.execute("DROP TABLE IF EXISTS integration_events")
    op.execute("DROP TABLE IF EXISTS integration_event_outbox")
