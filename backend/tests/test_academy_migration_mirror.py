"""0369: DDL akademii ma lustro w entrypoincie i sondy w `/api/health/deep`.

Prod alembic bywa osierocony — `entrypoint.sh` JEST wdrożeniem. Bez lustra
ekran akademii na produkcji pada na `UndefinedTableError`, a w CI (gdzie
działa migracja) wszystko jest zielone.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
MIGRATION = BACKEND / "alembic" / "versions" / "0369_academy.py"


def _collapse(sql: str) -> str:
    return re.sub(r"\s+", " ", sql).strip()


def _migration_module():
    spec = importlib.util.spec_from_file_location("m0369", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _entrypoint_text() -> str:
    raw = (BACKEND / "entrypoint.sh").read_text()
    return _collapse(re.sub(r'"\s*\n\s*"', "", raw))


def test_migration_chains_after_contract_termination_reversal():
    module = _migration_module()
    assert module.revision == "0369_academy"
    assert module.down_revision == "0368_contract_termination_reversal"


def test_every_ddl_statement_is_mirrored_in_entrypoint():
    entrypoint = _entrypoint_text()
    for statement in _migration_module().DDL_STATEMENTS:
        assert _collapse(statement) in entrypoint, statement


def test_ddl_is_idempotent():
    for statement in _migration_module().DDL_STATEMENTS:
        assert "IF NOT EXISTS" in _collapse(statement), statement


def test_ai_feature_enum_and_seed_are_mirrored():
    entrypoint = _entrypoint_text()
    module = _migration_module()
    assert _collapse(module.ENUM_AI_FEATURE) in entrypoint
    assert "SELECT 'academy_screening', TRUE, 0, now(), now()" in entrypoint


def test_status_check_matches_model_statuses():
    from app.models.academy import ACADEMY_STATUSES

    module = _migration_module()
    assert tuple(module.APPLICATION_STATUSES) == ACADEMY_STATUSES
    for status in ACADEMY_STATUSES:
        assert f"'{status}'" in module.CREATE_APPLICATIONS


def test_every_academy_table_has_a_deep_health_probe():
    source = (BACKEND / "app" / "main.py").read_text()
    for table in (
        "academy_programs",
        "academy_program_sources",
        "academy_sessions",
        "academy_applications",
    ):
        assert f'("{table}", ' in source, table
