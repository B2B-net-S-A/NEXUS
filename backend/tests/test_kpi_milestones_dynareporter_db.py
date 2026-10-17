"""Statystyki 1.01–11.10.2026 z DynaReportera na żywym Postgresie (0454).

Zespół klika w NEXUS-ie od 12.10.2026; wcześniej wynik to tygodniowy wpis
w DynaReporterze. Ruchy Tablicy z tych dni (import z Traffita) nie liczą się
do statystyk, liczą się wpisy — w widoku ``analytics_kpi_milestones``,
w ``credited`` (licznik celów, Mój miesiąc, Zespół) i na liście „Kto się
liczy” (liczba bez wierszy kandydatów). Przed 2026 i od 12.10 — bez zmian.

Baza testowa nie jest czyszczona, a granice są stałe (2026), więc asercje
patrzą tylko na konta utworzone przez test.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

import pytest
import pytest_asyncio
from sqlalchemy import text

from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.dr_kpi_body_leasing import DrKpiBodyLeasing
from app.models.job import Job
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.models.user import User, UserRole
from app.services.kpi_catalog import KpiMetric
from app.services.kpi_engine import count_canonical_metric

WARSAW = ZoneInfo("Europe/Warsaw")
# Ruch z importu Traffita we wrześniu 2026 — dzień z DynaReportera.
TRAFFIT_SEPTEMBER = datetime(2026, 9, 8, 9, 0, tzinfo=timezone.utc)
# Pierwszy tydzień w NEXUS-ie.
NEXUS_OCTOBER = datetime(2026, 10, 13, 9, 0, tzinfo=timezone.utc)
# Przed DynaReporterem — od 0455 (18.10.2026) też nie liczy się z Tablicy.
BEFORE_2026 = datetime(2025, 12, 10, 9, 0, tzinfo=timezone.utc)


def _week(user_id: int, day: date, *, draft: bool = False, **counts):
    return DrKpiBodyLeasing(
        user_id=user_id,
        report_date=day,
        week_number=day.isocalendar()[1],
        is_draft=draft,
        days_worked=counts.pop("days_worked", 5),
        **counts,
    )


def _local(day: date) -> datetime:
    return datetime(day.year, day.month, day.day, tzinfo=WARSAW)


@pytest_asyncio.fixture
async def seeded():
    """Rekruter R i Delivery Lead D: wpisy R w DynaReporterze we wrześniu,
    ruchy Tablicy we wrześniu (import Traffita), w październiku i w 2025."""
    unique = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        recruiter = User(
            email=f"drkpi-r-{unique}@example.com",
            password_hash=hash_password("x"),
            name="Wpis R",
            role=UserRole.recruiter,
            is_active=True,
        )
        lead = User(
            email=f"drkpi-d-{unique}@example.com",
            password_hash=hash_password("x"),
            name="Wpis D",
            role=UserRole.delivery_lead,
            is_active=True,
        )
        client = Client(name=f"DR KPI Client {unique}")
        db.add_all([recruiter, lead, client])
        await db.flush()
        job = Job(title=f"DR KPI Job {unique}", client_id=client.id)
        db.add(job)
        await db.flush()

        r, d = recruiter.id, lead.id
        db.add_all(
            [
                _week(
                    r,
                    date(2026, 9, 7),
                    verifications=6,
                    recommendations=4,
                    interviews=2,
                    placements=1,
                ),
                _week(r, date(2026, 9, 14), verifications=4, recommendations=2),
                # Szkic i wpis z dnia cutoveru się nie liczą.
                _week(r, date(2026, 9, 21), draft=True, recommendations=9),
                _week(r, date(2026, 10, 12), recommendations=7),
            ]
        )

        moves = []
        for when in (TRAFFIT_SEPTEMBER, NEXUS_OCTOBER, BEFORE_2026):
            candidate = Candidate(
                name="Kai", lastname=f"Wpis-{unique}", created_at=when
            )
            db.add(candidate)
            await db.flush()
            # Weryfikuje R, CV wysyła D — zasługa (credited) idzie do R.
            moves += [
                CandidateStage(
                    candidate_id=candidate.id,
                    job_id=job.id,
                    stage=PipelineStage.verified,
                    moved_at=when,
                    moved_by=r,
                ),
                CandidateStage(
                    candidate_id=candidate.id,
                    job_id=job.id,
                    stage=PipelineStage.cv_sent,
                    moved_at=when.replace(hour=11),
                    moved_by=d,
                ),
            ]
        db.add_all(moves)
        await db.commit()
        return {"recruiter": r, "lead": d}


async def _view_counts(db, user_id: int, start: date, end: date) -> dict:
    rows = (
        await db.execute(
            text(
                """
                SELECT stage::text AS stage, source, count(*) AS n
                FROM analytics_kpi_milestones
                WHERE first_moved_by = :uid
                  AND first_reached_at >= :start
                  AND first_reached_at < :end
                GROUP BY 1, 2
                """
            ),
            {"uid": user_id, "start": _local(start), "end": _local(end)},
        )
    ).all()
    return {(row.stage, row.source): int(row.n) for row in rows}


async def _credited(db, user_id: int, metric: KpiMetric, start: date, end: date):
    return await count_canonical_metric(
        db, user_id=user_id, metric=metric, since=_local(start), until=_local(end)
    )


@pytest.mark.asyncio
async def test_view_takes_dynareporter_weeks_instead_of_board_moves(seeded) -> None:
    r, d = seeded["recruiter"], seeded["lead"]
    async with AsyncSessionLocal() as db:
        september = await _view_counts(db, r, date(2026, 9, 1), date(2026, 10, 1))
        lead_september = await _view_counts(db, d, date(2026, 9, 1), date(2026, 10, 1))
        october = await _view_counts(db, r, date(2026, 10, 1), date(2026, 11, 1))
        december = await _view_counts(db, r, date(2025, 12, 1), date(2026, 1, 1))

    assert september == {
        ("verified", "dynareporter"): 10,
        ("cv_sent", "dynareporter"): 6,
        ("client_interview", "dynareporter"): 2,
        ("hired", "dynareporter"): 1,
    }
    # Import z Traffita we wrześniu nie daje D (ani R) żadnego kamienia.
    assert lead_september == {}
    # Wpis DynaReportera z 12.10 nie wchodzi — od 12.10 liczy Tablica.
    assert october == {("verified", "nexus"): 1}
    # 0455: ruchów Tablicy sprzed 12.10.2026 nie ma także przed 2026.
    assert december == {}


@pytest.mark.asyncio
async def test_goal_counter_counts_dynareporter_before_cutover(seeded) -> None:
    r, d = seeded["recruiter"], seeded["lead"]
    recommendations = KpiMetric.first_recommendations
    async with AsyncSessionLocal() as db:
        assert (
            await _credited(db, r, recommendations, date(2026, 9, 1), date(2026, 10, 1))
            == 6
        )
        assert (
            await _credited(db, d, recommendations, date(2026, 9, 1), date(2026, 10, 1))
            == 0
        )
        # Październik = 0 z DynaReportera (wpisy do 11.10 nie istnieją dla R)
        # + 1 rekomendacja z Tablicy 13.10 z zasługą weryfikatora R.
        assert (
            await _credited(
                db, r, recommendations, date(2026, 10, 1), date(2026, 11, 1)
            )
            == 1
        )
        assert (
            await _credited(
                db,
                r,
                KpiMetric.first_placements,
                date(2026, 9, 1),
                date(2026, 10, 1),
            )
            == 1
        )


@pytest.mark.asyncio
async def test_who_counts_total_includes_weeks_without_rows(seeded) -> None:
    from app.services.recruitment_activity import list_recruitment_activity_details

    r = seeded["recruiter"]
    async with AsyncSessionLocal() as db:
        recruiter = await db.get(User, r)
        listed = await list_recruitment_activity_details(
            db,
            recruiter,
            metric="recommendation",
            window="month",
            selected_day=date(2026, 9, 15),
            selected_month=date(2026, 9, 1),
            subject_user_id=r,
            team_scope=False,
            page=1,
            page_size=50,
        )
        counter = await _credited(
            db, r, KpiMetric.first_recommendations, date(2026, 9, 1), date(2026, 10, 1)
        )

    assert listed.period_total == counter == 6
    assert listed.history_total == 6
    assert listed.total == 0
    assert listed.items == []


def _yoy_march(payload: dict) -> tuple[int, int, list[str]]:
    metric = next(m for m in payload["metrics"] if m["key"] == "placements")
    placements = metric["series"]["2026"][2]
    clients = payload["component_series"]["client_placements"]["2026"][2]
    names = [c["name"] for c in payload["placements_by_client"]["2026"][2]["clients"]]
    return placements, clients, names


@pytest.mark.asyncio
async def test_year_over_year_takes_entries_and_clients_from_dynareporter() -> None:
    """Rok do roku przed 12.10.2026: „Liczba placementów” z wpisów rekruterów,
    klienci z placementów z klientem DynaReportera; ruch Tablicy się nie liczy."""
    from app.services.insights_board_yoy import compute_board_yoy

    unique = uuid.uuid4().hex[:8]
    today = date(2026, 10, 17)
    async with AsyncSessionLocal() as db:
        before = _yoy_march(await compute_board_yoy(db, [2025, 2026], today))

        recruiter = User(
            email=f"drkpi-yoy-{unique}@example.com",
            password_hash=hash_password("x"),
            name="Wpis RdR",
            role=UserRole.recruiter,
            is_active=True,
        )
        client = Client(name=f"DR YoY Client {unique}")
        db.add_all([recruiter, client])
        await db.flush()
        job = Job(title=f"DR YoY Job {unique}", client_id=client.id)
        candidate = Candidate(name="Ula", lastname=f"RdR-{unique}")
        db.add_all([job, candidate])
        await db.flush()
        dr_client_id = (
            await db.execute(
                text(
                    "INSERT INTO dr_clients (name, is_active) "
                    "VALUES (:name, true) RETURNING id"
                ),
                {"name": f"DR YoY Client {unique}"},
            )
        ).scalar_one()
        await db.execute(
            text(
                "INSERT INTO dr_placement_details (user_id, client_id, placement_date) "
                "VALUES (:uid, :cid, DATE '2026-03-05')"
            ),
            {"uid": recruiter.id, "cid": dr_client_id},
        )
        db.add_all(
            [
                _week(recruiter.id, date(2026, 3, 2), placements=2),
                CandidateStage(
                    candidate_id=candidate.id,
                    job_id=job.id,
                    stage=PipelineStage.hired,
                    moved_at=datetime(2026, 3, 10, 9, 0, tzinfo=timezone.utc),
                    moved_by=recruiter.id,
                ),
            ]
        )
        await db.commit()

        after = _yoy_march(await compute_board_yoy(db, [2025, 2026], today))

    # Wiersz placementów: +2 z wpisu, zatrudnienie z Tablicy w marcu się nie liczy.
    assert after[0] - before[0] == 2
    # Klienci: placement z klientem z DynaReportera, połączony z klientem NEXUS-a
    # po nazwie; para Tablicy z marca nie wchodzi.
    assert after[1] - before[1] == 1
    assert f"DR YoY Client {unique}" in after[2] or len(after[2]) >= 8
