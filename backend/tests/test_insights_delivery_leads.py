"""GET /api/insights/delivery-leads — ranking, trend, placementy per klient.

Pod ochroną cztery rzeczy, każda odpowiadająca konkretnemu defektowi
z docs/insights-dynareporter-migration-plan.md:

1. **Trend NIE jest kumulatywny** (§4 R4). `report_delivery_lead_trend`
   (`reports.py:898-945`) liczy koniec miesiąca i go wyrzuca, więc każdy punkt
   serii jest ogonem do dziś — wykres wychodzi monotonicznie malejący i czyta
   się jak zapaść wydajności DL. To jest test regresji na dokładnie ten defekt.
2. Okno jest PÓŁOTWARTE [start, end) — także na styku miesięcy.
3. Placement = definicja D2: PIERWSZY `hired` per para (kandydat, oferta).
   Legacy liczyło każdy wiersz `hired`, więc druga próba procesowa podwajała
   dorobek DL.
4. Zerowy mianownik daje `None`, nigdy `0.0` — a `target_achieved` też `None`,
   nie `False`. Pod D7 ten wiersz widzi cała firma.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.core.cache import cache_invalidate
from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.job import Job, JobStatus, RecruitmentType, RemotePolicy
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.models.user import User, UserRole

RANKING_URL = "/api/insights/delivery-leads"
BY_CLIENT_URL = "/api/insights/delivery-leads/placements-by-client"


def _utc(year: int, month: int, day: int, hour: int = 12) -> datetime:
    return datetime(year, month, day, hour, tzinfo=timezone.utc)


async def _seed_user(role: UserRole, label: str) -> tuple[int, str, str]:
    unique = uuid.uuid4().hex[:8]
    email = f"insdl-{label}-{role.value}-{unique}@example.com"
    password = f"T3st_{unique}!DlIns"
    async with AsyncSessionLocal() as db:
        u = User(
            email=email,
            name=f"DL {label} {unique}",
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


async def _seed_client(label: str) -> int:
    async with AsyncSessionLocal() as db:
        cli = Client(name=f"DlIns-{label}-{uuid.uuid4().hex[:6]}")
        db.add(cli)
        await db.commit()
        await db.refresh(cli)
        return cli.id


async def _seed_job(
    *,
    client_id: int,
    dl_id: int | None,
    created_at: datetime,
    headcount: int = 1,
    recruitment_type: RecruitmentType = RecruitmentType.body_leasing,
    job_status: JobStatus = JobStatus.published,
) -> int:
    async with AsyncSessionLocal() as db:
        job = Job(
            title=f"DlIns {uuid.uuid4().hex[:6]}",
            location="Warszawa",
            status=job_status,
            remote_policy=RemotePolicy.hybrid,
            recruitment_type=recruitment_type,
            client_id=client_id,
            delivery_lead_id=dl_id,
            headcount=headcount,
            created_at=created_at,
        )
        db.add(job)
        await db.commit()
        await db.refresh(job)
        return job.id


async def _seed_hired(job_id: int, moved_at: datetime, candidate_id: int | None = None):
    """Wstaw ruch `hired` — zasila widok `analytics_first_milestones`.

    Zwraca `candidate_id`, żeby test D2 mógł wstawić DRUGI `hired` dla tej
    samej pary (kandydat, oferta).
    """
    async with AsyncSessionLocal() as db:
        if candidate_id is None:
            cand = Candidate(
                name=f"Dl-{uuid.uuid4().hex[:4]}",
                lastname=f"Ins-{uuid.uuid4().hex[:4]}",
                email=f"dlins-{uuid.uuid4().hex[:8]}@example.com",
            )
            db.add(cand)
            await db.commit()
            await db.refresh(cand)
            candidate_id = cand.id
        db.add(
            CandidateStage(
                candidate_id=candidate_id,
                job_id=job_id,
                stage=PipelineStage.hired,
                moved_at=moved_at,
            )
        )
        await db.commit()
        return candidate_id


async def _flush_cache():
    for prefix in (
        "insights:delivery-leads:",
        "insights:delivery-leads-by-client:",
        "insights:delivery-lead-trend:",
    ):
        await cache_invalidate(prefix)


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


def _row_for(body: dict, dl_id: int) -> dict:
    matches = [r for r in body["per_dl"] if r["user_id"] == dl_id]
    assert matches, f"DL {dl_id} nieobecny w rankingu: {body['per_dl']}"
    return matches[0]


# ── Trend: TEN test jest powodem istnienia modułu ──────────────────────────


@pytest.mark.asyncio
async def test_trend_month_reports_only_its_own_placements(fx_client: AsyncClient):
    """Każdy miesiąc niesie WYŁĄCZNIE swoje placementy — seria nie kumuluje.

    Seed rośnie w czasie (1 → 2 → 3), więc defekt jest jednoznacznie widoczny:
    przy skumulowanym ogonie do dziś pierwszy punkt wyszedłby 6, drugi 5,
    trzeci 3 — czyli wykres MALEJĄCY z danych ROSNĄCYCH. Dokładnie tak wygląda
    dziś `/api/reports/delivery-leads/{id}/trend`.
    """
    await _flush_cache()
    dl_id, _, _ = await _seed_user(UserRole.delivery_lead, "trend")
    client_id = await _seed_client("trend")

    job_mar = await _seed_job(
        client_id=client_id, dl_id=dl_id, created_at=_utc(2011, 3, 2)
    )
    job_apr = await _seed_job(
        client_id=client_id, dl_id=dl_id, created_at=_utc(2011, 4, 2)
    )
    job_may = await _seed_job(
        client_id=client_id, dl_id=dl_id, created_at=_utc(2011, 5, 2)
    )

    await _seed_hired(job_mar, _utc(2011, 3, 10))
    for day in (10, 11):
        await _seed_hired(job_apr, _utc(2011, 4, day))
    for day in (10, 11, 12):
        await _seed_hired(job_may, _utc(2011, 5, day))

    _, email, password = await _seed_user(UserRole.admin, "trendview")
    headers = await _login(fx_client, email, password)

    resp = await fx_client.get(
        f"{RANKING_URL}/{dl_id}/trend",
        headers=headers,
        params={"months": 3, "anchor": "2011-05-15"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["cumulative"] is False

    series = {p["month"]: p["placements"] for p in body["trend"]}
    assert series == {"2011-03": 1, "2011-04": 2, "2011-05": 3}, body["trend"]

    values = [p["placements"] for p in body["trend"]]
    # Sedno regresji: najwcześniejszy punkt NIE MOŻE być sumą siebie
    # i wszystkich późniejszych. Przy kumulacji byłoby 6 >= 5.
    assert values[0] < sum(values[1:]), values
    # I objaw, który widać na wykresie: seria z rosnących danych nie maleje.
    assert values == sorted(values), values


@pytest.mark.asyncio
async def test_trend_month_boundary_is_half_open(fx_client: AsyncClient):
    """Placement o północy 1. dnia miesiąca należy do NOWEGO miesiąca.

    `[start, end)` w Europe/Warsaw: 2011-07-01 00:00 lokalnie to 2011-06-30
    22:00 UTC (czas letni). Naiwne porównanie w UTC wrzuciłoby ten wiersz
    do czerwca.
    """
    await _flush_cache()
    dl_id, _, _ = await _seed_user(UserRole.delivery_lead, "boundary")
    client_id = await _seed_client("boundary")
    job_id = await _seed_job(
        client_id=client_id, dl_id=dl_id, created_at=_utc(2011, 6, 1)
    )
    # Dokładnie pierwsza chwila lipca w Warszawie.
    await _seed_hired(job_id, datetime(2011, 6, 30, 22, 0, tzinfo=timezone.utc))

    _, email, password = await _seed_user(UserRole.admin, "boundaryview")
    headers = await _login(fx_client, email, password)

    body = (
        await fx_client.get(
            f"{RANKING_URL}/{dl_id}/trend",
            headers=headers,
            params={"months": 2, "anchor": "2011-07-15"},
        )
    ).json()
    series = {p["month"]: p["placements"] for p in body["trend"]}
    assert series == {"2011-06": 0, "2011-07": 1}, body["trend"]


@pytest.mark.asyncio
async def test_trend_for_unknown_user_is_404_not_a_flat_line(fx_client: AsyncClient):
    """Sześć zer pod nieistniejącym nazwiskiem czyta się jak „nic nie dowiózł"."""
    _, email, password = await _seed_user(UserRole.admin, "notfound")
    headers = await _login(fx_client, email, password)
    resp = await fx_client.get(
        f"{RANKING_URL}/999999999/trend", headers=headers, params={"months": 2}
    )
    assert resp.status_code == 404, resp.text


# ── Ranking ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ranking_window_is_half_open_and_excludes_next_period(
    fx_client: AsyncClient,
):
    """Oferta utworzona w kolejnym okresie nie może wpaść do bieżącego.

    Legacy `_period_start` nie miał górnej granicy, więc „poprzedni miesiąc"
    znaczył „od poprzedniego miesiąca do dziś".
    """
    await _flush_cache()
    dl_id, _, _ = await _seed_user(UserRole.delivery_lead, "halfopen")
    client_id = await _seed_client("halfopen")
    await _seed_job(
        client_id=client_id, dl_id=dl_id, created_at=_utc(2012, 1, 15), headcount=2
    )
    await _seed_job(
        client_id=client_id, dl_id=dl_id, created_at=_utc(2012, 2, 3), headcount=5
    )

    _, email, password = await _seed_user(UserRole.admin, "halfopenview")
    headers = await _login(fx_client, email, password)

    body = (
        await fx_client.get(
            RANKING_URL,
            headers=headers,
            params={
                "period": "custom",
                "date_from": "2012-01-01",
                "date_to": "2012-01-31",
            },
        )
    ).json()
    assert body["period"]["end"].startswith("2012-02-01")
    row = _row_for(body, dl_id)
    assert row["total_requests"] == 1
    assert row["total_vacancies"] == 2


@pytest.mark.asyncio
async def test_placement_is_first_hired_per_candidate_job_pair(fx_client: AsyncClient):
    """D2: druga próba procesowa tej samej pary NIE jest drugim placementem.

    Legacy `_compute_dl_metrics` liczyło każdy wiersz `candidate_stages`
    ze stage='hired', więc para z dwoma podejściami podwajała dorobek DL.
    """
    await _flush_cache()
    dl_id, _, _ = await _seed_user(UserRole.delivery_lead, "d2")
    client_id = await _seed_client("d2")
    job_id = await _seed_job(
        client_id=client_id, dl_id=dl_id, created_at=_utc(2012, 5, 2)
    )
    cand_id = await _seed_hired(job_id, _utc(2012, 5, 10))
    await _seed_hired(job_id, _utc(2012, 5, 20), candidate_id=cand_id)

    _, email, password = await _seed_user(UserRole.admin, "d2view")
    headers = await _login(fx_client, email, password)

    body = (
        await fx_client.get(
            RANKING_URL,
            headers=headers,
            params={
                "period": "custom",
                "date_from": "2012-05-01",
                "date_to": "2012-05-31",
            },
        )
    ).json()
    assert _row_for(body, dl_id)["placements"] == 1


@pytest.mark.asyncio
async def test_zero_denominator_yields_none_not_zero(fx_client: AsyncClient):
    """DL z placementami i bez nowych zapytań to LUKA, nie „poniżej progu".

    `_safe_pct` z legacy zwracało 0.0, a `target_achieved` wychodziło `False`.
    Pod D7 taki wiersz widzi cała firma — 0% obok nazwiska to zarzut.
    """
    await _flush_cache()
    dl_id, _, _ = await _seed_user(UserRole.delivery_lead, "zerodiv")
    client_id = await _seed_client("zerodiv")
    # Oferta z INNEGO okresu — w oknie pomiaru nie ma żadnego zapytania.
    job_id = await _seed_job(
        client_id=client_id, dl_id=dl_id, created_at=_utc(2012, 8, 1)
    )
    await _seed_hired(job_id, _utc(2012, 9, 10))

    _, email, password = await _seed_user(UserRole.admin, "zerodivview")
    headers = await _login(fx_client, email, password)

    body = (
        await fx_client.get(
            RANKING_URL,
            headers=headers,
            params={
                "period": "custom",
                "date_from": "2012-09-01",
                "date_to": "2012-09-30",
            },
        )
    ).json()
    row = _row_for(body, dl_id)
    assert row["placements"] == 1
    assert row["total_requests"] == 0
    assert row["hit_ratio"] is None
    assert row["fill_rate"] is None
    assert row["avg_vacancies_per_request"] is None
    assert row["target_achieved"] is None


@pytest.mark.asyncio
async def test_ranking_falls_back_to_head_delivery_lead_of_the_client(
    fx_client: AsyncClient,
):
    """Oferta bez `delivery_lead_id` liczy się głównemu opiekunowi klienta.

    Bez tego fallbacku ranking milczy o większości ofert (kolumna na ofercie
    jest opcjonalna), a placementy lądują w `unattributed`.
    """
    await _flush_cache()
    from app.models.team_structure import DeliveryLeadClientAssignment

    dl_id, _, _ = await _seed_user(UserRole.delivery_lead, "fallback")
    client_id = await _seed_client("fallback")
    async with AsyncSessionLocal() as db:
        db.add(
            DeliveryLeadClientAssignment(
                delivery_lead_user_id=dl_id, client_id=client_id, is_head=True
            )
        )
        await db.commit()

    job_id = await _seed_job(
        client_id=client_id, dl_id=None, created_at=_utc(2012, 11, 5), headcount=3
    )
    await _seed_hired(job_id, _utc(2012, 11, 10))

    _, email, password = await _seed_user(UserRole.admin, "fallbackview")
    headers = await _login(fx_client, email, password)

    body = (
        await fx_client.get(
            RANKING_URL,
            headers=headers,
            params={
                "period": "custom",
                "date_from": "2012-11-01",
                "date_to": "2012-11-30",
            },
        )
    ).json()
    row = _row_for(body, dl_id)
    assert row["total_requests"] == 1
    assert row["total_vacancies"] == 3
    assert row["placements"] == 1
    assert row["hit_ratio"] == 100.0


@pytest.mark.asyncio
async def test_unattributed_placements_stay_out_of_every_row(fx_client: AsyncClient):
    """Oferta bez DL i bez głównego opiekuna idzie do `unattributed`, org-level.

    Nigdy do czyjegoś wiersza (wzorzec `kpi_team.py`) — inaczej suma wierszy
    po cichu nie zgadza się z lejkiem.
    """
    await _flush_cache()
    client_id = await _seed_client("orphan")
    job_id = await _seed_job(
        client_id=client_id, dl_id=None, created_at=_utc(2013, 2, 4), headcount=2
    )
    await _seed_hired(job_id, _utc(2013, 2, 10))

    _, email, password = await _seed_user(UserRole.admin, "orphanview")
    headers = await _login(fx_client, email, password)

    body = (
        await fx_client.get(
            RANKING_URL,
            headers=headers,
            params={
                "period": "custom",
                "date_from": "2013-02-01",
                "date_to": "2013-02-28",
            },
        )
    ).json()
    assert body["unattributed"]["placements"] >= 1
    assert body["unattributed"]["requests"] >= 1
    assert all(r["user_id"] is not None for r in body["per_dl"])


@pytest.mark.asyncio
async def test_cache_key_carries_the_window(fx_client: AsyncClient):
    """Dwa różne okna nie mogą dzielić klucza — inaczej liczby jednego okresu
    wyjdą pod etykietą drugiego i obie będą wyglądały wiarygodnie."""
    await _flush_cache()
    dl_id, _, _ = await _seed_user(UserRole.delivery_lead, "cachekey")
    client_id = await _seed_client("cachekey")
    await _seed_job(client_id=client_id, dl_id=dl_id, created_at=_utc(2013, 4, 10))

    _, email, password = await _seed_user(UserRole.admin, "cachekeyview")
    headers = await _login(fx_client, email, password)

    april = (
        await fx_client.get(
            RANKING_URL,
            headers=headers,
            params={
                "period": "custom",
                "date_from": "2013-04-01",
                "date_to": "2013-04-30",
            },
        )
    ).json()
    may = (
        await fx_client.get(
            RANKING_URL,
            headers=headers,
            params={
                "period": "custom",
                "date_from": "2013-05-01",
                "date_to": "2013-05-31",
            },
        )
    ).json()
    assert april["period"]["start"] != may["period"]["start"]
    assert _row_for(april, dl_id)["total_requests"] == 1

    # Ten sam DL w maju: kolumny okna wyzerowane, bo oferta powstała w kwietniu.
    # Wiersz mimo to ZOSTAJE — niesie otwarty pipeline, który jest snapshotem
    # „na teraz" i celowo nie zależy od okna. Zera są nieocenialne, nie złe:
    # `hit_ratio`/`target_achieved` to `None`, więc UI ma czym to podpisać.
    may_row = _row_for(may, dl_id)
    assert may_row["total_requests"] == 0
    assert may_row["placements"] == 0
    assert may_row["hit_ratio"] is None
    assert may_row["target_achieved"] is None
    assert may_row["open_requests"] >= 1


# ── Placementy per klient (donut) ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_placements_by_client_uses_the_d2_definition(fx_client: AsyncClient):
    """Donut liczy z `analytics_first_milestones`, nie z `/api/reports/clients`.

    Tam placement to KAŻDY wiersz `hired` i tylko dla ofert zamkniętych — dwie
    definicje na jednym ekranie dają dwie różne sumy pod tą samą etykietą.
    Poza tym `sales_project` nie należy do body leasingu i nie może tu wejść.
    """
    await _flush_cache()
    dl_id, _, _ = await _seed_user(UserRole.delivery_lead, "donut")
    client_a = await _seed_client("donutA")
    client_b = await _seed_client("donutB")

    job_a = await _seed_job(
        client_id=client_a, dl_id=dl_id, created_at=_utc(2013, 7, 1)
    )
    job_b = await _seed_job(
        client_id=client_b, dl_id=dl_id, created_at=_utc(2013, 7, 1)
    )
    job_sales = await _seed_job(
        client_id=client_b,
        dl_id=dl_id,
        created_at=_utc(2013, 7, 1),
        recruitment_type=RecruitmentType.sales_project,
    )
    for day in (5, 6):
        await _seed_hired(job_a, _utc(2013, 7, day))
    await _seed_hired(job_b, _utc(2013, 7, 7))
    await _seed_hired(job_sales, _utc(2013, 7, 8))

    _, email, password = await _seed_user(UserRole.admin, "donutview")
    headers = await _login(fx_client, email, password)

    body = (
        await fx_client.get(
            BY_CLIENT_URL,
            headers=headers,
            params={
                "period": "custom",
                "date_from": "2013-07-01",
                "date_to": "2013-07-31",
            },
        )
    ).json()
    by_id = {c["client_id"]: c for c in body["clients"]}
    assert by_id[client_a]["placements"] == 2
    assert by_id[client_b]["placements"] == 1  # `sales_project` NIE wchodzi
    assert body["recruitment_type"] == "body_leasing"
    assert by_id[client_a]["share_pct"] is not None


# ── RBAC (D7) ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_every_logged_in_role_reaches_all_three_endpoints(
    fx_client: AsyncClient,
):
    """D7: /insights widzi KAŻDA zalogowana rola — także `sourcer` i `finance`.

    `/api/reports/delivery-leads` zostaje przy admin+HoR+TCM+finance; ta trasa
    jest nowa właśnie po to, żeby nie poszerzać tamtego guardu.
    """
    dl_id, _, _ = await _seed_user(UserRole.delivery_lead, "rbactarget")
    for role in (
        UserRole.admin,
        UserRole.head_of_recruitment,
        UserRole.delivery_lead,
        UserRole.talent_community_manager,
        UserRole.tac,
        UserRole.recruiter,
        UserRole.sourcer,
        UserRole.finance,
    ):
        _, email, password = await _seed_user(role, "rbac")
        headers = await _login(fx_client, email, password)
        for url in (
            RANKING_URL,
            BY_CLIENT_URL,
            f"{RANKING_URL}/{dl_id}/trend",
        ):
            resp = await fx_client.get(url, headers=headers)
            assert resp.status_code == 200, f"{role.value} {url}: {resp.text}"


@pytest.mark.asyncio
async def test_unauthenticated_is_rejected_on_every_endpoint(fx_client: AsyncClient):
    """„Wszyscy" znaczy „każdy ZALOGOWANY", nie „każdy z internetu"."""
    for url in (RANKING_URL, BY_CLIENT_URL, f"{RANKING_URL}/1/trend"):
        resp = await fx_client.get(url)
        assert resp.status_code in (401, 403), f"{url}: {resp.status_code}"


@pytest.mark.asyncio
async def test_invalid_period_returns_422_not_500(fx_client: AsyncClient):
    _, email, password = await _seed_user(UserRole.admin, "badperiod")
    headers = await _login(fx_client, email, password)
    resp = await fx_client.get(
        RANKING_URL, headers=headers, params={"period": "custom"}
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_anchor_selects_a_past_period_without_custom_dates(
    fx_client: AsyncClient,
):
    """Kotwica adresuje dowolny miesiąc — bez ręcznego liczenia granic.

    Bez niej jedynym sposobem na „lipiec 2013" był `custom` z datami liczonymi
    u każdego konsumenta osobno, po swojemu i z własnym błędem.
    """
    _, email, password = await _seed_user(UserRole.admin, "anchor")
    headers = await _login(fx_client, email, password)
    body = (
        await fx_client.get(
            RANKING_URL,
            headers=headers,
            params={"period": "month", "anchor": "2013-07-15"},
        )
    ).json()
    assert body["period"]["start"].startswith("2013-07-01")
    assert body["period"]["end"].startswith("2013-08-01")
