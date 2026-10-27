"""0521: formularz CV klienta — lustro w entrypoincie (alembic na prodzie bywa
osierocony), kolumny po tabeli ``job_files``, włączenie dla CEZ raz."""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

from app.models.client import Client
from app.services import client_form_schema as schema
from app.services.ezdrowie import EZDROWIE_CLIENT_ID

BACKEND = Path(__file__).resolve().parents[1]
MIGRATION = BACKEND / "alembic" / "versions" / "0521_client_form_documents.py"


def _migration():
    spec = importlib.util.spec_from_file_location("m0521", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_migration_chains_and_uses_the_shared_ddl() -> None:
    module = _migration()
    assert module.revision == "0521_client_form_documents"
    assert module.down_revision == "0520_talent_pool_team_visible"
    source = MIGRATION.read_text(encoding="utf-8")
    assert "schema.ALL_DDL" in source and "schema.DOWNGRADE_DDL" in source


def test_entrypoint_mirrors_every_statement_in_order() -> None:
    entrypoint = (BACKEND / "entrypoint.sh").read_text(encoding="utf-8")
    job_files_table = entrypoint.index("CREATE TABLE IF NOT EXISTS job_files (")
    for statement in schema.ALL_DDL:
        if statement in schema.SUPERSEDED_DDL:
            # 0525: indeks „jeden wzór na rekrutację” zastąpiony indeksem per
            # rodzaj — przy starcie wywróciłby się na Wordzie i Excelu naraz.
            assert statement not in entrypoint, statement
            continue
        assert statement in entrypoint, statement
        assert entrypoint.index(statement) > job_files_table, statement
    # Włączenie dla CEZ po dodaniu kolumny, w danych.
    assert entrypoint.index(schema.SEED_DDL) > entrypoint.index(
        schema.CLIENT_COLUMN_DDL
    )
    assert entrypoint.index(schema.SEED_DDL) > entrypoint.index("_DATA_STATEMENTS = [")


def test_ddl_is_idempotent_and_the_seed_runs_once() -> None:
    for statement in (schema.CLIENT_COLUMN_DDL, *schema.JOB_FILE_DDL):
        assert "IF NOT EXISTS" in re.sub(r"\s+", " ", statement), statement
    # Restart nie może cofnąć zmiany zrobionej później w edytorze reguły.
    assert f"WHERE key = '{schema.SEED_MARKER}'" in schema.SEED_DDL
    assert f"WHERE id = {EZDROWIE_CLIENT_ID};" in schema.SEED_DDL
    assert "ON CONFLICT (key) DO NOTHING" in schema.SEED_DDL


def test_one_template_of_each_kind_per_job_and_model_matches_the_ddl() -> None:
    from app.models.job_file import JobFile

    index = next(
        item
        for item in JobFile.__table__.indexes
        if item.name == "ux_job_files_client_form_kind"
    )
    assert index.unique
    assert [column.name for column in index.columns] == ["job_id", "client_form_kind"]
    assert any(
        "ux_job_files_client_form_kind ON job_files (job_id, client_form_kind)" in st
        for st in schema.SCORE_DDL
    )
    column = Client.__table__.columns["cv_client_document"]
    assert column.type.length >= max(len(value) for value in schema.CLIENT_DOCUMENTS)
    assert f"DEFAULT '{schema.COMPANY_CV}'" in schema.CLIENT_COLUMN_DDL


# ── 0522: wypełniony formularz pary + klucz AI ───────────────────────────────

MIGRATION_0522 = BACKEND / "alembic" / "versions" / "0522_candidate_client_forms.py"


def test_0522_chains_and_mirrors_table_key_and_probe() -> None:
    spec = importlib.util.spec_from_file_location("m0522", MIGRATION_0522)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    assert module.revision == "0522_candidate_client_forms"
    assert module.down_revision == "0523_client_job_opened_notification"
    assert "schema.FILL_DDL" in MIGRATION_0522.read_text(encoding="utf-8")

    entrypoint = (BACKEND / "entrypoint.sh").read_text(encoding="utf-8")
    job_files_columns = entrypoint.index(schema.JOB_FILE_DDL[0])
    for statement in schema.FILL_DDL:
        assert "IF NOT EXISTS" in statement, statement
        assert statement in entrypoint, statement
        assert entrypoint.index(statement) > job_files_columns, statement
    assert (
        "ALTER TYPE aifeaturekey ADD VALUE IF NOT EXISTS 'client_form_fill'"
        in entrypoint
    )
    assert "SELECT 'client_form_fill', TRUE, 0, now(), now() " in entrypoint

    main = (BACKEND / "app" / "main.py").read_text(encoding="utf-8")
    assert '("candidate_client_forms", CandidateClientForm)' in main
    assert "app.include_router(client_forms_api.router" in main


def test_0522_model_matches_the_ddl() -> None:
    from app.models.candidate_client_form import CandidateClientForm

    # 0525 dokłada rodzaj dokumentu osobnym ALTER TABLE.
    ddl = " ".join((schema.FILL_TABLE_DDL, *schema.SCORE_DDL))
    for column in CandidateClientForm.__table__.columns.keys():
        assert re.search(rf"\b{column}\b", ddl), column
    assert "UNIQUE (candidate_id, job_id)" in schema.FILL_TABLE_DDL
    assert "job_file_id INTEGER NULL REFERENCES job_files(id) ON DELETE SET NULL" in (
        schema.FILL_TABLE_DDL
    )


# ── 0525: tabela punktowa (Excel) obok formularza (Word) ─────────────────────

MIGRATION_0525 = BACKEND / "alembic" / "versions" / "0525_client_form_score_sheet.py"


def test_0525_chains_and_mirrors_every_statement_after_the_fill_table() -> None:
    spec = importlib.util.spec_from_file_location("m0525", MIGRATION_0525)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    assert module.revision == "0525_client_form_score_sheet"
    assert module.down_revision == "0524_agreement_admin_details"
    source = MIGRATION_0525.read_text(encoding="utf-8")
    assert "schema.SCORE_DDL" in source and "schema.SCORE_DOWNGRADE_DDL" in source

    entrypoint = (BACKEND / "entrypoint.sh").read_text(encoding="utf-8")
    fill_table = entrypoint.index(schema.FILL_TABLE_DDL)
    for statement in schema.SCORE_DDL:
        assert statement in entrypoint, statement
        assert entrypoint.index(statement) > fill_table, statement
    # Stary indeks znika PRZED założeniem nowego, a jedyny wpis z jego nazwą
    # w entrypoincie to DROP.
    assert entrypoint.index('DROP INDEX IF EXISTS ux_job_files_client_form"') < (
        entrypoint.index("ux_job_files_client_form_kind")
    )
    assert "INDEX IF NOT EXISTS ux_job_files_client_form ON" not in entrypoint


def test_0525_statements_are_idempotent() -> None:
    for statement in schema.SCORE_DDL:
        text = re.sub(r"\s+", " ", statement)
        assert (
            "IF NOT EXISTS" in text
            or "IF EXISTS" in text
            or text.startswith("UPDATE job_files SET client_form_kind = 'form' WHERE")
        ), statement
