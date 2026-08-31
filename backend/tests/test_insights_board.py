"""GET /api/insights/board — kokpit zarządu na danych natywnych NEXUSA.

Każdy test broni jednego konkretnego defektu `GET /api/reports/board`, a nie
„że endpoint działa":

1. **RBAC (D7)** — board rady widzi KAŻDA zalogowana rola, łącznie z `finance`,
   `sourcer` i wycofywanym legacy `user`. Stary endpoint stoi za
   `FinanceReadUser` i tamtego guardu nie ruszamy.
2. **Okno półotwarte [start, end)** — legacy liczył od 1 stycznia „do teraz",
   bez górnej granicy.
3. **Brak kursu NBP degraduje KAFEL, nie tylko baner** — `reports.py:105-120`
   robi `continue`, więc kwota znika z sumy, a liczba obok wygląda na pewną.
4. **Placement = pierwsze `hired` per para (kandydat, oferta)** — D2. Legacy
   liczył każdy wiersz `candidate_stages`, a ta tabela nie ma UNIQUE na
   (candidate_id, job_id, stage), więc powrót do etapu liczył się dwa razy.
5. **Zero pól przetargowych** i **żadnego `avg_hit_ratio`** liczonego jako
   `placements / COUNT(wszystkich ofert)`.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.core.cache import cache_invalidate
from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.contract import Contract, ContractStatus, RateUnit
from app.models.job import Job, JobStatus, RemotePolicy
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.models.user import User, UserRole

BOARD_URL = "/api/insights/board"

# ISO 4217 rezerwuje XTS na potrzeby testów, więc NBP nigdy go nie opublikuje —
# kurs dla tej waluty nie może się „przypadkiem znaleźć" w cache'u i uczynić
# testu degradacji zielonym z niewłaściwego powodu.
NO_FX_CURRENCY = "XTS"


def _ensure_board_router_mounted(app) -> None:
    """Zamontuj router, jeśli integrator jeszcze tego nie zrobił.

    Właścicielem `app/main.py` jest integrator, a ten plik powstaje równolegle
    z jego montażem. Warunek jest jednorazowy i staje się no-opem w chwili,
    gdy montaż wejdzie do `main.py` — dzięki temu testy sprawdzają realny
    router pod DOCELOWYM URL-em, zamiast czekać na cudzy commit albo mierzyć
    coś innego niż to, co pojedzie na produkcję.
    """
    if any(getattr(r, "path", None) == BOARD_URL for r in app.routes):
        return
    from app.api import insights_board

    app.include_router(insights_board.router, prefix="/api/insights", tags=["insights"])


@pytest_asyncio.fixture
async def board_client() -> AsyncClient:
    from app.core.rate_limit import limiter as _limiter
    from app.main import app

    _ensure_board_router_mounted(app)
    _limiter.enabled = False
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=True),
        base_url="http://testserver",
    ) as c:
        yield c


async def _seed_user(role: UserRole, label: str) -> tuple[int, str, str]:
    unique = uuid.uuid4().hex[:8]
    email = f"board-{label}-{role.value}-{unique}@example.com"
    password = f"T3st_{unique}!Board"
    async with AsyncSessionLocal() as db:
        u = User(
            email=email,
            name=f"Board {label} {unique}",
            password_hash=hash_password(password),
            role=role,
            is_active=True,
        )
        db.add(u)
        await db.commit()
        await db.refresh(u)
        return u.id, email, password


async def _login(client: AsyncClient, email: str, password: str) -> dict[str, str]:
    resp = await client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _seed_client_job_candidate() -> tuple[int, int, int]:
    """Minimalna trójka Klient/Oferta/Kandydat pod ruch etapów i kontrakty."""
    async with AsyncSessionLocal() as db:
        cli = Client(name=f"BoardCli-{uuid.uuid4().hex[:6]}")
        db.add(cli)
        await db.commit()
        await db.refresh(cli)
        job = Job(
            title=f"Board {uuid.uuid4().hex[:6]}",
            location="Warszawa",
            status=JobStatus.published,
            remote_policy=RemotePolicy.hybrid,
            client_id=cli.id,
        )
        cand = Candidate(
            name=f"Bo-{uuid.uuid4().hex[:4]}",
            lastname=f"Ard-{uuid.uuid4().hex[:4]}",
            email=f"board-{uuid.uuid4().hex[:8]}@example.com",
        )
        db.add_all([job, cand])
        await db.commit()
        await db.refresh(job)
        await db.refresh(cand)
        return cli.id, job.id, cand.id


async def _seed_stage(
    candidate_id: int, job_id: int, stage: PipelineStage, moved_at: datetime
) -> None:
    async with AsyncSessionLocal() as db:
        db.add(
            CandidateStage(
                candidate_id=candidate_id,
                job_id=job_id,
                stage=stage,
                moved_at=moved_at,
                external_source="manual",
            )
        )
        await db.commit()


async def _seed_contract(
    *,
    client_id: int,
    candidate_id: int,
    start: date,
    end: date,
    rate_client: Decimal,
    rate_candidate: Decimal,
    currency: str,
) -> int:
    async with AsyncSessionLocal() as db:
        contract = Contract(
            candidate_id=candidate_id,
            client_id=client_id,
            start_date=start,
            end_date=end,
            rate_client=rate_client,
            rate_candidate=rate_candidate,
            rate_unit=RateUnit.monthly,
            rate_client_currency=currency,
            rate_candidate_currency=currency,
            currency=currency,
            status=ContractStatus.active,
        )
        db.add(contract)
        await db.commit()
        await db.refresh(contract)
        return contract.id


def _window(date_from: str, date_to: str) -> dict[str, str]:
    return {"period": "custom", "date_from": date_from, "date_to": date_to}


async def _board(
    client: AsyncClient, headers: dict[str, str], params: dict[str, str]
) -> dict:
    # Klucz cache'u niesie okno, ale ten sam test woła to samo okno dwa razy
    # (przed i po zasianiu danych) — bez unieważnienia drugi odczyt zwróciłby
    # pierwszą odpowiedź i test przechodziłby także dla zepsutego liczenia.
    await cache_invalidate("insights:board:")
    resp = await client.get(BOARD_URL, headers=headers, params=params)
    assert resp.status_code == 200, resp.text
    return resp.json()


@pytest.mark.asyncio
async def test_board_is_reachable_for_every_logged_in_role(board_client: AsyncClient):
    """D7: kokpit zarządu widzi KAŻDA zalogowana rola, bez redakcji kwot.

    `finance` i `sourcer` to dwa końce spektrum uprawnień finansowych, a legacy
    `user` jest wycofywany — gdyby któryś guard rolowy wrócił tu cichym
    refaktorem, najpierw odbiłby się właśnie któryś z tych trzech.
    """
    for role in (
        UserRole.admin,
        UserRole.sourcer,
        UserRole.finance,
        UserRole.recruiter,
        UserRole.user,
    ):
        _, email, password = await _seed_user(role, "rbac")
        headers = await _login(board_client, email, password)
        resp = await board_client.get(BOARD_URL, headers=headers)
        assert resp.status_code == 200, f"{role.value}: {resp.text}"
        body = resp.json()
        # Brak redakcji: kwoty są obecne jako pola, nie wycięte dla roli.
        assert "revenue_monthly_pln" in body["kpis"]["finance"], role.value


@pytest.mark.asyncio
async def test_board_requires_authentication(board_client: AsyncClient):
    """„Wszyscy" znaczy „każdy ZALOGOWANY", nie „każdy z internetu"."""
    resp = await board_client.get(BOARD_URL)
    assert resp.status_code in (401, 403)


@pytest.mark.asyncio
async def test_window_is_half_open_and_excludes_the_next_period(
    board_client: AsyncClient,
):
    """Ruch z pierwszego dnia POZA oknem nie może wpaść do wyniku.

    To jest regresja na `_period_start` (`reports.py:138-149`) — okno bez
    górnej granicy sprawiało, że „poprzedni miesiąc" znaczył „od poprzedniego
    miesiąca do dziś".
    """
    _, email, password = await _seed_user(UserRole.admin, "halfopen")
    headers = await _login(board_client, email, password)
    params = _window("2013-03-01", "2013-03-31")

    before = await _board(board_client, headers, params)
    assert before["period"]["start"].startswith("2013-03-01")
    # end = pierwszy dzień POZA oknem.
    assert before["period"]["end"].startswith("2013-04-01")
    baseline = before["kpis"]["placements"]

    _, job_id, cand_id = await _seed_client_job_candidate()
    await _seed_stage(
        cand_id,
        job_id,
        PipelineStage.hired,
        datetime(2013, 3, 15, 12, tzinfo=timezone.utc),
    )
    _, out_job, out_cand = await _seed_client_job_candidate()
    await _seed_stage(
        out_cand,
        out_job,
        PipelineStage.hired,
        datetime(2013, 4, 1, 12, tzinfo=timezone.utc),
    )

    after = await _board(board_client, headers, params)
    assert after["kpis"]["placements"] == baseline + 1, (
        "zatrudnienie z 1 kwietnia wpadło do marca — okno przestało być półotwarte"
    )


@pytest.mark.asyncio
async def test_placements_use_the_milestone_view_not_raw_stage_rows(
    board_client: AsyncClient,
):
    """Dwa wiersze `hired` dla TEJ SAMEJ pary to JEDEN placement (D2).

    `candidate_stages` nie ma UNIQUE na (candidate_id, job_id, stage), więc
    powrót kandydata do etapu albo drugie podejście procesowe dawało w legacy
    dwa placementy z jednego zatrudnienia. Deduplikacja mieszka w definicji
    widoku `analytics_first_milestones`, nie w pamięci autora zapytania.
    """
    _, email, password = await _seed_user(UserRole.admin, "dedup")
    headers = await _login(board_client, email, password)
    params = _window("2014-05-01", "2014-05-31")

    baseline = (await _board(board_client, headers, params))["kpis"]["placements"]

    _, job_id, cand_id = await _seed_client_job_candidate()
    await _seed_stage(
        cand_id,
        job_id,
        PipelineStage.hired,
        datetime(2014, 5, 10, 9, tzinfo=timezone.utc),
    )
    await _seed_stage(
        cand_id,
        job_id,
        PipelineStage.hired,
        datetime(2014, 5, 20, 9, tzinfo=timezone.utc),
    )

    after = await _board(board_client, headers, params)
    assert after["kpis"]["placements"] == baseline + 1, (
        "dwa wiersze `hired` dla tej samej pary policzyły się dwa razy — "
        "to jest liczenie z `candidate_stages`, nie z widoku kamieni milowych"
    )
    assert after["kpis"]["placements_definition"] == "first_hired_per_candidate_job"


@pytest.mark.asyncio
async def test_missing_fx_rate_degrades_the_tile_instead_of_shrinking_it(
    board_client: AsyncClient,
):
    """Brak kursu NBP MUSI zostawić ślad w kopercie, nie tylko mniejszą sumę.

    Legacy `_fold_finance_pln` robi w tym miejscu `continue` — kwota znika,
    a kafel obok pokazuje pewną liczbę. Tutaj sprawdzamy trzy rzeczy naraz:
    przychód w walucie Z kursem nadal wchodzi do sumy (nie wylewamy dziecka
    z kąpielą), waluta BEZ kursu jest wymieniona z nazwy, a pominięcia są
    policzone.
    """
    _, email, password = await _seed_user(UserRole.admin, "fx")
    headers = await _login(board_client, email, password)
    params = _window("2019-03-01", "2019-03-31")

    before = await _board(board_client, headers, params)
    baseline_revenue = before["kpis"]["finance"]["revenue_monthly_pln"] or 0.0

    client_id, _job_id, cand_id = await _seed_client_job_candidate()
    await _seed_contract(
        client_id=client_id,
        candidate_id=cand_id,
        start=date(2019, 1, 1),
        end=date(2019, 12, 31),
        rate_client=Decimal("12345.67"),
        rate_candidate=Decimal("10000.00"),
        currency="PLN",
    )
    _, _job2, cand2 = await _seed_client_job_candidate()
    await _seed_contract(
        client_id=client_id,
        candidate_id=cand2,
        start=date(2019, 1, 1),
        end=date(2019, 12, 31),
        rate_client=Decimal("9999.00"),
        rate_candidate=Decimal("8000.00"),
        currency=NO_FX_CURRENCY,
    )

    after = await _board(board_client, headers, params)
    finance = after["kpis"]["finance"]
    degraded = after["degraded"]

    assert degraded is not None, "brak kursu przeszedł bez śladu w kopercie"
    assert "fx_missing" in degraded["reasons"]
    assert NO_FX_CURRENCY in degraded["fx"]["currencies"], degraded
    assert degraded["fx"]["kpi_contracts_excluded_from_revenue"] >= 1
    assert finance["complete"] is False

    # Kontrakt w PLN nadal wchodzi do sumy — degradacja dotyczy kwot, których
    # nie da się przeliczyć, a nie całego kafla.
    assert finance["revenue_monthly_pln"] >= baseline_revenue + 12345.67 - 0.01
    # …i nigdy nie wchodzi po nominale jak PLN.
    assert finance["revenue_monthly_pln"] < baseline_revenue + 12345.67 + 9999.00


@pytest.mark.asyncio
async def test_money_comes_from_rate_schedules_not_the_cached_columns(
    board_client: AsyncClient,
):
    """Wycena idzie z harmonogramów (R5) — i przede wszystkim NIE wywraca się.

    Brak `selectinload` trzech harmonogramów to w sesji async nie wolniejszy
    odczyt, tylko `MissingGreenlet` → 500 bez nagłówków CORS. Ten test jest
    stróżem tamtej krawędzi: kontrakt istnieje, endpoint musi zwrócić 200
    i policzoną kwotę, a nie „Network Error".
    """
    _, email, password = await _seed_user(UserRole.admin, "sched")
    headers = await _login(board_client, email, password)
    params = _window("2020-06-01", "2020-06-30")

    before = await _board(board_client, headers, params)
    baseline = before["kpis"]["finance"]["revenue_monthly_pln"] or 0.0

    client_id, _job_id, cand_id = await _seed_client_job_candidate()
    await _seed_contract(
        client_id=client_id,
        candidate_id=cand_id,
        start=date(2020, 1, 1),
        end=date(2020, 12, 31),
        rate_client=Decimal("20000.00"),
        rate_candidate=Decimal("15000.00"),
        currency="PLN",
    )

    after = await _board(board_client, headers, params)
    finance = after["kpis"]["finance"]
    assert finance["basis"] == "mrr_from_rate_schedules"
    assert finance["revenue_monthly_pln"] >= baseline + 20000.0 - 0.01
    # Marża = przychód − koszt, oba przeliczone niezależnie.
    assert finance["margin_monthly_pln"] is not None
    # Dzień wyceny należy do okna — bez niego nie da się sprawdzić, czemu
    # ostatni słupek serii różni się od kafla.
    assert finance["asof"] == "2020-06-30"


@pytest.mark.asyncio
async def test_zero_denominator_yields_none_never_zero(board_client: AsyncClient):
    """Brak mianownika to luka, nie zero.

    Na dashboardzie rady „policzyliśmy i wyszło 0%" i „nie było czego dzielić"
    to dwie różne odpowiedzi, a tylko jedna z nich jest prawdziwa.
    """
    _, email, password = await _seed_user(UserRole.admin, "zerodiv")
    headers = await _login(board_client, email, password)

    body = await _board(board_client, headers, _window("2012-01-01", "2012-01-31"))
    kpis = body["kpis"]
    if kpis["jobs_closed"] == 0:
        assert kpis["hit_ratio_pct"] is None
    if kpis["verified"] == 0:
        assert kpis["funnel_efficiency_pct"] is None


@pytest.mark.asyncio
async def test_no_tender_fields_and_no_lying_hit_ratio(board_client: AsyncClient):
    """Przetargi są poza zakresem, a `avg_hit_ratio` nie wraca pod tą nazwą.

    Stary board liczył `avg_hit_ratio` jako `placements_ytd / COUNT(ofert)` —
    licznik i mianownik z różnych populacji pod etykietą, której nie realizują.
    Nazwa ma nie wrócić razem z formułą.
    """
    _, email, password = await _seed_user(UserRole.admin, "shape")
    headers = await _login(board_client, email, password)
    body = await _board(board_client, headers, _window("2012-02-01", "2012-02-29"))

    serialized = str(body)
    assert "tender" not in serialized
    assert "avg_hit_ratio" not in body["kpis"]
    assert body["kpis"]["hit_ratio_definition"] == (
        "closed_jobs_with_at_least_one_placement"
    )


@pytest.mark.asyncio
async def test_cache_key_carries_the_window(board_client: AsyncClient):
    """Dwa różne okna nie mogą dzielić klucza cache'u.

    Gdyby dzieliły, liczby jednego miesiąca wyszłyby pod etykietą drugiego —
    i nikt by się nie dowiedział, bo obie są wiarygodne.
    """
    _, email, password = await _seed_user(UserRole.admin, "cachekey")
    headers = await _login(board_client, email, password)

    first = await board_client.get(
        BOARD_URL, headers=headers, params=_window("2016-01-01", "2016-01-31")
    )
    second = await board_client.get(
        BOARD_URL, headers=headers, params=_window("2016-02-01", "2016-02-29")
    )
    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert first.json()["period"]["start"] != second.json()["period"]["start"]
    assert first.json()["period"]["end"] != second.json()["period"]["end"]


@pytest.mark.asyncio
async def test_trend_and_comparison_shape(board_client: AsyncClient):
    """Seria 12 miesięcy + porównanie z poprzednim oknem tej samej granulacji."""
    _, email, password = await _seed_user(UserRole.admin, "trend")
    headers = await _login(board_client, email, password)

    body = await _board(board_client, headers, {"period": "month", "offset": "-1"})
    months = body["trend"]["months"]
    assert len(months) == 12
    assert months == sorted(months, key=lambda m: m["month"])
    for month in months:
        # Dzień wyceny per miesiąc — inaczej nie da się uzgodnić wykresu z kaflem.
        assert month["asof"] >= month["month"] + "-01"

    comparison = body["comparison"]
    # Poprzednie okno tej samej granulacji, nie „minus 30 dni".
    assert comparison["previous_period"]["kind"] == "month"
    assert comparison["previous_period"]["end"] == body["period"]["start"]
    assert set(comparison["placements"]) == {
        "current",
        "previous",
        "delta",
        "change_pct",
    }
    if comparison["placements"]["previous"] == 0:
        assert comparison["placements"]["change_pct"] is None


@pytest.mark.asyncio
async def test_invalid_period_returns_422_not_500(board_client: AsyncClient):
    _, email, password = await _seed_user(UserRole.admin, "badperiod")
    headers = await _login(board_client, email, password)
    resp = await board_client.get(
        BOARD_URL, headers=headers, params={"period": "custom"}
    )
    assert resp.status_code == 422
