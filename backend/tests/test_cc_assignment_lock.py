"""Runda 10 (R10-N8-7): zapis kategorii AI blokuje kandydata PRZED odczytem.

Backfill czytał istniejące wiersze M2M i kasował je bez blokady kandydata —
ręczny przydział zatwierdzony pomiędzy SELECT a DELETE ginął. Ręczny zapis
bierze `FOR UPDATE` na kandydacie, więc ta sama blokada na początku
`apply_candidate_cc_scores` szereguje oba zapisy.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy.dialects import postgresql

from app.services import candidate_cc_assignment as cc_assignment
from app.services.cc_classifier import CcScore


class _Result:
    def scalars(self):
        return self

    def all(self):
        return []


class _RecordingDb:
    def __init__(self) -> None:
        self.statements: list[str] = []

    async def execute(self, stmt, *_a, **_k):
        self.statements.append(
            str(stmt.compile(dialect=postgresql.dialect()))
        )
        return _Result()

    def add(self, _obj):
        pass


@pytest.mark.asyncio
async def test_candidate_row_is_locked_before_existing_rows_are_read():
    db = _RecordingDb()
    candidate = SimpleNamespace(id=5, competence_category_id=None)
    score = CcScore(
        cc_id=1,
        slug="software_development",
        name_pl="Development",
        score=0.95,
        keyword_ratio=0.9,
        embedding_score=0.9,
        keywords_matched=[],
    )

    await cc_assignment.apply_candidate_cc_scores(candidate, [score], db)

    assert db.statements, "zapis musi zapytać bazę"
    first = db.statements[0]
    assert "FOR UPDATE" in first
    assert "FROM candidates" in first
    assert "candidate_competence_categories" in db.statements[1]
