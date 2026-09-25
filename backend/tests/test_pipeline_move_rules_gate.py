"""``gate_stage_row`` — kolumna, od której liczą się bramki ruchu (runda 2
audytu 25.09.2026).

Bez bazy: sesja-atrapa liczy wywołania. Pilnujemy dwóch rzeczy:

* para bez wierszy stoi na początku drogi („new”), nie „poza bramkami”
  (``(None, None)`` przepuszczało świeżego kandydata na „CV wysłane” bez QC);
* kolumny liczy stała liczba zapytań — nie jedno zapytanie o definicję etapu
  na każdy wiersz pary (historia z importu bywa długa).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.services import pipeline_move_rules


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return list(self._rows)


class _FakeDb:
    def __init__(self, stage_rows, defs):
        self.stage_rows = stage_rows
        self.defs = defs
        self.calls = 0

    async def scalars(self, _stmt):
        self.calls += 1
        return _Result(self.stage_rows)

    async def execute(self, _stmt):
        self.calls += 1
        return _Result(self.defs)


def _row(i: int, stage: str, def_id):
    return SimpleNamespace(
        id=i,
        stage=stage,
        stage_def_id=def_id,
        moved_at=datetime(2031, 1, 1, tzinfo=timezone.utc) - timedelta(days=i),
    )


def _def(def_id: int, name: str, *, terminal: str | None = None):
    return SimpleNamespace(id=def_id, name=name, category=None, terminal_type=terminal)


@pytest.mark.asyncio
async def test_pair_without_rows_starts_at_new() -> None:
    db = _FakeDb([], [])
    row, column = await pipeline_move_rules.gate_stage_row(db, candidate_id=1, job_id=1)
    assert row is None
    assert column == "new"
    assert db.calls == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("closed_rows", [1, 5, 40])
async def test_column_lookup_uses_a_constant_number_of_queries(
    closed_rows: int,
) -> None:
    # Najnowsze wiersze pary to zamknięcia, pod nimi „Zweryfikowany”.
    rows = [_row(i, "rejected", 100 + i) for i in range(closed_rows)]
    rows.append(_row(closed_rows, "verified", 9))
    defs = [_def(100 + i, "Odrzucony", terminal="rejected") for i in range(closed_rows)]
    defs.append(_def(9, "Zweryfikowany"))
    db = _FakeDb(rows, defs)

    row, column = await pipeline_move_rules.gate_stage_row(db, candidate_id=1, job_id=1)

    assert column == "verified"
    assert row is rows[-1]
    assert db.calls == 2


@pytest.mark.asyncio
async def test_only_closed_rows_count_from_new() -> None:
    rows = [_row(0, "rejected", 7)]
    db = _FakeDb(rows, [_def(7, "Odrzucony", terminal="rejected")])
    row, column = await pipeline_move_rules.gate_stage_row(db, candidate_id=1, job_id=1)
    assert row is rows[0]
    assert column == "new"
