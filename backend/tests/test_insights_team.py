"""GET /api/insights/team-table — „Performance per osoba".

Pięć reguł pod ochroną. Każda odpowiada liczbie, która na ekranie znaczy
co innego, niż wygląda:

1. **Kamienie nieprzypisane nie znikają.** ``first_moved_by IS NULL`` nie ma
   swojego wiersza w tabeli, ale MUSI wyjść w ``totals.unattributed`` per etap,
   a ``totals.all`` musi zgadzać się z lejkiem. Suma kolumny mniejsza od lejka
   bez wyjaśnienia czyta się jako zepsuta tabela.
2. **Były pracownik zostaje.** Filtr ``is_active`` kasowałby wstecz dorobek
   osoby, która odeszła — raport za lipiec ma pokazywać lipiec.
3. **Placement = D2.** Drugie ``hired`` dla tej samej pary (kandydat, oferta)
   NIE liczy się drugi raz.
4. **Okno jest półotwarte i siedzi w kluczu cache'u.** Bez tego liczby jednego
   okresu wychodzą pod etykietą drugiego.
5. **Bramka D7.** Każda ZALOGOWANA rola widzi tabelę; anonim nie.

Router celowo nie jest zamontowany w ``app/main.py`` (montuje integrator), więc
testy stawiają własną aplikację z tym samym prefiksem, który jest zaproponowany
integratorowi. Świadomie NIE mutujemy globalnego ``app``: kontrakt
``tests/test_route_authz_contract.py`` chodzi po jego trasach, a trasa dołożona
z boku wywracałaby go w zależności od kolejności importu modułów testowych.
"""

from __future__ import annotations

import itertools
import uuid
from datetime import date, datetime, timedelta, timezone

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api import insights_team
from app.core.cache import cache_invalidate
from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.job import Job, JobStatus, RemotePolicy
from app.models.recruitment_pipeline import (
    CandidateStage,
    PipelineStage,
    VerificationStatus,
)
from app.models.user import User, UserRole

# Prefiks proponowany integratorowi — endpoint ląduje pod tą ścieżką.
URL = "/api/insights/team-table"

# Każdy test dostaje WŁASNY dzień kalendarzowy głęboko w przeszłości i pyta
# o okres `custom` obejmujący dokładnie ten dzień. Tabela agreguje wszystko,
# co w oknie — bez rozłącznych okien testy widziałyby nawzajem swoje wiersze
# (a także seedy innych plików, które celują w „teraz").
#
# Baza okna jest LOSOWANA PER PROCES — tak samo jak `slot`/`year` w
# `tests/test_insights_recruitment_funnel.py`. Stała data wygląda na
# wystarczającą izolację i nie jest: baza testowa bywa współdzielona i NIE
# jest czyszczona między przebiegami, więc dwa przebiegi tego pliku (albo ten
# plik obok innego celującego w ten sam rok) widzą nawzajem swoje wiersze.
# Objaw jest wtedy mylący: w tabeli pojawiają się CUDZE nazwiska i podwojone
# liczniki, czyli awaria wygląda na błąd atrybucji w kodzie, a jest zderzeniem
# okien. 200 lat × 300 dni startów czyni takie zderzenie nieistotnie rzadkim.
_DAY_SEQUENCE = itertools.count()
_WINDOW_EPOCH = date(1300 + int(uuid.uuid4().hex[:4], 16) % 200, 1, 1) + timedelta(
    days=int(uuid.uuid4().hex[4:8], 16) % 300
)


def _next_window() -> date:
    return _WINDOW_EPOCH + timedelta(days=next(_DAY_SEQUENCE))


def _at(day: date) -> datetime:
    """Południe UTC = ten sam dzień kalendarzowy w Europe/Warsaw."""
    return datetime(day.year, day.month, day.day, 12, 0, tzinfo=timezone.utc)


def _params(day: date) -> dict[str, str]:
    return {
        "period": "custom",
        "date_from": day.isoformat(),
        "date_to": day.isoformat(),
    }


async def _seed_user(
    role: UserRole = UserRole.sourcer,
    *,
    name: str | None = None,
    is_active: bool = True,
) -> tuple[int, str, str]:
    unique = uuid.uuid4().hex[:8]
    email = f"instt-{role.value}-{unique}@example.com"
    password = f"T3st_{unique}!Team"
    async with AsyncSessionLocal() as db:
        u = User(
            email=email,
            name=name or f"Team {unique}",
            password_hash=hash_password(password),
            role=role,
            is_active=is_active,
            # Recruiter/DL mają personę onboardingową — bez tego `CurrentUser`
            # odbija 403 `onboarding_required` i test mierzyłby onboarding,
            # nie bramkę D7.
            profile_completed=True,
        )
        db.add(u)
        await db.commit()
        await db.refresh(u)
        return u.id, email, password


async def _seed_pair() -> tuple[int, int]:
    """Nowa para (kandydat, oferta) — izoluje deduplikację D2 między testami."""
    async with AsyncSessionLocal() as db:
        cli = Client(name=f"TeamCli-{uuid.uuid4().hex[:6]}")
        db.add(cli)
        await db.commit()
        await db.refresh(cli)
        job = Job(
            title=f"Team {uuid.uuid4().hex[:6]}",
            location="Warszawa",
            status=JobStatus.published,
            remote_policy=RemotePolicy.hybrid,
            client_id=cli.id,
        )
        cand = Candidate(
            name=f"Tea-{uuid.uuid4().hex[:4]}",
            lastname=f"Mtb-{uuid.uuid4().hex[:4]}",
            email=f"team-{uuid.uuid4().hex[:8]}@example.com",
        )
        db.add_all([job, cand])
        await db.commit()
        await db.refresh(job)
        await db.refresh(cand)
        return cand.id, job.id


async def _seed_stage(
    *,
    candidate_id: int,
    job_id: int,
    stage: PipelineStage,
    moved_at: datetime,
    moved_by: int | None,
    verification_status: VerificationStatus = VerificationStatus.active,
) -> None:
    async with AsyncSessionLocal() as db:
        db.add(
            CandidateStage(
                candidate_id=candidate_id,
                job_id=job_id,
                stage=stage,
                moved_at=moved_at,
                moved_by=moved_by,
                verification_status=verification_status,
            )
        )
        await db.commit()


@pytest_asyncio.fixture
async def fx_app() -> AsyncClient:
    """Aplikacja z SAMYM routerem tabeli — bez dotykania globalnego `app`."""
    from app.core.rate_limit import limiter as _limiter

    _limiter.enabled = False
    test_app = FastAPI()
    test_app.include_router(
        insights_team.router, prefix="/api/insights", tags=["insights"]
    )
    async with AsyncClient(
        transport=ASGITransport(app=test_app, raise_app_exceptions=True),
        base_url="http://testserver",
    ) as c:
        yield c


@pytest_asyncio.fixture
async def fx_login() -> AsyncClient:
    """Klient na PRAWDZIWEJ aplikacji — wyłącznie po token (`/api/auth/login`)."""
    from app.core.rate_limit import limiter as _limiter
    from app.main import app

    _limiter.enabled = False
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=True),
        base_url="http://testserver",
    ) as c:
        yield c


@pytest_asyncio.fixture(autouse=True)
async def _clear_cache():
    # Cache jest procesowy i przeżywa między testami. Bez czyszczenia drugi
    # test na tym samym oknie dostałby odpowiedź pierwszego.
    await cache_invalidate("insights:team:table")
    yield
    await cache_invalidate("insights:team:table")


async def _headers(client: AsyncClient, email: str, password: str) -> dict[str, str]:
    resp = await client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


@pytest.mark.asyncio
async def test_table_is_reachable_for_every_logged_in_role(
    fx_app: AsyncClient, fx_login: AsyncClient
):
    """Decyzja D7: /insights widzi KAŻDA zalogowana rola, także `sourcer`."""
    for role in (
        UserRole.admin,
        UserRole.sourcer,
        UserRole.recruiter,
        UserRole.finance,
        UserRole.tac,
    ):
        _, email, password = await _seed_user(role)
        headers = await _headers(fx_login, email, password)
        resp = await fx_app.get(URL, headers=headers, params=_params(_next_window()))
        assert resp.status_code == 200, f"{role.value}: {resp.text}"


@pytest.mark.asyncio
async def test_table_requires_authentication(fx_app: AsyncClient):
    """„Wszyscy" znaczy „każdy ZALOGOWANY", nie „każdy z internetu"."""
    resp = await fx_app.get(URL, params=_params(_next_window()))
    assert resp.status_code in (401, 403)


@pytest.mark.asyncio
async def test_four_columns_are_attributed_to_the_person_who_moved_the_stage(
    fx_app: AsyncClient, fx_login: AsyncClient
):
    day = _next_window()
    owner_id, email, password = await _seed_user(UserRole.tac, name="Zenon Atrybut")
    other_id, _, _ = await _seed_user(UserRole.sourcer, name="Alicja Druga")
    cand, job = await _seed_pair()
    cand2, job2 = await _seed_pair()

    for stage in (
        PipelineStage.verified,
        PipelineStage.cv_sent,
        PipelineStage.interview,
        PipelineStage.hired,
    ):
        await _seed_stage(
            candidate_id=cand,
            job_id=job,
            stage=stage,
            moved_at=_at(day),
            moved_by=owner_id,
        )
    await _seed_stage(
        candidate_id=cand2,
        job_id=job2,
        stage=PipelineStage.verified,
        moved_at=_at(day),
        moved_by=other_id,
    )

    headers = await _headers(fx_login, email, password)
    body = (await fx_app.get(URL, headers=headers, params=_params(day))).json()

    rows = {r["user_id"]: r for r in body["rows"]}
    assert rows[owner_id]["verifications"] == 1
    assert rows[owner_id]["recommendations"] == 1
    assert rows[owner_id]["interviews"] == 1
    assert rows[owner_id]["placements"] == 1
    assert rows[owner_id]["role"] == "tac"
    assert rows[owner_id]["role_label"] == "TAC"
    # Kolumny sąsiada zostają zerami — atrybucja nie rozlewa się po zespole.
    assert rows[other_id]["verifications"] == 1
    assert rows[other_id]["placements"] == 0
    # Domyślny porządek: weryfikacje malejąco, remis po nazwisku.
    assert [r["name"] for r in body["rows"]] == ["Alicja Druga", "Zenon Atrybut"]


@pytest.mark.asyncio
async def test_unattributed_milestones_are_reported_per_stage_never_dropped(
    fx_app: AsyncClient, fx_login: AsyncClient
):
    """Kamień bez autora nie ma wiersza, ale MUSI wejść w sumę kolumny."""
    day = _next_window()
    owner_id, email, password = await _seed_user(UserRole.sourcer)
    cand, job = await _seed_pair()
    ghost_c, ghost_j = await _seed_pair()

    await _seed_stage(
        candidate_id=cand,
        job_id=job,
        stage=PipelineStage.verified,
        moved_at=_at(day),
        moved_by=owner_id,
    )
    # Operator Traffita bez dopasowania do konta w NEXUSIE.
    await _seed_stage(
        candidate_id=ghost_c,
        job_id=ghost_j,
        stage=PipelineStage.verified,
        moved_at=_at(day),
        moved_by=None,
    )
    await _seed_stage(
        candidate_id=ghost_c,
        job_id=ghost_j,
        stage=PipelineStage.hired,
        moved_at=_at(day),
        moved_by=None,
    )

    headers = await _headers(fx_login, email, password)
    body = (await fx_app.get(URL, headers=headers, params=_params(day))).json()

    assert [r["user_id"] for r in body["rows"]] == [owner_id]
    totals = body["totals"]
    assert totals["attributed"]["verifications"] == 1
    # Per etap, nie jednym skalarem — nieprzypisana weryfikacja i nieprzypisany
    # placement to dwie różne dziury i trafiają pod dwie różne kolumny.
    assert totals["unattributed"]["verifications"] == 1
    assert totals["unattributed"]["placements"] == 1
    assert totals["unattributed"]["interviews"] == 0
    # Suma widocznych + nieprzypisane = liczba z lejka org-level.
    assert totals["all"]["verifications"] == 2
    assert totals["all"]["placements"] == 1


@pytest.mark.asyncio
async def test_former_employee_with_results_stays_in_the_table(
    fx_app: AsyncClient, fx_login: AsyncClient
):
    """Odejście z firmy nie kasuje wstecz wyników osiągniętych w oknie."""
    day = _next_window()
    gone_id, _, _ = await _seed_user(
        UserRole.sourcer, name="Odeszla Osoba", is_active=False
    )
    _, email, password = await _seed_user(UserRole.admin)
    cand, job = await _seed_pair()
    await _seed_stage(
        candidate_id=cand,
        job_id=job,
        stage=PipelineStage.hired,
        moved_at=_at(day),
        moved_by=gone_id,
    )

    headers = await _headers(fx_login, email, password)
    body = (await fx_app.get(URL, headers=headers, params=_params(day))).json()

    row = next(r for r in body["rows"] if r["user_id"] == gone_id)
    assert row["is_active"] is False
    assert row["placements"] == 1
    assert body["totals"]["former_employees"] == 1
    # Nie zostaje zwinięty do „nieprzypisanych" — autor jest znany.
    assert body["totals"]["unattributed"]["placements"] == 0


@pytest.mark.asyncio
async def test_second_hired_for_the_same_pair_does_not_count_twice(
    fx_app: AsyncClient, fx_login: AsyncClient
):
    """Placement = D2: PIERWSZE `hired` dla pary (kandydat, oferta)."""
    day = _next_window()
    owner_id, email, password = await _seed_user(UserRole.tac)
    cand, job = await _seed_pair()
    await _seed_stage(
        candidate_id=cand,
        job_id=job,
        stage=PipelineStage.hired,
        moved_at=_at(day),
        moved_by=owner_id,
    )
    await _seed_stage(
        candidate_id=cand,
        job_id=job,
        stage=PipelineStage.hired,
        moved_at=_at(day) + timedelta(hours=2),
        moved_by=owner_id,
    )

    headers = await _headers(fx_login, email, password)
    body = (await fx_app.get(URL, headers=headers, params=_params(day))).json()

    row = next(r for r in body["rows"] if r["user_id"] == owner_id)
    assert row["placements"] == 1
    assert body["totals"]["all"]["placements"] == 1


@pytest.mark.asyncio
async def test_pending_verification_is_not_counted(
    fx_app: AsyncClient, fx_login: AsyncClient
):
    """Weryfikacja czekająca na akceptację to nie weryfikacja.

    Widok kamieni filtruje `verification_status='active'` (migracja 0184).
    Liczenie jej tutaj rozjechałoby tabelę z lejkiem org-level, który stoi
    na tym samym widoku.
    """
    day = _next_window()
    owner_id, email, password = await _seed_user(UserRole.sourcer)
    cand, job = await _seed_pair()
    await _seed_stage(
        candidate_id=cand,
        job_id=job,
        stage=PipelineStage.verified,
        moved_at=_at(day),
        moved_by=owner_id,
        verification_status=VerificationStatus.pending,
    )

    headers = await _headers(fx_login, email, password)
    body = (await fx_app.get(URL, headers=headers, params=_params(day))).json()

    assert body["rows"] == []
    assert body["totals"]["all"]["verifications"] == 0


@pytest.mark.asyncio
async def test_window_is_half_open_and_lives_in_the_cache_key(
    fx_app: AsyncClient, fx_login: AsyncClient
):
    """Dwa sąsiednie dni MUSZĄ dać dwie różne odpowiedzi.

    Gdyby klucz cache'u nie niósł okna, drugie zapytanie dostałoby liczby
    pierwszego — pod etykietą własnego okresu i bez żadnego sygnału.
    """
    day = _next_window()
    next_day = _next_window()
    owner_id, email, password = await _seed_user(UserRole.sourcer)
    cand, job = await _seed_pair()
    await _seed_stage(
        candidate_id=cand,
        job_id=job,
        stage=PipelineStage.verified,
        moved_at=_at(day),
        moved_by=owner_id,
    )

    headers = await _headers(fx_login, email, password)
    inside = (await fx_app.get(URL, headers=headers, params=_params(day))).json()
    outside = (await fx_app.get(URL, headers=headers, params=_params(next_day))).json()

    assert inside["totals"]["all"]["verifications"] == 1
    assert outside["totals"]["all"]["verifications"] == 0
    assert outside["rows"] == []
    assert inside["period"]["start"] != outside["period"]["start"]


@pytest.mark.asyncio
async def test_broken_period_is_422_not_a_silently_shifted_window(
    fx_app: AsyncClient, fx_login: AsyncClient
):
    _, email, password = await _seed_user(UserRole.admin)
    headers = await _headers(fx_login, email, password)
    resp = await fx_app.get(
        URL,
        headers=headers,
        params={"period": "custom", "date_from": "2026-01-10", "date_to": "2026-01-01"},
    )
    assert resp.status_code == 422
