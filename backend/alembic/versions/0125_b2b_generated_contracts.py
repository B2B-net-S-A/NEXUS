"""Generator Umów B2B v2 — log wygenerowanych umów (numeracja + standalone)

Revision ID: 0125_b2b_generated_contracts
Revises: 0124_seed_kpi_panel_targets
Create Date: 2026-06-05 13:00:00.000000

Context:
    Tryb standalone (ręczne wpisanie danych, bez rekordu Contract) potrzebuje
    persystentnego licznika numerów umów. Ta tabela loguje każdą finalnie
    wygenerowaną umowę (przy pobraniu DOCX) i z niej wyliczamy kolejny numer
    `<seq>/<rok>`.

    Chain: 0123 → 0124_seed_kpi_panel_targets → 0125 (re-chained, bo równolegle
    wmergowano 0124_seed_kpi z tym samym rodzicem 0123).

Safety net: idempotentne (`CREATE TABLE/INDEX IF NOT EXISTS`).
"""

from alembic import op


revision = "0125_b2b_generated_contracts"
down_revision = "0124_seed_kpi_panel_targets"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS b2b_generated_contracts (
            id              SERIAL PRIMARY KEY,
            year            INTEGER NOT NULL,
            seq             INTEGER NOT NULL,
            contract_number VARCHAR(64) NOT NULL,
            partner_name    VARCHAR(255),
            client_name     VARCHAR(255),
            language        VARCHAR(2) NOT NULL DEFAULT 'pl',
            signing_date    DATE,
            created_by      INTEGER REFERENCES users (id) ON DELETE SET NULL,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_b2b_generated_contracts_year "
        "ON b2b_generated_contracts (year)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS b2b_generated_contracts")
