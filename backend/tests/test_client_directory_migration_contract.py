"""Contract tests for the additive client-directory schema.

The hosted backend job performs the real PostgreSQL upgrade/downgrade cycle.
These fast checks pin the parts that are easiest to regress during review:

* the Alembic migration, ORM and startup safety-net describe the same schema;
* failed or rolled-back imports do not reserve a workbook hash forever;
* imported MSA periods cannot end before they start;
* the new enum value is committed before it can be used; and
* downgrade removes only schema introduced by revision 0205.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path


BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
MIGRATION = BACKEND / "alembic/versions/0205_client_directory_portfolio.py"
MIGRATION_0215 = BACKEND / "alembic/versions/0215_client_portfolio_scope_overrides.py"
ENTRYPOINT = BACKEND / "entrypoint.sh"
DIRECTORY_MODEL = BACKEND / "app/models/client_directory.py"
MSA_MODEL = BACKEND / "app/models/client_framework_contract.py"
MODELS_INIT = BACKEND / "app/models/__init__.py"
CI = ROOT / ".github/workflows/ci.yml"

TABLES = {
    "client_import_runs",
    "client_portfolio_scopes",
    "client_aliases",
    "client_import_rows",
}

INDEXES = {
    "ux_client_import_runs_applied_source_sha256",
    "ix_client_import_runs_status",
    "ux_client_framework_contracts_source_key",
    "ix_client_framework_contracts_import_run_id",
    "ux_client_portfolio_scopes_framework_contract_active",
    "ux_client_portfolio_scopes_source_key_active",
    "ix_client_portfolio_scopes_category_label_active",
    "ix_client_portfolio_scopes_client_id",
    "ux_client_aliases_source_key",
    "ix_client_aliases_client_id",
    "ix_client_aliases_normalized_alias",
    "ix_client_import_rows_import_run_id",
    "ix_client_import_rows_matched_client_id",
    "ix_client_import_rows_status",
}

CONSTRAINTS = {
    "fk_clients_merged_into_client_id",
    "fk_clients_archived_by",
    "ck_clients_not_merged_into_self",
    "ck_client_import_runs_status",
    "ck_client_import_runs_source_system_nonempty",
    "ck_client_import_runs_source_sha256",
    "fk_client_framework_contracts_import_run_id",
    "ck_client_framework_contracts_dates",
    "ck_client_framework_contracts_source_system_nonempty",
    "ck_client_framework_contracts_source_key_nonempty",
    "ck_client_portfolio_scopes_label_nonempty",
    "ck_client_portfolio_scopes_source_system_nonempty",
    "ck_client_portfolio_scopes_source_key_nonempty",
    "uq_client_aliases_client_normalized",
    "ck_client_aliases_alias_nonempty",
    "ck_client_aliases_normalized_nonempty",
    "ck_client_aliases_source_system_nonempty",
    "ck_client_aliases_source_key_nonempty",
    "uq_client_import_rows_sheet_row",
    "ck_client_import_rows_row_number_positive",
    "ck_client_import_rows_source_name_nonempty",
    "ck_client_import_rows_status",
    "ck_client_import_rows_match_confidence",
    "ck_client_import_rows_dates",
}


def _literal_assignment(tree: ast.Module, name: str) -> object:
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == name
            for target in node.targets
        ):
            return ast.literal_eval(node.value)
    raise AssertionError(f"missing assignment {name}")


def _node_source(source: str, node: ast.AST) -> str:
    value = ast.get_source_segment(source, node)
    assert value is not None
    return value


def _function_source(source: str, name: str) -> str:
    tree = ast.parse(source)
    node = next(
        item
        for item in tree.body
        if isinstance(item, ast.FunctionDef) and item.name == name
    )
    return _node_source(source, node)


def _class_source(source: str, name: str) -> str:
    tree = ast.parse(source)
    node = next(
        item
        for item in tree.body
        if isinstance(item, ast.ClassDef) and item.name == name
    )
    return _node_source(source, node)


def _normalise_sql(source: str) -> str:
    return re.sub(r"\s+", " ", source).strip()


def _named_check_expression(model_source: str, constraint_name: str) -> str:
    tree = ast.parse(model_source)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Name) or node.func.id != "CheckConstraint":
            continue
        name = next(
            (
                ast.literal_eval(keyword.value)
                for keyword in node.keywords
                if keyword.arg == "name"
            ),
            None,
        )
        if name == constraint_name:
            return ast.literal_eval(node.args[0])
    raise AssertionError(f"missing model check constraint {constraint_name}")


def test_revision_is_linear_and_upgrade_is_additive() -> None:
    source = MIGRATION.read_text(encoding="utf-8")
    tree = ast.parse(source)

    assert _literal_assignment(tree, "revision") == ("0205_client_directory_portfolio")
    assert _literal_assignment(tree, "down_revision") == (
        "0204_candidate_activity_summaries"
    )

    upgrade = _function_source(source, "upgrade").lower()
    assert "drop table" not in upgrade
    assert "drop column" not in upgrade
    assert "delete from" not in upgrade
    assert "update clients" not in upgrade
    assert "update client_framework_contracts" not in upgrade

    for table in TABLES:
        assert f"create table if not exists {table}" in upgrade
    for column in (
        "merged_into_client_id",
        "archived_at",
        "archived_by",
        "source_system",
        "source_key",
        "import_run_id",
    ):
        assert f"add column if not exists {column}" in upgrade


def test_applied_hash_uniqueness_is_partial_and_retry_safe() -> None:
    migration = _normalise_sql(MIGRATION.read_text(encoding="utf-8"))
    entrypoint = _normalise_sql(ENTRYPOINT.read_text(encoding="utf-8"))
    directory_model = DIRECTORY_MODEL.read_text(encoding="utf-8")
    run_model = _class_source(directory_model, "ClientImportRun")
    run_status_model = _class_source(directory_model, "ClientImportRunStatus")

    for label, source in (("migration", migration), ("entrypoint", entrypoint)):
        for token in (
            "CREATE UNIQUE INDEX IF NOT EXISTS",
            "ux_client_import_runs_applied_source_sha256",
            "ON client_import_runs (source_system, source_sha256)",
            "WHERE status = 'applied'",
        ):
            assert token.lower() in source.lower(), (
                f"{label} lost the applied-only workbook hash guard: {token}"
            )
        assert (
            "DROP CONSTRAINT IF EXISTS uq_client_import_runs_source_sha256" in source
        ), f"{label} would leave the old all-status uniqueness constraint"
        assert "UNIQUE (source_system, source_sha256)" not in source, (
            f"{label} would block failed/rolled-back retries"
        )

    assert '"ux_client_import_runs_applied_source_sha256"' in run_model
    assert "unique=True" in run_model
    assert "postgresql_where=text(\"status = 'applied'\")" in run_model
    assert "UniqueConstraint(" not in run_model
    for retryable_terminal_status in ("rolled_back", "failed"):
        assert retryable_terminal_status in run_status_model


def test_msa_date_constraint_and_import_provenance_match_every_layer() -> None:
    migration = _normalise_sql(MIGRATION.read_text(encoding="utf-8"))
    entrypoint = _normalise_sql(ENTRYPOINT.read_text(encoding="utf-8"))
    msa_model = MSA_MODEL.read_text(encoding="utf-8")
    model_check = _normalise_sql(
        _named_check_expression(msa_model, "ck_client_framework_contracts_dates")
    )
    expected_check = (
        "effective_date IS NULL OR expiry_date IS NULL OR expiry_date >= effective_date"
    )

    assert expected_check in model_check
    for label, source in (("migration", migration), ("entrypoint", entrypoint)):
        assert "ck_client_framework_contracts_dates" in source
        assert "effective_date is null or expiry_date is null" in source.lower(), (
            f"{label} date invariant lost its nullable-date semantics"
        )
        assert "expiry_date >= effective_date" in source.lower(), (
            f"{label} date invariant no longer rejects reversed periods"
        )
        for column in ("source_system", "source_key", "import_run_id"):
            assert f"ADD COLUMN IF NOT EXISTS {column}".lower() in source.lower(), (
                f"{label} is missing MSA provenance column {column}"
            )

    assert "ux_client_framework_contracts_source_key" in msa_model
    assert "source_key IS NOT NULL" in msa_model
    assert 'ForeignKey("client_import_runs.id", ondelete="SET NULL")' in msa_model


def test_legacy_import_enum_is_created_before_any_imported_msa_can_use_it() -> None:
    migration = MIGRATION.read_text(encoding="utf-8")
    entrypoint = ENTRYPOINT.read_text(encoding="utf-8")
    msa_model = MSA_MODEL.read_text(encoding="utf-8")

    assert 'legacy_import = "legacy_import"' in msa_model
    assert "autocommit_block" in migration
    for label, source in (("migration", migration), ("entrypoint", entrypoint)):
        assert "CREATE TYPE frameworkcontractsignedvia AS ENUM" in source
        assert source.index("frameworkcontractsignedvia") < source.index(
            "CREATE TABLE IF NOT EXISTS client_import_runs"
        ), f"{label} creates portfolio tables before repairing the MSA enum"

    assert '"frameworkcontractsignedvia": ("upload", "autenti", "legacy_import")' in (
        migration
    )
    assert "ALTER TYPE {enum_name} ADD VALUE IF NOT EXISTS" in migration
    assert (
        "ALTER TYPE frameworkcontractsignedvia ADD VALUE IF NOT EXISTS 'legacy_import'"
    ) in entrypoint


def test_startup_safety_net_mirrors_migration_objects_and_order() -> None:
    migration = MIGRATION.read_text(encoding="utf-8")
    entrypoint = ENTRYPOINT.read_text(encoding="utf-8")

    for table in TABLES:
        token = f"CREATE TABLE IF NOT EXISTS {table}"
        assert token in migration
        assert token in entrypoint
    for name in INDEXES | CONSTRAINTS:
        assert name in migration, f"migration is missing {name}"
        assert name in entrypoint, f"entrypoint mirror is missing {name}"

    for source in (migration, entrypoint):
        assert source.index("CREATE TABLE IF NOT EXISTS client_import_runs") < (
            source.index("REFERENCES client_import_runs(id)")
        )
        assert source.index("CREATE TABLE IF NOT EXISTS client_portfolio_scopes") < (
            source.index("CREATE TABLE IF NOT EXISTS client_import_rows")
        )
        assert source.index("CREATE TYPE clientportfoliocategory AS ENUM") < (
            source.index("clientportfoliocategory NOT NULL")
        )

    # Existing installations are changed with retry-safe ALTER statements.
    for source in (migration, entrypoint):
        assert "ADD COLUMN IF NOT EXISTS merged_into_client_id" in source
        assert "ADD COLUMN IF NOT EXISTS source_system" in source
        assert "EXCEPTION WHEN duplicate_object THEN NULL" in source


def test_models_register_all_tables_for_metadata_safety_net() -> None:
    models_init = MODELS_INIT.read_text(encoding="utf-8")
    directory_model = DIRECTORY_MODEL.read_text(encoding="utf-8")

    for model in (
        "ClientImportRun",
        "ClientImportRow",
        "ClientPortfolioScope",
        "ClientAlias",
    ):
        assert model in models_init
        assert f"class {model}(" in directory_model


def test_downgrade_respects_fk_order_and_preserves_shared_enum() -> None:
    source = MIGRATION.read_text(encoding="utf-8")
    downgrade = _function_source(source, "downgrade")

    assert downgrade.index("DROP TABLE IF EXISTS client_import_rows") < (
        downgrade.index("DROP TABLE IF EXISTS client_portfolio_scopes")
    )
    assert downgrade.index("fk_client_framework_contracts_import_run_id") < (
        downgrade.index("DROP TABLE IF EXISTS client_import_runs")
    )
    assert downgrade.index(
        'for column in ("import_run_id", "source_key", "source_system")'
    ) < downgrade.index("DROP TABLE IF EXISTS client_import_runs")
    assert downgrade.index("DROP TABLE IF EXISTS client_import_runs") < (
        downgrade.index(
            'for column in ("archived_by", "archived_at", "merged_into_client_id")'
        )
    )
    assert "DROP TYPE IF EXISTS clientportfoliocategory" in downgrade
    assert "DROP TYPE IF EXISTS frameworkcontractsignedvia" not in downgrade

    for column in ("import_run_id", "source_key", "source_system"):
        assert f'"{column}"' in downgrade
    for column in ("archived_by", "archived_at", "merged_into_client_id"):
        assert f'"{column}"' in downgrade


def test_placement_override_columns_parity_across_layers() -> None:
    """0215's override columns + date CHECK must exist identically in the
    migration, the startup safety-net and the ORM model. Prod alembic is
    orphaned, so entrypoint.sh is the live authority — a drift here would
    silently drop the override columns on prod while migration-only CI stays
    green (the same failure mode this file already guards for 0205)."""
    migration = _normalise_sql(MIGRATION_0215.read_text(encoding="utf-8")).lower()
    entrypoint = _normalise_sql(ENTRYPOINT.read_text(encoding="utf-8")).lower()
    model = DIRECTORY_MODEL.read_text(encoding="utf-8")

    for column in (
        "category_override",
        "contract_start_override",
        "contract_end_override",
    ):
        add_clause = f"add column if not exists {column}"
        assert add_clause in migration, f"0215 migration missing column {column}"
        assert add_clause in entrypoint, (
            f"entrypoint safety-net missing column {column}"
        )
        assert column in model, f"model missing column {column}"

    constraint = "ck_client_portfolio_scopes_override_dates"
    check_expr = "contract_end_override >= contract_start_override"
    for label, source in (("migration", migration), ("entrypoint", entrypoint)):
        assert constraint in source, f"{label} missing override-date constraint"
        assert check_expr in source, f"{label} lost the override-date invariant"
    model_check = _normalise_sql(_named_check_expression(model, constraint))
    assert check_expr in model_check


def test_hosted_ci_runs_fresh_retry_downgrade_and_reupgrade_cycle() -> None:
    workflow = _normalise_sql(CI.read_text(encoding="utf-8"))

    # The PostgreSQL service starts empty. The first upgrade reaches 0205,
    # the immediate second run proves idempotency, then CI rolls back below
    # this revision and upgrades to heads again.
    double_upgrade = (
        "alembic -c alembic/alembic.ini upgrade heads "
        "alembic -c alembic/alembic.ini upgrade heads"
    )
    assert double_upgrade in workflow
    assert "alembic -c alembic/alembic.ini downgrade 0199_candidate_stage_removals" in (
        workflow
    )
    assert workflow.count("alembic -c alembic/alembic.ini upgrade heads") >= 3
