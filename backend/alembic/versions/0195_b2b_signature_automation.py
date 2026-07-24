"""Add generated-contract signature state and source entity links.

The columns are additive and all historical rows remain ``unsigned``. No
name-based backfill is attempted: legacy rows are linked explicitly when a
trusted user confirms the signature.

Revision ID: 0195_b2b_signature_automation
Revises: 0194_match_score_invalidations
"""

from alembic import op


revision = "0195_b2b_signature_automation"
down_revision = "0194_match_score_invalidations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Production bootstrapping mirrors this additive DDL in entrypoint.sh
    # because some installations cannot yet rely on Alembic being current.
    # Every statement must therefore tolerate the safety-net having run first.
    op.execute(
        """
        ALTER TABLE b2b_generated_contracts
            ADD COLUMN IF NOT EXISTS signature_status VARCHAR(32)
                NOT NULL DEFAULT 'unsigned',
            ADD COLUMN IF NOT EXISTS signature_source VARCHAR(32) NULL,
            ADD COLUMN IF NOT EXISTS candidate_id INTEGER NULL,
            ADD COLUMN IF NOT EXISTS job_id INTEGER NULL,
            ADD COLUMN IF NOT EXISTS client_id INTEGER NULL,
            ADD COLUMN IF NOT EXISTS contract_id INTEGER NULL,
            ADD COLUMN IF NOT EXISTS signed_at TIMESTAMPTZ NULL,
            ADD COLUMN IF NOT EXISTS signed_by_user_id INTEGER NULL
        """
    )

    op.execute(
        """
        DO $$ BEGIN
            ALTER TABLE b2b_generated_contracts
                ADD CONSTRAINT ck_b2b_generated_contracts_signature_status
                CHECK (signature_status IN ('unsigned', 'signed_both'))
                NOT VALID;
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$
        """
    )
    op.execute(
        """
        DO $$ BEGIN
            ALTER TABLE b2b_generated_contracts
                ADD CONSTRAINT ck_b2b_generated_contracts_signature_source
                CHECK (
                    signature_source IS NULL
                    OR signature_source IN (
                        'manual_confirmation',
                        'validated_upload'
                    )
                )
                NOT VALID;
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$
        """
    )
    op.execute(
        """
        DO $$ BEGIN
            ALTER TABLE b2b_generated_contracts
                ADD CONSTRAINT fk_b2b_generated_contracts_candidate_id
                FOREIGN KEY (candidate_id) REFERENCES candidates (id)
                ON DELETE SET NULL NOT VALID;
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$
        """
    )
    op.execute(
        """
        DO $$ BEGIN
            ALTER TABLE b2b_generated_contracts
                ADD CONSTRAINT fk_b2b_generated_contracts_job_id
                FOREIGN KEY (job_id) REFERENCES jobs (id)
                ON DELETE SET NULL NOT VALID;
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$
        """
    )
    op.execute(
        """
        DO $$ BEGIN
            ALTER TABLE b2b_generated_contracts
                ADD CONSTRAINT fk_b2b_generated_contracts_client_id
                FOREIGN KEY (client_id) REFERENCES clients (id)
                ON DELETE SET NULL NOT VALID;
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$
        """
    )
    op.execute(
        """
        DO $$ BEGIN
            ALTER TABLE b2b_generated_contracts
                ADD CONSTRAINT fk_b2b_generated_contracts_contract_id
                FOREIGN KEY (contract_id) REFERENCES contracts (id)
                ON DELETE RESTRICT NOT VALID;
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$
        """
    )
    op.execute(
        """
        DO $$ BEGIN
            ALTER TABLE b2b_generated_contracts
                ADD CONSTRAINT fk_b2b_generated_contracts_signed_by_user_id
                FOREIGN KEY (signed_by_user_id) REFERENCES users (id)
                ON DELETE SET NULL NOT VALID;
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$
        """
    )

    # The entrypoint safety-net intentionally creates constraints NOT VALID to
    # keep startup bounded. Once Alembic reaches this revision, validate both
    # pre-existing and newly-created constraints.
    for constraint in (
        "ck_b2b_generated_contracts_signature_status",
        "ck_b2b_generated_contracts_signature_source",
        "fk_b2b_generated_contracts_candidate_id",
        "fk_b2b_generated_contracts_job_id",
        "fk_b2b_generated_contracts_client_id",
        "fk_b2b_generated_contracts_contract_id",
        "fk_b2b_generated_contracts_signed_by_user_id",
    ):
        op.execute(
            f"""
            ALTER TABLE b2b_generated_contracts
                VALIDATE CONSTRAINT {constraint}
            """
        )

    for column in (
        "candidate_id",
        "job_id",
        "client_id",
        "contract_id",
        "signed_by_user_id",
    ):
        op.execute(
            f"""
            CREATE INDEX IF NOT EXISTS ix_b2b_generated_contracts_{column}
                ON b2b_generated_contracts ({column})
            """
        )


def downgrade() -> None:
    for column in (
        "signed_by_user_id",
        "contract_id",
        "client_id",
        "job_id",
        "candidate_id",
    ):
        op.execute(f"DROP INDEX IF EXISTS ix_b2b_generated_contracts_{column}")

    for constraint in (
        "fk_b2b_generated_contracts_signed_by_user_id",
        "fk_b2b_generated_contracts_contract_id",
        "fk_b2b_generated_contracts_client_id",
        "fk_b2b_generated_contracts_job_id",
        "fk_b2b_generated_contracts_candidate_id",
        "ck_b2b_generated_contracts_signature_source",
        "ck_b2b_generated_contracts_signature_status",
    ):
        op.execute(
            f"""
            ALTER TABLE IF EXISTS b2b_generated_contracts
                DROP CONSTRAINT IF EXISTS {constraint}
            """
        )

    for column in (
        "signed_by_user_id",
        "signed_at",
        "contract_id",
        "client_id",
        "job_id",
        "candidate_id",
        "signature_source",
        "signature_status",
    ):
        op.execute(
            f"""
            ALTER TABLE IF EXISTS b2b_generated_contracts
                DROP COLUMN IF EXISTS {column}
            """
        )
