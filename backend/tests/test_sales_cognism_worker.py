from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy.dialects import postgresql

from app.core.config import settings
from app.services.sales import signal_targets as targets
from app.tasks import sales_signals as worker


class QueryResults:
    def __init__(self, *results):
        self.results = iter(results)
        self.queries = []

    async def execute(self, query):
        self.queries.append(query.compile(dialect=postgresql.dialect()))
        return next(self.results)


@pytest.mark.asyncio
async def test_cognism_research_requires_company_evidence_and_canonicalizes_ids():
    now = datetime(2026, 11, 17, 13, tzinfo=timezone.utc)
    started = now - timedelta(days=1)
    db = QueryResults(
        [
            ([1, 2], now, [1, 999], 1, "signals", {}),
            ([3, 4], now, None, 1, "signals", {}),
            ([5], now, None, 1, "enrich", {}),
            (
                [9, 10],
                now,
                [9, 10],
                2,
                "briefing",
                {"9": "first_call", "10": "ongoing"},
            ),
        ],
        [
            (6, "discovery", now - timedelta(hours=1), now),
            (7, "enrich", now - timedelta(hours=2), now),
        ],
    )
    evidence = await targets._research_evidence(db, since=started, canonical={1: 8})
    assert evidence == {5: now, 6: now, 7: now - timedelta(hours=2), 8: now, 9: now}
    for query in db.queries:
        assert started in query.params.values()
    assert "accepted" in db.queries[1].params.values()


@pytest.mark.asyncio
async def test_cognism_selects_only_unprocessed_eligible_companies_after_cooldown(
    monkeypatch,
):
    now = datetime(2026, 11, 17, 13, tzinfo=timezone.utc)
    evidence_at = now - timedelta(days=1)
    old = now - timedelta(hours=3)
    recent = now - timedelta(minutes=20)

    async def aliases(_db):
        return {99: 1}

    async def evidence(_db, *, since, canonical):
        assert since == evidence_at and canonical == {99: 1}
        return {
            **dict.fromkeys(range(1, 10), evidence_at),
            10: old + timedelta(minutes=1),
        }

    async def eligible(_db, ids):
        return set(ids) - {6}

    monkeypatch.setattr(settings, "SALES_COGNISM_PEOPLE_RESEARCH_SINCE", evidence_at)
    monkeypatch.setattr(targets, "company_merge_targets", aliases)
    monkeypatch.setattr(targets, "_research_evidence", evidence)
    monkeypatch.setattr(targets, "_eligible_people_companies", eligible)
    history = [
        ([99, 2], "received", old, old, None, [99]),
        ([10], "received", old, old, None, [10]),
        ([3], "failed", recent, None, None, None),
        ([4], "expired", old, None, recent, None),
        *[([5], "failed", old, None, None, None)] * 3,
    ]

    assert await targets.cognism_company_ids(QueryResults(history), now=now) == [
        2,
        7,
        8,
        9,
        10,
    ]
    assert await targets.cognism_company_ids(
        QueryResults(history), now=now, explicit_ids=[99, 2, 3, 4, 5, 6, 7, 8, 9, 10]
    ) == [2, 5, 7, 8, 9]


@pytest.mark.asyncio
async def test_worker_runs_independent_cognism_only_when_no_active_run(monkeypatch):
    now = datetime(2026, 11, 17, 13, tzinfo=timezone.utc)
    order = []
    active = False

    async def expire(_db, *, now):
        order.append("expire")
        return 1

    async def lock(_db):
        order.append("lock")

    async def in_progress(_db, *, now):
        order.append("active")
        return active

    async def company_ids(_db, *, now):
        order.append("choose")
        return [10, 20]

    async def start(_db, kind, ids, *, now, request):
        assert (kind, ids, request) == ("people", [10, 20], {"source": "cognism"})
        order.append("start")
        return SimpleNamespace(status="started")

    monkeypatch.setattr(settings, "SALES_COGNISM_PEOPLE_RESEARCH_SINCE", None)
    monkeypatch.setattr(worker.signals, "people_enabled", lambda: True)
    monkeypatch.setattr(worker.signals, "people_configured", lambda: True)
    monkeypatch.setattr(worker.signals, "expire_runs", expire)
    monkeypatch.setattr(worker.signals, "start_run", start)
    monkeypatch.setattr(targets, "lock_people_starts", lock)
    monkeypatch.setattr(targets, "cognism_run_active", in_progress)
    monkeypatch.setattr(targets, "cognism_company_ids", company_ids)

    async def tick():
        return await worker.tick(
            object(), now=now, local=now, legacy_ready=False, bot_tasks_ready=False
        )

    assert (await tick())["people"] == 0
    assert order == ["expire"]
    order.clear()

    monkeypatch.setattr(settings, "SALES_COGNISM_PEOPLE_RESEARCH_SINCE", now)
    assert (await tick()) == {
        "expired": 1,
        "signals": 0,
        "briefing": 0,
        "enrich": 0,
        "people": 2,
        # Biegi miesięczne (G-E, G-D) to krok zadań bota: tu wyłączony.
        "winback": 0,
        "discovery": 0,
        # Haczyk i teczka stoją bez kanału punktów i flagi zadań.
        "call_hook": 0,
        "meeting_prep": 0,
        # Teczka leada to też krok zadań bota.
        "dossier": 0,
    }
    assert order == ["expire", "lock", "active", "choose", "start"]
    order.clear()

    active = True
    assert (await tick())["people"] == 0
    assert order == ["expire", "lock", "active"]
