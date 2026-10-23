"""Widok Zespół w /insights (24.09.2026): ludzie, „Do uwagi", rekrutacje bez ruchu.

Pod ochroną:

1. Porównanie z poprzednim okresem idzie po TYM SAMYM odcinku — 24 dni
   września przeciw całemu sierpniowi dałyby fałszywy spadek.
2. Rekrutacja bez ruchu = opublikowana i bez etapu od 14 dni; bez etapów liczy
   się od otwarcia. Zamknięta nie jest „bez ruchu".
3. Trasy widoku wymagają ``VIEW_TEAM_KPI`` — rekruter dostaje 403, nie cudze
   wyniki.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from httpx import AsyncClient

from app.analytics.periods import resolve_period
from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.job import Job, JobStatus, RemotePolicy
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.models.user import User, UserRole
from app.services import board_tasks, dl_send_queue
from app.services.insights_team_signals import (
    TeamPeople,
    dl_send_stale_count,
    people_payload,
    previous_matching_window,
    stale_jobs,
    workdays_in_window,
)
from app.services.kpi_team import TeamMemberRow, TeamPanelResult, TeamTotals

WARSAW = ZoneInfo("Europe/Warsaw")


def test_month_in_progress_compares_with_same_stretch_of_previous_month() -> None:
    now = datetime(2026, 9, 24, 15, 0, tzinfo=WARSAW)
    period = resolve_period("month", offset=0, now=now)
    start, end = previous_matching_window(period, now)
    # 1–24 września ↔ 1–24 sierpnia (koniec wyłączny: 25 sierpnia 00:00).
    assert start == datetime(2026, 8, 1, tzinfo=WARSAW)
    assert end == datetime(2026, 8, 25, tzinfo=WARSAW)


def test_last_day_of_month_never_spills_into_the_current_month() -> None:
    now = datetime(2026, 3, 31, 12, 0, tzinfo=WARSAW)
    period = resolve_period("month", offset=0, now=now)
    start, end = previous_matching_window(period, now)
    assert start == datetime(2026, 2, 1, tzinfo=WARSAW)
    assert end == datetime(2026, 3, 1, tzinfo=WARSAW)


def test_end_of_quarter_never_spills_into_the_current_quarter() -> None:
    now = datetime(2026, 9, 30, 18, 0, tzinfo=WARSAW)
    period = resolve_period("quarter", offset=0, now=now)
    _, end = previous_matching_window(period, now)
    assert end <= period.start


def test_closed_month_compares_with_whole_previous_month() -> None:
    now = datetime(2026, 9, 24, 15, 0, tzinfo=WARSAW)
    period = resolve_period("month", offset=-1, now=now)
    start, end = previous_matching_window(period, now)
    assert start == datetime(2026, 7, 1, tzinfo=WARSAW)
    assert end == datetime(2026, 8, 1, tzinfo=WARSAW)


def test_quarter_wraps_the_year() -> None:
    now = datetime(2026, 2, 10, 12, 0, tzinfo=WARSAW)
    period = resolve_period("quarter", offset=0, now=now)
    start, _ = previous_matching_window(period, now)
    assert start == datetime(2025, 10, 1, tzinfo=WARSAW)


def _member(uid: int, *, placements: int = 0, verifications: int = 0) -> TeamMemberRow:
    return TeamMemberRow(
        user_id=uid,
        name=f"Osoba {uid}",
        role="recruiter",
        weryfikacje=verifications,
        rekomendacje=0,
        interview=0,
        akceptacje=0,
        placementy=placements,
        cv_to_base=0,
        precision_pct=None,
        precision_verified_30d=0,
        precision_sent_30d=0,
    )


def _panel(*rows: TeamMemberRow) -> TeamPanelResult:
    totals = TeamTotals(
        weryfikacje=sum(r.weryfikacje for r in rows),
        rekomendacje=0,
        interview=0,
        akceptacje=0,
        placementy=sum(r.placementy for r in rows),
        cv_to_base=0,
        precision_pct=None,
        people=len(rows),
    )
    return TeamPanelResult(
        period="month", precision_target_pct=75, rows=tuple(rows), totals=totals
    )


def test_admin_accounts_are_one_row_and_company_totals_stay() -> None:
    """Konta administracyjne poza tabelą, jednym wierszem (24.09.2026)."""
    people = TeamPeople(
        current=_panel(_member(1, placements=2), _member(99, placements=5)),
        previous=_panel(_member(1, placements=1), _member(99, placements=3)),
        workdays=10,
        outside_user_ids=frozenset({99}),
    )
    payload = people_payload(people)
    assert [r["user_id"] for r in payload["rows"]] == [1]
    assert payload["outside_scope"]["placements"] == 5
    assert payload["outside_scope"]["previous_placements"] == 3
    assert payload["outside_scope"]["people"] == 1
    # Suma firmy bez zmian.
    assert payload["totals"]["placements"] == 7


def test_person_with_placements_only_in_previous_period_stays_visible() -> None:
    """Spadek do zera ma być widoczny w kolumnie „vs poprzednio”."""
    people = TeamPeople(
        current=_panel(_member(1, placements=2)),
        previous=_panel(_member(1, placements=1), _member(2, placements=3)),
        workdays=10,
    )
    rows = {r["user_id"]: r for r in people_payload(people)["rows"]}
    assert rows[2]["placements"] == 0
    assert rows[2]["previous_placements"] == 3


def test_rows_carry_acceptances_monthly_target_and_people_in_flight() -> None:
    """Zespół v3 (22.10.2026): akceptacje, cel placementów i „w drodze” per osoba."""
    member = TeamMemberRow(**{**_member(1, placements=2).__dict__, "akceptacje": 3})
    people = TeamPeople(
        current=_panel(member, _member(2)),
        previous=_panel(),
        workdays=10,
        placements_targets={1: 2},
        in_flight={1: 7},
    )
    rows = {r["user_id"]: r for r in people_payload(people)["rows"]}
    assert rows[1]["acceptances"] == 3
    assert rows[1]["placements_target"] == 2
    assert rows[1]["in_flight"] == 7
    # Osoba bez celu w mapie (np. bez ustawionego celu) — brak, nie zero celu.
    assert rows[2]["placements_target"] is None
    assert rows[2]["in_flight"] == 0


def test_target_is_absent_outside_a_month_window() -> None:
    """Cel placementów jest miesięczny — przy kwartale nie ma czego porównać."""
    people = TeamPeople(
        current=_panel(_member(1, placements=5)), previous=_panel(), workdays=60
    )
    [row] = people_payload(people)["rows"]
    assert row["placements_target"] is None


def test_unattributed_milestones_are_one_row_per_column() -> None:
    """Wiersz „Bez osoby z zasługą” (17.10.2026): kamienie bez kredytu per kolumna."""
    current = _panel(_member(1, placements=2))
    current = TeamPanelResult(
        period=current.period,
        precision_target_pct=current.precision_target_pct,
        rows=current.rows,
        totals=TeamTotals(
            **{
                **current.totals.__dict__,
                "unattributed": 6,
                "unattributed_by_stage": (
                    ("cv_sent", 4),
                    ("hired", 1),
                    ("verified", 1),
                ),
            }
        ),
    )
    people = TeamPeople(current=current, previous=_panel(), workdays=10)
    payload = people_payload(people)
    assert payload["unattributed"] == {
        "verifications": 1,
        "recommendations": 4,
        "interviews": 0,
        "acceptances": 0,
        "placements": 1,
    }
    # Sumy firmy i wiersze osób bez zmian.
    assert payload["totals"]["unattributed"] == 6
    assert [r["user_id"] for r in payload["rows"]] == [1]


def test_workdays_stop_at_today_and_skip_holidays() -> None:
    start = datetime(2026, 11, 1, tzinfo=WARSAW)
    end = datetime(2026, 12, 1, tzinfo=WARSAW)
    # 1–13 listopada 2026: 11.11 to święto, 1.11 niedziela → 9 dni roboczych.
    assert workdays_in_window(start, end, date(2026, 11, 13)) == 9
    # Okres zamknięty liczy się do końca okna, nie do „dziś".
    assert workdays_in_window(start, end, date(2027, 1, 5)) == 20


def _send_row(**over) -> board_tasks.BoardTask:
    base = dict(
        kind=board_tasks.KIND_DL_REVIEW,
        stage_id=1,
        candidate_id=1,
        candidate_name="Kandydat Testowy",
        job_id=1,
        job_title="Rekrutacja testowa",
        client_id=7,
        client_name="Klient testowy",
        since=datetime(2026, 3, 2, 10, 0, tzinfo=timezone.utc),
        process_state_version=0,
        target_stage_def_id=None,
        ready=True,
    )
    base.update(over)
    return board_tasks.BoardTask(**base)


def test_dl_send_stale_counts_people_ready_for_three_workdays() -> None:
    """Sygnał „Gdzie stoi” (13.10.2026) liczy OSOBY z całej firmy, tą samą
    regułą co kolejka Delivery Leada: bez QC do poprawy i bez etapów z importu
    Traffita, a próg to dni robocze od gotowości."""
    stale = dl_send_queue.STALE_WORKDAYS
    rows = [
        _send_row(job_id=1, waiting_workdays=stale),
        _send_row(job_id=1, waiting_workdays=stale + 4),
        _send_row(job_id=2, waiting_workdays=stale),
        # Jeszcze przed progiem — rekruter może przypomnieć, Head nie widzi.
        _send_row(job_id=2, waiting_workdays=stale - 1),
        # QC do poprawy: ruch ma rekruter, nie Delivery Lead.
        _send_row(job_id=3, ready=False, waiting_workdays=0),
        _send_row(job_id=3, imported=True, waiting_workdays=stale + 10),
    ]
    assert dl_send_stale_count(rows) == 3
    assert dl_send_stale_count([]) == 0


async def _job(
    *,
    status: JobStatus,
    opened_days_ago: int,
    stage_days_ago: int | None,
    work_state: str = "to_review",
) -> int:
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        client = Client(name=f"Stale-{uuid.uuid4().hex[:6]}")
        db.add(client)
        await db.flush()
        job = Job(
            title=f"Bez ruchu {uuid.uuid4().hex[:6]}",
            location="Warszawa",
            status=status,
            remote_policy=RemotePolicy.hybrid,
            client_id=client.id,
            opened_at=now - timedelta(days=opened_days_ago),
            work_state=work_state,
        )
        db.add(job)
        await db.flush()
        if stage_days_ago is not None:
            cand = Candidate(
                name="Bez",
                lastname=f"Ruchu-{uuid.uuid4().hex[:4]}",
                email=f"stale-{uuid.uuid4().hex[:8]}@example.com",
            )
            db.add(cand)
            await db.flush()
            db.add(
                CandidateStage(
                    candidate_id=cand.id,
                    job_id=job.id,
                    stage=PipelineStage.verified,
                    moved_at=now - timedelta(days=stage_days_ago),
                )
            )
        await db.commit()
        return job.id


@pytest.mark.asyncio
async def test_stale_jobs_are_published_and_silent_for_14_days() -> None:
    silent = await _job(
        status=JobStatus.published, opened_days_ago=60, stage_days_ago=20
    )
    empty = await _job(
        status=JobStatus.published, opened_days_ago=30, stage_days_ago=None
    )
    fresh = await _job(status=JobStatus.published, opened_days_ago=60, stage_days_ago=2)
    closed = await _job(status=JobStatus.closed, opened_days_ago=60, stage_days_ago=40)
    new_empty = await _job(
        status=JobStatus.published, opened_days_ago=3, stage_days_ago=None
    )

    async with AsyncSessionLocal() as db:
        items = await stale_jobs(db, now=datetime.now(timezone.utc))
    by_id = {item["job_id"]: item for item in items}

    assert silent in by_id and by_id[silent]["people"] == 1
    assert by_id[silent]["days_without_move"] >= 19
    assert empty in by_id and by_id[empty]["people"] == 0
    assert fresh not in by_id
    assert closed not in by_id
    assert new_empty not in by_id


@pytest.mark.asyncio
async def test_stale_jobs_skip_client_silent_and_finished_requests() -> None:
    """„Klient milczy" i „Zakończony" to świadomy brak ruchu (audyt 24.09.2026).

    Status z Traffita zostaje `published`, więc bez filtra po `work_state`
    porządkowanie requestów w `/jobs/review-states` nie zmniejszało sygnału.
    """
    searching = await _job(
        status=JobStatus.published,
        opened_days_ago=60,
        stage_days_ago=20,
        work_state="searching",
    )
    silent = await _job(
        status=JobStatus.published,
        opened_days_ago=60,
        stage_days_ago=20,
        work_state="client_silent",
    )
    finished = await _job(
        status=JobStatus.published,
        opened_days_ago=60,
        stage_days_ago=None,
        work_state="finished",
    )

    async with AsyncSessionLocal() as db:
        items = await stale_jobs(db, now=datetime.now(timezone.utc))
    ids = {item["job_id"] for item in items}

    assert searching in ids
    assert silent not in ids
    assert finished not in ids


async def _login_as(client: AsyncClient, role: UserRole) -> dict[str, str]:
    unique = uuid.uuid4().hex[:8]
    email = f"team-signals-{role.value}-{unique}@example.com"
    password = f"T3st_{unique}!Sig"
    async with AsyncSessionLocal() as db:
        db.add(
            User(
                email=email,
                name=f"Sygnały {unique}",
                password_hash=hash_password(password),
                role=role,
                is_active=True,
                profile_completed=True,
            )
        )
        await db.commit()
    resp = await client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


@pytest.mark.asyncio
async def test_team_routes_answer_for_head_of_recruitment_and_refuse_recruiter(
    app_client: AsyncClient,
) -> None:
    hor = await _login_as(app_client, UserRole.head_of_recruitment)
    people = await app_client.get("/api/insights/team/people", headers=hor)
    assert people.status_code == 200, people.text
    body = people.json()
    assert {"rows", "totals", "previous_totals", "workdays"} <= set(body)
    for row in body["rows"]:
        assert "precision_pct" in row and "previous_placements" in row
        # Bez kwot: widok Zespół nie niesie pieniędzy.
        assert not any(key.endswith("_pln") for key in row)

    attention = await app_client.get("/api/insights/team/attention", headers=hor)
    assert attention.status_code == 200, attention.text
    kinds = {item["kind"] for item in attention.json()["items"]}
    assert kinds <= {
        "stale_jobs",
        "low_precision",
        "weak_preps",
        # 04.10.2026: „Gdzie stoi” na pulpicie Heada i admina.
        "no_one_sent",
        "overdue",
        "stale_postings",
        # 13.10.2026: gotowe CV czekające na wysyłkę do klienta.
        "dl_send_stale",
    }
    for item in attention.json()["items"]:
        # Każdy sygnał prowadzi gdzieś: raport Insights albo lista rekrutacji.
        assert (
            item.get("report")
            or item.get("href")
            or item["kind"]
            in {
                "low_precision",
                "stale_postings",
            }
        )

    stale = await app_client.get("/api/insights/recruitment/stale-jobs", headers=hor)
    assert stale.status_code == 200, stale.text

    recruiter = await _login_as(app_client, UserRole.recruiter)
    for url in (
        "/api/insights/team/people",
        "/api/insights/team/attention",
        "/api/insights/recruitment/stale-jobs",
    ):
        resp = await app_client.get(url, headers=recruiter)
        assert resp.status_code == 403, f"{url}: {resp.text}"
