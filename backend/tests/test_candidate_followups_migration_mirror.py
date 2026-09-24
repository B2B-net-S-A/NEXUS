"""0371: tabela follow-upów ma lustro w entrypoincie i sondę w `/api/health/deep`.

Prod alembic bywa osierocony — `entrypoint.sh` JEST wdrożeniem. Bez lustra
pulpit („Czeka na Ciebie”) i Tablica padają na produkcji na
`UndefinedTableError`, a w CI (gdzie działa migracja) wszystko jest zielone.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
MIGRATION = BACKEND / "alembic" / "versions" / "0371_candidate_followups.py"


def _collapse(sql: str) -> str:
    return re.sub(r"\s+", " ", sql).strip()


def _migration_module():
    spec = importlib.util.spec_from_file_location("m0371", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _entrypoint_text() -> str:
    raw = (BACKEND / "entrypoint.sh").read_text()
    return _collapse(re.sub(r'"\s*\n\s*"', "", raw))


def test_migration_chains_after_teams_prep():
    module = _migration_module()
    assert module.revision == "0371_candidate_followups"
    assert module.down_revision == "0370_teams_prep_transcripts"


def test_every_ddl_statement_is_mirrored_in_entrypoint():
    entrypoint = _entrypoint_text()
    for statement in _migration_module().DDL_STATEMENTS:
        assert _collapse(statement) in entrypoint, statement


def test_ddl_is_idempotent():
    for statement in _migration_module().DDL_STATEMENTS:
        assert "IF NOT EXISTS" in _collapse(statement), statement


def test_notification_enum_is_mirrored():
    assert _collapse(_migration_module().ENUM_NOTIFICATION) in _entrypoint_text()


def test_outcome_check_matches_model():
    from app.models.candidate_followup import FOLLOWUP_OUTCOMES

    module = _migration_module()
    assert tuple(module.OUTCOMES) == FOLLOWUP_OUTCOMES
    for outcome in FOLLOWUP_OUTCOMES:
        assert f"'{outcome}'" in module.CREATE_CANDIDATE_FOLLOWUPS


def test_table_is_probed_by_deep_health_and_registered():
    main = (BACKEND / "app" / "main.py").read_text()
    assert '("candidate_followups", CandidateFollowup)' in main
    models = (BACKEND / "app" / "models" / "__init__.py").read_text()
    assert "from app.models.candidate_followup import CandidateFollowup" in models
