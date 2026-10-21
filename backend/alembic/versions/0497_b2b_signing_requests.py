"""Wnioski o podpis umowy B2B w NEXUSIE (droga obok „Oznacz jako podpisaną”).

Revision ID: 0497_b2b_signing_requests
Revises: 0496_b2b_generated_signed_file

* ``b2b_signing_requests`` — jedna wysyłka umowy z rejestru Generatora do
  podpisu kwalifikowanego kontraktora, potem reprezentanta B2B Network.
  PDF z Worda zamrożony odciskiem; najwyżej jeden wniosek w toku na wiersz
  rejestru (indeks częściowy). Model: ``app.models.b2b_signing_request``.

Lustro w ``entrypoint.sh`` (alembic na prodzie bywa osierocony).
"""

from alembic import op

revision = "0497_b2b_signing_requests"
down_revision = "0496_b2b_generated_signed_file"
branch_labels = None
depends_on = None

_CREATE = """
CREATE TABLE IF NOT EXISTS b2b_signing_requests (
    id SERIAL PRIMARY KEY,
    generated_contract_id INTEGER NOT NULL
        REFERENCES b2b_generated_contracts(id) ON DELETE CASCADE,
    status VARCHAR(24) NOT NULL DEFAULT 'sent',
    contractor_name VARCHAR(255) NOT NULL,
    contractor_email VARCHAR(255) NOT NULL,
    contractor_token_hash VARCHAR(64) UNIQUE,
    company_signer_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    source_pdf_path VARCHAR(512) NOT NULL,
    source_sha256 VARCHAR(64) NOT NULL,
    source_size INTEGER NOT NULL,
    contractor_pdf_path VARCHAR(512),
    contractor_sha256 VARCHAR(64),
    contractor_size INTEGER,
    final_pdf_path VARCHAR(512),
    validation JSONB,
    sent_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    sent_at TIMESTAMPTZ NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    contractor_signed_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    closed_at TIMESTAMPTZ,
    closed_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    close_reason TEXT,
    last_reminder_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_b2b_signing_requests_status CHECK (
        status IN ('sent', 'contractor_signed', 'completed', 'withdrawn', 'expired')
    )
)
"""

_INDEXES = (
    "CREATE INDEX IF NOT EXISTS ix_b2b_signing_requests_generated_contract_id "
    "ON b2b_signing_requests (generated_contract_id)",
    "CREATE INDEX IF NOT EXISTS ix_b2b_signing_requests_company_signer_id "
    "ON b2b_signing_requests (company_signer_id)",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_b2b_signing_requests_open_per_row "
    "ON b2b_signing_requests (generated_contract_id) "
    "WHERE status IN ('sent', 'contractor_signed')",
)


def upgrade() -> None:
    op.execute(_CREATE)
    for statement in _INDEXES:
        op.execute(statement)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS b2b_signing_requests")
