"""0428: tabela plików rekrutacji ma lustro w entrypoincie (prod alembic bywa
osierocony) — PO tabeli formularzy, na którą wskazuje klucz obcy — sondę
w ``/api/health/deep``, a model zgadza się z DDL."""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

from app.services import job_file_schema

BACKEND = Path(__file__).resolve().parents[1]
MIGRATION = BACKEND / "alembic" / "versions" / "0428_job_files.py"


def _migration_module():
    spec = importlib.util.spec_from_file_location("m0427", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_migration_chains_after_framework_contract_text() -> None:
    module = _migration_module()
    assert module.revision == "0428_job_files"
    assert module.down_revision == "0427_user_email_opt_outs"
    assert "schema.ALL_DDL" in MIGRATION.read_text(encoding="utf-8")


def test_entrypoint_mirrors_every_statement_after_the_forms_table() -> None:
    entrypoint = (BACKEND / "entrypoint.sh").read_text(encoding="utf-8")
    forms_table = entrypoint.index("CREATE TABLE IF NOT EXISTS job_intake_forms (")
    for statement in job_file_schema.ALL_DDL:
        assert statement in entrypoint, statement
        assert entrypoint.index(statement) > forms_table, statement


def test_ddl_is_idempotent() -> None:
    for statement in job_file_schema.ALL_DDL:
        assert "IF NOT EXISTS" in re.sub(r"\s+", " ", statement), statement


def test_model_columns_match_the_ddl() -> None:
    from app.models.job_file import JobFile

    table = job_file_schema.TABLE_DDL
    for column in JobFile.__table__.columns.keys():
        assert re.search(rf"\b{column}\b", table), column
    # Rekrutacja zabiera swoje pliki; formularz i autor tylko się odpinają.
    assert "job_id INTEGER NULL REFERENCES jobs(id) ON DELETE CASCADE" in table
    assert (
        "intake_form_id INTEGER NULL REFERENCES job_intake_forms(id) ON DELETE SET NULL"
        in table
    )
    assert "uploaded_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL" in table
    width = JobFile.__table__.columns["source"].type.length
    assert all(len(source) <= width for source in job_file_schema.SOURCES)
    for source in job_file_schema.SOURCES:
        assert f"'{source}'" in table


def test_health_deep_probes_the_table_and_model_is_registered() -> None:
    main = (BACKEND / "app" / "main.py").read_text(encoding="utf-8")
    assert '("job_files", JobFile)' in main
    assert "app.include_router(job_files_api.router" in main
    models = (BACKEND / "app" / "models" / "__init__.py").read_text(encoding="utf-8")
    assert "from app.models.job_file import JobFile" in models
