"""GET /api/insights/clients/{ranking,hit-ratio} — Klienci / MRR.

Cztery rzeczy pod ochroną, każda odpowiadająca konkretnemu defektowi:

1. **D7** — endpoint widzi KAŻDA zalogowana rola, także `sourcer` i `finance`.
   Powierzchnie źródłowe (`/api/admin/clients-overview` na `FinanceReadUser`,
   `/api/reports/clients` na czterech rolach) są współdzielone i ich guardów
   NIE wolno poszerzać — stąd osobny router.
2. **Pieniądze z HARMONOGRAMÓW stawek, nie z kolumn `contracts.rate_*`.**
   Kolumna niesie kwotę z ostatniego ZAPISU kontraktu, więc krok progresywny
   albo aneks z datą, która już nadeszła, pokazywały marżę pierwszego okresu.
   Test seeduje dokładnie ten kształt: kolumna mówi 50, harmonogram 200.
3. **Kafel = suma widocznych wierszy.** Kafel będący sumą innych liczb niż
   widoczne pod nim nie daje się zweryfikować wzrokiem.
4. **Placement = D2** — pierwsze `hired` per para (kandydat, oferta).
   `reports.py:1080-1098` liczy tu każdy wiersz `candidate_stages.hired`, więc
   para z dwoma podejściami procesowymi wchodzi tam dwa razy.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import AsyncIterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.core.cache import cache_invalidate
from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.contact import Contact
from app.models.contract import Contract, ContractStatus, RateUnit
from app.models.contract_candidate_rate import ContractCandidateRate
from app.models.contract_client_rate import ContractClientRate
from app.models.job import Job, JobStatus, RemotePolicy
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.models.user import User, UserRole

RANKING = "/api/insights/clients/ranking"
HIT_RATIO = "/api/insights/clients/hit-ratio"


async def _seed_user(role: UserRole, label: str) -> tuple[int, str, str]:
    unique = uuid.uuid4().hex[:8]
    email = f"insc-{label}-{role.value}-{unique}@example.com"
    password = f"T3st_{unique}!Clients"
    async with AsyncSessionLocal() as db:
        u = User(
            email=email,
            name=f"Clients {label} {unique}",
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


@pytest_asyncio.fixture
async def fx_client() -> AsyncIterator[AsyncClient]:
    from app.core.rate_limit import limiter as _limiter
    from app.main import app

    _limiter.enabled = False
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=True),
        base_url="http://testserver",
    ) as c:
        yield c


@pytest_asyncio.fixture
async def admin_headers(fx_client: AsyncClient) -> dict[str, str]:
    _, email, password = await _seed_user(UserRole.admin, "base")
    return await _login(fx_client, email, password)


@pytest_asyncio.fixture
async def stale_rate_column_contract() -> AsyncIterator[dict]:
    """Kontrakt, którego KOLUMNA stawki kłamie, a harmonogram mówi prawdę.

    To jest naprawiany defekt: `contracts.rate_client`/`rate_candidate` niosą
    kwotę z ostatniego ZAPISU kontraktu. Aneks `rate_change` z datą, która już
    nadeszła, wpisuje do kolumny wartość z chwili UTWORZENIA aneksu i nic jej
    potem nie przelicza — więc kolumna pokazuje stawkę sprzed zmiany.

    Kolumny: 100 − 50 = 50 zł marży. Harmonogram: 300 − 100 = 200 zł.
    Jeśli endpoint pokaże 50, czyta z kolumny i defekt wrócił.
    """
    sfx = uuid.uuid4().hex[:8]
    effective_from = date.today() - timedelta(days=365)
    async with AsyncSessionLocal() as db:
        client = Client(name=f"InsCliRate-{sfx}")
        candidate = Candidate(
            name=f"Ins-{sfx}",
            lastname=f"Rate-{sfx}",
            email=f"ins-rate-{sfx}@example.com",
        )
        db.add_all([client, candidate])
        await db.commit()
        await db.refresh(client)
        await db.refresh(candidate)

        contract = Contract(
            client_id=client.id,
            candidate_id=candidate.id,
            status=ContractStatus.active,
            rate_unit=RateUnit.monthly,
            currency="PLN",
            rate_client_currency="PLN",
            rate_candidate_currency="PLN",
            # Nieaktualny cache — dokładnie to, co widać po aneksie z datą
            # przeszłą, którego nikt nie „dotknął" ponownym zapisem.
            rate_client=Decimal("100"),
            rate_candidate=Decimal("50"),
            start_date=effective_from,
        )
        db.add(contract)
        await db.commit()
        await db.refresh(contract)

        db.add_all(
            [
                ContractClientRate(
                    contract_id=contract.id,
                    rate=Decimal("300"),
                    effective_from=effective_from,
                ),
                ContractCandidateRate(
                    contract_id=contract.id,
                    rate=Decimal("100"),
                    effective_from=effective_from,
                ),
            ]
        )
        await db.commit()
        payload = {
            "client_id": client.id,
            "contract_id": contract.id,
            "candidate_id": candidate.id,
            "column_margin": 50,
            "schedule_margin": 200,
        }

    try:
        yield payload
    finally:
        # Sprzątamy, bo aktywny kontrakt wchodzi do globalnych agregatów innych
        # zestawów testowych. Kolejność: kontrakt (kaskaduje harmonogramy) →
        # kandydat → klient.
        async with AsyncSessionLocal() as db:
            for model, key in (
                (Contract, "contract_id"),
                (Candidate, "candidate_id"),
                (Client, "client_id"),
            ):
                row = await db.get(model, payload[key])
                if row is not None:
                    await db.delete(row)
                    await db.commit()


@pytest_asyncio.fixture
async def closed_job_hired_twice() -> AsyncIterator[dict]:
    """Oferta zamknięta w oknie, z DWOMA wierszami `hired` dla tej samej pary.

    D2 mówi: to JEDEN placement. Liczenie wierszy `candidate_stages` (tak robi
    `reports.py`) dałoby dwa i `fill_rate` 200% przy jednym wakacie.
    """
    sfx = uuid.uuid4().hex[:8]
    closed_at = datetime(2015, 5, 15, 12, tzinfo=timezone.utc)
    async with AsyncSessionLocal() as db:
        client = Client(name=f"InsCliHit-{sfx}")
        candidate = Candidate(
            name=f"Hit-{sfx}",
            lastname=f"Ratio-{sfx}",
            email=f"ins-hit-{sfx}@example.com",
        )
        db.add_all([client, candidate])
        await db.commit()
        await db.refresh(client)
        await db.refresh(candidate)

        job = Job(
            title=f"InsHit {sfx}",
            location="Warszawa",
            status=JobStatus.closed,
            remote_policy=RemotePolicy.hybrid,
            client_id=client.id,
            headcount=1,
            closed_at=closed_at,
        )
        db.add(job)
        await db.commit()
        await db.refresh(job)

        db.add_all(
            [
                CandidateStage(
                    candidate_id=candidate.id,
                    job_id=job.id,
                    stage=PipelineStage.hired,
                    moved_at=closed_at - timedelta(days=10),
                    external_source="manual",
                ),
                # Drugie podejście procesowe tej samej pary — w widoku kamieni
                # milowych jest odcinane, w surowych `candidate_stages` nie.
                CandidateStage(
                    candidate_id=candidate.id,
                    job_id=job.id,
                    stage=PipelineStage.hired,
                    moved_at=closed_at - timedelta(days=3),
                    external_source="manual",
                ),
            ]
        )
        await db.commit()
        payload = {
            "client_id": client.id,
            "job_id": job.id,
            "candidate_id": candidate.id,
        }

    try:
        yield payload
    finally:
        async with AsyncSessionLocal() as db:
            from sqlalchemy import delete

            await db.execute(
                delete(CandidateStage).where(CandidateStage.job_id == payload["job_id"])
            )
            await db.commit()
            for model, key in (
                (Job, "job_id"),
                (Candidate, "candidate_id"),
                (Client, "client_id"),
            ):
                row = await db.get(model, payload[key])
                if row is not None:
                    await db.delete(row)
                    await db.commit()


# ── D7: każdy zalogowany ────────────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "role",
    [
        UserRole.admin,
        UserRole.head_of_recruitment,
        UserRole.delivery_lead,
        UserRole.finance,
        UserRole.tac,
        UserRole.recruiter,
        UserRole.sourcer,
    ],
)
async def test_every_role_reaches_both_endpoints(fx_client: AsyncClient, role):
    """Decyzja D7: /insights widzi KAŻDA zalogowana rola — bez redakcji kwot."""
    _, email, password = await _seed_user(role, "rbac")
    headers = await _login(fx_client, email, password)

    for url in (RANKING, HIT_RATIO):
        resp = await fx_client.get(url, headers=headers)
        assert resp.status_code == 200, f"{role.value} @ {url}: {resp.text}"


@pytest.mark.asyncio
async def test_endpoints_require_authentication(fx_client: AsyncClient):
    """„Wszyscy" znaczy „każdy ZALOGOWANY", nie „każdy z internetu"."""
    for url in (RANKING, HIT_RATIO):
        resp = await fx_client.get(url)
        assert resp.status_code in (401, 403), url


@pytest.mark.asyncio
async def test_money_is_not_redacted_for_a_role_without_view_finance(
    fx_client: AsyncClient,
    stale_rate_column_contract: dict,
):
    """Rola `sourcer` widzi kwoty — inaczej D7 nie jest zrealizowane.

    Redakcja na /insights jest zdjęta świadomie; jeśli ktoś ją tu doda, ten
    test padnie zanim wersja trafi na produkcję.
    """
    await cache_invalidate("insights:clients:")
    _, email, password = await _seed_user(UserRole.sourcer, "money")
    headers = await _login(fx_client, email, password)

    body = (await fx_client.get(RANKING, headers=headers)).json()
    row = next(
        r
        for r in body["clients"]
        if r["client_id"] == stale_rate_column_contract["client_id"]
    )
    assert row["monthly_margin_total"] == stale_rate_column_contract["schedule_margin"]


# ── Pieniądze z harmonogramów, nie z kolumn ─────────────────────────────────


@pytest.mark.asyncio
async def test_margin_comes_from_rate_schedule_not_the_cached_column(
    fx_client: AsyncClient,
    admin_headers: dict[str, str],
    stale_rate_column_contract: dict,
):
    """Kolumna `contracts.rate_*` jest cache'em ostatniego zapisu — kłamie.

    Ten wiersz ma w kolumnach marżę 50 zł, a w harmonogramach 200 zł. Wynik 50
    znaczy, że endpoint czyta z kolumny i defekt wrócił.
    """
    await cache_invalidate("insights:clients:")
    body = (await fx_client.get(RANKING, headers=admin_headers)).json()

    row = next(
        r
        for r in body["clients"]
        if r["client_id"] == stale_rate_column_contract["client_id"]
    )
    assert row["monthly_margin_total"] == stale_rate_column_contract["schedule_margin"]
    assert row["monthly_margin_total"] != stale_rate_column_contract["column_margin"]
    assert row["active_contracts"] == 1
    assert row["active_consultants"] == 1


@pytest.mark.asyncio
async def test_admin_overview_reports_the_same_margin_as_insights(
    fx_client: AsyncClient,
    admin_headers: dict[str, str],
    stale_rate_column_contract: dict,
):
    """Obie powierzchnie liczą tym samym serwisem — więc muszą się zgadzać.

    Rozjazd tutaj znaczy, że ktoś odkleił jedną z nich od
    `app/services/insights_clients.py` i kopie zaczęły żyć własnym życiem.
    """
    await cache_invalidate("insights:clients:")
    insights = (await fx_client.get(RANKING, headers=admin_headers)).json()
    admin = (
        await fx_client.get("/api/admin/clients-overview", headers=admin_headers)
    ).json()

    client_id = stale_rate_column_contract["client_id"]
    ins_row = next(r for r in insights["clients"] if r["client_id"] == client_id)
    adm_row = next(r for r in admin if r["client_id"] == client_id)
    assert ins_row["monthly_margin_total"] == adm_row["monthly_margin_total"]
    assert ins_row["active_consultants"] == adm_row["active_consultants"]


# ── Kafel = suma widocznych wierszy ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_mrr_tile_equals_the_sum_of_the_listed_rows(
    fx_client: AsyncClient,
    admin_headers: dict[str, str],
    stale_rate_column_contract: dict,
):
    """Kafel „Suma MRR" musi dać się sprawdzić dodając kolumnę na ekranie.

    Suma zaokrągleń ≠ zaokrąglenie sumy, więc kafel liczony z surowych
    `Decimal` różniłby się od kolumny o złotówki (`app/schemas/money.py`).
    """
    await cache_invalidate("insights:clients:")
    body = (await fx_client.get(RANKING, headers=admin_headers)).json()
    clients, totals = body["clients"], body["totals"]

    assert totals["monthly_margin_total"] == sum(
        c["monthly_margin_total"] or 0 for c in clients
    )
    assert totals["total_revenue_all_time"] == sum(
        c["total_revenue_all_time"] or 0 for c in clients
    )
    assert totals["active_revenue"] == sum(c["active_revenue"] or 0 for c in clients)
    assert totals["clients"] == len(clients)
    assert totals["active_clients"] == sum(1 for c in clients if c["active_contracts"])
    assert totals["active_consultants"] == sum(c["active_consultants"] for c in clients)

    # Kontrakt z fixture'a MUSI być w sumowanej liście — inaczej test
    # przechodziłby także wtedy, gdy obie strony równania są puste.
    seeded = next(
        c for c in clients if c["client_id"] == stale_rate_column_contract["client_id"]
    )
    assert (
        seeded["monthly_margin_total"]
        == (stale_rate_column_contract["schedule_margin"])
    )


@pytest.mark.asyncio
async def test_hit_ratio_overall_folds_the_returned_rows(
    fx_client: AsyncClient,
    admin_headers: dict[str, str],
    closed_job_hired_twice: dict,
):
    """`overall` liczy się z listy PO filtrze, nie z pełnego zbioru.

    `reports.py` liczy `overall` po wszystkich klientach, a wyświetla
    przefiltrowanych przez `min_closed` — kafel nie zgadza się wtedy z sumą
    tabeli pod nim.
    """
    await cache_invalidate("insights:clients:")
    body = (
        await fx_client.get(
            HIT_RATIO,
            headers=admin_headers,
            params={
                "period": "custom",
                "date_from": "2015-05-01",
                "date_to": "2015-05-31",
            },
        )
    ).json()

    clients, overall = body["clients"], body["overall"]
    assert overall["total_closed_jobs"] == sum(c["closed_jobs"] for c in clients)
    assert overall["total_placements"] == sum(c["placements"] for c in clients)
    assert overall["total_filled_jobs"] == sum(c["filled_jobs"] for c in clients)
    assert overall["total_clients"] == len(clients)


# ── D2: placement = pierwsze `hired` per para ───────────────────────────────


@pytest.mark.asyncio
async def test_placement_is_first_hired_per_candidate_and_job(
    fx_client: AsyncClient,
    admin_headers: dict[str, str],
    closed_job_hired_twice: dict,
):
    """Dwa wiersze `hired` dla jednej pary to JEDEN placement (D2).

    Liczenie wierszy `candidate_stages` dałoby 2 placementy przy 1 wakacie,
    czyli `fill_rate` 200% — i nikt by tego nie zakwestionował, bo liczba
    wygląda wiarygodnie dopóki nie przekroczy stu procent.
    """
    await cache_invalidate("insights:clients:")
    body = (
        await fx_client.get(
            HIT_RATIO,
            headers=admin_headers,
            params={
                "period": "custom",
                "date_from": "2015-05-01",
                "date_to": "2015-05-31",
            },
        )
    ).json()

    assert body["placement_definition"] == "first_hired_per_candidate_and_job"
    row = next(
        r
        for r in body["clients"]
        if r["client_id"] == closed_job_hired_twice["client_id"]
    )
    assert row["closed_jobs"] == 1
    assert row["placements"] == 1, "drugie podejście procesowe nie jest placementem"
    assert row["filled_jobs"] == 1
    assert row["hit_ratio"] == 100.0
    assert row["fill_rate"] == 100.0


# ── Okno, mianowniki, klucze cache'u ────────────────────────────────────────


@pytest.mark.asyncio
async def test_hit_ratio_window_is_half_open(
    fx_client: AsyncClient,
    admin_headers: dict[str, str],
    closed_job_hired_twice: dict,
):
    """Oferta zamknięta 15 maja nie może wpaść do okna kwietniowego.

    Legacy `_period_start` nie miał górnej granicy, więc „poprzedni miesiąc"
    znaczył „od poprzedniego miesiąca do dziś".
    """
    await cache_invalidate("insights:clients:")
    body = (
        await fx_client.get(
            HIT_RATIO,
            headers=admin_headers,
            params={
                "period": "custom",
                "date_from": "2015-04-01",
                "date_to": "2015-04-30",
            },
        )
    ).json()

    assert body["period"]["start"].startswith("2015-04-01")
    # end = 1 maja, czyli PIERWSZY dzień POZA oknem (półotwarte).
    assert body["period"]["end"].startswith("2015-05-01")
    assert not [
        r
        for r in body["clients"]
        if r["client_id"] == closed_job_hired_twice["client_id"]
    ]


@pytest.mark.asyncio
async def test_zero_denominator_yields_none_not_zero(
    fx_client: AsyncClient,
    admin_headers: dict[str, str],
):
    """Brak mianownika to luka, nie zero.

    0.0 czyta się jako „policzyliśmy i wyszło zero"; None mówi „nie było czego
    dzielić". Na ekranie oceniającym klientów to jest różnica.
    """
    await cache_invalidate("insights:clients:")
    body = (
        await fx_client.get(
            HIT_RATIO,
            headers=admin_headers,
            params={
                "period": "custom",
                "date_from": "1999-01-01",
                "date_to": "1999-01-31",
            },
        )
    ).json()

    assert body["clients"] == []
    assert body["overall"]["global_hit_ratio"] is None
    assert body["overall"]["global_fill_rate"] is None
    assert body["overall"]["avg_hit_ratio"] is None


@pytest.mark.asyncio
async def test_at_risk_does_not_invent_a_previous_ratio(
    fx_client: AsyncClient,
    admin_headers: dict[str, str],
    closed_job_hired_twice: dict,
):
    """Klient bez porównywalnego poprzedniego okna trafia do `not_comparable`.

    `reports.py` podstawia tam 0.0, czyli twierdzi, że klient miał zerową
    skuteczność — a on nie miał ANI JEDNEJ zamkniętej oferty.
    """
    await cache_invalidate("insights:clients:")
    body = (
        await fx_client.get(
            HIT_RATIO,
            headers=admin_headers,
            params={
                "period": "custom",
                "date_from": "2015-05-01",
                "date_to": "2015-05-31",
                "at_risk_min_closed": 1,
            },
        )
    ).json()

    at_risk = body["at_risk"]
    # Poprzednie okno przylega do bieżącego bez luki i bez zakładki — inaczej
    # porównywalibyśmy wycinek innego okresu.
    assert at_risk["previous_period"]["end"] == body["period"]["start"]
    assert at_risk["not_comparable"] >= 1
    assert not [
        c
        for c in at_risk["clients"]
        if c["client_id"] == closed_job_hired_twice["client_id"]
    ]


@pytest.mark.asyncio
async def test_two_windows_do_not_share_a_cache_key(
    fx_client: AsyncClient,
    admin_headers: dict[str, str],
):
    """Klucz cache'u niesie okno — inaczej liczby jednego okresu wychodzą pod
    etykietą drugiego i nikt się nie dowie, bo obie są wiarygodne."""
    a = await fx_client.get(
        HIT_RATIO,
        headers=admin_headers,
        params={"period": "custom", "date_from": "2014-01-01", "date_to": "2014-01-31"},
    )
    b = await fx_client.get(
        HIT_RATIO,
        headers=admin_headers,
        params={"period": "custom", "date_from": "2014-02-01", "date_to": "2014-02-28"},
    )
    assert a.json()["period"]["start"] != b.json()["period"]["start"]

    r1 = await fx_client.get(
        RANKING,
        headers=admin_headers,
        params={"period": "month", "offset": 0},
    )
    r2 = await fx_client.get(
        RANKING,
        headers=admin_headers,
        params={"period": "month", "offset": -1},
    )
    assert r1.json()["period"]["start"] != r2.json()["period"]["start"]
    # Dzień wyceny też się różni — inaczej okno w kluczu byłoby dekoracją.
    assert r1.json()["valuation"]["on"] != r2.json()["valuation"]["on"]


@pytest.mark.asyncio
async def test_invalid_period_returns_422_not_500(
    fx_client: AsyncClient,
    admin_headers: dict[str, str],
):
    for url in (RANKING, HIT_RATIO):
        resp = await fx_client.get(
            url, headers=admin_headers, params={"period": "custom"}
        )
        assert resp.status_code == 422, f"{url}: {resp.text}"


@pytest.mark.asyncio
async def test_unknown_exclude_reason_is_rejected_not_ignored(
    fx_client: AsyncClient,
    admin_headers: dict[str, str],
):
    """Literówka w filtrze cicho poszerza mianownik i podnosi hit ratio.

    `reports.py:_parse_exclude_reasons` gubi nieznane wartości milcząco —
    tutaj żądanie ma się odbić, nie policzyć czegoś innego niż poproszono.
    """
    resp = await fx_client.get(
        HIT_RATIO,
        headers=admin_headers,
        params={"exclude_reasons": "paused,typo_reason"},
    )
    assert resp.status_code == 422, resp.text


# ── hiring-managers (odpowiednik /api/reports/hiring-managers) ──────────────

HIRING_MANAGERS = "/api/insights/clients/hiring-managers"


async def _seed_hiring_manager(*, job_created_at: datetime) -> tuple[int, str]:
    """Klient + kontakt + JEDNA opublikowana rekrutacja prowadzona przez ten kontakt.

    ``Job.created_at`` ustawiamy wprost, bo to właśnie ta kolumna jest filtrowana
    oknem — bez niej rekrutacja lądowałaby „dziś" i test okna nic by nie mierzył.
    """
    sfx = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"HmCli-{sfx}")
        db.add(client)
        await db.commit()
        await db.refresh(client)

        contact = Contact(client_id=client.id, name=f"HM {sfx}", position="CTO")
        db.add(contact)
        await db.commit()
        await db.refresh(contact)

        job = Job(
            title=f"Hm {sfx}",
            location="Warszawa",
            status=JobStatus.published,
            remote_policy=RemotePolicy.hybrid,
            client_id=client.id,
            hiring_manager_contact_id=contact.id,
            created_at=job_created_at,
        )
        db.add(job)
        await db.commit()
        return contact.id, f"HM {sfx}"


@pytest.mark.asyncio
async def test_hiring_managers_is_open_to_every_logged_in_role(
    fx_client: AsyncClient,
):
    """D7 — także dla `recruiter`, `sourcer`, `tac`, `delivery_lead` i `user`.

    To są dokładnie te role, dla których legacy `/api/reports/hiring-managers`
    zwraca 403 (`require_roles(admin, head_of_recruitment, finance)`), a sekcja
    na `/insights` renderowała ten 403 jako „Błąd ładowania".
    """
    for role in (
        UserRole.recruiter,
        UserRole.sourcer,
        UserRole.tac,
        UserRole.delivery_lead,
        UserRole.user,
        UserRole.admin,
    ):
        _, email, password = await _seed_user(role, "hm-rbac")
        headers = await _login(fx_client, email, password)
        resp = await fx_client.get(HIRING_MANAGERS, headers=headers)
        assert resp.status_code == 200, f"{role.value}: {resp.text}"


@pytest.mark.asyncio
async def test_hiring_managers_requires_authentication(fx_client: AsyncClient):
    resp = await fx_client.get(HIRING_MANAGERS)
    assert resp.status_code in (401, 403)


@pytest.mark.asyncio
async def test_legacy_hiring_managers_guard_was_not_widened(fx_client: AsyncClient):
    """Otwarcie `/insights` NIE MOŻE otworzyć powierzchni legacy.

    `/api/reports/hiring-managers` jest osobnym routerem z własnym, węższym
    guardem. Gdyby ktoś „uprościł" refaktor i podmienił tam bramkę na
    `CurrentUser`, zmiana przeszłaby bez śladu.
    """
    _, email, password = await _seed_user(UserRole.recruiter, "hm-legacy")
    headers = await _login(fx_client, email, password)
    resp = await fx_client.get("/api/reports/hiring-managers", headers=headers)
    assert resp.status_code == 403, resp.text


@pytest.mark.asyncio
async def test_hiring_managers_window_filters_jobs_by_creation_date(
    fx_client: AsyncClient,
):
    """Rekrutacja spoza okna nie może wejść do rankingu.

    Legacy liczy CAŁĄ historię i nie zna okresu w ogóle — to jest regresja na
    tę różnicę. Okno jest półotwarte `[start, end)`.
    """
    await cache_invalidate("insights:clients:hiring-managers:")
    year = 1600 + int(uuid.uuid4().hex[:6], 16) % 90
    inside_id, _ = await _seed_hiring_manager(
        job_created_at=datetime(year, 4, 10, tzinfo=timezone.utc)
    )
    outside_id, _ = await _seed_hiring_manager(
        job_created_at=datetime(year, 5, 2, tzinfo=timezone.utc)
    )

    _, email, password = await _seed_user(UserRole.sourcer, "hm-window")
    headers = await _login(fx_client, email, password)
    body = (
        await fx_client.get(
            HIRING_MANAGERS,
            headers=headers,
            params={
                "period": "custom",
                "date_from": f"{year}-04-01",
                "date_to": f"{year}-04-30",
                "limit": 200,
            },
        )
    ).json()

    ids = {m["contact_id"] for m in body["managers"]}
    assert inside_id in ids, body
    assert outside_id not in ids, body

    row = next(m for m in body["managers"] if m["contact_id"] == inside_id)
    assert row["jobs_total"] == 1
    assert row["jobs_open"] == 1
    assert row["position"] == "CTO"
    # Bez kontraktu: 0 z 1 rekrutacji to POLICZONE zero, nie luka.
    assert row["contract_rate_pct"] == 0.0

    # Kafle to fold po WIDOCZNEJ liście — muszą dać się sprawdzić dodając
    # kolumnę na ekranie.
    assert body["totals"]["jobs_total"] == sum(
        m["jobs_total"] for m in body["managers"]
    )
    assert body["totals"]["managers"] == len(body["managers"])
    # `contracts_active` to migawka na dziś, nie stan z końca okna — koperta
    # musi to powiedzieć, inaczej liczba czyta się jak stan historyczny.
    assert body["scope"]["contracts_active_is_snapshot_now"] is True


@pytest.mark.asyncio
async def test_hiring_managers_empty_window_gives_none_not_zero(
    fx_client: AsyncClient,
):
    """Zero rekrutacji → `open_rate_pct` = `None`, nie `0.0`.

    „Nie było czego dzielić" to co innego niż „policzone i wyszło zero" —
    na ekranie oceniającym ludzi po stronie klienta to jest różnica między
    pytaniem a werdyktem.
    """
    _, email, password = await _seed_user(UserRole.admin, "hm-zero")
    headers = await _login(fx_client, email, password)
    body = (
        await fx_client.get(
            HIRING_MANAGERS,
            headers=headers,
            params={
                "period": "custom",
                "date_from": "1803-01-01",
                "date_to": "1803-01-31",
            },
        )
    ).json()
    assert body["managers"] == []
    assert body["totals"]["jobs_total"] == 0
    assert body["totals"]["open_rate_pct"] is None
    assert body["truncated"] == 0


@pytest.mark.asyncio
async def test_hiring_managers_reports_how_many_rows_the_limit_cut(
    fx_client: AsyncClient,
):
    """Przycięta lista bez licznika czyta się jako komplet."""
    await cache_invalidate("insights:clients:hiring-managers:")
    year = 1900 + int(uuid.uuid4().hex[:6], 16) % 90
    for _ in range(3):
        await _seed_hiring_manager(
            job_created_at=datetime(year, 8, 3, tzinfo=timezone.utc)
        )

    _, email, password = await _seed_user(UserRole.admin, "hm-trunc")
    headers = await _login(fx_client, email, password)
    body = (
        await fx_client.get(
            HIRING_MANAGERS,
            headers=headers,
            params={
                "period": "custom",
                "date_from": f"{year}-08-01",
                "date_to": f"{year}-08-31",
                "limit": 2,
            },
        )
    ).json()

    assert len(body["managers"]) == 2
    assert body["truncated"] == 1


# ── Regresja: wycena musi iść kalendarzem Warszawy, nie zegarem kontenera ──


def test_valuation_date_uses_warsaw_calendar_in_the_utc_midnight_window():
    """Między północą UTC a północną warszawską obie daty się różnią.

    To jest regresja na defekt, który przez ~2 godziny KAŻDEJ doby wyceniał
    ranking BIEŻĄCEGO miesiąca ostatnim dniem miesiąca POPRZEDNIEGO — innym
    krokiem harmonogramu stawek i innym kursem NBP. Objaw był cichy: liczba
    poprawna, tylko opisująca inny dzień.

    Test przypina zegar wprost, zamiast liczyć na to, że przebieg CI trafi
    w to okno. Poprzednia wersja pilnowała tego pośrednio (przez klucz cache'u)
    i failowała wyłącznie wtedy, gdy akurat trafiła — czyli w praktyce nigdy.
    """
    from datetime import date as _date
    from datetime import datetime as _datetime
    from datetime import timezone as _timezone
    from zoneinfo import ZoneInfo as _ZoneInfo

    from app.api.insights_clients import _valuation_date
    from app.analytics.periods import resolve_period

    # 2026-08-31 22:30 UTC = 2026-09-01 00:30 w Warszawie (CEST, UTC+2).
    utc_moment = _datetime(2026, 8, 31, 22, 30, tzinfo=_timezone.utc)
    warsaw_day = utc_moment.astimezone(_ZoneInfo("Europe/Warsaw")).date()
    utc_day = utc_moment.date()

    # Założenie testu: kalendarze NAPRAWDĘ się w tej chwili różnią.
    assert warsaw_day == _date(2026, 9, 1)
    assert utc_day == _date(2026, 8, 31)

    wrzesien = resolve_period("month", now=utc_moment)
    sierpien = resolve_period("month", offset=-1, now=utc_moment)

    # Bieżący (wrzesień) wycenia się DNIEM WARSZAWSKIM, nie ostatnim dniem
    # sierpnia — inaczej wrześniowy ranking niesie sierpniowe stawki.
    assert _valuation_date(wrzesien, today=warsaw_day) == _date(2026, 9, 1)

    # Poprzedni (sierpień) wycenia się swoim ostatnim dniem.
    assert _valuation_date(sierpien, today=warsaw_day) == _date(2026, 8, 31)

    # I przede wszystkim: dwa różne okna NIE MOGĄ dzielić daty wyceny.
    assert _valuation_date(wrzesien, today=warsaw_day) != _valuation_date(
        sierpien, today=warsaw_day
    )


def test_valuation_date_with_utc_clock_would_collapse_both_windows():
    """Dowód, że defekt był realny, a nie teoretyczny.

    Gdyby „dziś" brać z zegara kontenera (UTC), obie daty wyceny zlewają się
    w jedną — i właśnie dlatego ten test przypina zegar zamiast go czytać.
    """
    from datetime import date as _date
    from datetime import datetime as _datetime
    from datetime import timezone as _timezone

    from app.api.insights_clients import _valuation_date
    from app.analytics.periods import resolve_period

    utc_moment = _datetime(2026, 8, 31, 22, 30, tzinfo=_timezone.utc)
    utc_day = utc_moment.date()  # 2026-08-31 — o dzień z tyłu

    wrzesien = resolve_period("month", now=utc_moment)
    sierpien = resolve_period("month", offset=-1, now=utc_moment)

    assert _valuation_date(wrzesien, today=utc_day) == _date(2026, 8, 31)
    assert _valuation_date(sierpien, today=utc_day) == _date(2026, 8, 31)
    assert _valuation_date(wrzesien, today=utc_day) == _valuation_date(
        sierpien, today=utc_day
    )


def test_valuation_date_defaults_to_the_warsaw_business_day():
    """Bez wstrzyknięcia MUSI pytać `business_today()`, nie `date.today()`.

    Strażnik na wypadek, gdyby ktoś „uprościł" wywołanie z powrotem do zegara
    systemowego — wtedy oba testy wyżej dalej by przechodziły, bo wstrzykują
    datę jawnie, a produkcja znów kłamałaby przez dwie godziny na dobę.
    """
    import ast
    import inspect
    import textwrap

    from app.api import insights_clients

    # Docstring tej funkcji CYTUJE `date.today()`, żeby wytłumaczyć defekt,
    # więc surowy `getsource` zawsze by go zawierał. Patrzymy na samo CIAŁO.
    tree = ast.parse(
        textwrap.dedent(inspect.getsource(insights_clients._valuation_date))
    )
    fn = tree.body[0]
    body = fn.body[1:] if ast.get_docstring(fn) else fn.body
    code = "\n".join(ast.unparse(node) for node in body)

    assert "business_today()" in code
    assert "date.today()" not in code
