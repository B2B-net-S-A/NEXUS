"""Add business status (active/closed) to generated B2B contracts.

Purely additive: every historical row becomes ``active`` via the column
default, so no backfill decides anything on the user's behalf. Closing a
contract never deletes the row — it only records why and when the engagement
ended, next to the (independent) signature state.

The coherence CHECK is the reason this cannot be a pair of loose columns:
``closed`` without a reason or without an end date is unusable in a register,
and ``active`` carrying a closure reason is a contradiction.

Revision ID: 0203_b2b_generated_contract_status
Revises: 0202_cv_content_mode
"""

from alembic import op


revision = "0203_b2b_generated_contract_status"
down_revision = "0202_cv_content_mode"
branch_labels = None
depends_on = None


_CONSTRAINTS = (
    (
        "ck_b2b_generated_contracts_contract_status",
        "CHECK (contract_status IN ('active', 'closed'))",
    ),
    (
        "ck_b2b_generated_contracts_closure_reason",
        """CHECK (
            closure_reason IS NULL
            OR closure_reason IN (
                'resignation_before_signing',
                'termination',
                'mutual_agreement',
                'other'
            )
        )""",
    ),
    (
        "ck_b2b_generated_contracts_closure_coherence",
        """CHECK (
            (
                contract_status = 'active'
                AND closure_reason IS NULL
                AND closure_date IS NULL
                AND closure_reason_other IS NULL
            )
            OR (
                contract_status = 'closed'
                AND closure_reason IS NOT NULL
                AND closure_date IS NOT NULL
                AND (
                    (closure_reason = 'other')
                    = (closure_reason_other IS NOT NULL)
                )
            )
        )""",
    ),
)


def upgrade() -> None:
    # Production bootstrapping mirrors this additive DDL in entrypoint.sh, so
    # every statement must tolerate the safety-net having run first.
    op.execute(
        """
        ALTER TABLE b2b_generated_contracts
            ADD COLUMN IF NOT EXISTS contract_status VARCHAR(16)
                NOT NULL DEFAULT 'active',
            ADD COLUMN IF NOT EXISTS closure_reason VARCHAR(32) NULL,
            ADD COLUMN IF NOT EXISTS closure_reason_other TEXT NULL,
            ADD COLUMN IF NOT EXISTS closure_date DATE NULL
        """
    )

    for name, definition in _CONSTRAINTS:
        op.execute(
            f"""
            DO $$ BEGIN
                ALTER TABLE b2b_generated_contracts
                    ADD CONSTRAINT {name} {definition} NOT VALID;
            EXCEPTION WHEN duplicate_object THEN NULL;
            END $$
            """
        )

    # The entrypoint safety-net creates constraints NOT VALID to keep startup
    # bounded. Once Alembic reaches this revision, validate them — the table
    # only ever contained rows that satisfy them (all default to ``active``).
    for name, _definition in _CONSTRAINTS:
        op.execute(f"ALTER TABLE b2b_generated_contracts VALIDATE CONSTRAINT {name}")

    # Rejestr filtruje listę po statusie (`GET /generated?contract_status=`).
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_b2b_generated_contracts_contract_status
            ON b2b_generated_contracts (contract_status)
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_b2b_generated_contracts_contract_status")

    for name, _definition in reversed(_CONSTRAINTS):
        op.execute(
            f"""
            ALTER TABLE IF EXISTS b2b_generated_contracts
                DROP CONSTRAINT IF EXISTS {name}
            """
        )

    for column in (
        "closure_date",
        "closure_reason_other",
        "closure_reason",
        "contract_status",
    ):
        op.execute(
            f"""
            ALTER TABLE IF EXISTS b2b_generated_contracts
                DROP COLUMN IF EXISTS {column}
            """
        )
