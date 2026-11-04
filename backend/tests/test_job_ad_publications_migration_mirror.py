"""0432: tabela oznaczeń publikacji ogłoszenia ma lustro w entrypoincie (prod
alembic bywa osierocony), sondę w ``/api/health/deep``, a model zgadza się z DDL."""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

from app.services import job_ad_publication_schema as schema

BACKEND = Path(__file__).resolve().parents[1]
MIGRATION = BACKEND / "alembic" / "versions" / "0432_job_ad_publications.py"


def _migration_module():
    spec = importlib.util.spec_from_file_location("m0431", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_migration_runs_the_shared_ddl() -> None:
    module = _migration_module()
    assert module.revision == "0432_job_ad_publications"
    assert module.down_revision
    assert "schema.ALL_DDL" in MIGRATION.read_text(encoding="utf-8")


def test_entrypoint_mirrors_every_statement() -> None:
    entrypoint = (BACKEND / "entrypoint.sh").read_text(encoding="utf-8")
    for statement in schema.ALL_DDL:
        assert statement in entrypoint, statement


def test_ddl_is_idempotent() -> None:
    for statement in schema.ALL_DDL:
        assert "IF NOT EXISTS" in re.sub(r"\s+", " ", statement), statement


def test_model_columns_match_the_ddl() -> None:
    from app.models.job_ad_publication import JobAdPublication

    table = schema.TABLE_DDL
    columns = JobAdPublication.__table__.columns
    for column in columns.keys():
        assert re.search(rf"\b{column}\b", table), column
    # Jeden wiersz na rekrutację i portal; rekrutacja zabiera swoje wiersze,
    # autorzy tylko się odpinają.
    assert "PRIMARY KEY (job_id, portal)" in table
    assert [c.name for c in JobAdPublication.__table__.primary_key.columns] == [
        "job_id",
        "portal",
    ]
    assert "job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE" in table
    assert "published_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL" in table
    assert "removed_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL" in table
    for portal in schema.PORTALS:
        assert f"'{portal}'" in table
        assert len(portal) <= columns["portal"].type.length
    assert columns["url"].type.length == schema.URL_MAX
    assert f"url VARCHAR({schema.URL_MAX})" in table


def test_health_deep_probes_the_table_and_model_is_registered() -> None:
    main = (BACKEND / "app" / "main.py").read_text(encoding="utf-8")
    assert '("job_ad_publications", JobAdPublication)' in main
    models = (BACKEND / "app" / "models" / "__init__.py").read_text(encoding="utf-8")
    assert "from app.models.job_ad_publication import JobAdPublication" in models
