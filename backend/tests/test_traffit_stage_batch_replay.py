"""Wsad etapów Traffita: nieudany commit nie może wyrzucić całego wsadu.

Historyczny tryb awarii: rollback wsadu kasował do `commit_every` już
zaimportowanych `candidate_stages` (pierwszy run zgubił tak ~18k ruchów), a
jedyny ślad — błąd wsadowy — nie ma `ext=<id>`, więc kwarantanna (#968/#972)
nie ma czego zaparkować i faza zamarza. `_flush_stage_batch` odtwarza teraz
wsad wiersz po wierszu; każdy wiersz commituje etap RAZEM ze swoim
`RecruitmentProcess`, więc niezmiennik pary zostaje utrzymany.
"""

from __future__ import annotations

import inspect
from typing import Any, Optional

import pytest

from app.services.traffit import importer as importer_mod
from app.services.traffit.importer import PhaseProgress, TraffitImporter


class _FakeDB:
    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1


def _importer(db: _FakeDB) -> TraffitImporter:
    """Goła instancja — `_flush_stage_batch` używa wyłącznie `self.db`."""

    imp = TraffitImporter.__new__(TraffitImporter)
    imp.db = db  # type: ignore[attr-defined]
    return imp


def _rows(
    *external_ids: str, job_id: int = 100
) -> list[tuple[dict[str, Any], Optional[int], bool]]:
    return [
        (
            {"external_id": ext, "candidate_id": index, "job_id": job_id},
            None,
            True,
        )
        for index, ext in enumerate(external_ids, start=1)
    ]


@pytest.fixture
def patched_sync(monkeypatch):
    """Podmienia sync procesów; zwraca rejestr wywołań + sterowanie błędami."""

    state: dict[str, Any] = {"calls": [], "fail_when": lambda pairs: False}

    async def fake_sync(_db, *, pairs):
        state["calls"].append(list(pairs))
        if state["fail_when"](list(pairs)):
            raise RuntimeError("deadlock detected")
        return len(pairs)

    monkeypatch.setattr(importer_mod, "sync_external_observed_processes", fake_sync)
    return state


async def test_happy_path_commits_the_whole_batch_once(patched_sync) -> None:
    db = _FakeDB()
    imp = _importer(db)
    progress = PhaseProgress(phase="pipelines")

    await imp._flush_stage_batch(progress, _rows("e1", "e2", "e3"))

    assert db.commits == 1
    assert db.rollbacks == 0
    assert progress.inserted == 3
    assert progress.errors == 0
    assert patched_sync["calls"] == [[(1, 100), (2, 100), (3, 100)]]


async def test_failed_batch_replays_every_row_instead_of_dropping_them(
    patched_sync, monkeypatch
) -> None:
    db = _FakeDB()
    imp = _importer(db)
    progress = PhaseProgress(phase="pipelines")
    # Pada tylko wsad (>1 para) — pojedyncze pary przechodzą, jak przy
    # przejściowym lock-waicie/deadlocku na FOR UPDATE.
    patched_sync["fail_when"] = lambda pairs: len(pairs) > 1

    async def fake_upsert(payload, rejection_reason_id):
        return True

    imp._upsert_stage_row = fake_upsert  # type: ignore[method-assign]

    await imp._flush_stage_batch(progress, _rows("e1", "e2", "e3"))

    # Zero utraconych wierszy i zero nieprzypisywalnych błędów.
    assert progress.inserted == 3
    assert progress.errors == 0
    # Jeden commit na wiersz — etap i proces nadal w tej samej transakcji.
    assert db.commits == 3
    assert patched_sync["calls"][1:] == [[(1, 100)], [(2, 100)], [(3, 100)]]


async def test_poison_row_is_attributable_and_does_not_take_the_batch_with_it(
    patched_sync,
) -> None:
    db = _FakeDB()
    imp = _importer(db)
    progress = PhaseProgress(phase="pipelines")
    patched_sync["fail_when"] = lambda pairs: len(pairs) > 1

    async def fake_upsert(payload, rejection_reason_id):
        if payload["external_id"] == "e2":
            raise RuntimeError("withdrawn_requires_reason")
        return payload["external_id"] != "e3"  # e3 = UPDATE, reszta INSERT

    imp._upsert_stage_row = fake_upsert  # type: ignore[method-assign]

    await imp._flush_stage_batch(progress, _rows("e1", "e2", "e3"))

    assert progress.inserted == 1
    assert progress.updated == 1
    assert progress.errors == 1
    # `stage:e2` — kwarantanna umie zaparkować konkretną parę zamiast zamrażać
    # całą fazę na nieprzypisywalnym błędzie wsadowym.
    assert progress.error_refs == {"stage:e2"}
    assert progress.attributed_errors == 1
    assert db.commits == 2


async def test_empty_batch_is_a_no_op(patched_sync) -> None:
    db = _FakeDB()
    imp = _importer(db)
    progress = PhaseProgress(phase="pipelines")

    await imp._flush_stage_batch(progress, [])

    assert db.commits == 0
    assert patched_sync["calls"] == []


def test_import_pipelines_flushes_through_the_replaying_path() -> None:
    """Pętla musi domykać wsad przez `_flush_stage_batch`, nie własnym commitem."""

    src = inspect.getsource(TraffitImporter.import_pipelines)
    assert "_flush_stage_batch" in src
    # Stary kształt: gołe `db.commit()` w pętli + rollback gubiący liczniki.
    assert "await self.db.commit()" not in src
    assert "await self.db.rollback()" not in src


def test_pending_rows_retain_the_payload_needed_for_a_replay() -> None:
    src = inspect.getsource(TraffitImporter.import_pipelines)
    assert "pending_rows.append((payload, rejection_reason_id, was_insert))" in src
