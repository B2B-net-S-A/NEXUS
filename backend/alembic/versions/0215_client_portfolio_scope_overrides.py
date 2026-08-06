"""Manual placement overrides for client portfolio scopes.

Revision ID: 0215_client_portfolio_scope_overrides
Revises: 0214_order_parser_ai_feature
Create Date: 2026-08-05

Adds three nullable columns to ``client_portfolio_scopes`` so the Clients
directory can be curated from the UI (move a client between the
Aktywni/Relacyjni/Nieaktywni tabs, pin a contract period) WITHOUT mutating the
manifest-owned ``category`` / linked-MSA dates.

Why a separate override instead of editing ``category`` in place:
``get_client_portfolio_import_health`` compares the live manifest scopes
(``source_system='client_excel'``) against the applied import rows on
``category`` and the linked MSA dates.  Editing those base columns makes the
live state diverge from the manifest → ``applied_manifest_state_inconsistent``
→ ``/api/health/deep`` reports the portfolio import as unhealthy (HTTP 503).
The directory READ prefers these override columns while the invariant keeps
reading the untouched base columns, so a manual placement never trips that
check.  The manifest apply never writes these columns.

Additive and reversible.  Mirrored in ``entrypoint.sh`` because production
alembic is orphaned and the safety-net owns the live schema.
"""

from alembic import op


revision = "0215_client_portfolio_scope_overrides"
down_revision = "0214_order_parser_ai_feature"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ``clientportfoliocategory`` already exists (0087/0205); reuse it.
    op.execute(
        """
        ALTER TABLE client_portfolio_scopes
            ADD COLUMN IF NOT EXISTS category_override
                clientportfoliocategory NULL,
            ADD COLUMN IF NOT EXISTS contract_start_override DATE NULL,
            ADD COLUMN IF NOT EXISTS contract_end_override DATE NULL
        """
    )
    op.execute(
        """
        DO $$ BEGIN
            ALTER TABLE client_portfolio_scopes
                ADD CONSTRAINT ck_client_portfolio_scopes_override_dates
                CHECK (
                    contract_start_override IS NULL
                    OR contract_end_override IS NULL
                    OR contract_end_override >= contract_start_override
                );
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$
        """
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE IF EXISTS client_portfolio_scopes "
        "DROP CONSTRAINT IF EXISTS ck_client_portfolio_scopes_override_dates"
    )
    for column in (
        "contract_end_override",
        "contract_start_override",
        "category_override",
    ):
        op.execute(
            "ALTER TABLE IF EXISTS client_portfolio_scopes "
            f"DROP COLUMN IF EXISTS {column}"
        )
