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
    assert added == {name for name in model_columns if name.startswith("text_")}

    table = TABLE_DDL[0]
    for column in ClientFrameworkContractChunk.__table__.columns.keys():
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
