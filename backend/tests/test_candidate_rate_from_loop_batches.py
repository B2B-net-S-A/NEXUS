"""Pętla „Stawka od” trzyma blokady wierszy kandydatów krótko (26.11.2026).

Paczka pętli to jedna transakcja: ``recompute`` blokuje wszystkie jej wiersze
(``FOR NO KEY UPDATE SKIP LOCKED``) do commitu, a UPDATE jednego kandydata
kosztuje na produkcji ok. 120 ms (wyzwalacz pełnotekstowy, 42 indeksy). Przy
paczce 500 osób blokada trwała 60–75 s, a zapis kandydata z tej paczki
(``SELECT … FOR UPDATE`` w PATCH, tagach, lokalizacji) czekał na nią — w
``pg_stat_statements`` produkcji do 60,7 s. Paczka 25 osób to ok. 3 s.
"""

from __future__ import annotations

import pytest

from app.tasks import candidate_rate_from as task

_MAX_LOCKED_PER_TRANSACTION = 25


class _Session:
    def __init__(self, log: list) -> None:
        self.log = log

    async def __aenter__(self) -> "_Session":
        self.log.append("begin")
        return self

    async def __aexit__(self, *_exc) -> bool:
        return False

    async def commit(self) -> None:
        self.log.append("commit")


@pytest.mark.asyncio
async def test_kazda_transakcja_petli_blokuje_najwyzej_25_kandydatow(monkeypatch):
    log: list = []
    queue = list(range(60))

    async def process_queue(db, *, limit: int) -> int:
        taken = queue[:limit]
        del queue[:limit]
        log.append(("batch", len(taken), limit))
        return len(taken)

    monkeypatch.setattr(task, "AsyncSessionLocal", lambda: _Session(log))
    monkeypatch.setattr(task.rate_from, "process_queue", process_queue)
    monkeypatch.setattr(task, "_PAUSE_SECONDS", 0)

    assert await task._drain() == 60
    assert queue == []
    batches = [entry for entry in log if isinstance(entry, tuple)]
    assert max(limit for _, _, limit in batches) <= _MAX_LOCKED_PER_TRANSACTION
    # Każda paczka to osobna transakcja zamknięta commitem przed następną.
    assert log == [step for batch in batches for step in ("begin", batch, "commit")]
