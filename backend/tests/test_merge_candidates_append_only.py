"""Scalanie duplikatów kandydatów vs tabela append-only (migracja 0201).

`candidate_contact_events` ma trigger BEFORE UPDATE **OR DELETE** podnoszący
SQLSTATE 55000. asyncpg mapuje 55000 na goły ``DBAPIError``, a nie na
``IntegrityError`` — stary ``except IntegrityError`` w ogóle go nie łapał, więc
wyjątek wysadzał jedyną transakcję runu. Fallback na DELETE też by nie pomógł
(ten sam trigger), a pominięcie tabeli zostawiłoby zdarzenia z `candidate_id`
wskazującym na skasowaną osobę — tabela nie ma FK do `candidates`, więc byłoby
to świeże osierocone PII. Repoint pod zdjętym triggerem przenosi historię pod
kandydata, który przeżył.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Optional

import pytest
from sqlalchemy.exc import DBAPIError, IntegrityError

from scripts.merge_duplicate_candidates import (
    _APPEND_ONLY_TRIGGERS,
    _is_unique_violation,
    _repoint_append_only,
    merge_pairs,
)

BACKEND_ROOT = Path(__file__).resolve().parent.parent
MIGRATION = (
    BACKEND_ROOT / "alembic/versions/0201_candidate_contact_coordination.py"
).read_text(encoding="utf-8")


# ── rejestr triggerów zgodny z migracją ──────────────────────────────────────


def test_registry_matches_the_trigger_declared_in_the_migration() -> None:
    match = re.search(
        r"CREATE TRIGGER\s+(\w+)\s+BEFORE\s+([A-Z ]+?)\s+ON candidate_contact_events",
        MIGRATION,
    )
    assert match is not None, "migracja 0201 nie deklaruje już tego triggera"

    assert _APPEND_ONLY_TRIGGERS["candidate_contact_events"] == match.group(1)
    # DELETE w zdarzeniu triggera = fallback „skasuj nadmiarowe dziecko"
    # padłby dokładnie tak samo jak UPDATE. Stąd brak fallbacku w tej gałęzi.
    assert "DELETE" in match.group(2)


def test_trigger_uses_a_sqlstate_that_is_not_an_integrity_error() -> None:
    assert "ERRCODE = '55000'" in MIGRATION
    assert not _is_unique_violation(_dbapi_error("55000"))


# ── klasyfikacja błędu ───────────────────────────────────────────────────────


class _PgError(Exception):
    def __init__(self, sqlstate: Optional[str]) -> None:
        super().__init__(f"pg error {sqlstate}")
        self.sqlstate = sqlstate


def _dbapi_error(sqlstate: Optional[str]) -> DBAPIError:
    return DBAPIError("UPDATE ...", {}, _PgError(sqlstate))


@pytest.mark.parametrize(
    ("sqlstate", "expected"),
    [
        ("23505", True),  # unique_violation — jedyny przypadek na DELETE
        ("55000", False),  # object_not_in_prerequisite_state (trigger 0201)
        ("23503", False),  # foreign_key_violation
        ("23514", False),  # check_violation
        (None, False),
    ],
)
def test_is_unique_violation(sqlstate: Optional[str], expected: bool) -> None:
    assert _is_unique_violation(_dbapi_error(sqlstate)) is expected


def test_trigger_error_is_not_an_integrity_error() -> None:
    """Sedno defektu: 55000 nie jest ``IntegrityError``, więc stary handler pudłował."""

    assert not isinstance(_dbapi_error("55000"), IntegrityError)


# ── atrapa sesji ─────────────────────────────────────────────────────────────


class _FakeResult:
    def __init__(self, rows: Optional[list[Any]] = None, rowcount: int = 0) -> None:
        self._rows = rows or []
        self.rowcount = rowcount

    def all(self) -> list[Any]:
        return self._rows

    def scalar(self) -> int:
        return 0


class _FakeNested:
    async def __aenter__(self) -> "_FakeNested":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False  # wyjątek leci dalej, savepoint „wycofany"


class _FakeDB:
    """Rejestruje SQL i pozwala wstrzyknąć błąd dla wybranego fragmentu."""

    def __init__(
        self,
        fk_tables: list[tuple[str, str]],
        failures: Optional[dict[str, Exception]] = None,
        rowcount: int = 7,
    ) -> None:
        self.fk_tables = fk_tables
        self.failures = failures or {}
        self.rowcount = rowcount
        self.executed: list[str] = []

    def begin_nested(self) -> _FakeNested:
        return _FakeNested()

    async def execute(self, clause, params=None) -> _FakeResult:
        sql = str(clause)
        self.executed.append(sql)
        if "information_schema.columns" in sql:
            return _FakeResult(rows=list(self.fk_tables))
        for needle, exc in self.failures.items():
            if needle in sql:
                raise exc
        return _FakeResult(rowcount=self.rowcount)


# ── repoint tabeli append-only ───────────────────────────────────────────────


async def test_append_only_repoint_brackets_the_update_with_the_trigger_toggle() -> (
    None
):
    db = _FakeDB(fk_tables=[])

    moved = await _repoint_append_only(
        db, "candidate_contact_events", "candidate_id", "trg_x"
    )

    assert moved == 7
    assert db.executed == [
        "ALTER TABLE candidate_contact_events DISABLE TRIGGER trg_x",
        "UPDATE candidate_contact_events t SET candidate_id = mp.canonical_id "
        "FROM merge_pairs mp WHERE t.candidate_id = mp.dup_id",
        "ALTER TABLE candidate_contact_events ENABLE TRIGGER trg_x",
    ]


async def test_merge_repoints_append_only_history_instead_of_orphaning_it() -> None:
    db = _FakeDB(fk_tables=[("candidate_contact_events", "candidate_id")])

    stats = await merge_pairs(db, [(1, 2)])

    joined = "\n".join(db.executed)
    assert "DISABLE TRIGGER trg_candidate_contact_events_immutable" in joined
    assert "ENABLE TRIGGER trg_candidate_contact_events_immutable" in joined
    # Historia przenosi się pod kandydata kanonicznego — nigdy nie kasujemy.
    assert "DELETE FROM candidate_contact_events" not in joined
    assert stats.repointed["candidate_contact_events"] == 7
    assert stats.repoint_conflicts == {}


# ── klasyfikacja w pętli po tabelach ─────────────────────────────────────────


async def test_unique_clash_still_drops_the_redundant_child_row() -> None:
    db = _FakeDB(
        fk_tables=[("candidate_tags", "candidate_id")],
        failures={"UPDATE candidate_tags": _dbapi_error("23505")},
    )

    stats = await merge_pairs(db, [(1, 2)])

    assert stats.repoint_conflicts["candidate_tags"] == 7
    assert "DELETE FROM candidate_tags" in "\n".join(db.executed)


async def test_non_unique_error_aborts_loudly_instead_of_deleting_rows() -> None:
    """Przyszły trigger na innej tabeli ma paść głośno, nie po cichu skasować."""

    db = _FakeDB(
        fk_tables=[("candidate_audit", "candidate_id")],
        failures={"UPDATE candidate_audit": _dbapi_error("55000")},
    )

    with pytest.raises(RuntimeError, match="refusing the DELETE fallback"):
        await merge_pairs(db, [(1, 2)])

    assert "DELETE FROM candidate_audit" not in "\n".join(db.executed)
