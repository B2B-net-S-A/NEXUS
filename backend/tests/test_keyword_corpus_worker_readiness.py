"""Worker czyta gotowość korpusu z bazy (web i worker osobno, 08.11.2026).

``keyword_corpus_backfill`` biegnie tylko w web, a flagi gotowości to pamięć
procesu. Bez odczytu z bazy worker zawsze liczył wyszukiwanie starą ścieżką:
``saved_search_alerts`` powtarza w nim zapisane wyszukiwanie przez ASGITransport
i dostawał inny wynik niż lista w web.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from app.core.config import settings
from app.services import keyword_corpus as kc
from app.tasks import keyword_corpus_backfill as loop


@pytest.fixture(autouse=True)
def clean_flags(monkeypatch):
    def reset() -> None:
        kc.mark_ready(False)
        kc.mark_fold_ready(False)
        kc.mark_notes_ready(False)

    reset()
    monkeypatch.setattr(settings, "NEXUS_PROCESS_ROLE", "worker")
    monkeypatch.setattr(settings, "KEYWORD_SEARCH_FOLDED_FTS", True)
    yield
    reset()


def _database(monkeypatch, **overrides) -> SimpleNamespace:
    """Stan bazy po skończonym backfillu; ``overrides`` psują pojedyncze warunki."""
    state = SimpleNamespace(
        pending=set(),
        db_version=kc.FOLD_VERSION,
        stored_version=kc.FOLD_VERSION,
        sleeps=[],
        queries=0,
        **overrides,
    )

    async def pending(sql: str = kc.PENDING_EXISTS_SQL) -> bool:
        state.queries += 1
        return sql in state.pending

    async def db_version() -> int | None:
        return state.db_version

    async def stored_version() -> int | None:
        return state.stored_version

    async def sleep(seconds: float) -> None:
        state.sleeps.append(seconds)
        state.on_sleep(state)

    monkeypatch.setattr(loop, "_pending", pending)
    monkeypatch.setattr(loop, "_db_fold_version", db_version)
    monkeypatch.setattr(loop, "_stored_fold_version", stored_version)
    monkeypatch.setattr(loop.asyncio, "sleep", sleep)
    return state


def test_finished_backfill_turns_the_folded_path_on_in_the_worker(monkeypatch):
    state = _database(monkeypatch)
    assert kc.folded_search_enabled() is False

    asyncio.run(loop.keyword_corpus_readiness_loop())

    assert kc.ready() is True
    assert kc.folded_search_enabled() is True
    assert kc.notes_folded_search_enabled() is True
    assert state.sleeps == []


def test_recompute_in_web_keeps_the_old_path_until_it_ends(monkeypatch):
    """Nowa ``FOLD_VERSION``: web przelicza, a worker nie może wyprzedzić go."""

    def web_finishes(state: SimpleNamespace) -> None:
        assert kc.ready() is True
        assert kc.folded_search_enabled() is False
        assert kc.notes_folded_search_enabled() is False
        state.stored_version = kc.FOLD_VERSION

    state = _database(monkeypatch, on_sleep=web_finishes)
    state.stored_version = kc.FOLD_VERSION - 1

    asyncio.run(loop.keyword_corpus_readiness_loop())

    assert len(state.sleeps) == 1
    assert kc.folded_search_enabled() is True


@pytest.mark.parametrize(
    "unfinished", [kc.FOLD_PENDING_EXISTS_SQL, kc.NOTES_PENDING_EXISTS_SQL]
)
def test_unfilled_rows_keep_the_old_path(monkeypatch, unfinished):
    def web_finishes(state: SimpleNamespace) -> None:
        assert kc.folded_search_enabled() is False
        state.pending.clear()

    state = _database(monkeypatch, on_sleep=web_finishes)
    state.pending.add(unfinished)

    asyncio.run(loop.keyword_corpus_readiness_loop())

    assert len(state.sleeps) == 1
    assert kc.folded_search_enabled() is True


def test_empty_legacy_corpus_keeps_every_flag_off(monkeypatch):
    def web_finishes(state: SimpleNamespace) -> None:
        assert kc.ready() is False
        assert kc.folded_search_enabled() is False
        state.pending.clear()

    state = _database(monkeypatch, on_sleep=web_finishes)
    state.pending.add(kc.PENDING_EXISTS_SQL)

    asyncio.run(loop.keyword_corpus_readiness_loop())

    assert kc.ready() is True


def test_outdated_db_function_keeps_the_old_path(monkeypatch):
    def deploy_fixes_it(state: SimpleNamespace) -> None:
        assert kc.folded_search_enabled() is False
        state.db_version = kc.FOLD_VERSION

    state = _database(monkeypatch, on_sleep=deploy_fixes_it)
    state.db_version = kc.FOLD_VERSION - 1

    asyncio.run(loop.keyword_corpus_readiness_loop())

    assert kc.folded_search_enabled() is True


def test_database_error_retries_instead_of_ending_the_loop(monkeypatch):
    state = _database(monkeypatch, on_sleep=lambda _state: None)
    real_pending = loop._pending
    calls = {"n": 0}

    async def flaky(sql: str = kc.PENDING_EXISTS_SQL) -> bool:
        calls["n"] += 1
        if calls["n"] == 1:
            raise ConnectionError("restart postgresa")
        return await real_pending(sql)

    monkeypatch.setattr(loop, "_pending", flaky)

    asyncio.run(loop.keyword_corpus_readiness_loop())

    assert state.sleeps == [loop._RETRY_SECONDS]
    assert kc.folded_search_enabled() is True


def test_process_with_its_own_backfill_reads_nothing(monkeypatch):
    """Rola ``all`` ma prawdziwy backfill, a odczyt nie może mu nadpisać flag."""
    monkeypatch.setattr(settings, "NEXUS_PROCESS_ROLE", "all")
    state = _database(monkeypatch)

    asyncio.run(loop.keyword_corpus_readiness_loop())

    assert state.queries == 0
    assert kc.ready() is False
