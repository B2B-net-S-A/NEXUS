"""0430: tabela ogłoszeń do wklejenia na portale ma lustro w entrypoincie (prod
alembic bywa osierocony), sondę w ``/api/health/deep``, a model zgadza się z DDL."""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

from app.services import job_ad_schema

BACKEND = Path(__file__).resolve().parents[1]
MIGRATION = BACKEND / "alembic" / "versions" / "0430_job_ads.py"


def _migration_module():
    spec = importlib.util.spec_from_file_location("m0430", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_migration_runs_the_shared_ddl() -> None:
    module = _migration_module()
    assert module.revision == "0430_job_ads"
    assert module.down_revision
    assert "schema.ALL_DDL" in MIGRATION.read_text(encoding="utf-8")


def test_entrypoint_mirrors_every_statement() -> None:
    entrypoint = (BACKEND / "entrypoint.sh").read_text(encoding="utf-8")
    for statement in job_ad_schema.ALL_DDL:
        assert statement in entrypoint, statement


def test_ddl_is_idempotent() -> None:
    for statement in job_ad_schema.ALL_DDL:
        assert "IF NOT EXISTS" in re.sub(r"\s+", " ", statement), statement


def test_model_columns_match_the_ddl() -> None:
    from app.models.job_ad import JobAd

    table = job_ad_schema.TABLE_DDL
    for column in JobAd.__table__.columns.keys():
        assert re.search(rf"\b{column}\b", table), column
    # Rekrutacja zabiera swoje ogłoszenie; autorzy tylko się odpinają.
    assert "job_id INTEGER PRIMARY KEY REFERENCES jobs(id) ON DELETE CASCADE" in table
    assert "generated_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL" in table
    assert "updated_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL" in table
    for value in (*job_ad_schema.LANGS, *job_ad_schema.SOURCES):
        assert f"'{value}'" in table
    assert all(
        len(lang) <= JobAd.__table__.columns["lang"].type.length
        for lang in job_ad_schema.LANGS
    )
    assert all(
        len(source) <= JobAd.__table__.columns["source"].type.length
        for source in job_ad_schema.SOURCES
    )


def test_health_deep_probes_the_table_and_model_is_registered() -> None:
    main = (BACKEND / "app" / "main.py").read_text(encoding="utf-8")
    assert '("job_ads", JobAd)' in main
    assert "app.include_router(job_ads_api.router" in main
    models = (BACKEND / "app" / "models" / "__init__.py").read_text(encoding="utf-8")
    assert "from app.models.job_ad import JobAd" in models
