"""GET /api/insights/charts/* — statystyki roczne i analiza placementów.

Każdy test broni jednego konkretnego defektu, a nie „że endpoint działa":

1. **RBAC (D7)** — obie trasy widzi KAŻDA zalogowana rola, ale nie anonim.
2. **Okno półotwarte [start, end)** — placement z 1 stycznia następnego roku
   nie może wpaść do grudnia, a kubełek miesiąca liczy się czasem WARSZAWSKIM
   (ruch z 31.12 22:00 UTC to już styczeń w Warszawie).
3. **Placement = D2** — dwa wiersze `hired` dla tej samej pary (kandydat,
   oferta) liczą się RAZ. `candidate_stages` nie ma tam unikalności, a import
   Traffita dopisuje wiersz na każde zdarzenie.
4. **Zerowy mianownik → `null`, nigdy `0.0`** — „nie da się policzyć" i
   „policzone, wyszło zero" to dwa różne zdania, a na wykresie zero rysuje
   linię spadającą do podłogi.
5. **Konwersja NIE jest przycinana do 100%** — wynik ponad sto procent jest
   sygnałem o kolejności etapów w danych z importu i ma być widoczny.
6. **Miesiąc, który się nie zaczął, NIE MA wiersza** — zero za przyszłość
   czyta się jak zapaść zespołu.
7. **Donut sumuje się do kafla nad sobą** — placement bez atrybucji i bez
   klienta zostaje w rozbiciu (jako nazwany koszyk), a nie znika po cichu.
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
from app.models.job import Job, JobStatus, RemotePolicy
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.models.user import User, UserRole

YEARLY_URL = "/api/insights/charts/yearly-stats"
PLACEMENTS_URL = "/api/insights/charts/placement-analysis"

# Ten plik zajmuje TRZY KOLEJNE lata i wszystkie trzy muszą być wolne — także
# ten, w którym nic nie siejemy, bo to na nim stoi jedyna asercja „ma być zero".
# Baza testowa jest wspólna dla całego przebiegu i NIE jest czyszczona, więc
# rok użyty przez sąsiedni plik wraca tu jako „regresja" w kodzie, którym nikt
# nie ruszał (pierwsze podejście stało na 2009-2011: 2010 zajmuje
# `test_backfill_candidate_experience.py` i `test_candidates_position_filters.py`,
# 2011 — `test_insights_campaigns.py` i `test_insights_delivery_leads.py`).
#
# Zanim zmienisz te lata, sprawdź, co jest zajęte:
#   grep -rhoE 'datetime\((1[89][0-9]{2}|20[0-9]{2})|date\((1[89][0-9]{2}|20[0-9]{2})|"(1[89][0-9]{2}|20[0-9]{2})-' backend/tests/ \
#     | grep -oE '(1[89][0-9]{2}|20[0-9]{2})' | sort -u
TEST_YEAR = 2003

# Rok, w którym ten plik sieje weryfikacje/rekomendacje (test konwersji), oraz
# rok, w którym NIE sieje NIC — ten drugi jest jedynym miejscem, gdzie „zero"
# wolno asertować wprost.
RATIO_YEAR = TEST_YEAR + 1
NULL_YEAR = TEST_YEAR + 2


def _ensure_charts_router_mounted(app) -> None:
    """Zamontuj router, jeśli integrator jeszcze tego nie zrobił.

    Właścicielem `app/main.py` jest integrator, a ten plik powstaje równolegle
    z jego montażem. Warunek staje się no-opem w chwili, gdy montaż wejdzie do
    `main.py` — dzięki temu testy mierzą realny router pod DOCELOWYM URL-em,
    zamiast czekać na cudzy commit.
    """
    if any(getattr(r, "path", None) == YEARLY_URL for r in app.routes):
        return
    from app.api import insights_charts

    app.include_router(
        insights_charts.router, prefix="/api/insights/charts", tags=["insights"]
    )


@pytest_asyncio.fixture
async def charts_client() -> AsyncClient:
    from app.core.rate_limit import limiter as _limiter
    from app.main import app

    _ensure_charts_router_mounted(app)
    _limiter.enabled = False
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=True),
        base_url="http://testserver",
    ) as c:
        yield c


async def _seed_user(role: UserRole, label: str) -> tuple[int, str, str]:
    unique = uuid.uuid4().hex[:8]
    email = f"charts-{label}-{role.value}-{unique}@example.com"
    password = f"T3st_{unique}!Charts"
    async with AsyncSessionLocal() as db:
        u = User(
            email=email,
            name=f"Charts {label} {unique}",
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


async def _seed_job_candidate(client_id: int | None = None) -> tuple[int, int, int]:
    """Trójka Klient/Oferta/Kandydat.

    ``client_id`` pozwala powiesić dwie oferty na TYM SAMYM kliencie — bez tego
    nie da się sprawdzić, że donut klientów agreguje po kliencie, a nie po
    ofercie. `jobs.client_id` jest NOT NULL od migracji 0120, więc oferty bez
    klienta zasiać się nie da i ta ścieżka jest testowana jako niemożliwa,
    a nie jako scenariusz.
    """
    async with AsyncSessionLocal() as db:
        if client_id is None:
            cli = Client(name=f"ChartsCli-{uuid.uuid4().hex[:6]}")
            db.add(cli)
            await db.commit()
            await db.refresh(cli)
            client_id = cli.id
        job = Job(
            title=f"Charts {uuid.uuid4().hex[:6]}",
            location="Warszawa",
            status=JobStatus.published,
            remote_policy=RemotePolicy.hybrid,
            client_id=client_id,
        )
        cand = Candidate(
            name=f"Ch-{uuid.uuid4().hex[:4]}",
            lastname=f"Arts-{uuid.uuid4().hex[:4]}",
            email=f"charts-{uuid.uuid4().hex[:8]}@example.com",
        )
        db.add_all([job, cand])
        await db.commit()
        await db.refresh(job)
        await db.refresh(cand)
        return client_id, job.id, cand.id


async def _seed_stage(
    candidate_id: int,
    job_id: int,
    stage: PipelineStage,
    moved_at: datetime,
    moved_by: int | None = None,
) -> None:
    async with AsyncSessionLocal() as db:
        db.add(
            CandidateStage(
                candidate_id=candidate_id,
                job_id=job_id,
                stage=stage,
                moved_at=moved_at,
                moved_by=moved_by,
                external_source="manual",
            )
        )
        await db.commit()


async def _yearly(
    client: AsyncClient, headers: dict[str, str], year: int = TEST_YEAR
) -> dict:
    # Klucz cache'u niesie okno, ale ten sam test woła ten sam rok dwa razy
    # (przed i po zasianiu danych) — bez unieważnienia drugi odczyt zwróciłby
    # pierwszą odpowiedź i test przechodziłby także dla zepsutego liczenia.
    await cache_invalidate("insights:charts:")
    resp = await client.get(YEARLY_URL, headers=headers, params={"year": year})
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _placements(
    client: AsyncClient, headers: dict[str, str], params: dict
) -> dict:
    await cache_invalidate("insights:charts:")
    resp = await client.get(PLACEMENTS_URL, headers=headers, params=params)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _month(payload: dict, month: str) -> dict:
    for row in payload["months"]:
        if row["month"] == month:
            return row
    raise AssertionError(
        f"brak miesiąca {month} w {[r['month'] for r in payload['months']]}"
    )


@pytest.mark.asyncio
async def test_both_charts_are_reachable_for_every_logged_in_role(
    charts_client: AsyncClient,
):
    """D7: wykresy widzi KAŻDA zalogowana rola.

    `finance` i `sourcer` to dwa końce spektrum uprawnień, a legacy `user` jest
    wycofywany — gdyby guard rolowy wrócił tu cichym refaktorem, najpierw
    odbiłby się któryś z tych trzech.
    """
    for role in (
        UserRole.admin,
        UserRole.sourcer,
        UserRole.finance,
        UserRole.recruiter,
        UserRole.user,
    ):
        _, email, password = await _seed_user(role, "rbac")
        headers = await _login(charts_client, email, password)
        for url in (YEARLY_URL, PLACEMENTS_URL):
            resp = await charts_client.get(url, headers=headers)
            assert resp.status_code == 200, f"{role.value} {url}: {resp.text}"


@pytest.mark.asyncio
async def test_charts_require_authentication(charts_client: AsyncClient):
    """„Wszyscy" znaczy „każdy ZALOGOWANY", nie „każdy z internetu"."""
    for url in (YEARLY_URL, PLACEMENTS_URL):
        resp = await charts_client.get(url)
        assert resp.status_code in (401, 403), url


@pytest.mark.asyncio
async def test_year_window_is_half_open_and_buckets_by_warsaw_month(
    charts_client: AsyncClient,
):
    """Ruch z 1 stycznia następnego roku nie może wpaść do grudnia.

    Drugi wiersz (31.12 23:30 UTC) to regresja na strefie: w Warszawie jest
    już 1 stycznia, więc kubełkowanie po UTC wrzuciłoby go do grudnia — i rok
    zamknąłby się liczbą, której nie da się odtworzyć z kalendarza.
    """
    _, email, password = await _seed_user(UserRole.admin, "halfopen")
    headers = await _login(charts_client, email, password)

    before = await _yearly(charts_client, headers)
    assert before["period"]["start"].startswith(f"{TEST_YEAR}-01-01")
    assert before["period"]["end"].startswith(f"{TEST_YEAR + 1}-01-01")
    baseline = _month(before, f"{TEST_YEAR}-12-01")["hired"]

    _, job_in, cand_in = await _seed_job_candidate()
    await _seed_stage(
        cand_in,
        job_in,
        PipelineStage.hired,
        datetime(TEST_YEAR, 12, 15, 12, tzinfo=timezone.utc),
    )
    # 31.12 23:30 UTC = 1 stycznia 00:30 w Warszawie → następny rok.
    _, job_tz, cand_tz = await _seed_job_candidate()
    await _seed_stage(
        cand_tz,
        job_tz,
        PipelineStage.hired,
        datetime(TEST_YEAR, 12, 31, 23, 30, tzinfo=timezone.utc),
    )
    # 1 stycznia następnego roku — poza oknem [start, end).
    _, job_out, cand_out = await _seed_job_candidate()
    await _seed_stage(
        cand_out,
        job_out,
        PipelineStage.hired,
        datetime(TEST_YEAR + 1, 1, 5, 12, tzinfo=timezone.utc),
    )

    after = await _yearly(charts_client, headers)
    assert _month(after, f"{TEST_YEAR}-12-01")["hired"] == baseline + 1, (
        "grudzień wchłonął ruch spoza okna albo ruch, który w Warszawie "
        "należy już do stycznia"
    )


@pytest.mark.asyncio
async def test_repeated_hired_for_the_same_pair_counts_once(
    charts_client: AsyncClient,
):
    """D2: placement to PIERWSZE `hired` pary (kandydat, oferta).

    `candidate_stages` nie ma UNIQUE na (candidate_id, job_id, stage), a import
    Traffita dopisuje wiersz na każde zdarzenie — liczenie surowych wierszy
    podwoiłoby powrót kandydata na etap.
    """
    _, email, password = await _seed_user(UserRole.admin, "d2")
    headers = await _login(charts_client, email, password)

    before = await _yearly(charts_client, headers)
    baseline = _month(before, f"{TEST_YEAR}-05-01")["hired"]

    _, job_id, cand_id = await _seed_job_candidate()
    await _seed_stage(
        cand_id,
        job_id,
        PipelineStage.hired,
        datetime(TEST_YEAR, 5, 10, 9, tzinfo=timezone.utc),
    )
    await _seed_stage(
        cand_id,
        job_id,
        PipelineStage.hired,
        datetime(TEST_YEAR, 5, 20, 9, tzinfo=timezone.utc),
    )

    after = await _yearly(charts_client, headers)
    assert _month(after, f"{TEST_YEAR}-05-01")["hired"] == baseline + 1


@pytest.mark.asyncio
async def test_conversion_is_null_without_denominator_and_is_not_capped(
    charts_client: AsyncClient,
):
    """Dwie reguły naraz, bo obie dotyczą tej samej liczby.

    Pusty miesiąc: `null` (luka na wykresie), NIGDY `0.0` — zero rysuje linię
    spadającą do podłogi i czyta się jak „konwersja padła".

    Miesiąc, w którym rekomendacji jest więcej niż weryfikacji: ponad 100%,
    nie równe sto — sufit schowałby fakt, że kolejność etapów w danych się
    nie trzyma.

    Obie asercje są liczone WZGLĘDEM stanu zastanego, a nie od zera: testowa
    baza NIE jest czyszczona między biegami, więc miesiąc zasiany poprzednim
    uruchomieniem tego samego pliku zostaje w niej na zawsze. Test pisany na
    twarde „ma być 1" przechodzi dokładnie raz w życiu bazy, a potem wygląda
    jak regresja kodu, którym nikt nie ruszył.
    """
    _, email, password = await _seed_user(UserRole.admin, "ratio")
    headers = await _login(charts_client, email, password)

    # Rok, w którym ten plik NIGDY nie sieje — dlatego luka zostaje luką także
    # przy dziesiątym uruchomieniu.
    empty = await _yearly(charts_client, headers, year=NULL_YEAR)
    july = _month(empty, f"{NULL_YEAR}-07-01")
    assert july["verified"] == 0, (
        f"rok {NULL_YEAR} miał być pusty — testowa baza jest zanieczyszczona"
    )
    assert july["conv_verified_to_cv_sent"] is None, (
        "zerowy mianownik dał 0.0 zamiast luki"
    )

    before = _month(
        await _yearly(charts_client, headers, year=RATIO_YEAR),
        f"{RATIO_YEAR}-07-01",
    )
    when = datetime(RATIO_YEAR, 7, 12, 10, tzinfo=timezone.utc)

    _, job_v, cand_v = await _seed_job_candidate()
    await _seed_stage(cand_v, job_v, PipelineStage.verified, when)
    verified_after = int(before["verified"]) + 1

    # Tyle rekomendacji, żeby licznik PRZEBIŁ mianownik niezależnie od tego,
    # co poprzednie biegi zostawiły w tym miesiącu.
    needed = max(verified_after + 1 - int(before["cv_sent"]), 1)
    for _ in range(needed):
        _, job_c, cand_c = await _seed_job_candidate()
        await _seed_stage(cand_c, job_c, PipelineStage.cv_sent, when)

    after = await _yearly(charts_client, headers, year=RATIO_YEAR)
    row = _month(after, f"{RATIO_YEAR}-07-01")
    assert row["verified"] == verified_after
    assert row["cv_sent"] > row["verified"], "zasiew nie dał przewagi licznika"
    assert row["conv_verified_to_cv_sent"] > 100.0, (
        "konwersja została przycięta do 100% — sygnał o jakości danych zniknął"
    )
    assert row["conv_verified_to_cv_sent"] == round(
        row["cv_sent"] / row["verified"] * 100, 1
    )


@pytest.mark.asyncio
async def test_future_months_have_no_row(charts_client: AsyncClient):
    """Miesiąc, który się jeszcze nie zaczął, nie dostaje zera.

    Rok w całości przyszły nie ma ANI JEDNEGO punktu — gdyby dostał dwanaście
    zer, wykres twierdziłby, że zespół przez rok nic nie zrobił.
    """
    _, email, password = await _seed_user(UserRole.admin, "future")
    headers = await _login(charts_client, email, password)

    future = await _yearly(charts_client, headers, year=2099)
    assert future["months"] == []

    past = await _yearly(charts_client, headers, year=TEST_YEAR)
    assert len(past["months"]) == 12
    assert all(row["is_partial"] is False for row in past["months"])


@pytest.mark.asyncio
async def test_placement_analysis_donuts_sum_to_the_tile_above_them(
    charts_client: AsyncClient,
):
    """Placement bez atrybucji i bez klienta ZOSTAJE w rozbiciu.

    Import Traffita zostawia `moved_by` puste dla ruchu sprzed NEXUSA, a oferta
    bywa bez klienta. Wycięcie takich wierszy z donuta zostawiłoby wykres,
    który nie sumuje się do liczby nad sobą — czyta się to jak błąd
    zaokrąglenia, a jest utratą wiersza. Kafel „Osoby" liczy jednak WYŁĄCZNIE
    atrybuowane wiersze: „(nieprzypisane)" to nie jest osoba.
    """
    user_id, _, _ = await _seed_user(UserRole.recruiter, "donut")
    _, admin_email, admin_password = await _seed_user(UserRole.admin, "donutadm")
    headers = await _login(charts_client, admin_email, admin_password)
    window = {
        "period": "custom",
        "date_from": f"{TEST_YEAR}-08-01",
        "date_to": f"{TEST_YEAR}-08-31",
    }

    before = await _placements(charts_client, headers, window)
    base_total = before["totals"]["placements"]
    base_people = before["totals"]["people"]
    base_clients = before["totals"]["clients"]

    when = datetime(TEST_YEAR, 8, 12, 10, tzinfo=timezone.utc)
    client_id, job_named, cand_named = await _seed_job_candidate()
    await _seed_stage(cand_named, job_named, PipelineStage.hired, when, user_id)
    # Drugi placement u TEGO SAMEGO klienta, ale bez atrybucji — tak wygląda
    # ruch zaimportowany z Traffita, czyli większość bazy.
    _, job_import, cand_import = await _seed_job_candidate(client_id=client_id)
    await _seed_stage(cand_import, job_import, PipelineStage.hired, when, None)

    after = await _placements(charts_client, headers, window)
    totals = after["totals"]
    assert totals["placements"] == base_total + 2
    assert totals["people"] == base_people + 1, (
        "wiersz bez atrybucji policzył się jako osoba"
    )
    # Dwie oferty, jeden klient — rozbicie agreguje po kliencie, nie po ofercie.
    assert totals["clients"] == base_clients + 1

    assert sum(p["placements"] for p in after["by_person"]) == totals["placements"]
    assert sum(c["placements"] for c in after["by_client"]) == totals["placements"]

    unattributed = [p for p in after["by_person"] if not p["attributed"]]
    assert unattributed and unattributed[0]["name"] == "(nieprzypisane)"
    assert totals["unattributed_placements"] >= 1
    assert totals["placements_without_job"] == 0

    named = [p for p in after["by_person"] if p["user_id"] == user_id]
    assert named and named[0]["placements"] == 1
    assert named[0]["share_pct"] is not None

    mine = [c for c in after["by_client"] if c["client_id"] == client_id]
    assert mine and mine[0]["placements"] == 2


@pytest.mark.asyncio
async def test_placement_analysis_shares_are_null_on_an_empty_window(
    charts_client: AsyncClient,
):
    """Puste okno to pusta lista, a nie zera udziałów.

    Zero procent przy zerowym mianowniku byłoby werdyktem („nikt nic nie ma")
    zamiast informacją o braku danych.
    """
    _, email, password = await _seed_user(UserRole.admin, "empty")
    headers = await _login(charts_client, email, password)
    body = await _placements(
        charts_client,
        headers,
        # Okno sprzed epoki danych — testowa baza nie jest czyszczona między
        # biegami i jest współdzielona z innymi plikami, więc „byle stary rok"
        # nie wystarcza (2007 ma już 15 placementów z cudzego zasiewu).
        {"period": "custom", "date_from": "1901-02-01", "date_to": "1901-02-28"},
    )
    assert body["totals"]["placements"] == 0, (
        "okno 1901 przestało być puste — testowa baza jest zanieczyszczona"
    )
    assert body["by_person"] == []
    assert body["by_client"] == []


@pytest.mark.asyncio
async def test_invalid_period_is_422_not_500(charts_client: AsyncClient):
    """Błędny zakres wraca jako 422 z komunikatem, nie jako awaria."""
    _, email, password = await _seed_user(UserRole.admin, "badperiod")
    headers = await _login(charts_client, email, password)
    resp = await charts_client.get(
        PLACEMENTS_URL, headers=headers, params={"period": "custom"}
    )
    assert resp.status_code == 422, resp.text
