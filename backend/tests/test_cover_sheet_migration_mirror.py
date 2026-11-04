"""0626: wzór „Karty przed CV” — lustro w entrypoincie (alembic na prodzie bywa
osierocony) i zgodność modelu z DDL."""

from __future__ import annotations

import importlib.util
from pathlib import Path

from app.models.candidate_client_form import CandidateClientForm
from app.models.client_cover_sheet_template import ClientCoverSheetTemplate
from app.services import cover_sheet_schema as schema

BACKEND = Path(__file__).resolve().parents[1]
MIGRATION = BACKEND / "alembic" / "versions" / "0626_client_cover_sheet_templates.py"


def test_migration_chains_and_uses_the_shared_ddl() -> None:
    spec = importlib.util.spec_from_file_location("m0626", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    assert module.revision == "0626_client_cover_sheet_templates"
    assert module.down_revision == "0625_novelty_progress"
    source = MIGRATION.read_text(encoding="utf-8")
    assert "schema.ALL_DDL" in source and "schema.DOWNGRADE_DDL" in source


def test_entrypoint_mirrors_the_table_after_candidate_client_forms() -> None:
    entrypoint = (BACKEND / "entrypoint.sh").read_text(encoding="utf-8")
    forms = entrypoint.index("CREATE TABLE IF NOT EXISTS candidate_client_forms (")
    for statement in schema.ALL_DDL:
        assert "IF NOT EXISTS" in statement
        assert statement in entrypoint, statement
        assert entrypoint.index(statement) > forms


def test_model_matches_the_ddl_and_cover_kind_fits() -> None:
    columns = set(ClientCoverSheetTemplate.__table__.columns.keys())
    assert columns == {
        "client_id",
        "filename",
        "content",
        "sha256",
        "fields",
        "uploaded_by",
        "uploaded_at",
    }
    for column in columns:
        assert column in schema.TABLE_DDL
    kind = CandidateClientForm.__table__.columns["kind"]
    assert kind.type.length >= len(schema.KIND_COVER)
