"""Runda 8 audytu (R8-N15-1, R8-N15-2): downgrade nie gubi danych po cichu.

* 0388 — `DROP TABLE purged_candidates` kasował nagrobki usuniętych kandydatów,
  a nocny sync Traffita odtwarzał te osoby po ponownym upgrade.
* 0381 / 0383 — wartości enumów zostają po downgrade (Postgres nie ma DROP
  VALUE), a kod sprzed rewizji ich nie zna: ORM rzuca `LookupError` (500).

Downgrade odmawia (RAISE EXCEPTION w bazie), gdy takie wiersze istnieją.
Test wykonujący SQL na Postgresie: ten sam blok DO przy pustych i niepustych
tabelach sprawdza CI (`test_migration_downgrade_guards_round8_db`).
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_VERSIONS = Path(__file__).resolve().parents[1] / "alembic" / "versions"


def _downgrade_sql(filename: str, monkeypatch) -> list[str]:
    spec = importlib.util.spec_from_file_location(filename, _VERSIONS / filename)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    executed: list[str] = []
    monkeypatch.setattr(module.op, "execute", executed.append, raising=False)
    module.downgrade()
    return executed


@pytest.mark.parametrize(
    ("filename", "needles"),
    [
        ("0388_purged_candidates.py", ["FROM purged_candidates"]),
        ("0381_job_boards_jjit_rocketjobs.py", ["portal::text = 'rocketjobs'"]),
        (
            "0383_legacy_interview_questions.py",
            [
                "source::text = 'legacy_import'",
                "feature::text = 'interview_question_import'",
            ],
        ),
    ],
)
def test_downgrade_refuses_before_anything_is_dropped(filename, needles, monkeypatch):
    executed = _downgrade_sql(filename, monkeypatch)
    guard = executed[0]
    assert "RAISE EXCEPTION" in guard
    for needle in needles:
        assert needle in guard
    # Odmowa idzie PIERWSZA — nic nie jest usunięte przed sprawdzeniem.
    assert "DROP" not in guard and "DELETE" not in guard


def test_0388_guard_does_not_plan_a_query_on_a_missing_table(monkeypatch):
    guard = _downgrade_sql("0388_purged_candidates.py", monkeypatch)[0]
    outer = guard.index("to_regclass('purged_candidates') IS NOT NULL THEN")
    assert outer < guard.index("EXISTS (SELECT 1 FROM purged_candidates)")
