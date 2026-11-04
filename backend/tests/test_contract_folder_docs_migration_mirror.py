"""0402: DDL dokumentów kontraktów z SharePointa ma lustro w entrypoincie
i sondy w `/api/health/deep` (prod alembic bywa osierocony)."""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
MIGRATION = BACKEND / "alembic" / "versions" / "0402_contract_docs_sharepoint.py"


def _migration_module():
    spec = importlib.util.spec_from_file_location("m0402", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_migration_chains_after_annex_rates() -> None:
    module = _migration_module()
    assert module.revision == "0402_contract_docs_sharepoint"
    assert module.down_revision == "0401_b2b_annex_rates"


def test_entrypoint_imports_the_single_ddl_source() -> None:
    text = (BACKEND / "entrypoint.sh").read_text()
    assert "from app.services.contract_folder_docs import schema_sql" in text
    assert "*_CONTRACT_DOCS_SP_DDL," in text


def test_ddl_is_idempotent() -> None:
    from app.services.contract_folder_docs.schema_sql import TABLE_DDL

    for statement in TABLE_DDL:
        assert "IF NOT EXISTS" in re.sub(r"\s+", " ", statement), statement


def test_runs_table_precedes_the_column_that_references_it() -> None:
    from app.services.contract_folder_docs.schema_sql import TABLE_DDL

    joined = [re.sub(r"\s+", " ", s) for s in TABLE_DDL]
    runs = next(
        i
        for i, s in enumerate(joined)
        if "CREATE TABLE IF NOT EXISTS contract_doc_sp_runs" in s
    )
    column = next(
        i for i, s in enumerate(joined) if "ADD COLUMN IF NOT EXISTS import_run_id" in s
    )
    assert runs < column


def test_status_checks_match_the_model() -> None:
    from app.models.contract_doc_sharepoint import ITEM_STATUSES, RUN_MODES
    from app.services.contract_folder_docs.schema_sql import TABLE_DDL

    ddl = " ".join(TABLE_DDL)
    for value in (*RUN_MODES, *ITEM_STATUSES):
        assert f"'{value}'" in ddl, value


def test_deep_health_probes_the_new_tables() -> None:
    text = (BACKEND / "app" / "main.py").read_text()
    assert '("contract_doc_sp_runs", ContractDocSpRun)' in text
    assert '("contract_doc_sp_items", ContractDocSpItem)' in text
