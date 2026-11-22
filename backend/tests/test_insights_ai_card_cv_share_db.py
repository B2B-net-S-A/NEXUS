"""GET /api/insights/recruitment/cv-from-ai-card na prawdziwej bazie (CI).

Pod ochroną (zasady: docs/claude/finanse-insights/cv-do-klienta-z-karty-ai.md):

1. Mianownik to PIERWSZE ``cv_sent`` pary; druga wysyłka nie jest nowym CV.
2. Licznik bierze najnowszy proces pary otwarty nie później niż wysyłka —
   proces otwarty po wysyłce nie przypisuje jej karcie AI wstecz.
3. Tydzień bez wysyłek to ``share_pct = None``, nie 0.
4. Bramka sekcji Insights: rola bez Insights (praktykant) dostaje 403.

Baza testowa jest współdzielona, a liczba jest firmowa, więc testy ustawiają
„dziś” w latach, w których nikt inny nie zapisuje wysyłek.
"""

import uuid
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.core.cache import cache_invalidate
from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.job import Job, JobStatus, RemotePolicy
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.models.recruitment_process import ProcessStatus, RecruitmentProcess
from app.models.user import User, UserRole

WARSAW = ZoneInfo("Europe/Warsaw")
URL = "/api/insights/recruitment/cv-from-ai-card"


def _warsaw(day: date, hour: int = 12) -> datetime:
    return datetime.combine(day, time(hour), tzinfo=WARSAW)


async def _login(client: AsyncClient, role: UserRole) -> dict[str, str]:
    unique = uuid.uuid4().hex[:8]
    email = f"aicard-{role.value}-{unique}@example.com"
    password = f"T3st_{unique}!AiCard"
    async with AsyncSessionLocal() as db:
        db.add(
            User(
                email=email,
                name=f"Karta AI {unique}",
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


def _pin_today(monkeypatch, today: date) -> None:
    monkeypatch.setattr("app.api.insights_recruitment.business_today", lambda: today)


async def _job() -> int:
    async with AsyncSessionLocal() as db:
        client = Client(name=f"AiCardCli-{uuid.uuid4().hex[:6]}")
        db.add(client)
        await db.flush()
        job = Job(
            title=f"Karta AI {uuid.uuid4().hex[:6]}",
            location="Warszawa",
            status=JobStatus.published,
            remote_policy=RemotePolicy.hybrid,
            client_id=client.id,
        )
        db.add(job)
        await db.commit()
        return job.id


async def _pair(
    job_id: int,
    sends: list[datetime],
    processes: list[tuple[datetime, str | None]],
) -> None:
    """Kandydat z wysyłkami CV i procesami ``(opened_at, entry_source)``."""
    async with AsyncSessionLocal() as db:
        cand = Candidate(
            name=f"AiCard-{uuid.uuid4().hex[:4]}",
            lastname=f"Pair-{uuid.uuid4().hex[:4]}",
            email=f"aicard-{uuid.uuid4().hex[:8]}@example.com",
        )
        db.add(cand)
        await db.flush()
        for when in sends:
            db.add(
                CandidateStage(
                    candidate_id=cand.id,
                    job_id=job_id,
                    stage=PipelineStage.cv_sent,
                    moved_at=when,
                )
            )
        for attempt, (opened_at, source) in enumerate(processes, start=1):
            last = attempt == len(processes)
            db.add(
                RecruitmentProcess(
                    job_id=job_id,
                    candidate_id=cand.id,
                    entry_source=source,
                    opened_at=opened_at,
                    attempt_no=attempt,
                    status=ProcessStatus.open if last else ProcessStatus.closed,
                )
            )
        await db.commit()


@pytest.mark.asyncio
async def test_empty_weeks_are_dashes_not_zero_percent(
    fx_client: AsyncClient, monkeypatch
) -> None:
    today = date(2037, 6, 17)
    _pin_today(monkeypatch, today)
    await cache_invalidate("insights:recruitment:cv-from-ai-card")
    headers = await _login(fx_client, UserRole.head_of_recruitment)

    resp = await fx_client.get(URL, headers=headers)

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["target_pct"] == 100
    assert body["window_from"] == "2037-05-18"
    assert len(body["weeks"]) == 5
    assert all(w["cv_sent"] == 0 for w in body["weeks"])
    assert all(w["share_pct"] is None for w in body["weeks"])
    assert body["weeks"][-1]["in_progress"] is True


@pytest.mark.asyncio
async def test_week_with_sends_counts_first_send_and_process_before_it(
    fx_client: AsyncClient, monkeypatch
) -> None:
    today = date(2037, 3, 18)  # środa; bieżący tydzień od 16.03
    week = date(2037, 3, 9)
    _pin_today(monkeypatch, today)
    await cache_invalidate("insights:recruitment:cv-from-ai-card")
    job_id = await _job()
    sent = _warsaw(week + timedelta(days=1))

    # Karta od porcji, CV wysłane: liczy się.
    await _pair(job_id, [sent], [(sent - timedelta(days=1), "system")])
    # Dodana ręcznie: w mianowniku, nie w liczniku.
    await _pair(job_id, [sent], [(sent - timedelta(days=1), "added_manual")])
    # Pierwsza próba ręczna, druga z porcji otwarta PO wysyłce: nie karta AI.
    await _pair(
        job_id,
        [sent],
        [
            (sent - timedelta(days=2), "added_manual"),
            (sent + timedelta(hours=1), "system"),
        ],
    )
    # Starsza próba z porcji, nowsza ręczna przed wysyłką: decyduje nowsza.
    await _pair(
        job_id,
        [sent],
        [(sent - timedelta(days=3), "system"), (sent - timedelta(days=1), None)],
    )
    # Druga wysyłka tej samej pary w następnym tygodniu nie jest nowym CV.
    await _pair(
        job_id,
        [sent, sent + timedelta(days=7)],
        [(sent - timedelta(days=1), "system")],
    )
    # Wysyłka w bieżącym tygodniu.
    now_sent = _warsaw(date(2037, 3, 17))
    await _pair(job_id, [now_sent], [(now_sent - timedelta(hours=2), "system")])

    headers = await _login(fx_client, UserRole.head_of_recruitment)
    resp = await fx_client.get(URL, headers=headers)

    assert resp.status_code == 200, resp.text
    weeks = {w["week_start"]: w for w in resp.json()["weeks"]}
    assert weeks["2037-03-09"]["cv_sent"] == 5
    assert weeks["2037-03-09"]["from_ai_card"] == 2
    assert weeks["2037-03-09"]["share_pct"] == 40.0
    assert weeks["2037-03-16"]["cv_sent"] == 1
    assert weeks["2037-03-16"]["from_ai_card"] == 1
    assert weeks["2037-03-16"]["in_progress"] is True
    assert weeks["2037-03-02"]["share_pct"] is None


@pytest.mark.asyncio
async def test_role_without_insights_is_denied(fx_client: AsyncClient) -> None:
    headers = await _login(fx_client, UserRole.trainee)
    resp = await fx_client.get(URL, headers=headers)
    assert resp.status_code == 403, resp.text


@pytest.mark.asyncio
async def test_requires_login(fx_client: AsyncClient) -> None:
    resp = await fx_client.get(URL)
    assert resp.status_code in (401, 403)
