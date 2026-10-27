"""0527: „Czego Jarvis nie umie” ma lustro w entrypoincie (prod alembic bywa
osierocony), sondę w ``/api/health/deep``, a model zgadza się z DDL."""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

from app.models.jarvis import JarvisGap
from app.services.jarvis import gap_schema as schema

BACKEND = Path(__file__).resolve().parents[1]
MIGRATION = BACKEND / "alembic" / "versions" / "0527_jarvis_gaps.py"


def _migration_module():
    spec = importlib.util.spec_from_file_location("m0527", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_migration_runs_the_shared_ddl() -> None:
    module = _migration_module()
    assert module.revision == "0527_jarvis_gaps"
    assert module.down_revision == "0526_job_ad_reminders"
    assert "schema.ALL_DDL" in MIGRATION.read_text(encoding="utf-8")


def test_entrypoint_mirrors_every_statement() -> None:
    entrypoint = (BACKEND / "entrypoint.sh").read_text(encoding="utf-8")
    for statement in schema.ALL_DDL:
        assert statement in entrypoint, statement
    # Tabela odwołuje się do rozmów — lustro musi stać PO ich CREATE TABLE.
    assert entrypoint.index(schema.TABLE_DDL) > entrypoint.index(
        "CREATE TABLE IF NOT EXISTS jarvis_conversations ("
    )


def test_ddl_is_idempotent() -> None:
    for statement in schema.ALL_DDL:
        assert "IF NOT EXISTS" in re.sub(r"\s+", " ", statement), statement


def test_model_matches_the_ddl() -> None:
    columns = {c.name: c for c in JarvisGap.__table__.columns}
    for name in re.findall(r"(?:\(|, )([a-z_]+) [A-Z]", schema.TABLE_DDL):
        assert name in columns, name
    assert columns["need"].type.length == schema.NEED_MAX
    assert columns["why"].type.length == schema.WHY_MAX
    for kind in schema.GAP_KINDS:
        assert f"'{kind}'" in schema.TABLE_DDL


def test_deep_health_probes_the_table() -> None:
    assert '("jarvis_gaps", JarvisGap)' in (BACKEND / "app" / "main.py").read_text()
