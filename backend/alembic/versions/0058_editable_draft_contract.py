"""Editable contract draft + JDG/business fields on candidates and clients.

Revision ID: 0058_editable_draft_contract
Revises: 0057_champion_suggestion_rating
Create Date: 2026-04-24 09:00:00.000000

Adds the storage for the in-app contract draft editor:

  contracts.draft_content_html      — rendered/edited HTML body of the draft
  contracts.draft_template_id       — FK contract_templates(id) (re-render source)
  contracts.draft_updated_at        — last edit timestamp
  contracts.draft_updated_by        — FK users(id), who edited last

Plus the merge-field source data that the Jinja templates expect:

  candidates.legal_name             — nazwa prawna (osoba fizyczna lub firma)
  candidates.nip                    — NIP (jeśli JDG / sp. z o.o.)
  candidates.regon                  — REGON
  candidates.business_address       — adres siedziby firmy kontraktora
  candidates.business_form          — `jdg|sp_zoo|sa|sc|osoba_fizyczna`

  clients.legal_name                — nazwa prawna klienta (do umowy)
  clients.nip                       — NIP klienta
  clients.regon                     — REGON klienta

Idempotent + reversible. All columns are NULL-able, so no backfill needed —
existing draft contracts continue to work; the FE will lazy-render the default
template the first time someone opens the new "Umowa" tab.
"""

from alembic import op


revision = "0058_editable_draft_contract"
down_revision = "0057_champion_suggestion_rating"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── contracts: draft body + provenance ────────────────────────────────
    op.execute(
        "ALTER TABLE contracts "
        "ADD COLUMN IF NOT EXISTS draft_content_html TEXT NULL"
    )
    op.execute(
        "ALTER TABLE contracts "
        "ADD COLUMN IF NOT EXISTS draft_template_id INTEGER NULL"
    )
    op.execute(
        "ALTER TABLE contracts "
        "ADD COLUMN IF NOT EXISTS draft_updated_at TIMESTAMPTZ NULL"
    )
    op.execute(
        "ALTER TABLE contracts "
        "ADD COLUMN IF NOT EXISTS draft_updated_by INTEGER NULL"
    )
    # FK guards (drop+recreate so the migration is idempotent on rerun)
    op.execute(
        "ALTER TABLE contracts "
        "DROP CONSTRAINT IF EXISTS fk_contracts_draft_template_id"
    )
    op.execute(
        "ALTER TABLE contracts "
        "ADD CONSTRAINT fk_contracts_draft_template_id "
        "FOREIGN KEY (draft_template_id) REFERENCES contract_templates(id) "
        "ON DELETE SET NULL"
    )
    op.execute(
        "ALTER TABLE contracts "
        "DROP CONSTRAINT IF EXISTS fk_contracts_draft_updated_by"
    )
    op.execute(
        "ALTER TABLE contracts "
        "ADD CONSTRAINT fk_contracts_draft_updated_by "
        "FOREIGN KEY (draft_updated_by) REFERENCES users(id) "
        "ON DELETE SET NULL"
    )

    # ── candidates: JDG / business entity fields ─────────────────────────
    op.execute(
        "ALTER TABLE candidates "
        "ADD COLUMN IF NOT EXISTS legal_name VARCHAR(255) NULL"
    )
    op.execute(
        "ALTER TABLE candidates "
        "ADD COLUMN IF NOT EXISTS nip VARCHAR(32) NULL"
    )
    op.execute(
        "ALTER TABLE candidates "
        "ADD COLUMN IF NOT EXISTS regon VARCHAR(32) NULL"
    )
    op.execute(
        "ALTER TABLE candidates "
        "ADD COLUMN IF NOT EXISTS business_address TEXT NULL"
    )
    op.execute(
        "ALTER TABLE candidates "
        "ADD COLUMN IF NOT EXISTS business_form VARCHAR(64) NULL"
    )

    # ── clients: business entity fields used in contract merge ───────────
    op.execute(
        "ALTER TABLE clients "
        "ADD COLUMN IF NOT EXISTS legal_name VARCHAR(255) NULL"
    )
    op.execute(
        "ALTER TABLE clients "
        "ADD COLUMN IF NOT EXISTS nip VARCHAR(32) NULL"
    )
    op.execute(
        "ALTER TABLE clients "
        "ADD COLUMN IF NOT EXISTS regon VARCHAR(32) NULL"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE contracts "
        "DROP CONSTRAINT IF EXISTS fk_contracts_draft_updated_by"
    )
    op.execute(
        "ALTER TABLE contracts "
        "DROP CONSTRAINT IF EXISTS fk_contracts_draft_template_id"
    )
    for col in (
        "draft_updated_by",
        "draft_updated_at",
        "draft_template_id",
        "draft_content_html",
    ):
        op.execute(f"ALTER TABLE contracts DROP COLUMN IF EXISTS {col}")

    for col in (
        "business_form",
        "business_address",
        "regon",
        "nip",
        "legal_name",
    ):
        op.execute(f"ALTER TABLE candidates DROP COLUMN IF EXISTS {col}")

    for col in ("regon", "nip", "legal_name"):
        op.execute(f"ALTER TABLE clients DROP COLUMN IF EXISTS {col}")
