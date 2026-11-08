"""GET /api/insights/clients/funnel — tabela „Klienci” (audyt 08.11.2026, B3).

Definicje pod ochroną: zdarzenia to pierwsze wejście pary na etap w oknie,
wykluczony placement się nie liczy, hit ratio to wygrane / (wygrane + przegrane),
a zamknięcia bez powodu stoją osobno i nie obniżają wyniku klienta.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient

from app.analytics.periods import resolve_period
from app.core.cache import cache_invalidate
from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today, local_day_start_utc
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.job import Job, JobCloseReason, JobStatus, RemotePolicy
from app.models.placement_exclusion import PlacementExclusion
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.services.insights_client_funnel import (
    ClientFunnelRow,
    compute_client_funnel,
    cv_per_hire,
    fold_funnel_totals,
)

FUNNEL = "/api/insights/clients/funnel"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _row(**kw) -> ClientFunnelRow:
    base = dict(
        client_id=1,
        client_name="A",
        cv_sent=0,
        client_interviews=0,
        hires=0,
        cv_per_hire=None,
        won=0,
        lost=0,
        unreviewed=0,
        hit_ratio=None,
        first_cv_median_days=None,
        first_cv_jobs=0,
    )
    base.update(kw)
    return ClientFunnelRow(**base)


async def _client(name: str) -> int:
    async with AsyncSessionLocal() as db:
        client = Client(name=f"{name} {uuid.uuid4().hex[:8]}")
        db.add(client)
        await db.commit()
        return client.id


async def _job(
    client_id: int,
    *,
    status: JobStatus = JobStatus.published,
    reason: JobCloseReason | None = None,
    closed_at: datetime | None = None,
    opened_at: datetime | None = None,
) -> int:
    async with AsyncSessionLocal() as db:
        job = Job(
            title=f"Lejek {uuid.uuid4().hex[:6]}",
            description="x",
            status=status,
            client_id=client_id,
            remote_policy=RemotePolicy.remote,
            close_reason=reason,
            closed_at=closed_at,
            opened_at=opened_at,
        )
        db.add(job)
        await db.commit()
        return job.id


async def _candidate() -> int:
    async with AsyncSessionLocal() as db:
        candidate = Candidate(
            name="Profil",
            lastname=uuid.uuid4().hex[:8],
            email=f"lejek-{uuid.uuid4().hex[:8]}@example.com",
        )
        db.add(candidate)
        await db.commit()
        return candidate.id


async def _stage(
    candidate_id: int, job_id: int, stage: PipelineStage, at: datetime
) -> None:
    async with AsyncSessionLocal() as db:
        db.add(
            CandidateStage(
                candidate_id=candidate_id, job_id=job_id, stage=stage, moved_at=at
            )
        )
        await db.commit()


async def _row_for(client_id: int, start: datetime, end: datetime) -> ClientFunnelRow:
    async with AsyncSessionLocal() as db:
        rows = await compute_client_funnel(db, start=start, end=end)
    found = [r for r in rows if r.client_id == client_id]
    assert len(found) == 1
    return found[0]


def test_cv_per_hire_is_empty_without_hires() -> None:
    assert cv_per_hire(35, 0) is None
    assert cv_per_hire(811, 23) == 35.3


def test_totals_fold_the_visible_rows() -> None:
    totals = fold_funnel_totals(
        [
            _row(cv_sent=10, hires=2, won=1, lost=3, unreviewed=4, client_interviews=5),
            _row(client_id=2, cv_sent=5, hires=1, won=1, lost=1),
        ]
    )
    assert totals["cv_sent"] == 15
    assert totals["hires"] == 3
    assert totals["cv_per_hire"] == 5.0
    assert totals["unreviewed"] == 4
    # 2 wygrane z 6 rozstrzygniętych; „do przejrzenia” poza mianownikiem.
    assert totals["hit_ratio"] == 33.3


@pytest.mark.asyncio
async def test_counts_first_entry_per_pair_inside_the_window_only() -> None:
    client_id = await _client("Okno")
    job_id = await _job(client_id)
    start = _now() - timedelta(days=10)
    end = _now() + timedelta(hours=1)
    inside = _now() - timedelta(days=2)
    candidate = await _candidate()
    await _stage(candidate, job_id, PipelineStage.cv_sent, inside)
    # Drugie wejście tej samej pary na etap nie jest nowym CV.
    await _stage(candidate, job_id, PipelineStage.cv_sent, inside + timedelta(hours=3))
    await _stage(candidate, job_id, PipelineStage.client_interview, inside)
    await _stage(candidate, job_id, PipelineStage.hired, inside)
    # Para z CV przed oknem nie wchodzi do CV tego okresu.
    old = await _candidate()
    await _stage(old, job_id, PipelineStage.cv_sent, start - timedelta(days=5))

    row = await _row_for(client_id, start, end)

    assert (row.cv_sent, row.client_interviews, row.hires) == (1, 1, 1)
    assert row.cv_per_hire == 1.0


@pytest.mark.asyncio
async def test_excluded_placement_is_not_a_hire() -> None:
    client_id = await _client("Wykluczenie")
    job_id = await _job(client_id)
    candidate = await _candidate()
    at = _now() - timedelta(days=1)
    await _stage(candidate, job_id, PipelineStage.cv_sent, at)
    await _stage(candidate, job_id, PipelineStage.hired, at)
    async with AsyncSessionLocal() as db:
        db.add(
            PlacementExclusion(candidate_id=candidate, job_id=job_id, reason="manual")
        )
        await db.commit()

    row = await _row_for(client_id, _now() - timedelta(days=5), _now())

    assert (row.cv_sent, row.hires, row.cv_per_hire) == (1, 0, None)


@pytest.mark.asyncio
async def test_hit_ratio_shows_unreviewed_apart_from_lost() -> None:
    """Zamknięte bez powodu nie obniżają hit ratio; stoją w osobnej kolumnie."""
    client_id = await _client("Hit")
    start = _now() - timedelta(days=14)
    closed = _now() - timedelta(days=2)
    candidate = await _candidate()
    # Wygrana: zatrudnienie, nawet bez powodu zamknięcia.
    won_without_reason = await _job(
        client_id, status=JobStatus.closed, closed_at=closed
    )
    await _stage(candidate, won_without_reason, PipelineStage.hired, closed)
    await _job(
        client_id,
        status=JobStatus.closed,
        reason=JobCloseReason.competitor,
        closed_at=closed,
    )
    await _job(
        client_id,
        status=JobStatus.closed,
        reason=JobCloseReason.no_activity,
        closed_at=closed,
    )
    # Duplikat nie liczy się nigdzie; bez powodu i „Inny” — do przejrzenia.
    await _job(
        client_id,
        status=JobStatus.closed,
        reason=JobCloseReason.duplicate,
        closed_at=closed,
    )
    await _job(client_id, status=JobStatus.closed, closed_at=closed)
    await _job(
        client_id,
        status=JobStatus.closed,
        reason=JobCloseReason.other,
        closed_at=closed,
    )

    row = await _row_for(client_id, start, _now())

    assert (row.won, row.lost, row.unreviewed) == (1, 2, 2)
    assert row.hit_ratio == 33.3


@pytest.mark.asyncio
async def test_hit_ratio_ignores_closures_before_the_rule_started() -> None:
    client_id = await _client("Przed")
    before = local_day_start_utc(business_today()) - timedelta(days=400)
    await _job(
        client_id,
        status=JobStatus.closed,
        reason=JobCloseReason.competitor,
        closed_at=before,
    )
    candidate = await _candidate()
    job_id = await _job(client_id)
    await _stage(candidate, job_id, PipelineStage.cv_sent, before)

    row = await _row_for(
        client_id, before - timedelta(days=1), before + timedelta(days=1)
    )

    assert (row.won, row.lost, row.unreviewed) == (0, 0, 0)
    assert row.cv_sent == 1
    assert row.hit_ratio is None


@pytest.mark.asyncio
async def test_first_cv_median_counts_days_from_opening() -> None:
    client_id = await _client("Mediana")
    now = _now()
    for days_to_first_cv in (1, 3, 5):
        opened = now - timedelta(days=days_to_first_cv + 1)
        job_id = await _job(client_id, opened_at=opened)
        first = await _candidate()
        at = opened + timedelta(days=days_to_first_cv)
        await _stage(first, job_id, PipelineStage.cv_sent, at)
        later = await _candidate()
        # Drugie CV w tej samej rekrutacji nie zmienia „pierwszego CV”.
        await _stage(later, job_id, PipelineStage.cv_sent, at + timedelta(hours=20))

    row = await _row_for(client_id, now - timedelta(days=30), now + timedelta(days=1))

    assert row.first_cv_jobs == 3
    assert row.first_cv_median_days == 3.0


@pytest.mark.asyncio
async def test_hidden_client_does_not_appear() -> None:
    client_id = await _client("Ukryty")
    async with AsyncSessionLocal() as db:
        client = await db.get(Client, client_id)
        client.hidden = True
        await db.commit()
    job_id = await _job(client_id)
    candidate = await _candidate()
    await _stage(candidate, job_id, PipelineStage.cv_sent, _now() - timedelta(days=1))
    async with AsyncSessionLocal() as db:
        rows = await compute_client_funnel(
            db, start=_now() - timedelta(days=5), end=_now() + timedelta(hours=1)
        )
    assert client_id not in {r.client_id for r in rows}


@pytest.mark.asyncio
async def test_route_returns_rows_totals_and_no_money(
    app_client: AsyncClient, app_auth_headers: dict
) -> None:
    client_id = await _client("Trasa")
    job_id = await _job(client_id)
    candidate = await _candidate()
    # Stempel liczony od początku okna, bo „2 godziny temu” w poniedziałek
    # o 00:30 w Warszawie to jeszcze poprzedni tydzień.
    in_this_week = resolve_period("week").start + timedelta(minutes=1)
    await _stage(candidate, job_id, PipelineStage.cv_sent, in_this_week)
    await cache_invalidate("insights:clients:funnel:")

    response = await app_client.get(
        FUNNEL, params={"period": "week"}, headers=app_auth_headers
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["hit_ratio_target_pct"] == 30.0
    assert body["hit_ratio_since"].startswith("2026-10-1")
    row = next(r for r in body["clients"] if r["client_id"] == client_id)
    assert row["cv_sent"] == 1
    assert body["totals"]["cv_sent"] >= 1
    assert "margin" not in str(body) and "revenue" not in str(body)
