"""Liczniki „W bazie” mają kopię wspólną dla procesów web (26.11.2026).

Każdy proces web zaczynał z pustą pamięcią, a procesy w kontenerze wstają na
nowo po każdym padnięciu: zapytanie liczące szło na produkcji ok. 28 tys. razy
w 23 h (ok. 6 580 s bazy), choć jeden obrót to ok. 540 wierszy.
"""

from __future__ import annotations

import json
import time

import pytest
from httpx import AsyncClient
from sqlalchemy import text

from app.core.database import AsyncSessionLocal
from app.services import requirement_row_counts as counts
from app.tasks import requirement_row_counts as task

ROWS = [(["Crisis plans"], []), (["Java"], ["PHP"])]


@pytest.fixture(autouse=True)
async def _isolated(app_client: AsyncClient):
    counts.clear()
    await _drop_shared()
    yield
    counts.clear()
    await _drop_shared()


async def _drop_shared() -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(
            text("DELETE FROM app_settings WHERE key = :k"), {"k": counts.SHARED_KEY}
        )
        await db.commit()


async def _shared_entries() -> dict:
    async with AsyncSessionLocal() as db:
        value = await db.scalar(
            text("SELECT value FROM app_settings WHERE key = :k"),
            {"k": counts.SHARED_KEY},
        )
    return (value or {}).get("entries", {})


def _fake_counter(monkeypatch) -> list:
    asked: list = []

    async def fake_count(db, words, exclude):
        asked.append(list(words))
        return 3 if words == ["Crisis plans"] else 40

    monkeypatch.setattr(counts, "count_row", fake_count)
    return asked


@pytest.mark.asyncio
async def test_new_process_reads_counted_rows_instead_of_counting_again(monkeypatch):
    asked = _fake_counter(monkeypatch)
    async with AsyncSessionLocal() as db:
        assert await counts.ensure(db, ROWS, deadline=time.monotonic() + 60) == 2
        assert await counts.save_shared(db) == 2
        await db.commit()

    counts.clear()  # nowy proces: pusta pamięć
    async with AsyncSessionLocal() as db:
        assert await counts.load_shared(db) == 2
        assert await counts.ensure(db, ROWS, deadline=time.monotonic() + 60) == 0
    assert asked == [["Crisis plans"], ["Java"]]
    assert counts.cached(["Crisis plans"], []) == 3
    assert counts.cached(["Java"], ["PHP"]) == 40
    # Wpis bliski wygaśnięcia nadal liczy się ponownie (pętla, fresh_for).
    async with AsyncSessionLocal() as db:
        assert (
            await counts.ensure(
                db,
                ROWS,
                deadline=time.monotonic() + 60,
                fresh_for=counts.CACHE_TTL_SECONDS,
            )
            == 2
        )


@pytest.mark.asyncio
async def test_save_keeps_the_later_expiry_and_drops_expired_entries(monkeypatch):
    wall = time.time()
    fresher = json.dumps([["crisis plans"], []], ensure_ascii=False)
    expired = json.dumps([["cobol"], []], ensure_ascii=False)
    async with AsyncSessionLocal() as db:
        await db.execute(
            text(
                "INSERT INTO app_settings (key, value) VALUES (:k, CAST(:v AS jsonb))"
            ),
            {
                "k": counts.SHARED_KEY,
                "v": json.dumps(
                    {
                        "entries": {
                            fresher: [5, wall + 20 * 3600],
                            expired: [1, wall - 60],
                        }
                    }
                ),
            },
        )
        await db.commit()

    _fake_counter(monkeypatch)
    async with AsyncSessionLocal() as db:
        # Ten proces policzył „Crisis plans” wcześniej (krótsze życie) i „Java”.
        await counts.ensure(db, ROWS, deadline=time.monotonic() + 60)
        k = counts.key(["Crisis plans"], [])
        counts._cache[k] = (3, time.monotonic() + 3600)
        await counts.save_shared(db)
        await db.commit()

    entries = await _shared_entries()
    assert expired not in entries
    assert entries[fresher][0] == 5  # dłuższe życie z kopii wygrywa
    assert entries[json.dumps([["java"], ["php"]], ensure_ascii=False)][0] == 40

    counts.clear()
    async with AsyncSessionLocal() as db:
        await counts.load_shared(db)
    assert counts.cached(["Crisis plans"], []) == 5
    assert counts.cached(["Cobol"], []) is None


@pytest.mark.asyncio
async def test_pass_reads_the_copy_first_and_saves_after_every_chunk(monkeypatch):
    log: list = []
    chunks = iter([5, 3, 0])

    async def warm_counts(db, *, budget):
        assert 0 < budget <= task._SAVE_EVERY_SECONDS
        n = next(chunks)
        log.append(("count", n))
        return n

    async def load_shared():
        log.append("load")
        return 0

    async def save_shared():
        log.append("save")

    from app.services import requirement_cleanup

    monkeypatch.setattr(requirement_cleanup, "warm_counts", warm_counts)
    monkeypatch.setattr(task, "_load_shared", load_shared)
    monkeypatch.setattr(task, "_save_shared", save_shared)

    assert await task.warm_pass(3600.0) == 8
    assert log == ["load", ("count", 5), "save", ("count", 3), "save", ("count", 0)]
