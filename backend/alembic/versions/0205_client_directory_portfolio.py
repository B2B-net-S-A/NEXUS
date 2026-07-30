"""Add the local client directory, import audit and MSA provenance.

Revision ID: 0205_client_directory_portfolio
Revises: 0204_candidate_activity_summaries
Create Date: 2026-07-30

The migration is additive and does not derive portfolio state from the legacy
``clients.status`` field.  That separation is intentional: Traffit-facing
operational state remains untouched, while the local directory can represent
one row per MSA period.

Excel data lands in reviewable import-run/row tables.  Applying a run may add
aliases, create/update MSA provenance and create portfolio scopes, but the
migration itself does not mutate any client business data.
"""

from alembic import op


revision = "0205_client_directory_portfolio"
down_revision = "0204_candidate_activity_summaries"
branch_labels = None
depends_on = None


_ENUM_CREATE_STATEMENTS = (
    """
    DO $$
    BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM pg_type WHERE typname = 'clientportfoliocategory'
        ) THEN
            CREATE TYPE clientportfoliocategory AS ENUM (
                'active', 'relationship', 'inactive'
            );
        END IF;
    END $$
    """,
    # The type normally exists since 0087.  Keeping this guard makes the
    # production safety-net and a partially restored database converge.
    """
    DO $$
    BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM pg_type WHERE typname = 'frameworkcontractsignedvia'
        ) THEN
            CREATE TYPE frameworkcontractsignedvia AS ENUM (
                'upload', 'autenti', 'legacy_import'
            );
        END IF;
    END $$
    """,
)

_ENUM_VALUES = {
    "clientportfoliocategory": ("active", "relationship", "inactive"),
    "frameworkcontractsignedvia": ("upload", "autenti", "legacy_import"),
}


def _add_constraint(table: str, name: str, definition: str) -> None:
    op.execute(
        f"""
        DO $$ BEGIN
            ALTER TABLE {table}
                ADD CONSTRAINT {name} {definition};
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$
        """
    )


def upgrade() -> None:
    for statement in _ENUM_CREATE_STATEMENTS:
        op.execute(statement)

    # Commit CREATE TYPE first and add every label outside the migration
    # transaction.  PostgreSQL does not allow a newly-added enum label to be
    # referenced by a table default until that label has been committed.
    with op.get_context().autocommit_block():
        for enum_name, values in _ENUM_VALUES.items():
            for value in values:
                op.execute(f"ALTER TYPE {enum_name} ADD VALUE IF NOT EXISTS '{value}'")

    # Canonicalisation is soft: a duplicate may point at the retained client,
    # while the source row and all historical references remain queryable.
    op.execute(
        """
        ALTER TABLE clients
            ADD COLUMN IF NOT EXISTS merged_into_client_id INTEGER NULL,
            ADD COLUMN IF NOT EXISTS archived_at TIMESTAMPTZ NULL,
            ADD COLUMN IF NOT EXISTS archived_by INTEGER NULL
        """
    )
    _add_constraint(
        "clients",
        "fk_clients_merged_into_client_id",
        "FOREIGN KEY (merged_into_client_id) REFERENCES clients(id) "
        "ON DELETE RESTRICT",
    )
    _add_constraint(
        "clients",
        "fk_clients_archived_by",
        "FOREIGN KEY (archived_by) REFERENCES users(id) ON DELETE SET NULL",
    )
    _add_constraint(
        "clients",
        "ck_clients_not_merged_into_self",
        "CHECK (merged_into_client_id IS NULL OR merged_into_client_id <> id) "
        "NOT VALID",
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_clients_merged_into_client_id "
        "ON clients (merged_into_client_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_clients_archived_at ON clients (archived_at)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_clients_archived_by ON clients (archived_by)"
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS client_import_runs (
            id              SERIAL PRIMARY KEY,
            source_system   VARCHAR(32) NOT NULL DEFAULT 'client_excel',
            source_filename VARCHAR(255) NOT NULL,
            source_sha256   VARCHAR(64) NOT NULL,
            status          VARCHAR(32) NOT NULL DEFAULT 'uploaded',
            summary         JSONB NOT NULL DEFAULT '{}'::jsonb,
            error_message   TEXT NULL,
            created_by      INTEGER NULL
                                REFERENCES users(id) ON DELETE SET NULL,
            approved_by     INTEGER NULL
                                REFERENCES users(id) ON DELETE SET NULL,
            approved_at     TIMESTAMPTZ NULL,
            applied_at      TIMESTAMPTZ NULL,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_client_import_runs_status CHECK (
                status IN (
                    'uploaded', 'reviewed', 'applying', 'applied',
                    'rolled_back', 'failed'
                )
            ),
            CONSTRAINT ck_client_import_runs_source_system_nonempty
                CHECK (char_length(btrim(source_system)) > 0),
            CONSTRAINT ck_client_import_runs_source_sha256
                CHECK (char_length(source_sha256) = 64)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_client_import_runs_status "
        "ON client_import_runs (status)"
    )
    # Failed/rolled-back attempts are durable audit records and must not block
    # a corrected retry.  Only one successfully applied run is allowed for a
    # source hash.
    op.execute(
        "ALTER TABLE client_import_runs "
        "DROP CONSTRAINT IF EXISTS uq_client_import_runs_source_sha256"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS "
        "ux_client_import_runs_applied_source_sha256 "
        "ON client_import_runs (source_system, source_sha256) "
        "WHERE status = 'applied'"
    )

    # The MSA dates are the source of truth for Start/Koniec umowy.  A
    # provenance key makes an import replay update the same agreement instead
    # of creating another one.
    op.execute(
        """
        ALTER TABLE client_framework_contracts
            ADD COLUMN IF NOT EXISTS source_system VARCHAR(32)
                NOT NULL DEFAULT 'manual',
            ADD COLUMN IF NOT EXISTS source_key VARCHAR(255) NULL,
            ADD COLUMN IF NOT EXISTS import_run_id INTEGER NULL
        """
    )
    _add_constraint(
        "client_framework_contracts",
        "fk_client_framework_contracts_import_run_id",
        "FOREIGN KEY (import_run_id) REFERENCES client_import_runs(id) "
        "ON DELETE SET NULL",
    )
    _add_constraint(
        "client_framework_contracts",
        "ck_client_framework_contracts_dates",
        "CHECK (effective_date IS NULL OR expiry_date IS NULL "
        "OR expiry_date >= effective_date) NOT VALID",
    )
    _add_constraint(
        "client_framework_contracts",
        "ck_client_framework_contracts_source_system_nonempty",
        "CHECK (char_length(btrim(source_system)) > 0) NOT VALID",
    )
    _add_constraint(
        "client_framework_contracts",
        "ck_client_framework_contracts_source_key_nonempty",
        "CHECK (source_key IS NULL OR char_length(btrim(source_key)) > 0) "
        "NOT VALID",
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_client_framework_contracts_import_run_id "
        "ON client_framework_contracts (import_run_id)"
    )
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS
            ux_client_framework_contracts_source_key
        ON client_framework_contracts (source_system, source_key)
        WHERE source_key IS NOT NULL
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS client_portfolio_scopes (
            id                      SERIAL PRIMARY KEY,
            client_id               INTEGER NOT NULL
                                        REFERENCES clients(id) ON DELETE CASCADE,
            framework_contract_id   INTEGER NULL
                                        REFERENCES client_framework_contracts(id)
                                        ON DELETE SET NULL,
            category                clientportfoliocategory NOT NULL
                                        DEFAULT 'inactive',
            label                   VARCHAR(255) NULL,
            source_system           VARCHAR(32) NOT NULL DEFAULT 'manual',
            source_key              VARCHAR(255) NULL,
            archived_at             TIMESTAMPTZ NULL,
            created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_client_portfolio_scopes_label_nonempty
                CHECK (label IS NULL OR char_length(btrim(label)) > 0),
            CONSTRAINT ck_client_portfolio_scopes_source_system_nonempty
                CHECK (char_length(btrim(source_system)) > 0),
            CONSTRAINT ck_client_portfolio_scopes_source_key_nonempty
                CHECK (
                    source_key IS NULL OR char_length(btrim(source_key)) > 0
                )
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_client_portfolio_scopes_client_id "
        "ON client_portfolio_scopes (client_id)"
    )
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS
            ux_client_portfolio_scopes_framework_contract_active
        ON client_portfolio_scopes (framework_contract_id)
        WHERE framework_contract_id IS NOT NULL AND archived_at IS NULL
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS
            ux_client_portfolio_scopes_source_key_active
        ON client_portfolio_scopes (source_system, source_key)
        WHERE source_key IS NOT NULL AND archived_at IS NULL
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS
            ix_client_portfolio_scopes_category_label_active
        ON client_portfolio_scopes (category, label)
        WHERE archived_at IS NULL
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS client_aliases (
            id                  SERIAL PRIMARY KEY,
            client_id           INTEGER NOT NULL
                                    REFERENCES clients(id) ON DELETE CASCADE,
            alias               VARCHAR(255) NOT NULL,
            normalized_alias    VARCHAR(255) NOT NULL,
            source_system       VARCHAR(32) NOT NULL DEFAULT 'manual',
            source_key          VARCHAR(255) NULL,
            created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_client_aliases_client_normalized
                UNIQUE (client_id, normalized_alias),
            CONSTRAINT ck_client_aliases_alias_nonempty
                CHECK (char_length(btrim(alias)) > 0),
            CONSTRAINT ck_client_aliases_normalized_nonempty
                CHECK (char_length(btrim(normalized_alias)) > 0),
            CONSTRAINT ck_client_aliases_source_system_nonempty
                CHECK (char_length(btrim(source_system)) > 0),
            CONSTRAINT ck_client_aliases_source_key_nonempty
                CHECK (
                    source_key IS NULL OR char_length(btrim(source_key)) > 0
                )
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_client_aliases_client_id "
        "ON client_aliases (client_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_client_aliases_normalized_alias "
        "ON client_aliases (normalized_alias)"
    )
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS ux_client_aliases_source_key
        ON client_aliases (source_system, source_key)
        WHERE source_key IS NOT NULL
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS client_import_rows (
            id                      SERIAL PRIMARY KEY,
            import_run_id           INTEGER NOT NULL
                                        REFERENCES client_import_runs(id)
                                        ON DELETE CASCADE,
            sheet_name              VARCHAR(255) NOT NULL,
            row_number              INTEGER NOT NULL,
            source_key              VARCHAR(255) NULL,
            source_name             VARCHAR(255) NOT NULL,
            normalized_name         VARCHAR(255) NULL,
            proposed_display_name   VARCHAR(255) NULL,
            proposed_legal_name     VARCHAR(255) NULL,
            category                clientportfoliocategory NOT NULL,
            start_date              DATE NULL,
            end_date                DATE NULL,
            status                  VARCHAR(32) NOT NULL DEFAULT 'pending',
            match_confidence        NUMERIC(5, 4) NULL,
            raw_payload             JSONB NOT NULL DEFAULT '{}'::jsonb,
            error_message           TEXT NULL,
            matched_client_id       INTEGER NULL
                                        REFERENCES clients(id) ON DELETE SET NULL,
            portfolio_scope_id      INTEGER NULL
                                        REFERENCES client_portfolio_scopes(id)
                                        ON DELETE SET NULL,
            framework_contract_id   INTEGER NULL
                                        REFERENCES client_framework_contracts(id)
                                        ON DELETE SET NULL,
            resolved_by             INTEGER NULL
                                        REFERENCES users(id) ON DELETE SET NULL,
            resolved_at             TIMESTAMPTZ NULL,
            created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_client_import_rows_sheet_row
                UNIQUE (import_run_id, sheet_name, row_number),
            CONSTRAINT ck_client_import_rows_row_number_positive
                CHECK (row_number >= 1),
            CONSTRAINT ck_client_import_rows_source_name_nonempty
                CHECK (char_length(btrim(source_name)) > 0),
            CONSTRAINT ck_client_import_rows_status CHECK (
                status IN (
                    'pending', 'matched', 'create', 'ambiguous',
                    'ignored', 'applied', 'failed'
                )
            ),
            CONSTRAINT ck_client_import_rows_match_confidence CHECK (
                match_confidence IS NULL
                OR (match_confidence >= 0 AND match_confidence <= 1)
            ),
            CONSTRAINT ck_client_import_rows_dates CHECK (
                start_date IS NULL OR end_date IS NULL OR end_date >= start_date
            )
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_client_import_rows_import_run_id "
        "ON client_import_rows (import_run_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_client_import_rows_matched_client_id "
        "ON client_import_rows (matched_client_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_client_import_rows_status "
        "ON client_import_rows (status)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS client_import_rows")
    op.execute("DROP TABLE IF EXISTS client_aliases")
    op.execute("DROP TABLE IF EXISTS client_portfolio_scopes")

    op.execute(
        "DROP INDEX IF EXISTS ux_client_framework_contracts_source_key"
    )
    op.execute(
        "DROP INDEX IF EXISTS ix_client_framework_contracts_import_run_id"
    )
    for constraint in (
        "ck_client_framework_contracts_source_key_nonempty",
        "ck_client_framework_contracts_source_system_nonempty",
        "ck_client_framework_contracts_dates",
        "fk_client_framework_contracts_import_run_id",
    ):
        op.execute(
            "ALTER TABLE IF EXISTS client_framework_contracts "
            f"DROP CONSTRAINT IF EXISTS {constraint}"
        )
    for column in ("import_run_id", "source_key", "source_system"):
        op.execute(
            "ALTER TABLE IF EXISTS client_framework_contracts "
            f"DROP COLUMN IF EXISTS {column}"
        )

    op.execute("DROP TABLE IF EXISTS client_import_runs")

    for index in (
        "ix_clients_archived_by",
        "ix_clients_archived_at",
        "ix_clients_merged_into_client_id",
    ):
        op.execute(f"DROP INDEX IF EXISTS {index}")
    for constraint in (
        "ck_clients_not_merged_into_self",
        "fk_clients_archived_by",
        "fk_clients_merged_into_client_id",
    ):
        op.execute(
            f"ALTER TABLE IF EXISTS clients DROP CONSTRAINT IF EXISTS {constraint}"
        )
    for column in ("archived_by", "archived_at", "merged_into_client_id"):
        op.execute(
            f"ALTER TABLE IF EXISTS clients DROP COLUMN IF EXISTS {column}"
        )

    op.execute("DROP TYPE IF EXISTS clientportfoliocategory")
    # PostgreSQL cannot remove a single enum label safely.  ``legacy_import``
    # is intentionally retained on downgrade; no row can reference it after
    # the provenance columns/tables above are removed.
