"""Testy KPI Coach v2 + kanonicznych metryk (plan PR 4).

Pokrywa: powtórne przejście przez stage, atrybucję pierwszego weryfikatora,
fallback bez verified, rozmowy completed z COALESCE(started_at, created_at),
CloudTalk unavailable (KPI rozmów znika zamiast straszyć zerem), target
resolution (override → rola → code default), hire rate źródeł ≤ 100%.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.call import Call, CallStatus
from app.models.candidate import Candidate
from app.models.candidate_source_event import CandidateSourceEvent, SourceChannel
from app.models.client import Client
from app.models.job import Job
from app.models.kpi_target import UserKpiTarget
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.models.user import User, UserRole
from app.services.kpi_catalog import KPI_CATALOG, KpiMetric, get_kpi
from app.services.kpi_engine import (
    count_canonical_metric,
    evaluate_user_kpis,
    resolve_target,
)

T0 = datetime(2026, 7, 6, 10, 0, tzinfo=timezone.utc)


@pytest_asyncio.fixture
async def seeded():
    """Para (kandydat, job): verified(A) → cv_sent(B) → verified(B, powtórka)
    → hired(B). Plus rozmowy usera A i eventy źródeł."""
    unique = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        user_a = User(
            email=f"kpiA-{unique}@example.com",
            password_hash=hash_password("x"),
            name="KPI A",
            role=UserRole.recruiter,
            is_active=True,
        )
        user_b = User(
            email=f"kpiB-{unique}@example.com",
            password_hash=hash_password("x"),
            name="KPI B",
            role=UserRole.recruiter,
            is_active=True,
        )
        client = Client(name=f"KPI Client {unique}")
        db.add_all([user_a, user_b, client])
        await db.flush()

        job = Job(title=f"KPI Job {unique}", client_id=client.id)
        candidate = Candidate(
            name="Kai",
            lastname=f"Piae-{unique}",
            created_by=user_a.id,
            # Jawnie w oknie T0 — server_default now() wypadałby poza
            # deterministyczne okna testów.
            created_at=T0,
        )
        db.add_all([job, candidate])
        await db.flush()

        stages = [
            (PipelineStage.verified, T0, user_a.id),
            (PipelineStage.cv_sent, T0 + timedelta(hours=2), user_b.id),
            (PipelineStage.verified, T0 + timedelta(hours=3), user_b.id),
            (PipelineStage.hired, T0 + timedelta(days=2), user_b.id),
        ]
        for stage, moved_at, moved_by in stages:
            db.add(
                CandidateStage(
                    candidate_id=candidate.id,
                    job_id=job.id,
                    stage=stage,
                    moved_at=moved_at,
                    moved_by=moved_by,
                )
            )

        # Rozmowy usera A: completed bez started_at (fallback created_at),
        # completed ze started_at, failed (nie liczy się), completed poza oknem.
        calls = [
            Call(
                candidate_id=candidate.id,
                user_id=user_a.id,
                status=CallStatus.completed,
                started_at=None,
                created_at=T0 + timedelta(hours=1),
            ),
            Call(
                candidate_id=candidate.id,
                user_id=user_a.id,
                status=CallStatus.completed,
                started_at=T0 + timedelta(hours=2),
            ),
            Call(
                candidate_id=candidate.id,
                user_id=user_a.id,
                status=CallStatus.failed,
                started_at=T0 + timedelta(hours=3),
            ),
            Call(
                candidate_id=candidate.id,
                user_id=user_a.id,
                status=CallStatus.completed,
                started_at=T0 + timedelta(days=30),
            ),
        ]
        db.add_all(calls)

        # Źródła: 3 eventy w JEDNYM kanale dla zatrudnionego kandydata —
        # stary licznik dawał hired=3 przy candidates=1 (rate 300%).
        for offset in (0, 1, 2):
            db.add(
                CandidateSourceEvent(
                    candidate_id=candidate.id,
                    channel=SourceChannel.posting,
                    captured_at=T0 - timedelta(days=offset),
                )
            )
        await db.commit()

        return {
            "user_a": user_a.id,
            "user_b": user_b.id,
            "candidate": candidate.id,
            "job": job.id,
        }


# ── Atrybucja kanoniczna ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_first_verification_credited_once_to_first_verifier(seeded):
    """Powtórne verified NIE liczy się drugi raz; kredyt = pierwszy weryfikator."""
    window = (T0 - timedelta(days=1), T0 + timedelta(days=1))
    async with AsyncSessionLocal() as db:
        a = await count_canonical_metric(
            db,
            user_id=seeded["user_a"],
            metric=KpiMetric.first_verifications,
            since=window[0],
            until=window[1],
        )
        b = await count_canonical_metric(
            db,
            user_id=seeded["user_b"],
            metric=KpiMetric.first_verifications,
            since=window[0],
            until=window[1],
        )
    assert a == 1, "pierwszy weryfikator (A) dostaje kredyt"
    assert b == 0, "powtórne verified (B) nie liczy się w ogóle"


@pytest.mark.asyncio
async def test_placement_credited_to_verifier_not_mover(seeded):
    """hired kliknął B, ale kredyt idzie do A (verifier-anchored, §4.2)."""
    window = (T0, T0 + timedelta(days=3))
    async with AsyncSessionLocal() as db:
        a = await count_canonical_metric(
            db,
            user_id=seeded["user_a"],
            metric=KpiMetric.first_placements,
            since=window[0],
            until=window[1],
        )
        b = await count_canonical_metric(
            db,
            user_id=seeded["user_b"],
            metric=KpiMetric.first_placements,
            since=window[0],
            until=window[1],
        )
    assert a == 1
    assert b == 0


@pytest.mark.asyncio
async def test_completed_calls_effective_date(seeded):
    """completed po COALESCE(started_at, created_at); failed nie liczy się."""
    window = (T0, T0 + timedelta(days=1))
    async with AsyncSessionLocal() as db:
        count = await count_canonical_metric(
            db,
            user_id=seeded["user_a"],
            metric=KpiMetric.completed_calls,
            since=window[0],
            until=window[1],
        )
    # 2 completed w oknie (1 z fallbackiem created_at); failed + poza oknem odpadają.
    assert count == 2


# ── Targety (plan: 15 rozmów / 4 weryfikacje, niezależne, konfigurowalne) ───


def test_catalog_defaults_match_plan():
    calls = get_kpi("daily_completed_calls")
    ver = get_kpi("daily_first_verifications")
    assert calls is not None and ver is not None
    assert calls.default_targets[UserRole.recruiter] == 15
    assert ver.default_targets[UserRole.recruiter] == 4
    # niezależne KPI — osobne wpisy katalogu
    assert calls.kpi_id != ver.kpi_id
    # katalog nie zawiera już KPI liczonych z UserActivity
    assert all(hasattr(k, "metric") for k in KPI_CATALOG)


@pytest.mark.asyncio
async def test_target_override_beats_default(seeded):
    async with AsyncSessionLocal() as db:
        user = await db.get(User, seeded["user_a"])
        db.add(
            UserKpiTarget(
                user_id=user.id,
                kpi_id="daily_completed_calls",
                target_value=25,
            )
        )
        await db.commit()

        kpi_def = get_kpi("daily_completed_calls")
        target = await resolve_target(db, user=user, kpi_def=kpi_def)
    assert target == 25


@pytest.mark.asyncio
async def test_cloudtalk_off_hides_calls_kpi(seeded, monkeypatch):
    """CloudTalk off ⇒ KPI rozmów ZNIKA (unavailable), nie świeci zerem."""
    monkeypatch.setattr(settings, "CLOUDTALK_ENABLED", False)
    async with AsyncSessionLocal() as db:
        user = await db.get(User, seeded["user_a"])
        results = await evaluate_user_kpis(db, user=user)
    ids = {r.kpi_id for r in results}
    assert "daily_completed_calls" not in ids
    assert "daily_first_verifications" in ids


@pytest.mark.asyncio
async def test_cloudtalk_on_shows_calls_kpi(seeded, monkeypatch):
    monkeypatch.setattr(settings, "CLOUDTALK_ENABLED", True)
    async with AsyncSessionLocal() as db:
        user = await db.get(User, seeded["user_a"])
        results = await evaluate_user_kpis(db, user=user)
    ids = {r.kpi_id for r in results}
    assert "daily_completed_calls" in ids


# ── Źródła: hire rate ≤ 100% ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_sources_hire_rate_not_above_100(seeded):
    """Kandydat z 3 eventami w kanale = hired 1, nie 3 (plan §3.2)."""
    from httpx import ASGITransport, AsyncClient

    from app.core.rate_limit import limiter as _limiter
    from app.main import app

    _limiter.enabled = False
    async with AsyncSessionLocal() as db:
        user = await db.get(User, seeded["user_a"])
        email = user.email

    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=True),
        base_url="http://testserver",
    ) as client:
        resp = await client.post(
            "/api/auth/login", json={"email": email, "password": "x"}
        )
        assert resp.status_code == 200, resp.text
        headers = {"Authorization": f"Bearer {resp.json()['access_token']}"}
        report = await client.get("/api/reports/sources?days=365", headers=headers)
        assert report.status_code == 200, report.text
        for row in report.json()["rows"]:
            assert row["hired"] <= row["candidates_total"], row
            assert row["hire_rate_pct"] <= 100.0, row


# ── Lista „Kto się liczy” = licznik celu (17.10.2026) ─────────────────────────

# Poniedziałek 13.07.2026, 10:00 w Warszawie — tydzień celu 13–19.07.
T_WEEK = datetime(2026, 7, 13, 8, 0, tzinfo=timezone.utc)


@pytest_asyncio.fixture
async def who_counts_seeded():
    """Rekruter A weryfikuje trzy pary, „CV wysłane” klika głównie DL B.

    - C1 × J1: weryfikacja A, CV wysłał B — czeka na klienta,
    - C1 × J2: weryfikacja A, CV wysłał A, rozmowa u klienta (ta sama osoba
      w dwóch rekrutacjach = dwie rekomendacje),
    - C2 × J1: weryfikacja A, CV wysłał B, klient odrzucił.
    """
    unique = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        recruiter = User(
            email=f"whoA-{unique}@example.com",
            password_hash=hash_password("x"),
            name="Lista A",
            role=UserRole.recruiter,
            is_active=True,
        )
        lead = User(
            email=f"whoB-{unique}@example.com",
            password_hash=hash_password("x"),
            name="Lista B",
            role=UserRole.delivery_lead,
            is_active=True,
        )
        client = Client(name=f"Lista Client {unique}")
        db.add_all([recruiter, lead, client])
        await db.flush()
        job_one = Job(title=f"Lista Job 1 {unique}", client_id=client.id)
        job_two = Job(title=f"Lista Job 2 {unique}", client_id=client.id)
        first = Candidate(name="Ala", lastname=f"Lista-{unique}", created_at=T_WEEK)
        second = Candidate(name="Ola", lastname=f"Lista-{unique}", created_at=T_WEEK)
        db.add_all([job_one, job_two, first, second])
        await db.flush()

        a, b = recruiter.id, lead.id
        hours = lambda n: T_WEEK + timedelta(hours=n)  # noqa: E731
        stages = [
            (first, job_one, PipelineStage.verified, hours(0), a, None),
            (first, job_one, PipelineStage.cv_sent, hours(1), b, None),
            (first, job_two, PipelineStage.verified, hours(2), a, None),
            (first, job_two, PipelineStage.cv_sent, hours(3), a, None),
            (first, job_two, PipelineStage.client_interview, hours(24), b, None),
            (second, job_one, PipelineStage.verified, hours(4), a, None),
            (second, job_one, PipelineStage.cv_sent, hours(5), b, None),
            (second, job_one, PipelineStage.rejected, hours(48), b, "client"),
        ]
        for candidate, job, stage, moved_at, moved_by, ended_by in stages:
            db.add(
                CandidateStage(
                    candidate_id=candidate.id,
                    job_id=job.id,
                    stage=stage,
                    moved_at=moved_at,
                    moved_by=moved_by,
                    ended_by=ended_by,
                )
            )
        await db.commit()
        return {
            "recruiter": a,
            "lead": b,
            "first": first.id,
            "second": second.id,
            "job_one": job_one.id,
        }


async def _who_counts(db, user, *, metric: str, subject_user_id: int, **kwargs):
    from datetime import date

    from app.services.recruitment_activity import list_recruitment_activity_details

    return await list_recruitment_activity_details(
        db,
        user,
        metric=metric,
        window="week",
        selected_day=date(2026, 7, 15),
        selected_month=date(2026, 7, 1),
        subject_user_id=subject_user_id,
        team_scope=False,
        page=1,
        page_size=100,
        **kwargs,
    )


@pytest.mark.asyncio
async def test_who_counts_list_equals_the_goal_counter(who_counts_seeded):
    """Liczba wierszy listy = licznik celu w pasku dla tej samej osoby i tygodnia."""
    from zoneinfo import ZoneInfo

    warsaw = ZoneInfo("Europe/Warsaw")
    since = datetime(2026, 7, 13, tzinfo=warsaw)
    until = datetime(2026, 7, 20, tzinfo=warsaw)
    seeded = who_counts_seeded
    async with AsyncSessionLocal() as db:
        recruiter = await db.get(User, seeded["recruiter"])
        lead = await db.get(User, seeded["lead"])
        for metric, kpi_metric in (
            ("recommendation", KpiMetric.first_recommendations),
            ("verification", KpiMetric.first_verifications),
        ):
            for user in (recruiter, lead):
                counter = await count_canonical_metric(
                    db, user_id=user.id, metric=kpi_metric, since=since, until=until
                )
                listed = await _who_counts(
                    db, user, metric=metric, subject_user_id=user.id
                )
                assert listed.period_total == counter, (metric, user.name)
                assert listed.total == len(listed.items) == counter, (metric, user.name)

        recommendations = await _who_counts(
            db, recruiter, metric="recommendation", subject_user_id=recruiter.id
        )

    # Zasługa idzie do weryfikatora, choć dwa z trzech „CV wysłane” kliknął DL.
    assert recommendations.period_total == 3
    assert recommendations.people == 2
    assert recommendations.moved_by_credited == 1
    assert recommendations.states == {
        "waiting": 1,
        "at_client": 1,
        "rejected_by_client": 1,
    }
    by_pair = {(item.candidate.id, item.job.id): item for item in recommendations.items}
    sent_by_lead = by_pair[(seeded["first"], seeded["job_one"])]
    assert sent_by_lead.moved_by is not None
    assert sent_by_lead.moved_by.id == seeded["lead"]
    assert sent_by_lead.credited_user is not None
    assert sent_by_lead.credited_user.id == seeded["recruiter"]
    assert sent_by_lead.candidate_jobs == 2
    assert by_pair[(seeded["second"], seeded["job_one"])].candidate_jobs == 1
    assert recommendations.period_start.isoformat() == "2026-07-13"
    assert recommendations.period_end.isoformat() == "2026-07-19"


@pytest.mark.asyncio
async def test_who_counts_state_filter_keeps_period_counts(who_counts_seeded):
    seeded = who_counts_seeded
    async with AsyncSessionLocal() as db:
        recruiter = await db.get(User, seeded["recruiter"])
        rejected = await _who_counts(
            db,
            recruiter,
            metric="recommendation",
            subject_user_id=recruiter.id,
            state="rejected_by_client",
        )
    assert rejected.total == 1
    assert rejected.period_total == 3
    assert [item.candidate.id for item in rejected.items] == [seeded["second"]]
    assert rejected.items[0].state_stage == "rejected"
