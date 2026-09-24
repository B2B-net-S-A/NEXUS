"""GET /api/insights/board/yoy — tabele rok-do-roku kokpitu Rady.

Każdy test broni jednej decyzji, a nie „że endpoint działa":

1. **Miesiąc przyszły to `null`, nie zero.** „Nie wydarzył się" i „wyszło zero"
   to dwie różne odpowiedzi, a w tabeli rocznej różnica jest widoczna
   natychmiast: dwanaście zer w kolumnie bieżącego roku czyta się jak awaria
   systemu. Miesiąc BIEŻĄCY wraca z realną, ale niepełną wartością i musi być
   wskazany — bez tego siedem dni danych czyta się jak załamanie.
2. **Każda metryka niesie `aggregate`.** Bez tego widok potrzebuje własnej
   listy „co się sumuje, a co uśrednia" — czyli drugiego lustra tej wiedzy.
   W DynaReporterze tego pola nie było i wiersz „Suma" pod kolumną procentów
   pokazywał 874%.
3. **Rezygnacje są PODZBIOREM zejść** i liczą się w miesiącu faktycznego
   rozstania (`terminated_at`), nie w pierwotnym terminie umowy.
4. **Marża na godzinę wyklucza ryczałt z LICZNIKA i MIANOWNIKA naraz.**
   Wzięcie pełnej marży i podzielenie jej przez godziny części kontraktów
   zawyżałoby wskaźnik tym bardziej, im więcej jest ryczałtów.
5. **Rozbicie na klientów sumuje się do liczby placementów** — łącznie
   z placementami bez przypisanego klienta. Wiersz, który nie domyka się do
   wiersza wyżej, jest gorszy niż jego brak.
6. **Pieniądze liczy TA SAMA funkcja co kafle** — nie kopia. Kafel „Marża / mc"
   i komórka „Marża" w tabeli obok muszą pochodzić z jednego miejsca.
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
from app.models.contract import (
    Contract,
    ContractStatus,
    ContractTerminationReason,
    RateUnit,
)
from app.models.job import Job, JobStatus, RemotePolicy
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.models.user import User, UserRole
from app.core.scheduling import business_today

YOY_URL = "/api/insights/board/yoy"

# Rok bazowy testu. Dwa warunki naraz, i pierwsze podejście spełniało tylko
# jeden z nich:
#
# 1. **Musi być WOLNY od fixture'ów innych plików.** Baza testowa jest wspólna
#    dla przebiegu i NIE jest czyszczona, więc rok zajęty przez sąsiedni plik
#    wraca jako „regresja" w kodzie, którym nikt nie ruszał.
# 2. **Musi przejść walidację endpointu** (`end_year >= 2000`). Rok 1976
#    spełniał warunek pierwszy i łamał drugi — osiem testów dostawało 422
#    zamiast danych. Bramka w endpointcie jest sanity-checkiem produkcyjnym
#    i to TEST się do niej dostosowuje, nie odwrotnie.
#
# Testy sięgają w dół do `BASE_YEAR - 2`, a `years=2` dokłada jeszcze jeden rok
# wstecz — potrzebne są więc cztery kolejne wolne lata (2005–2008).
BASE_YEAR = 2008


@pytest_asyncio.fixture
async def yoy_client() -> AsyncClient:
    from app.core.rate_limit import limiter as _limiter
    from app.main import app

    _limiter.enabled = False
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=True),
        base_url="http://testserver",
    ) as c:
        yield c


async def _seed_user(role: UserRole) -> tuple[str, str]:
    unique = uuid.uuid4().hex[:8]
    email = f"yoy-{role.value}-{unique}@example.com"
    password = f"T3st_{unique}!Yoy"
    async with AsyncSessionLocal() as db:
        db.add(
            User(
                email=email,
                name=f"Yoy {unique}",
                password_hash=hash_password(password),
                role=role,
                is_active=True,
                profile_completed=True,
            )
        )
        await db.commit()
    return email, password


async def _login(client: AsyncClient, email: str, password: str) -> dict:
    resp = await client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _seed_client_job_candidate(client_name: str | None = None) -> tuple:
    async with AsyncSessionLocal() as db:
        cli = Client(name=client_name or f"YoyCli-{uuid.uuid4().hex[:6]}")
        db.add(cli)
        await db.commit()
        await db.refresh(cli)
        job = Job(
            title=f"Yoy {uuid.uuid4().hex[:6]}",
            location="Warszawa",
            status=JobStatus.published,
            remote_policy=RemotePolicy.hybrid,
            client_id=cli.id,
        )
        cand = Candidate(
            name=f"Yo-{uuid.uuid4().hex[:4]}",
            lastname=f"Y-{uuid.uuid4().hex[:4]}",
            email=f"yoy-{uuid.uuid4().hex[:8]}@example.com",
        )
        db.add_all([job, cand])
        await db.commit()
        await db.refresh(job)
        await db.refresh(cand)
        return cli.id, job.id, cand.id


async def _seed_hire(candidate_id: int, job_id: int, when: datetime) -> None:
    async with AsyncSessionLocal() as db:
        db.add(
            CandidateStage(
                candidate_id=candidate_id,
                job_id=job_id,
                stage=PipelineStage.hired,
                moved_at=when,
                external_source="manual",
            )
        )
        await db.commit()


async def _seed_contract(
    *,
    client_id: int,
    candidate_id: int,
    start: date,
    end: date | None,
    rate_client: Decimal,
    rate_candidate: Decimal,
    unit: RateUnit = RateUnit.monthly,
    status: ContractStatus = ContractStatus.active,
    terminated_at: date | None = None,
    reason: ContractTerminationReason | None = None,
    billing_hours: int | None = None,
) -> int:
    async with AsyncSessionLocal() as db:
        contract = Contract(
            candidate_id=candidate_id,
            client_id=client_id,
            start_date=start,
            end_date=end,
            rate_client=rate_client,
            rate_candidate=rate_candidate,
            rate_unit=unit,
            rate_client_currency="PLN",
            rate_candidate_currency="PLN",
            currency="PLN",
            status=status,
            terminated_at=terminated_at,
            termination_reason=reason,
        )
        if billing_hours is not None:
            contract.billing_hours_per_month = billing_hours
        db.add(contract)
        await db.commit()
        await db.refresh(contract)
        return contract.id


async def _yoy(client: AsyncClient, headers: dict, **params) -> dict:
    # Klucz cache'u niesie lata i dzień, ale ten sam test woła te same lata
    # dwa razy (przed i po zasianiu) — bez unieważnienia drugi odczyt zwróciłby
    # pierwszą odpowiedź i test przechodziłby także dla zepsutego liczenia.
    await cache_invalidate("insights:board:yoy:")
    resp = await client.get(YOY_URL, headers=headers, params=params)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _metric(payload: dict, key: str) -> dict:
    found = [m for m in payload["metrics"] if m["key"] == key]
    assert found, f"brak metryki {key} w odpowiedzi"
    return found[0]


# ── 1. Przyszłość to null, teraźniejszość jest oznaczona ────────────────────


@pytest.mark.asyncio
async def test_future_months_are_null_and_the_running_month_is_flagged(
    yoy_client: AsyncClient,
):
    """Pusty miesiąc przyszły nie może udawać zera.

    Zera w kolumnie bieżącego roku czytają się jak awaria systemu, a nie jak
    „grudzień jeszcze nie nadszedł". Miesiąc trwający musi być wskazany —
    inaczej jego niepełna wartość czyta się jako załamanie wyniku.
    """
    email, password = await _seed_user(UserRole.admin)
    headers = await _login(yoy_client, email, password)
    today = business_today()

    payload = await _yoy(yoy_client, headers)

    assert payload["years"][-1] == today.year
    # OSTATNIEGO dnia miesiąca `partial_month` jest puste i tak ma być: dzień
    # wyceny równa się wtedy ostatniemu dniowi, więc miesiąc nie jest już
    # „w trakcie". Test asertuje KONTRAKT (jeśli pole jest, wskazuje miesiąc
    # bieżący), a nie kalendarz dnia, w którym akurat leci CI — inaczej byłby
    # zielony przez 11 miesięcy w roku i czerwony 30 września.
    partial = payload["partial_month"]
    if partial is not None:
        assert partial == {"year": today.year, "month": today.month}

    for metric in payload["metrics"]:
        current = metric["series"][str(today.year)]
        assert len(current) == 12
        # Miesiące PO bieżącym nie wydarzyły się — muszą być puste.
        for month_idx in range(today.month, 12):
            assert current[month_idx] is None, (
                f"{metric['key']}: miesiąc {month_idx + 1} jest w przyszłości, "
                "a nie jest `null`"
            )


@pytest.mark.asyncio
async def test_a_closed_year_has_no_null_holes_in_flow_metrics(
    yoy_client: AsyncClient,
):
    """Zamknięty rok ma dwanaście POLICZONYCH miesięcy, także pustych.

    Przepływ bez zdarzeń to zero, nie brak danych — inaczej pusty miesiąc
    historyczny byłby nieodróżnialny od miesiąca, który jeszcze nie nastąpił.
    """
    email, password = await _seed_user(UserRole.admin)
    headers = await _login(yoy_client, email, password)

    payload = await _yoy(yoy_client, headers, end_year=BASE_YEAR, years=2)

    for key in ("placements", "departures", "resignations"):
        for year in payload["years"]:
            series = _metric(payload, key)["series"][str(year)]
            assert all(v is not None for v in series), (
                f"{key}/{year}: zamknięty rok nie może mieć dziur"
            )


# ── 2. Instrukcja czytania jedzie z liczbami ────────────────────────────────


@pytest.mark.asyncio
async def test_every_metric_declares_how_to_aggregate_it(yoy_client: AsyncClient):
    """`aggregate` istnieje po to, żeby nie powtórzyć „Suma 874%".

    Stan (MRR, liczba konsultantów) uśrednia się przez rok; przepływ
    (placementy, zejścia) sumuje. Wskaźniki NIE sumują się i NIE uśredniają —
    liczą się od nowa jako Σlicznik / Σmianownik (audyt 18.09.2026: średnia
    miesięcznych procentów dawała hit ratio 16,58% zamiast 14,5% i odwracała
    werdykt roku). Liczność zbioru nie powstaje z miesięcy żadnym działaniem.
    """
    email, password = await _seed_user(UserRole.admin)
    headers = await _login(yoy_client, email, password)
    payload = await _yoy(yoy_client, headers, end_year=BASE_YEAR, years=2)

    expected = {
        "revenue_monthly_pln": "avg",
        "consultant_cost_monthly_pln": "avg",
        "margin_monthly_pln": "avg",
        "consultants": "avg",
        "departures": "sum",
        "resignations": "sum",
        "placements": "sum",
        "margin_pct": "ratio",
        "top_client_share_pct": "ratio",
        "hit_ratio_pct": "ratio",
        "margin_per_hour_pln": "ratio",
        "unique_clients": "distinct",
    }
    for key, aggregate in expected.items():
        assert _metric(payload, key)["aggregate"] == aggregate, key

    # Żaden wskaźnik procentowy nie może być sumowalny ani uśredniany — to jest
    # dokładnie ta pomyłka, która dała 874% w kolumnie „udział top klienta"
    # i +2,0 pp „Lepiej" tam, gdzie prawda brzmiała −2,9 pp „Gorzej".
    for metric in payload["metrics"]:
        if metric["unit"] == "pct":
            assert metric["aggregate"] == "ratio", metric["key"]


@pytest.mark.asyncio
async def test_every_ratio_metric_ships_its_numerator_and_denominator(
    yoy_client: AsyncClient,
):
    """Wskaźnik bez składowych nie ma jak zostać policzony za rok.

    Widok NIE ma własnej listy „co dzielić przez co" — gdyby ją miał, byłaby
    drugim lustrem tej wiedzy i rozjechałaby się przy pierwszej nowej metryce.
    Dlatego brak serii składowej to błąd kontraktu, nie brak danych.
    """
    email, password = await _seed_user(UserRole.admin)
    headers = await _login(yoy_client, email, password)
    payload = await _yoy(yoy_client, headers, end_year=BASE_YEAR, years=2)

    component_series = payload["component_series"]
    years = [str(y) for y in payload["years"]]
    for metric in payload["metrics"]:
        if metric["aggregate"] != "ratio":
            continue
        components = metric["components"]
        assert components is not None, metric["key"]
        for role in ("numerator", "denominator"):
            key = components[role]
            assert key in component_series, f"{metric['key']}.{role} = {key}"
            for year in years:
                assert len(component_series[key][year]) == 12, key

    for metric in payload["metrics"]:
        if metric["aggregate"] != "distinct":
            continue
        assert metric["yearly"] is not None, metric["key"]
        assert set(metric["yearly"]) == set(years), metric["key"]


@pytest.mark.asyncio
async def test_unique_clients_year_is_a_set_not_an_average_of_months(
    yoy_client: AsyncClient,
):
    """Klient obsłużony w marcu i w lipcu to JEDEN klient.

    Na produkcji ta metryka pokazywała 4,33 / 6,75 / 8,63 przy realnych
    18 / 23 / 25 — czyli średnią miesięcznych liczności zbioru.
    """
    email, password = await _seed_user(UserRole.admin)
    headers = await _login(yoy_client, email, password)
    payload = await _yoy(yoy_client, headers, end_year=BASE_YEAR, years=2)

    metric = _metric(payload, "unique_clients")
    for year, months in metric["series"].items():
        counted = [m for m in months if m is not None]
        if not counted:
            continue
        yearly = metric["yearly"][year]
        assert yearly is not None
        # Rok nie może być mniejszy niż najlepszy miesiąc ani większy niż suma
        # miesięcy: pierwsze znaczyłoby, że klient zniknął, drugie — że tego
        # samego klienta policzono dwa razy.
        assert yearly >= max(counted)
        assert yearly <= sum(counted)


@pytest.mark.asyncio
async def test_metrics_that_are_bad_when_they_grow_say_so(yoy_client: AsyncClient):
    """`lower_is_better` rządzi kolumną „Ocena".

    Bez tej flagi wzrost zejść i kosztów dostałby zieloną strzałkę w górę,
    czyli komunikat odwrotny do prawdy.
    """
    email, password = await _seed_user(UserRole.admin)
    headers = await _login(yoy_client, email, password)
    payload = await _yoy(yoy_client, headers, end_year=BASE_YEAR, years=2)

    for key in (
        "departures",
        "resignations",
        "consultant_cost_monthly_pln",
        "top_client_share_pct",
    ):
        assert _metric(payload, key)["lower_is_better"] is True, key
    for key in ("placements", "margin_monthly_pln", "consultants", "hit_ratio_pct"):
        assert _metric(payload, key)["lower_is_better"] is False, key


# ── 3. Zejścia i rezygnacje ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_resignations_are_a_subset_of_departures_dated_by_actual_parting(
    yoy_client: AsyncClient,
):
    """Rezygnacja liczy się w miesiącu ROZSTANIA, nie w pierwotnym terminie.

    Kontrakt wypowiedziany w marcu, z umową do grudnia, jest zejściem marcowym.
    Data zejścia to `COALESCE(terminated_at, end_date)` — ta sama definicja,
    której używa `contract_analytics.termination_analysis`.
    """
    email, password = await _seed_user(UserRole.admin)
    headers = await _login(yoy_client, email, password)
    client_id, _job_id, cand_a = await _seed_client_job_candidate()
    _c2, _j2, cand_b = await _seed_client_job_candidate()

    # Rezygnacja: rozstanie w MARCU, choć umowa biegła do grudnia.
    await _seed_contract(
        client_id=client_id,
        candidate_id=cand_a,
        start=date(BASE_YEAR, 1, 1),
        end=date(BASE_YEAR, 3, 20),
        terminated_at=date(BASE_YEAR, 3, 20),
        reason=ContractTerminationReason.consultant_resigned,
        status=ContractStatus.ended,
        rate_client=Decimal("20000"),
        rate_candidate=Decimal("15000"),
    )
    # Zejście, które rezygnacją NIE jest — projekt się skończył.
    await _seed_contract(
        client_id=client_id,
        candidate_id=cand_b,
        start=date(BASE_YEAR, 1, 1),
        end=date(BASE_YEAR, 3, 31),
        terminated_at=date(BASE_YEAR, 3, 31),
        reason=ContractTerminationReason.project_ended,
        status=ContractStatus.ended,
        rate_client=Decimal("20000"),
        rate_candidate=Decimal("15000"),
    )

    payload = await _yoy(yoy_client, headers, end_year=BASE_YEAR, years=2)
    year = str(BASE_YEAR)
    departures = _metric(payload, "departures")["series"][year]
    resignations = _metric(payload, "resignations")["series"][year]

    assert departures[2] >= 2, "oba rozstania są marcowe"
    assert resignations[2] >= 1
    # Podzbiór — w KAŻDYM miesiącu, nie tylko w tym zasianym.
    for month_idx, (dep, res) in enumerate(zip(departures, resignations)):
        assert res <= dep, f"miesiąc {month_idx + 1}: rezygnacji więcej niż zejść"


# ── 4. Marża na godzinę ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_monthly_retainers_leave_both_sides_of_margin_per_hour(
    yoy_client: AsyncClient,
):
    """Ryczałt nie wchodzi ani do licznika, ani do mianownika.

    Kontrakt godzinowy: 100 zł/h marży przy 100 h = 10 000 zł marży.
    Kontrakt ryczałtowy obok ma marżę, ale nie niesie godzin — gdyby jego
    marża trafiła do licznika, wskaźnik by DRGNĄŁ po jego zasianiu.

    Porównujemy odczyt PRZED i PO zasianiu ryczałtu, a nie z bezwzględnym
    „100 zł/h": wskaźnik jest liczony po CAŁEJ firmie, a wspólna baza testowa
    nie jest czyszczona. `test_finance_order_changes.py` zostawia kontrakt
    dzienny BEZ daty startu (380 zł/dzień) — taki obowiązuje w każdym miesiącu
    historii, więc żaden „własny rok" przed nim nie chroni: przy wspólnym
    shardzie wskaźnik wychodził (10 000 + 380·22)/(100 + 22·8) = 66,52.
    Czy oba pliki trafią do jednego sharda, rozstrzyga round-robin po liście
    plików, czyli dopisanie DOWOLNEGO nowego pliku testowego.
    """
    email, password = await _seed_user(UserRole.admin)
    headers = await _login(yoy_client, email, password)
    client_id, _job, cand_hourly = await _seed_client_job_candidate()
    _c, _j, cand_monthly = await _seed_client_job_candidate()

    year = BASE_YEAR - 1  # własny rok, żeby nie zderzyć się z testem zejść
    await _seed_contract(
        client_id=client_id,
        candidate_id=cand_hourly,
        start=date(year, 1, 1),
        end=date(year, 12, 31),
        rate_client=Decimal("300"),
        rate_candidate=Decimal("200"),
        unit=RateUnit.hourly,
        billing_hours=100,
    )
    before = await _yoy(yoy_client, headers, end_year=year, years=2)
    per_hour_before = _metric(before, "margin_per_hour_pln")["series"][str(year)][5]
    margin_before = _metric(before, "margin_monthly_pln")["series"][str(year)][5]
    # Kontrakt godzinowy sam z siebie daje wskaźnik — bez tego porównanie
    # „przed == po" przechodziłoby także dla metryki, która zwraca stałe None.
    assert per_hour_before is not None
    assert margin_before >= 10000

    await _seed_contract(
        client_id=client_id,
        candidate_id=cand_monthly,
        start=date(year, 1, 1),
        end=date(year, 12, 31),
        rate_client=Decimal("99000"),
        rate_candidate=Decimal("1000"),
        unit=RateUnit.monthly,
    )
    after = await _yoy(yoy_client, headers, end_year=year, years=2)
    per_hour_after = _metric(after, "margin_per_hour_pln")["series"][str(year)][5]
    margin_after = _metric(after, "margin_monthly_pln")["series"][str(year)][5]

    assert per_hour_after == pytest.approx(per_hour_before), (
        "ryczałt (98 000 zł marży, zero godzin) przeciekł do wskaźnika"
    )
    # Marża CAŁKOWITA nadal zawiera ryczałt — to dwa różne pytania i tylko
    # wskaźnik godzinowy zawęża populację.
    assert margin_after >= margin_before + 98000


# ── 5. Rozbicie na klientów domyka się do liczby placementów ────────────────


@pytest.mark.asyncio
async def test_client_breakdown_sums_to_the_placement_count(yoy_client: AsyncClient):
    """Suma rozbicia == „Liczba placementów" tego samego miesiąca.

    Placement bez przypisanego klienta ma zostać POLICZONY, tylko bez nazwy —
    wycięcie go dałoby wiersz, który nie domyka się do wiersza wyżej.
    """
    email, password = await _seed_user(UserRole.admin)
    headers = await _login(yoy_client, email, password)
    year = BASE_YEAR - 2
    when = datetime(year, 5, 12, 10, 0, tzinfo=timezone.utc)

    _cli, job_id, cand_id = await _seed_client_job_candidate()
    await _seed_hire(cand_id, job_id, when)
    _cli2, job2, cand2 = await _seed_client_job_candidate()
    await _seed_hire(cand2, job2, when)

    payload = await _yoy(yoy_client, headers, end_year=year, years=2)
    placements = _metric(payload, "placements")["series"][str(year)][4]
    breakdown = payload["placements_by_client"][str(year)][4]

    assert placements >= 2
    named = sum(c["count"] for c in breakdown["clients"])
    assert (
        named + breakdown["other_count"] + breakdown["unassigned_count"]
        == breakdown["total"]
        == placements
    )


@pytest.mark.asyncio
async def test_top_client_share_never_exceeds_one_hundred_percent(
    yoy_client: AsyncClient,
):
    """Udział jednego klienta nie może przekroczyć całości.

    W DynaReporterze ta kolumna pokazywała 114,3% w czerwcu 2026 — licznik
    i mianownik pochodziły z różnych populacji.
    """
    email, password = await _seed_user(UserRole.admin)
    headers = await _login(yoy_client, email, password)
    payload = await _yoy(yoy_client, headers, end_year=BASE_YEAR - 2, years=2)

    for year in payload["years"]:
        for value in _metric(payload, "top_client_share_pct")["series"][str(year)]:
            if value is not None:
                assert 0 < value <= 100, value


# ── 6. Jedna implementacja pieniędzy ────────────────────────────────────────


def test_money_is_the_same_function_as_the_board_tiles_not_a_copy():
    """Kafle i tabela liczą pieniądze TYM SAMYM obiektem funkcji.

    Test tożsamości, nie zachowania: dwie kopie tej samej matematyki
    przechodzą każdy test wartości, dopóki ktoś nie poprawi jednej z nich.
    Wtedy kafel „Marża / mc" i komórka „Marża" w tabeli obok zaczynają
    pokazywać dwie różne kwoty pod jedną nazwą — na jednym ekranie.
    """
    # Kafle liczy od PR3 (23.09.2026) serwis `services/insights_board.py`
    # — router `/api/insights/board` tylko go woła.
    from app.services import insights_board, insights_board_money, insights_board_yoy

    assert insights_board.fold_money is insights_board_money.fold_money
    assert insights_board_yoy.fold_money is insights_board_money.fold_money
    assert insights_board.running_on is insights_board_money.running_on


# ── RBAC i walidacja ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_yoy_is_reachable_only_for_admin_finance_and_hor(
    yoy_client: AsyncClient,
):
    """Rok do roku: admin · finance z kwotami, HoR BEZ kwot (24.09.2026)."""
    params = {"end_year": BASE_YEAR, "years": 2}
    for role in (UserRole.admin, UserRole.finance):
        email, password = await _seed_user(role)
        headers = await _login(yoy_client, email, password)
        resp = await yoy_client.get(YOY_URL, headers=headers, params=params)
        assert resp.status_code == 200, f"{role.value}: {resp.text}"
        assert _metric(resp.json(), "margin_monthly_pln")["series"] is not None

    email, password = await _seed_user(UserRole.head_of_recruitment)
    headers = await _login(yoy_client, email, password)
    resp = await yoy_client.get(YOY_URL, headers=headers, params=params)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    keys = {m["key"] for m in body["metrics"]}
    # Rekrutacja zostaje, pieniędzy nie ma w żadnej postaci.
    assert {"placements", "hit_ratio_pct", "consultants", "departures"} <= keys
    assert not any(m["unit"] == "pln" for m in body["metrics"])
    assert "margin_pct" not in keys
    assert not {
        "margin_monthly_pln",
        "revenue_monthly_pln",
        "margin_with_known_hours_pln",
    } & set(body["component_series"])
    assert body["money_redacted"] is True

    for role in (UserRole.sourcer, UserRole.tac, UserRole.recruiter):
        email, password = await _seed_user(role)
        headers = await _login(yoy_client, email, password)
        resp = await yoy_client.get(YOY_URL, headers=headers, params=params)
        assert resp.status_code == 403, f"{role.value}: {resp.text}"


@pytest.mark.asyncio
async def test_yoy_requires_authentication(yoy_client: AsyncClient):
    resp = await yoy_client.get(YOY_URL)
    assert resp.status_code in (401, 403)


@pytest.mark.asyncio
async def test_year_count_out_of_range_is_422_not_500(yoy_client: AsyncClient):
    """Sufit lat jest sufitem KOSZTU — każdy rok to dwanaście wycen wszystkich
    żywych kontraktów, więc żądanie o dwadzieścia lat ma zostać odrzucone
    czytelnie, a nie wywrócić proces."""
    email, password = await _seed_user(UserRole.admin)
    headers = await _login(yoy_client, email, password)
    for params in ({"years": 20}, {"years": 1}, {"end_year": 1500}):
        resp = await yoy_client.get(YOY_URL, headers=headers, params=params)
        assert resp.status_code == 422, f"{params}: {resp.status_code}"


def test_zero_billing_hours_is_a_value_not_a_missing_field():
    """Jawne zero godzin wyklucza kontrakt, nie udaje etatu 160 h.

    `billing_hours_per_month or 160` zamieniało zero na 160, zanim guard
    w `fold_money` („hours <= 0") zdążył je zobaczyć — czyli mechanizm
    wykluczania był martwy dla dokładnie tego przypadku, który miał łapać.
    Fallback należy się WYŁĄCZNIE brakowi wartości.
    """
    from types import SimpleNamespace

    from app.models.contract import RateUnit
    from app.services.insights_board_money import (
        DEFAULT_BILLING_HOURS,
        _billable_hours,
    )

    hourly = lambda h: SimpleNamespace(  # noqa: E731
        rate_unit=RateUnit.hourly, billing_hours_per_month=h
    )
    assert _billable_hours(hourly(None)) == DEFAULT_BILLING_HOURS
    assert _billable_hours(hourly(120)) == 120
    # Zero przechodzi dalej jako zero i dopiero `fold_money` je odrzuca —
    # kontrakt wypada z licznika I mianownika marży na godzinę.
    assert _billable_hours(hourly(0)) == 0

    monthly = SimpleNamespace(rate_unit=RateUnit.monthly, billing_hours_per_month=None)
    assert _billable_hours(monthly) is None


def test_coverage_flags_years_whose_contract_basis_is_a_fraction_of_the_latest():
    """Rosnąca EWIDENCJA nie może udawać rosnącego biznesu.

    Zmierzone na produkcji 08.09.2026: styczeń 2024 → 17 wycenionych
    kontraktów, sierpień 2026 → 452, przy realnej liczbie ~320 konsultantów
    w 2024 (dane DynaReportera). Kontrakty zaczęły powstawać w NEXUSIE później
    niż firma i nie zostały uzupełnione wstecz, więc wiersz „Przychody"
    pokazywał **+935% wzrostu** — liczbę arytmetycznie poprawną i semantycznie
    fałszywą. Członek Rady wyciągnąłby z niej wniosek o dziesięciokrotnym
    wzroście firmy.

    Podstawa (`contracts_by_year`) jest FAKTEM; heurystyczny jest wyłącznie
    próg ostrzeżenia i celowo ostrzega raczej za często: fałszywy alarm każe
    spojrzeć na podstawę, przeoczenie każe uwierzyć w nieistniejący wzrost.
    """
    from app.services.insights_board_yoy import _contract_coverage

    # Ewidencja narastająca — dokładnie kształt z produkcji.
    metrics = [
        {"label": "Przychody (MRR)", "basis": "contracts"},
        {"label": "Liczba zejść", "basis": "contracts"},
        {"label": "Liczba placementów", "basis": "pipeline"},
        {"label": "Hit ratio", "basis": "pipeline"},
    ]
    growing = _contract_coverage(
        {
            "2024": [17] * 12,
            "2025": [26] * 12,
            "2026": [191] * 9 + [None] * 3,
        },
        [2024, 2025, 2026],
        metrics,
    )
    assert growing["money_comparable_across_years"] is False
    assert growing["message"] is not None
    assert "17" in growing["message"] and "191" in growing["message"]
    # Wiadomość musi wskazać, KTÓRE metryki problemu NIE mają — inaczej
    # ostrzeżenie podważa całą stronę i uczy je ignorować.
    assert "Liczba placementów" in growing["message"]
    assert "Hit ratio" in growing["message"]
    # ...i NIE MOŻE wymieniać metryk liczonych z kontraktów. Pierwsza wersja
    # wpisywała tam „zejścia", czyli metrykę, przez którą to ostrzeżenie
    # w ogóle pojawia się nad grupą HR — komunikat zaprzeczał własnej
    # przyczynie. Lista jest wyprowadzana z `basis`, więc rozjazd wymagałby
    # zmiany danych, nie tylko zdania.
    assert "zejść" not in growing["message"]
    assert "Przychody" not in growing["message"]

    # Stabilna ewidencja — żadnego ostrzeżenia, mimo realnego wzrostu.
    stable = _contract_coverage(
        {"2024": [300] * 12, "2025": [330] * 12, "2026": [360] * 9 + [None] * 3},
        [2024, 2025, 2026],
        metrics,
    )
    assert stable["money_comparable_across_years"] is True
    assert stable["message"] is None
    assert stable["contracts_by_year"] == {"2024": 300, "2025": 330, "2026": 360}

    # Brak danych nie jest ostrzeżeniem — nie ma czego porównać.
    empty = _contract_coverage(
        {"2024": [None] * 12, "2025": [None] * 12}, [2024, 2025], metrics
    )
    assert empty["money_comparable_across_years"] is True
    assert empty["contracts_by_year"] == {"2024": None, "2025": None}


def test_metrics_say_whether_the_contract_backlog_affects_them():
    """`basis` oddziela metryki dotknięte luką w ewidencji od reszty.

    Pieniądze, konsultanci i zejścia idą z kontraktów; placementy, klienci
    i hit ratio z historii pipeline'u (import Traffita), która sięga wstecz.
    Bez tego rozróżnienia ostrzeżenie o pokryciu wisiałoby nad tabelami,
    których nie dotyczy — a ostrzeżenie podważające wszystko uczy ignorować
    ostrzeżenia.
    """
    from app.services.insights_board_yoy import _metric

    series = {k: {"2026": [1] * 12} for k in ("a", "b")}
    assert _metric("a", "finanse", "A", "pln", "avg", series)["basis"] == "contracts"
    assert (
        _metric("b", "hr", "B", "count", "sum", series, basis="pipeline")["basis"]
        == "pipeline"
    )


def test_without_money_strips_amounts_and_keeps_cached_result_intact() -> None:
    """Redakcja dla HoR działa na KOPII — cache admina zostaje z kwotami."""
    from app.services.insights_board_yoy import without_money

    cached = {
        "metrics": [
            {"key": "revenue_monthly_pln", "unit": "pln"},
            {"key": "margin_pct", "unit": "pct"},
            {"key": "placements", "unit": "count"},
            {"key": "hit_ratio_pct", "unit": "pct"},
        ],
        "component_series": {
            "margin_monthly_pln": {},
            "revenue_monthly_pln": {},
            "closed_jobs_total": {},
        },
        "degraded": {
            "reasons": ["fx_missing"],
            "fx": {"currencies": ["EUR"], "months_affected": ["2026-01"]},
            "contracts_without_termination_reason": 0,
            "message": "Brak kursu NBP dla walut: EUR",
        },
    }
    stripped = without_money(cached)
    assert [m["key"] for m in stripped["metrics"]] == ["placements", "hit_ratio_pct"]
    assert set(stripped["component_series"]) == {"closed_jobs_total"}
    assert stripped["degraded"] is None
    assert stripped["money_redacted"] is True
    assert len(cached["metrics"]) == 4
    assert "margin_monthly_pln" in cached["component_series"]
