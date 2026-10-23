"""Insights → „W drodze” (`/api/insights/recruitment/in-flight`) i akceptacje w lejku.

Prośba Artura 22.10.2026: widać placementy, ale nie widać, ile akceptacji
czeka na domknięcie i ile z nich zwykle się domyka. Kolumna pary = reguła
Tablicy (ta sama co „Teraz” w raporcie „Lejek po etapach”), „od kiedy” =
wejście do kolumny, a nie do ostatniej odznaki w niej.

Baza testowa jest wspólna: serwis zawężamy do własnych rekrutacji
(`job_ids`), a daty leżą w roku, którego nie używa nikt inny.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.api.insights_recruitment import stage_counted_from, trend_weeks
from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.job import Job, JobStatus, RemotePolicy
from app.models.pipeline_template import (
    PipelineStageDef,
    PipelineTemplate,
    StageCategoryEnum,
)
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.models.user import User, UserRole
from app.services.insights_in_flight import (
    MIN_FORECAST_SAMPLE,
    compute_in_flight,
    forecast_range,
)

_YEAR = 2057


def _at(month: int, day: int) -> datetime:
    return datetime(_YEAR, month, day, 12, 0, tzinfo=timezone.utc)


# ── Czysta arytmetyka ────────────────────────────────────────────────────────


def test_forecast_needs_enough_resolved_acceptances() -> None:
    assert forecast_range(10, 8, MIN_FORECAST_SAMPLE - 1) == {
        "rate_pct": None,
        "low": None,
        "high": None,
    }


def test_forecast_gives_a_range_not_false_precision() -> None:
    # 43 z 50 = 86% → 10 otwartych × 0,86 = 8,6 → „8–9”.
    assert forecast_range(10, 43, 50) == {"rate_pct": 86.0, "low": 8, "high": 9}


def test_forecast_with_no_open_acceptances_is_zero() -> None:
    assert forecast_range(0, 9, 10) == {"rate_pct": 90.0, "low": 0, "high": 0}


def test_acceptance_before_cutover_is_counted_only_from_cutover() -> None:
    september = datetime(2026, 9, 1, tzinfo=timezone.utc)
    november = datetime(2026, 11, 1, tzinfo=timezone.utc)
    assert stage_counted_from("acceptance", september) == date(2026, 10, 12)
    assert stage_counted_from("acceptance", november) is None
    # Etapy z DynaReportera mają liczby także przed 12.10.
    for stage in ("verified", "cv_sent", "client_interview", "hired"):
        assert stage_counted_from(stage, september) is None


def test_trend_weeks_end_with_the_current_monday() -> None:
    weeks = trend_weeks(date(2026, 10, 22), 8)  # czwartek
    assert len(weeks) == 8
    assert weeks[-1] == date(2026, 10, 19)
    assert weeks[0] == date(2026, 8, 31)
    assert all(w.weekday() == 0 for w in weeks)


# ── Liczby z prawdziwej bazy ─────────────────────────────────────────────────


async def _seed() -> dict[str, Any]:
    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        dl = User(
            email=f"in-flight-dl-{tag}@example.com",
            name=f"DL {tag}",
            password_hash=hash_password(f"T3st_{tag}!Dl"),
            role=UserRole.delivery_lead,
            is_active=True,
        )
        rec = User(
            email=f"in-flight-rec-{tag}@example.com",
            name=f"Rekruter {tag}",
            password_hash=hash_password(f"T3st_{tag}!Rec"),
            role=UserRole.recruiter,
            is_active=True,
        )
        db.add(rec)
        cli = Client(name=f"InFlight-{tag}")
        tpl = PipelineTemplate(name=f"W drodze {tag}")
        db.add_all([dl, cli, tpl])
        await db.flush()
        contract_sent = PipelineStageDef(
            template_id=tpl.id,
            name="Umowa wysłana",
            order=1,
            category=StageCategoryEnum.external,
        )
        open_job = Job(
            title=f"W drodze A {tag}",
            location="Warszawa",
            status=JobStatus.published,
            remote_policy=RemotePolicy.hybrid,
            client_id=cli.id,
            delivery_lead_id=dl.id,
        )
        closed_job = Job(
            title=f"W drodze B {tag}",
            location="Warszawa",
            status=JobStatus.closed,
            remote_policy=RemotePolicy.hybrid,
            client_id=cli.id,
        )
        db.add_all([contract_sent, open_job, closed_job])
        await db.flush()

        cands = []
        for i in range(6):
            c = Candidate(
                name=f"Droga{i}",
                lastname=f"Test-{tag}",
                email=f"in-flight-{tag}-{i}@example.com",
            )
            db.add(c)
            cands.append(c)
        await db.flush()
        c = [x.id for x in cands]
        a, b = open_job.id, closed_job.id

        def row(cand: int, job: int, stage: PipelineStage, when: datetime, **kw):
            db.add(
                CandidateStage(
                    candidate_id=cand, job_id=job, stage=stage, moved_at=when, **kw
                )
            )

        # c0: CV u klienta od 1.03.
        row(c[0], a, PipelineStage.verified, _at(2, 20))
        row(c[0], a, PipelineStage.cv_sent, _at(3, 1))
        # c1: zweryfikowany przez rekrutera; akceptacja 10.03, potem „Umowa
        # wysłana” (kod `new` + nazwa) 20.03 — nadal kolumna Umowa, od 10.03.
        row(c[1], a, PipelineStage.verified, _at(2, 25), moved_by=rec.id)
        row(c[1], a, PipelineStage.cv_sent, _at(3, 1))
        row(c[1], a, PipelineStage.acceptance, _at(3, 10))
        row(c[1], a, PipelineStage.new, _at(3, 20), stage_def_id=contract_sent.id)
        # c2: akceptacja, potem powrót na rozmowę — liczy się od powrotu.
        row(c[2], a, PipelineStage.acceptance, _at(3, 5))
        row(c[2], a, PipelineStage.client_interview, _at(3, 15))
        # c3: akceptacja domknięta placementem.
        row(c[3], a, PipelineStage.acceptance, _at(3, 2))
        row(c[3], a, PipelineStage.hired, _at(3, 12))
        # c4: akceptacja zakończona odrzuceniem.
        row(c[4], a, PipelineStage.acceptance, _at(3, 3))
        row(c[4], a, PipelineStage.rejected, _at(3, 13), ended_by="client")
        # c5: akceptacja w zamkniętej rekrutacji, bez rozstrzygnięcia — ani
        # „w drodze”, ani w skuteczności.
        row(c[5], b, PipelineStage.acceptance, _at(3, 4))
        await db.commit()
        return {
            "open_job": a,
            "closed_job": b,
            "client": cli.name,
            "dl": dl.name,
            "dl_id": dl.id,
            "rec_id": rec.id,
            "c1": c[1],
        }


@pytest.mark.asyncio
async def test_in_flight_counts_columns_ages_and_acceptances() -> None:
    world = await _seed()
    async with AsyncSessionLocal() as db:
        result = await compute_in_flight(
            db,
            today=date(_YEAR, 3, 31),
            now=_at(3, 31),
            with_acceptances=True,
            job_ids=[world["open_job"], world["closed_job"]],
        )

    by_col = {c["column"]: c for c in result["columns"]}
    assert [c["column"] for c in result["columns"]] == [
        "cv_qc",
        "cv_sent",
        "client_interview",
        "contract",
    ]
    assert by_col["cv_qc"]["count"] == 0
    assert by_col["cv_qc"]["oldest_days"] is None
    assert by_col["cv_sent"]["count"] == 1
    assert by_col["cv_sent"]["oldest_days"] == 30
    assert by_col["cv_sent"]["stale_count"] == 1
    assert by_col["client_interview"]["count"] == 1
    assert by_col["client_interview"]["oldest_days"] == 16
    assert by_col["contract"]["count"] == 1

    [acc] = result["acceptances"]
    assert acc["job_id"] == world["open_job"]
    assert acc["client_name"] == world["client"]
    assert acc["delivery_lead_name"] == world["dl"]
    assert acc["stage_key"] == "contract_sent"
    assert acc["stage_label"] == "Umowa wysłana"
    assert acc["since"] == f"{_YEAR}-03-10"
    assert acc["days"] == 21
    # Nigdy nazwiska kandydata.
    assert "candidate_id" not in acc and "candidate_name" not in acc

    forecast = result["forecast"]
    assert forecast["open"] == 1
    assert (forecast["hired"], forecast["resolved"]) == (1, 2)
    assert forecast["rate_pct"] is None  # 2 < MIN_FORECAST_SAMPLE


@pytest.mark.asyncio
async def test_in_flight_without_list_keeps_counts() -> None:
    world = await _seed()
    async with AsyncSessionLocal() as db:
        result = await compute_in_flight(
            db,
            today=date(_YEAR, 3, 31),
            now=_at(3, 31),
            with_acceptances=False,
            job_ids=[world["open_job"]],
        )
    assert result["acceptances"] is None
    assert sum(c["count"] for c in result["columns"]) == 3


@pytest.mark.asyncio
async def test_my_in_flight_keeps_only_pairs_i_verified() -> None:
    world = await _seed()
    async with AsyncSessionLocal() as db:
        result = await compute_in_flight(
            db,
            today=date(_YEAR, 3, 31),
            now=_at(3, 31),
            with_acceptances=False,
            owner=("verifier", world["rec_id"]),
            with_people=True,
            job_ids=[world["open_job"]],
        )
    [person] = result["people"]
    assert person["candidate_id"] == world["c1"]
    assert person["candidate_name"].startswith("Droga1 ")
    assert person["column"] == "contract"
    assert person["stage_label"] == "Umowa wysłana"
    assert sum(c["count"] for c in result["columns"]) == 1


@pytest.mark.asyncio
async def test_portfolio_in_flight_is_the_delivery_leads_jobs() -> None:
    world = await _seed()
    async with AsyncSessionLocal() as db:
        result = await compute_in_flight(
            db,
            today=date(_YEAR, 3, 31),
            now=_at(3, 31),
            with_acceptances=False,
            owner=("delivery_lead", world["dl_id"]),
            with_people=True,
            job_ids=[world["open_job"], world["closed_job"]],
        )
    # Trzy pary w drodze w otwartej rekrutacji DL; zamknięta — poza.
    assert len(result["people"]) == 3
    assert [p["column"] for p in result["people"]] == [
        "contract",
        "client_interview",
        "cv_sent",
    ]


# ── API ──────────────────────────────────────────────────────────────────────


async def _login(client: AsyncClient, role: UserRole) -> dict[str, str]:
    unique = uuid.uuid4().hex[:8]
    email = f"in-flight-{role.value}-{unique}@example.com"
    password = f"T3st_{unique}!Droga"
    async with AsyncSessionLocal() as db:
        db.add(
            User(
                email=email,
                name=f"Droga {unique}",
                password_hash=hash_password(password),
                role=role,
                is_active=True,
            )
        )
        await db.commit()
    resp = await client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


@pytest_asyncio.fixture
async def fx_client() -> AsyncClient:
    from app.core.rate_limit import limiter as _limiter
    from app.main import app

    _limiter.enabled = False
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=True),
        base_url="http://testserver",
    ) as c:
        yield c


@pytest.mark.asyncio
async def test_in_flight_requires_login(fx_client: AsyncClient) -> None:
    resp = await fx_client.get("/api/insights/recruitment/in-flight")
    assert resp.status_code in (401, 403)


@pytest.mark.asyncio
async def test_recruiter_gets_counts_without_the_acceptance_list(
    fx_client: AsyncClient,
) -> None:
    headers = await _login(fx_client, UserRole.recruiter)
    resp = await fx_client.get("/api/insights/recruitment/in-flight", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["acceptances"] is None
    assert {c["column"] for c in body["columns"]} == {
        "cv_qc",
        "cv_sent",
        "client_interview",
        "contract",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("role", [UserRole.head_of_recruitment, UserRole.board])
async def test_team_readers_get_the_acceptance_list(
    fx_client: AsyncClient, role: UserRole
) -> None:
    headers = await _login(fx_client, role)
    resp = await fx_client.get("/api/insights/recruitment/in-flight", headers=headers)
    assert resp.status_code == 200, resp.text
    assert isinstance(resp.json()["acceptances"], list)


@pytest.mark.asyncio
async def test_my_in_flight_portfolio_is_only_for_delivery_leads(
    fx_client: AsyncClient,
) -> None:
    headers = await _login(fx_client, UserRole.recruiter)
    mine = await fx_client.get(
        "/api/insights/recruitment/in-flight/me", headers=headers
    )
    assert mine.status_code == 200, mine.text
    assert isinstance(mine.json()["people"], list)
    portfolio = await fx_client.get(
        "/api/insights/recruitment/in-flight/me",
        headers=headers,
        params={"scope": "portfolio"},
    )
    assert portfolio.status_code == 403


@pytest.mark.asyncio
async def test_funnel_marks_acceptance_as_counted_from_cutover(
    fx_client: AsyncClient,
) -> None:
    headers = await _login(fx_client, UserRole.recruiter)
    resp = await fx_client.get(
        "/api/insights/recruitment/funnel",
        headers=headers,
        params={
            "period": "custom",
            "date_from": "2026-09-01",
            "date_to": "2026-10-31",
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    stages = {s["stage"]: s for s in body["stages"]}
    assert stages["acceptance"]["counted_from"] == "2026-10-12"
    assert stages["hired"]["counted_from"] is None
    conversions = {c["key"]: c for c in body["conversions"]}
    # Akceptacje tylko od 12.10, rozmowy z całego okna — ilorazu nie ma.
    assert conversions["interview_to_acceptance"]["partial_window"] is True
    assert conversions["interview_to_acceptance"]["pct"] is None
    assert conversions["acceptance_to_hired"]["pct"] is None
    assert conversions["verified_to_cv_sent"]["partial_window"] is False


@pytest.mark.asyncio
async def test_weekly_trend_marks_acceptance_before_cutover_as_missing(
    fx_client: AsyncClient,
) -> None:
    headers = await _login(fx_client, UserRole.recruiter)
    resp = await fx_client.get(
        "/api/insights/recruitment/weekly-trend", headers=headers, params={"weeks": 8}
    )
    assert resp.status_code == 200, resp.text
    weeks = resp.json()["weeks"]
    assert len(weeks) == 8
    assert weeks[-1]["partial"] is True
    for week in weeks:
        assert set(week["counts"]) == {
            "verified",
            "cv_sent",
            "client_interview",
            "acceptance",
            "hired",
        }
        if week["week_start"] < "2026-10-12":
            assert week["counts"]["acceptance"] is None
        assert isinstance(week["counts"]["hired"], int)


@pytest.mark.asyncio
async def test_team_goals_are_sums_for_any_insights_reader(
    fx_client: AsyncClient,
) -> None:
    headers = await _login(fx_client, UserRole.recruiter)
    resp = await fx_client.get("/api/insights/recruitment/team-goals", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["kind"] == "team"
    assert isinstance(body["goals"], list)
