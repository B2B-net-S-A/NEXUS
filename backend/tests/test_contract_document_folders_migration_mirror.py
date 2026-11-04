"""0494: DDL folderów w Dokumentach kontraktu ma lustro w entrypoincie
(produkcyjny alembic bywa osierocony)."""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
MIGRATION = BACKEND / "alembic" / "versions" / "0494_contract_document_folders.py"


def _migration_module():
    spec = importlib.util.spec_from_file_location("m0492", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_migration_uses_the_single_ddl_source() -> None:
    from app.services.contract_document_folders_schema import TABLE_DDL

    module = _migration_module()
    assert module.revision == "0494_contract_document_folders"
    assert module.TABLE_DDL is TABLE_DDL


def test_entrypoint_imports_the_single_ddl_source() -> None:
    text = (BACKEND / "entrypoint.sh").read_text()
    assert "from app.services import contract_document_folders_schema" in text
    assert "*_CONTRACT_DOC_FOLDERS_DDL," in text


def test_ddl_is_idempotent() -> None:
    from app.services.contract_document_folders_schema import TABLE_DDL

    for statement in TABLE_DDL:
        assert "IF NOT EXISTS" in re.sub(r"\s+", " ", statement), statement


def test_folders_table_precedes_the_column_that_references_it() -> None:
    from app.services.contract_document_folders_schema import TABLE_DDL

    joined = [re.sub(r"\s+", " ", s) for s in TABLE_DDL]
    table = next(
        i
        for i, s in enumerate(joined)
        if "CREATE TABLE IF NOT EXISTS contract_document_folders" in s
    )
    column = next(
        i for i, s in enumerate(joined) if "ADD COLUMN IF NOT EXISTS folder_id" in s
    )
    assert table < column


def test_folder_delete_releases_files_instead_of_deleting_them() -> None:
    from app.services.contract_document_folders_schema import TABLE_DDL

    column = next(s for s in TABLE_DDL if "folder_id" in s and "ADD COLUMN" in s)
    assert "ON DELETE SET NULL" in column


def test_kind_check_matches_the_service() -> None:
    from app.services.contract_document_folders_schema import FOLDER_KINDS, TABLE_DDL

    ddl = " ".join(TABLE_DDL)
    for kind in FOLDER_KINDS:
        assert f"'{kind}'" in ddl


def test_deep_health_probes_the_new_table() -> None:
    text = (BACKEND / "app" / "main.py").read_text()
    assert '("contract_document_folders", ContractDocumentFolder)' in text
