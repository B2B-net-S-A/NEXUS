"""API integracyjne v1: paragony zapisów, źródło „integracja”, skrót pliku MD.

Revision ID: 0441_integrations_v1
Revises: 0440_cv_ready_notification

Decyzja Artura 14.10.2026: procesy firmy (na start rozliczanie klientów)
podpinane pod NEXUSA przez ``/api/integrations/v1`` na kluczach ``X-API-Key``.

* ``integration_write_receipts`` — idempotencja zapisów (``Idempotency-Key``)
  i rejestr „co zapisała automatyzacja” dla ekranu „Klucze API”.
* ``order_change_events.source`` + ``integration`` i
  ``created_by_service_account_id`` — zmiana stawki albo daty końca zapisana
  kluczem nie wygląda w „Zmianach w zamówieniach” jak „system”.
* ``md_consumption_imports.file_sha256`` i ``uploaded_by_service_account_id``
  — ten sam plik za ten sam miesiąc drugi raz to 409, autor importu z
  automatyzacji widoczny na ekranie.

Lustro w ``entrypoint.sh`` (prod alembic bywa osierocony).
"""

from alembic import op

revision = "0441_integrations_v1"
down_revision = "0440_cv_ready_notification"
branch_labels = None
depends_on = None

UPGRADE = [
    """CREATE TABLE IF NOT EXISTS integration_write_receipts (
        id SERIAL PRIMARY KEY,
        service_account_id INTEGER NOT NULL
            REFERENCES service_accounts(id) ON DELETE CASCADE,
        key_id VARCHAR(64) NOT NULL,
        idempotency_key VARCHAR(80) NOT NULL,
        method VARCHAR(8) NOT NULL,
        route VARCHAR(255) NOT NULL,
        payload_sha256 VARCHAR(64) NOT NULL,
        state VARCHAR(16) NOT NULL DEFAULT 'pending',
        status_code INTEGER,
        response_json JSONB,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        completed_at TIMESTAMPTZ,
        CONSTRAINT uq_integration_write_receipts_account_key
            UNIQUE (service_account_id, idempotency_key),
        CONSTRAINT ck_integration_write_receipts_state
            CHECK (state IN ('pending', 'done'))
    )""",
    "CREATE INDEX IF NOT EXISTS ix_integration_write_receipts_account_created "
    "ON integration_write_receipts (service_account_id, created_at)",
    "ALTER TABLE order_change_events "
    "ADD COLUMN IF NOT EXISTS created_by_service_account_id INTEGER",
    """DO $$ BEGIN
        ALTER TABLE order_change_events
            DROP CONSTRAINT IF EXISTS ck_order_change_events_source;
        ALTER TABLE order_change_events
            ADD CONSTRAINT ck_order_change_events_source
            CHECK (source IN ('user', 'system', 'integration'));
    END $$""",
    "ALTER TABLE md_consumption_imports "
    "ADD COLUMN IF NOT EXISTS file_sha256 VARCHAR(64)",
    "ALTER TABLE md_consumption_imports "
    "ADD COLUMN IF NOT EXISTS uploaded_by_service_account_id INTEGER "
    "REFERENCES service_accounts(id) ON DELETE SET NULL",
    "CREATE INDEX IF NOT EXISTS ix_md_consumption_imports_file_sha256 "
    "ON md_consumption_imports (period_month, file_sha256)",
]

# Kod sprzed tej rewizji nie zna źródła „integration” — schemat odpowiedzi
# „Zmian w zamówieniach” odrzuciłby taki wpis (500 na ekranie Finansów).
REFUSE_WITH_INTEGRATION_ROWS = """DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM order_change_events WHERE source = 'integration') THEN
        RAISE EXCEPTION 'Downgrade 0441 odmawia: order_change_events ma wpisy source=integration, których kod sprzed tej rewizji nie odczyta.';
    END IF;
END $$"""


def upgrade() -> None:
    for statement in UPGRADE:
        op.execute(statement)


def downgrade() -> None:
    op.execute(REFUSE_WITH_INTEGRATION_ROWS)
    op.execute("DROP INDEX IF EXISTS ix_md_consumption_imports_file_sha256")
    op.execute(
        "ALTER TABLE md_consumption_imports "
        "DROP COLUMN IF EXISTS uploaded_by_service_account_id"
    )
    op.execute("ALTER TABLE md_consumption_imports DROP COLUMN IF EXISTS file_sha256")
    op.execute(
        """DO $$ BEGIN
        ALTER TABLE order_change_events
            DROP CONSTRAINT IF EXISTS ck_order_change_events_source;
        ALTER TABLE order_change_events
            ADD CONSTRAINT ck_order_change_events_source
            CHECK (source IN ('user', 'system'));
    END $$"""
    )
    op.execute(
        "ALTER TABLE order_change_events "
        "DROP COLUMN IF EXISTS created_by_service_account_id"
    )
    op.execute("DROP TABLE IF EXISTS integration_write_receipts")
