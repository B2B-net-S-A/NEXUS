"""Testy serwisu recruitment_trend (PR 2 sekcji „Statystyki rekrutacji").

Pokrywa: bucketowanie miesięczne w Europe/Warsaw (zdarzenie 22:30 UTC
ostatniego dnia miesiąca ląduje w NASTĘPNYM miesiącu), dopełnianie zerami do
dokładnie N punktów, clamp `months`, spójność z compute_team_panel (to samo
CTE atrybucji) oraz czyste funnel_conversions (mianownik 0 → None).

Trend liczy CAŁĄ bazę (bez filtra usera), a baza testowa jest współdzielona
między plikami — dlatego asercje liczbowe robimy na DELCIE dwóch wywołań
w obrębie jednego testu, nie na wartościach absolutnych.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.job import Job
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.models.user import User, UserRole
from app.services.kpi_team import compute_team_panel
from app.services.recruitment_trend import (
    funnel_conversions,
    monthly_milestone_trend,
)

WARSAW = ZoneInfo("Europe/Warsaw")
T_NOW = datetime(2026, 8, 20, 12, 0, tzinfo=WARSAW)


async def _seed_stage(stage: PipelineStage, moved_at: datetime) -> tuple[int, int, int]:
    """Świeży user+kandydat×job z jednym kamieniem milowym `stage`."""
    unique = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        user = User(
            email=f"trend-{unique}@example.com",
            password_hash=hash_password("x"),
            name=f"Trend {unique}",
            role=UserRole.recruiter,
            is_active=True,
        )
        client = Client(name=f"Trend Client {unique}")
        db.add_all([user, client])
        await db.flush()

        job = Job(title=f"Trend Job {unique}", client_id=client.id)
        candidate = Candidate(
            name="Tre",
            lastname=f"Nd-{unique}",
            created_by=user.id,
            created_at=moved_at,
        )
        db.add_all([job, candidate])
        await db.flush()
        db.add(
            CandidateStage(
                candidate_id=candidate.id,
                job_id=job.id,
                stage=stage,
                moved_at=moved_at,
                moved_by=user.id,
            )
        )
        await db.commit()
        return user.id, candidate.id, job.id


def _month_map(points):
    return {p.month: p for p in points}


@pytest.mark.asyncio
async def test_warsaw_bucketing_crosses_utc_month_boundary():
    """22:30 UTC 31.07 = 00:30 CEST 1.08 → kubełek 2026-08, nie 2026-07."""
    async with AsyncSessionLocal() as db:
        before = await monthly_milestone_trend(db, months=3, now=T_NOW)

    await _seed_stage(
        PipelineStage.verified,
        datetime(2026, 7, 31, 22, 30, tzinfo=timezone.utc),
    )

    async with AsyncSessionLocal() as db:
        after = await monthly_milestone_trend(db, months=3, now=T_NOW)

    b, a = _month_map(before), _month_map(after)
    assert a["2026-08"].weryfikacje == b["2026-08"].weryfikacje + 1
    assert a["2026-07"].weryfikacje == b["2026-07"].weryfikacje


@pytest.mark.asyncio
async def test_returns_exactly_n_zero_filled_contiguous_months():
    async with AsyncSessionLocal() as db:
        points = await monthly_milestone_trend(db, months=12, now=T_NOW)

    assert len(points) == 12
    assert points[0].month == "2025-09"
    assert points[-1].month == "2026-08"
    months = [p.month for p in points]
    assert months == sorted(months)
    # Miesiące bez aktywności istnieją w wyniku (zera, nie dziury).
    for p in points:
        assert p.weryfikacje >= 0 and p.placementy >= 0

    async with AsyncSessionLocal() as db:
        clamped_low = await monthly_milestone_trend(db, months=0, now=T_NOW)
        clamped_high = await monthly_milestone_trend(db, months=99, now=T_NOW)
    assert len(clamped_low) == 1
    assert len(clamped_high) == 24


@pytest.mark.asyncio
async def test_all_five_stages_map_to_fields():
    """Każdy z 5 kamieni (w tym acceptance) ląduje we właściwym polu."""
    stamp = datetime(2026, 8, 10, 9, 0, tzinfo=timezone.utc)
    async with AsyncSessionLocal() as db:
        before = _month_map(await monthly_milestone_trend(db, months=2, now=T_NOW))

    for stage in (
        PipelineStage.verified,
        PipelineStage.cv_sent,
        PipelineStage.interview,
        PipelineStage.acceptance,
        PipelineStage.hired,
    ):
        await _seed_stage(stage, stamp)

    async with AsyncSessionLocal() as db:
        after = _month_map(await monthly_milestone_trend(db, months=2, now=T_NOW))

    cur_b, cur_a = before["2026-08"], after["2026-08"]
    assert cur_a.weryfikacje == cur_b.weryfikacje + 1
    assert cur_a.rekomendacje == cur_b.rekomendacje + 1
    assert cur_a.interview == cur_b.interview + 1
    assert cur_a.akceptacje == cur_b.akceptacje + 1
    assert cur_a.placementy == cur_b.placementy + 1


@pytest.mark.asyncio
async def test_current_month_delta_consistent_with_team_panel():
    """Trend i panel zespołu liczą tym samym CTE — świeże zdarzenie widać
    w obu identycznie (spójność kafle ↔ wykres)."""
    stamp = datetime(2026, 8, 12, 9, 0, tzinfo=timezone.utc)
    async with AsyncSessionLocal() as db:
        before = _month_map(await monthly_milestone_trend(db, months=1, now=T_NOW))

    uid, _, _ = await _seed_stage(PipelineStage.verified, stamp)

    async with AsyncSessionLocal() as db:
        after = _month_map(await monthly_milestone_trend(db, months=1, now=T_NOW))
        panel = await compute_team_panel(
            db,
            bounds=(datetime(2026, 8, 1, tzinfo=WARSAW), T_NOW),
            now=T_NOW,
        )

    assert after["2026-08"].weryfikacje == before["2026-08"].weryfikacje + 1
    row = next(r for r in panel.rows if r.user_id == uid)
    assert row.weryfikacje == 1


@pytest.mark.asyncio
async def test_future_dated_rows_are_excluded_at_query_level():
    """Wiersz z przyszłą datą (np. przypadkowy seed) nie wpada do żadnego
    kubełka — wykluczony górną granicą w SQL, nie po cichu w Pythonie."""
    async with AsyncSessionLocal() as db:
        before = _month_map(await monthly_milestone_trend(db, months=2, now=T_NOW))

    # Miesiąc PO oknie (T_NOW = 2026-08-20 → wiersz z września).
    await _seed_stage(
        PipelineStage.verified,
        datetime(2026, 9, 10, 9, 0, tzinfo=timezone.utc),
    )

    async with AsyncSessionLocal() as db:
        after = _month_map(await monthly_milestone_trend(db, months=2, now=T_NOW))

    assert set(after.keys()) == {"2026-07", "2026-08"}
    assert after["2026-08"].weryfikacje == before["2026-08"].weryfikacje
    assert after["2026-07"].weryfikacje == before["2026-07"].weryfikacje


def test_funnel_conversions_null_denominator_and_rounding():
    empty = funnel_conversions(
        weryfikacje=0, rekomendacje=0, interview=0, akceptacje=0, placementy=0
    )
    assert empty.verified_to_recommendation_pct is None
    assert empty.recommendation_to_interview_pct is None
    assert empty.interview_to_acceptance_pct is None
    assert empty.acceptance_to_placement_pct is None
    assert empty.interview_to_placement_pct is None
    assert empty.overall_pct is None

    conv = funnel_conversions(
        weryfikacje=132, rekomendacje=97, interview=41, akceptacje=12, placementy=7
    )
    assert conv.verified_to_recommendation_pct == 73.5
    assert conv.recommendation_to_interview_pct == 42.3
    assert conv.interview_to_acceptance_pct == 29.3
    assert conv.acceptance_to_placement_pct == 58.3
    assert conv.interview_to_placement_pct == 17.1
    assert conv.overall_pct == 5.3

    # Mianownik 0 w środku lejka nie psuje pozostałych stopni.
    partial = funnel_conversions(
        weryfikacje=10, rekomendacje=0, interview=0, akceptacje=0, placementy=2
    )
    assert partial.verified_to_recommendation_pct == 0.0
    assert partial.recommendation_to_interview_pct is None
    assert partial.overall_pct == 20.0
