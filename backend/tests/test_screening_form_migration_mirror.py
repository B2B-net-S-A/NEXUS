"""0424: historia formularza screeningu ma lustro w entrypoincie i sondę
w ``/api/health/deep`` (prod alembic bywa osierocony), CHECK-i zgadzają się
z wartościami, które zapisuje kod, a CHECK źródła zmiany stawki jest jawnie
poszerzany (``CREATE TABLE IF NOT EXISTS`` istniejącego więzu nie zmieni)."""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
MIGRATION = BACKEND / "alembic" / "versions" / "0424_screening_form_versions.py"


def _migration_module():
    spec = importlib.util.spec_from_file_location("m0424", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_migration_chains_after_notes_facts() -> None:
    module = _migration_module()
    assert module.revision == "0424_screening_form_versions"
    assert module.down_revision == "0423_notes_facts_to_fields"


def test_entrypoint_imports_the_single_ddl_source() -> None:
    text = (BACKEND / "entrypoint.sh").read_text(encoding="utf-8")
    assert "from app.services import screening_form_schema as _screening_form" in text
    # Tabela przed danymi, CHECK w fazie więzów, odwołanie tokenów w danych.
    assert "*_SCREENING_FORM_DDL," in text
    assert "*_SCREENING_FORM_DATA," in text
    assert "*_SCREENING_FORM_CONSTRAINTS," in text
    columns = text.index("_COLUMN_STATEMENTS = [")
    data = text.index("_DATA_STATEMENTS = [")
    constraints = text.index("_CONSTRAINT_STATEMENTS = [")
    assert columns < text.index("*_SCREENING_FORM_DDL,") < data
    assert data < text.index("*_SCREENING_FORM_DATA,") < constraints
    assert constraints < text.index("*_SCREENING_FORM_CONSTRAINTS,")


def test_ddl_is_idempotent() -> None:
    from app.services.screening_form_schema import ALL_DDL

    for statement in ALL_DDL:
        flat = re.sub(r"\s+", " ", statement)
        assert (
            "IF NOT EXISTS" in flat
            or flat.startswith("DO $$")
            or "WHERE revoked = false" in flat
        ), statement


def test_checks_cover_every_value_the_code_writes() -> None:
    from app.services import screening_form
    from app.services.screening_form_schema import ACTIONS, SOURCES, TABLE_DDL

    ddl = " ".join(TABLE_DDL)
    for value in (*ACTIONS, *SOURCES):
        assert f"'{value}'" in ddl
    source = Path(screening_form.__file__).read_text(encoding="utf-8")
    activities = {"screening_answered", "screening_form_saved"}  # dziennik, nie wersja
    written = set(re.findall(r'action="([a-z_]+)"', source)) - activities
    assert written >= {"baseline", "external", "save"}
    assert written <= set(ACTIONS), written - set(ACTIONS)
    assert "fix_requested" in ACTIONS  # PR 2 bez drugiej migracji


def test_rate_change_source_check_accepts_the_form() -> None:
    from app.services import candidate_rate_change as rate_change
    from app.services.candidate_rate_change_schema import (
        SOURCES,
        TABLE_DDL,
        source_constraint_ddl,
    )
    from app.services.screening_form_schema import CONSTRAINT_DDL

    assert "screening" in SOURCES
    assert set(SOURCES) <= set(rate_change.SOURCE_LABELS)
    widen = source_constraint_ddl()
    assert widen in CONSTRAINT_DDL
    assert "DROP CONSTRAINT IF EXISTS ck_candidate_rate_changes_source" in widen
    assert "'screening'" in widen
    # Świeża baza dostaje szeroki CHECK już w CREATE TABLE z 0418.
    assert "'screening'" in " ".join(TABLE_DDL)


def test_champion_share_tokens_are_revoked() -> None:
    from app.services.screening_form_schema import DATA_DDL

    assert DATA_DDL == (
        "UPDATE champion_card_share_tokens SET revoked = true WHERE revoked = false",
    )


def test_health_deep_probes_the_table_and_model_is_registered() -> None:
    main = (BACKEND / "app" / "main.py").read_text(encoding="utf-8")
    assert '("screening_form_versions", ScreeningFormVersion)' in main
    models = (BACKEND / "app" / "models" / "__init__.py").read_text(encoding="utf-8")
    assert (
        "from app.models.screening_form_version import ScreeningFormVersion" in models
    )


class _FakeResult:
    def __init__(self, value: int) -> None:
        self._value = value

    def scalar(self) -> int:
        return self._value


class _FakeBind:
    def __init__(self, counts: dict[str, int]) -> None:
        self.counts = counts

    def exec_driver_sql(self, sql: str) -> _FakeResult:
        table = "candidate_rate_changes" if "candidate_rate_changes" in sql else "v"
        return _FakeResult(self.counts.get(table, 0))


@pytest.mark.parametrize("counts", [{"v": 3}, {"v": 0, "candidate_rate_changes": 2}])
def test_downgrade_refuses_before_anything_is_dropped(monkeypatch, counts) -> None:
    module = _migration_module()
    executed: list[str] = []
    monkeypatch.setattr(module.op, "execute", executed.append, raising=False)
    monkeypatch.setattr(module.op, "get_bind", lambda: _FakeBind(counts), raising=False)
    with pytest.raises(RuntimeError):
        module.downgrade()
    assert executed == []


def test_downgrade_restores_the_narrow_check(monkeypatch) -> None:
    module = _migration_module()
    executed: list[str] = []
    monkeypatch.setattr(module.op, "execute", executed.append, raising=False)
    monkeypatch.setattr(module.op, "get_bind", lambda: _FakeBind({}), raising=False)
    module.downgrade()
    assert executed[0] == "DROP TABLE IF EXISTS screening_form_versions"
    assert "'screening'" not in executed[1]
    assert "'move'" in executed[1]
