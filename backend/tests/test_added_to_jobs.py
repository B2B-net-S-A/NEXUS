"""„Kto ilu dodał” do rekrutacji poza Tablicą (decyzja Artura 16.11.2026).

Pod ochroną (zasady: docs/claude/rekrutacja-tablica/kto-ilu-dodal-w-zespole-rekrutacji.md):

1. Dodanie to para (kandydat, rekrutacja) liczona raz, osobie z pierwszego
   wpisu etapu — późniejszy ruch kogoś innego nie przenosi dodania.
2. Bez ``moved_by`` osoba z ``recruitment_processes.opened_by_user_id``;
   silnik „Nowi” (``entry_source = 'system'``) i wpisy bez osoby nie liczą się
   nikomu, tylko osobnymi liczbami.
3. „Dziś” i „7 dni” to dni kalendarza firmy: granica o północy w Warszawie,
   nie w UTC.
4. Trasa pulpitu wymaga ``VIEW_TEAM_KPI`` — HoR i DL widzą, rekruter 403.
5. Insights → Raporty (team-activity) niesie tę samą liczbę obok „Kandydatów”.

Każdy test zakłada własnego klienta i filtruje po nim — baza testowa jest
współdzielona, więc liczby globalne zbierałyby wiersze innych testów.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from httpx import AsyncClient

from app.core.cache import cache_invalidate
from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today, local_day_start_utc
from app.core.security import hash_password
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.job import Job, JobStatus, RemotePolicy
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.models.recruitment_process import RecruitmentProcess
from app.models.user import User, UserRole
from app.models.user_activity import UserActivity, UserActionType
from app.services.added_to_jobs import (
    added_today_and_last_days,
    count_added_to_jobs,
)

WARSAW = ZoneInfo("Europe/Warsaw")


def _warsaw(day: date, hour: int = 0, minute: int = 0, second: int = 0) -> datetime:
    return datetime.combine(day, time(hour, minute, second), tzinfo=WARSAW)


async def _user(role: UserRole = UserRole.recruiter) -> tuple[int, str, str]:
    unique = uuid.uuid4().hex[:8]
    email = f"added-{role.value}-{unique}@example.com"
    password = f"T3st_{unique}!Add"
    async with AsyncSessionLocal() as db:
        user = User(
            email=email,
            name=f"Dodający {unique}",
            password_hash=hash_password(password),
            role=role,
            is_active=True,
            profile_completed=True,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user.id, email, password


async def _login(client: AsyncClient, email: str, password: str) -> dict[str, str]:
    resp = await client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _job() -> tuple[int, int]:
    async with AsyncSessionLocal() as db:
        client = Client(name=f"AddCli-{uuid.uuid4().hex[:6]}")
        db.add(client)
        await db.flush()
        job = Job(
            title=f"Dodani {uuid.uuid4().hex[:6]}",
            location="Warszawa",
            status=JobStatus.published,
            remote_policy=RemotePolicy.hybrid,
            client_id=client.id,
        )
        db.add(job)
        await db.commit()
        return client.id, job.id


async def _pair(
    job_id: int,
    *moves: tuple[datetime, int | None],
    entry_source: str | None = None,
    opened_by: int | None = None,
) -> int:
    """Kandydat w rekrutacji z wpisami etapów ``(kiedy, kto)``."""
    async with AsyncSessionLocal() as db:
        cand = Candidate(
            name=f"Add-{uuid.uuid4().hex[:4]}",
            lastname=f"Pair-{uuid.uuid4().hex[:4]}",
            email=f"added-{uuid.uuid4().hex[:8]}@example.com",
        )
        db.add(cand)
        await db.flush()
        for index, (when, who) in enumerate(moves):
            db.add(
                CandidateStage(
                    candidate_id=cand.id,
                    job_id=job_id,
                    stage=PipelineStage.new if index == 0 else PipelineStage.screening,
                    moved_at=when,
                    moved_by=who,
                )
            )
        if entry_source is not None or opened_by is not None:
            db.add(
                RecruitmentProcess(
                    job_id=job_id,
                    candidate_id=cand.id,
                    entry_source=entry_source,
                    opened_by_user_id=opened_by,
                    opened_at=moves[0][0],
                    attempt_no=1,
                )
            )
        await db.commit()
        return cand.id


@pytest.mark.asyncio
async def test_people_first_entry_and_automat_kept_apart() -> None:
    first, _, _ = await _user()
    second, _, _ = await _user()
    opener, _, _ = await _user()
    client_id, job_id = await _job()
    other_client, other_job = await _job()
    day = date(2026, 11, 10)
    noon = _warsaw(day, 12)

    await _pair(job_id, (noon, first))
    await _pair(job_id, (noon, first))
    # Drugi ruch kogoś innego nie zabiera dodania pierwszej osobie.
    await _pair(job_id, (noon, first), (noon + timedelta(hours=2), second))
    await _pair(job_id, (noon, second))
    # Bez autora wpisu: osoba, która otworzyła proces pary.
    await _pair(job_id, (noon, None), entry_source="added_manual", opened_by=opener)
    # Silnik „Nowi” — nikomu.
    await _pair(job_id, (noon, None), entry_source="system")
    await _pair(job_id, (noon, None), entry_source="system")
    # Stary wpis bez osoby i bez procesu.
    await _pair(job_id, (noon, None))
    # Para dodana przed oknem, ruszona w oknie — to nie jest dodanie w oknie.
    await _pair(job_id, (noon - timedelta(days=3), first), (noon, first))
    # Inny klient nie wchodzi przy filtrze klienta.
    await _pair(other_job, (noon, first))

    async with AsyncSessionLocal() as db:
        counts = await count_added_to_jobs(
            db,
            since=_warsaw(day),
            until=_warsaw(day + timedelta(days=1)),
            client_id=client_id,
        )

    assert dict(counts.by_user) == {first: 3, second: 1, opener: 1}
    assert counts.system == 2
    assert counts.unattributed == 1
    assert counts.by_people == 5
    assert counts.total == 8
    assert other_client != client_id


@pytest.mark.asyncio
async def test_today_and_seven_days_split_at_warsaw_midnight() -> None:
    person, _, _ = await _user()
    client_id, job_id = await _job()
    today = date(2026, 11, 16)

    # Dziś tuż po północy w Warszawie (w UTC to jeszcze wczoraj, 23:00).
    await _pair(job_id, (_warsaw(today, 0, 0, 1), person))
    # Wczoraj tuż przed północą — 7 dni tak, dziś nie.
    await _pair(job_id, (_warsaw(today - timedelta(days=1), 23, 59, 59), person))
    # Szósty dzień wstecz od północy — ostatni dzień okna.
    await _pair(job_id, (_warsaw(today - timedelta(days=6)), person))
    # Siódmy dzień wstecz, sekunda przed północą — poza oknem.
    await _pair(job_id, (_warsaw(today - timedelta(days=7), 23, 59, 59), person))
    # Jutro — poza oboma oknami.
    await _pair(job_id, (_warsaw(today + timedelta(days=1), 0, 0, 1), person))

    async with AsyncSessionLocal() as db:
        day, week = await added_today_and_last_days(
            db, today=today, client_id=client_id
        )

    assert dict(day.by_user) == {person: 1}
    assert dict(week.by_user) == {person: 3}


@pytest.mark.asyncio
async def test_naive_window_is_refused() -> None:
    async with AsyncSessionLocal() as db:
        with pytest.raises(ValueError):
            await count_added_to_jobs(
                db, since=datetime(2026, 11, 16), until=datetime(2026, 11, 17)
            )


@pytest.mark.asyncio
async def test_dashboard_route_for_head_and_delivery_lead_refuses_recruiter(
    app_client: AsyncClient,
) -> None:
    person, _, _ = await _user()
    client_id, job_id = await _job()
    # Tuż po północy w Warszawie „5 minut temu” to wczoraj — kolejka merge'ów
    # biegnie nocą (17.11.2026 o 00:00:03 test padł na `today == 0`).
    now = datetime.now(timezone.utc)
    when = max(
        now - timedelta(minutes=5),
        local_day_start_utc(business_today()) + timedelta(seconds=1),
    )
    await _pair(job_id, (when, person))
    await _pair(job_id, (when, None), entry_source="system")
    await cache_invalidate("insights:team:added-to-jobs:")

    for role in (UserRole.head_of_recruitment, UserRole.delivery_lead):
        _, email, password = await _user(role)
        headers = await _login(app_client, email, password)
        resp = await app_client.get(
            "/api/insights/team/added-to-jobs",
            headers=headers,
            params={"client_id": client_id},
        )
        assert resp.status_code == 200, f"{role.value}: {resp.text}"
        body = resp.json()
        assert body["date_to"] == business_today().isoformat()
        assert body["days"] == 7
        rows = {row["user_id"]: row for row in body["rows"]}
        assert rows[person]["today"] == 1
        assert rows[person]["last_days"] == 1
        assert body["system"] == {"today": 1, "last_days": 1}

    _, email, password = await _user(UserRole.recruiter)
    headers = await _login(app_client, email, password)
    resp = await app_client.get("/api/insights/team/added-to-jobs", headers=headers)
    assert resp.status_code == 403, resp.text


@pytest.mark.asyncio
async def test_team_activity_report_carries_additions_next_to_candidates(
    app_client: AsyncClient,
) -> None:
    await cache_invalidate("insights:recruitment:team-activity:")
    # Rok bez innych danych i unikalny per przebieg — baza testowa jest
    # współdzielona.
    year = 1300 + int(uuid.uuid4().hex[:6], 16) % 200
    person, email, password = await _user()
    _, job_id = await _job()
    inside = datetime(year, 6, 15, 12, tzinfo=timezone.utc)
    await _pair(job_id, (inside, person))
    await _pair(job_id, (inside, person))
    await _pair(job_id, (inside, None), entry_source="system")
    await _pair(job_id, (datetime(year, 7, 2, 12, tzinfo=timezone.utc), person))
    # Dodanie w aplikacji zapisuje ruch etapu w `user_activities` — z niego
    # osoba trafia do rankingu.
    async with AsyncSessionLocal() as db:
        db.add(
            UserActivity(
                user_id=person,
                action_type=UserActionType.stage_changed,
                entity_type="candidate",
                entity_id=1,
                created_at=inside,
            )
        )
        await db.commit()

    headers = await _login(app_client, email, password)
    body = (
        await app_client.get(
            "/api/insights/recruitment/team-activity",
            headers=headers,
            params={
                "period": "custom",
                "date_from": f"{year}-06-01",
                "date_to": f"{year}-06-30",
                "limit": 50,
            },
        )
    ).json()

    mine = [e for e in body["entries"] if e["user_id"] == person]
    assert len(mine) == 1, body
    assert mine[0]["added_to_jobs"] == 2
    # „Kandydaci” to nowo utworzone profile — tu żadnego.
    assert mine[0]["candidates_added"] == 0
    assert body["totals"]["added_to_jobs_system"] == 1
