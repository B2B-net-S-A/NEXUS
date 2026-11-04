"""Runda 7 (R7-X3-2): przeliczanie wersji składania po rollbacku kodu.

Zapisana pozycja przeliczania była ważna, dopóki zgadzała się wersja. Nic nie
sprawdzało, czy w międzyczasie nie działał proces z INNĄ funkcją składania
(rollback w Coolify, revert): jej trigger przeliczał zmieniane wiersze także
poniżej pozycji, a po powrocie nowej wersji przeliczanie wznawiało się od
pozycji i ogłaszało gotowość na kolumnie z tokenami dwóch funkcji. W drugą
stronę starszy kod widział zapisaną „swoją” wersję i od razu ogłaszał
gotowość, choć nowsza przeliczyła już część wierszy.
"""

from __future__ import annotations

import json

import pytest

from app.services import keyword_corpus as kc
from app.tasks import keyword_corpus_backfill as loop


def test_in_progress_entry_is_not_a_finished_version():
    in_progress = {"in_progress_version": kc.FOLD_VERSION, "started_at": "x"}
    assert loop._parse_stored_fold_version(in_progress) is None
    assert loop._parse_stored_fold_version(json.dumps(in_progress)) is None
    assert (
        loop._parse_stored_fold_version({"version": kc.FOLD_VERSION}) == kc.FOLD_VERSION
    )
    assert loop._parse_stored_fold_version(None) is None


def _patch_phase(monkeypatch, *, previous_process: int | None):
    calls: list[str] = []
    starts: dict[str, int] = {}

    async def db_version():
        return kc.FOLD_VERSION

    async def stored():
        return None

    async def mark_in_progress():
        calls.append("in_progress")

    async def position():
        calls.append("load_position")
        return {"candidates": 30_000, "notes": 500}

    async def clear():
        calls.append("cleared")

    async def save(name, after):
        return None

    async def store():
        calls.append("stored")

    async def batch(sql, after, limit, trigger):
        name = "notes" if limit == loop._NOTES_BATCH else "candidates"
        starts.setdefault(name, after)
        return 0

    monkeypatch.setattr(loop, "_db_fold_version", db_version)
    monkeypatch.setattr(loop, "_stored_fold_version", stored)
    monkeypatch.setattr(loop, "_mark_recompute_in_progress", mark_in_progress)
    monkeypatch.setattr(loop, "_load_recompute_position", position)
    monkeypatch.setattr(loop, "_clear_recompute_position", clear)
    monkeypatch.setattr(loop, "_save_recompute_position", save)
    monkeypatch.setattr(loop, "_store_fold_version", store)
    monkeypatch.setattr(loop, "_fill_keyset_batch", batch)
    monkeypatch.setattr(loop, "_previous_process_version", previous_process)
    monkeypatch.setattr(kc, "_fold_ready", False)
    monkeypatch.setattr(kc, "_notes_ready", False)
    loop._recompute_after.clear()
    return calls, starts


@pytest.mark.asyncio
async def test_same_version_process_resumes_saved_position(monkeypatch):
    calls, starts = _patch_phase(monkeypatch, previous_process=kc.FOLD_VERSION)
    try:
        await loop._version_phase()
    finally:
        loop._recompute_after.clear()
    assert calls[0] == "in_progress", "wersja „w toku” przed pierwszą paczką"
    assert starts == {"candidates": 30_000, "notes": 500}
    assert kc.fold_ready()


@pytest.mark.asyncio
async def test_other_version_process_in_between_restarts_from_zero(monkeypatch):
    calls, starts = _patch_phase(monkeypatch, previous_process=kc.FOLD_VERSION - 1)
    try:
        await loop._version_phase()
    finally:
        loop._recompute_after.clear()
    assert "load_position" not in calls
    assert calls[:2] == ["in_progress", "cleared"]
    assert starts == {"candidates": 0, "notes": 0}
    # Ponowienie w tym samym procesie wznawia już własne pozycje.
    assert loop._position_trusted()
