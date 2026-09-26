"""Runda 6 audytu (M3): wersja składania zapisuje się tylko wtedy, gdy baza
ma funkcję ``candidate_keyword_fold`` w tej wersji.

Do tej rundy ``_version_phase`` zapisywał ``FOLD_VERSION`` ze stałej Pythona:
gdy DDL funkcji przegrał blokadę (siatka w ``entrypoint.sh`` loguje i idzie
dalej), pętla przeliczała kolumny STARĄ funkcją, oznaczała wersję jako
przeliczoną i włączała nową ścieżkę zapytań — kolejny start z poprawną
funkcją już niczego nie przeliczał.
"""

from __future__ import annotations

import pytest

from app.services import keyword_corpus as kc
from app.tasks import keyword_corpus_backfill as loop


async def _noop() -> None:
    return None


def test_fold_function_body_carries_the_version_marker():
    assert kc.fold_version_marker(kc.FOLD_VERSION) in kc.FOLD_FUNCTION_DDL
    assert kc.parse_fold_version(kc.FOLD_FUNCTION_DDL) == kc.FOLD_VERSION
    assert kc.parse_fold_version("BEGIN RETURN t; END;") is None


@pytest.mark.asyncio
async def test_outdated_db_function_blocks_recompute_and_readiness(monkeypatch):
    calls: list[str] = []

    async def fake_recompute(name, sql, limit, trigger):
        calls.append(name)
        return 0

    async def fake_store():
        calls.append("stored")

    async def stored():
        return kc.FOLD_VERSION - 1

    async def db_version():
        return kc.FOLD_VERSION - 1

    monkeypatch.setattr(loop, "_recompute", fake_recompute)
    monkeypatch.setattr(loop, "_store_fold_version", fake_store)
    monkeypatch.setattr(loop, "_mark_recompute_in_progress", _noop)
    monkeypatch.setattr(loop, "_stored_fold_version", stored)
    monkeypatch.setattr(loop, "_db_fold_version", db_version)
    monkeypatch.setattr(kc, "_fold_ready", True)
    monkeypatch.setattr(kc, "_notes_ready", True)

    with pytest.raises(loop.FoldFunctionOutdated):
        await loop._version_phase()
    assert calls == []
    assert not kc.fold_ready() and not kc.notes_ready()


@pytest.mark.asyncio
async def test_matching_db_function_recomputes_and_stores(monkeypatch):
    calls: list[str] = []

    async def fake_recompute(name, sql, limit, trigger):
        calls.append(name)
        return 0

    async def fake_store():
        calls.append("stored")

    async def stored():
        return kc.FOLD_VERSION - 1

    async def db_version():
        return kc.FOLD_VERSION

    monkeypatch.setattr(loop, "_recompute", fake_recompute)
    monkeypatch.setattr(loop, "_store_fold_version", fake_store)
    monkeypatch.setattr(loop, "_mark_recompute_in_progress", _noop)
    monkeypatch.setattr(loop, "_stored_fold_version", stored)
    monkeypatch.setattr(loop, "_db_fold_version", db_version)
    monkeypatch.setattr(kc, "_fold_ready", False)
    monkeypatch.setattr(kc, "_notes_ready", False)

    await loop._version_phase()
    assert calls == ["candidates", "notes", "stored"]
    assert kc.fold_ready() and kc.notes_ready()


@pytest.mark.asyncio
async def test_migrated_database_reports_the_current_fold_version():
    """Baza po migracjach ma funkcję z bieżącym znacznikiem (CI z Postgresem)."""
    assert await loop._db_fold_version() == kc.FOLD_VERSION
