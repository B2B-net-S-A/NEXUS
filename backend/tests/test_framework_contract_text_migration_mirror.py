"""0426: tabela fragmentów umów i kolumny stanu odczytu mają lustro
w entrypoincie i sondę w ``/api/health/deep`` (prod alembic bywa osierocony),
a model zgadza się z DDL."""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
MIGRATION = BACKEND / "alembic" / "versions" / "0426_framework_contract_text.py"


def _migration_module():
    spec = importlib.util.spec_from_file_location("m0426", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_migration_chains_after_daily_digest_opt_out() -> None:
    module = _migration_module()
    assert module.revision == "0426_framework_contract_text"
    assert module.down_revision == "0425_daily_digest_opt_out"
    assert "schema.ALL_DDL" in MIGRATION.read_text(encoding="utf-8")


def test_entrypoint_imports_the_single_ddl_source() -> None:
    text = (BACKEND / "entrypoint.sh").read_text(encoding="utf-8")
    assert "from app.services import framework_contract_text_schema as _fc_text" in text
    columns = text.index("_COLUMN_STATEMENTS = [")
    data = text.index("_DATA_STATEMENTS = [")
    assert columns < text.index("*_FC_TEXT_DDL,") < data


def test_ddl_is_idempotent_and_alters_before_creating() -> None:
    from app.services.framework_contract_text_schema import ALL_DDL, COLUMN_DDL

    for statement in ALL_DDL:
        assert "IF NOT EXISTS" in re.sub(r"\s+", " ", statement), statement
    assert ALL_DDL[: len(COLUMN_DDL)] == COLUMN_DDL


def test_model_columns_match_the_ddl() -> None:
    from app.models.client_framework_contract import ClientFrameworkContract
    from app.models.client_framework_contract_chunk import (
        ClientFrameworkContractChunk,
    )
    from app.services.framework_contract_text_schema import COLUMN_DDL, TABLE_DDL

    added = {
        re.search(r"ADD COLUMN IF NOT EXISTS (\w+)", statement).group(1)
        for statement in COLUMN_DDL
    }
    model_columns = set(ClientFrameworkContract.__table__.columns.keys())
    assert added <= model_columns
    # `text_ocr_pages` doszła w 0627 (AMENDMENT_COLUMN_DDL).
    assert added == {name for name in model_columns if name.startswith("text_")} - {
        "text_ocr_pages"
    }

    table = TABLE_DDL[0]
    for column in ClientFrameworkContractChunk.__table__.columns.keys():
        if column != "amendment_id":  # doszła w 0627
            assert re.search(rf"\b{column}\b", table), column
    assert "ON DELETE CASCADE" in table
    assert "uq_client_framework_contract_chunks_position" in table


def test_every_status_the_code_writes_fits_the_column() -> None:
    from app.models.client_framework_contract import ClientFrameworkContract
    from app.services.framework_contract_text_schema import STATUSES

    width = ClientFrameworkContract.__table__.columns["text_status"].type.length
    assert all(len(status) <= width for status in STATUSES)


def test_health_deep_probes_both_tables_and_model_is_registered() -> None:
    main = (BACKEND / "app" / "main.py").read_text(encoding="utf-8")
    assert '("client_framework_contracts", ClientFrameworkContract)' in main
    assert '("client_framework_contract_chunks", ClientFrameworkContractChunk)' in main
    models = (BACKEND / "app" / "models" / "__init__.py").read_text(encoding="utf-8")
    assert "from app.models.client_framework_contract_chunk import" in models


def test_0627_chains_after_cover_sheets_and_mirrors_the_single_source() -> None:
    from app.models.client_contract_amendment import ClientContractAmendment
    from app.models.client_framework_contract_chunk import (
        ClientFrameworkContractChunk,
    )
    from app.services.framework_contract_text_schema import (
        AMENDMENT_ALL_DDL,
        AMENDMENT_COLUMN_DDL,
    )

    migration = BACKEND / "alembic" / "versions" / "0627_client_amendment_text.py"
    source = migration.read_text(encoding="utf-8")
    assert 'revision = "0627_client_amendment_text"' in source
    assert 'down_revision = "0626_client_cover_sheet_templates"' in source
    assert "schema.AMENDMENT_ALL_DDL" in source
    entrypoint = (BACKEND / "entrypoint.sh").read_text(encoding="utf-8")
    assert "*_fc_text.AMENDMENT_ALL_DDL" in entrypoint
    for statement in AMENDMENT_ALL_DDL:
        assert "IF NOT EXISTS" in statement or "IF EXISTS" in statement, statement
    amendment_columns = {
        statement.split("ADD COLUMN IF NOT EXISTS ")[1].split()[0]
        for statement in AMENDMENT_COLUMN_DDL
        if "client_contract_amendments " in statement
    }
    model_columns = set(ClientContractAmendment.__table__.columns.keys())
    assert amendment_columns == {c for c in model_columns if c.startswith("text_")}
    assert "amendment_id" in ClientFrameworkContractChunk.__table__.columns


def test_health_deep_probes_the_amendment_columns() -> None:
    main = (BACKEND / "app" / "main.py").read_text(encoding="utf-8")
    assert '("client_contract_amendments", ClientContractAmendment)' in main
