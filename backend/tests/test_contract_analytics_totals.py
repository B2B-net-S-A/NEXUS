"""Kafle analityki kontraktów mają mówić prawdę o CAŁEJ firmie.

Audyt 18.09.2026 zmierzył na produkcji dwa niezależne kłamstwa na jednym ekranie:

* ``utilization_pct = 0.8`` przy realnych ``91,3%`` (błąd 114×) i
  ``candidates_on_bench = 56 647`` przy realnych ``45`` — mianownikiem była
  CAŁA BAZA CV, nie populacja konsultantów;
* kafel „Miesięczny przychód” pokazywał 12 555 483 zamiast 12 772 543 PLN,
  bo front sumował ranking przycięty do 20 klientów po MARŻY.

Testy seedują własne wiersze i asertują po nich (baza testowa jest
współdzielona w przebiegu i nie jest czyszczona), a `consultant_population`
jest sprawdzana też jako czysta arytmetyka, bez bazy.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import func, select

from app.core.database import AsyncSessionLocal
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.contract import Contract, ContractStatus, ContractType, RateUnit
from app.services.consultant_population import (
    ConsultantPopulation,
    consultant_population,
)
from app.core.scheduling import business_today


# --- arytmetyka populacji (bez DB) -----------------------------------------


def _population(**kwargs) -> ConsultantPopulation:
    base = {
        "on": date(2026, 9, 18),
        "active_keys": frozenset(),
        "ever_keys": frozenset(),
        "bench_last_end": {},
    }
    base.update(kwargs)
    return ConsultantPopulation(**base)


def test_utilization_denominator_is_the_consultant_population():
    population = _population(
        active_keys=frozenset({("a",), ("b",)}),
        ever_keys=frozenset({("a",), ("b",), ("c",)}),
    )
    assert population.total == 3
    assert population.bench == 1
    assert population.utilization_pct == 66.7


def test_no_consultants_at_all_is_none_not_zero_percent():
    # Zero znaczyłoby „żaden z naszych konsultantów nie pracuje” — czyli coś
    # zupełnie innego niż „nie mamy jeszcze ani jednego konsultanta”.
    assert _population().utilization_pct is None


def test_bench_average_ignores_people_who_are_back_at_work():
    today = date(2026, 9, 18)
    population = _population(
        active_keys=frozenset({("a",)}),
        ever_keys=frozenset({("a",), ("b",)}),
        # ("a",) pracuje — jego stara data końca nie jest przerwą.
        bench_last_end={("a",): date(2026, 1, 1), ("b",): date(2026, 9, 8)},
    )
    assert population.avg_bench_days(today=today) == 10.0


def test_bench_average_is_none_when_nobody_has_a_known_end_date():
    # Osoba bez daty końca nadal JEST na ławce (liczy się do `bench`), ale nie
    # wnosi przerwy. Ta asymetria jest powodem, dla którego obie liczby wychodzą
    # z jednego obiektu — kafel „Śr. dni na bench” i licznik pod nim.
    population = _population(
        active_keys=frozenset(),
        ever_keys=frozenset({("b",)}),
        bench_last_end={},
    )
    assert population.bench == 1
    assert population.avg_bench_days(today=date(2026, 9, 18)) is None


# --- DB ---------------------------------------------------------------------


@pytest_asyncio.fixture
async def seeded():
    """Jeden pracujący konsultant, jeden na ławce, jeden kandydat bez kontraktu."""
    pytest.importorskip("asyncpg")
    marker = uuid.uuid4().hex[:8]
    today = business_today()
    async with AsyncSessionLocal() as db:
        client = Client(name=f"Utylizacja {marker}")
        working = Candidate(name="Pracuje", lastname=f"Konsultant{marker}")
        benched = Candidate(name="Czeka", lastname=f"Konsultant{marker}")
        never = Candidate(name="Nigdy", lastname=f"Kandydat{marker}")
        db.add_all([client, working, benched, never])
        await db.flush()
        db.add_all(
            [
                Contract(
                    candidate_id=working.id,
                    client_id=client.id,
                    contract_type=ContractType.b2b,
                    status=ContractStatus.active,
                    start_date=today - timedelta(days=100),
                    rate_unit=RateUnit.monthly,
                    rate_client=Decimal("20000"),
                    rate_candidate=Decimal("15000"),
                ),
                Contract(
                    candidate_id=benched.id,
                    client_id=client.id,
                    contract_type=ContractType.b2b,
                    status=ContractStatus.ended,
                    start_date=today - timedelta(days=200),
                    end_date=today - timedelta(days=30),
                    rate_unit=RateUnit.monthly,
                    rate_client=Decimal("20000"),
                    rate_candidate=Decimal("15000"),
                ),
            ]
        )
        await db.commit()
        yield {
            "working": working.id,
            "benched": benched.id,
            "never": never.id,
            "client": client.id,
        }


async def test_a_candidate_who_never_had_a_contract_is_not_on_the_bench(seeded):
    """To jest cały błąd 114×: baza CV nie jest populacją konsultantów."""
    async with AsyncSessionLocal() as db:
        population = await consultant_population(db)
        from app.models.candidate import Candidate as C

        never = await db.get(C, seeded["never"])
        working = await db.get(C, seeded["working"])
        benched = await db.get(C, seeded["benched"])

    from app.services.contractor_identity import candidate_identity_key

    assert candidate_identity_key(working) in population.active_keys
    assert candidate_identity_key(benched) in population.bench_keys
    assert candidate_identity_key(never) not in population.ever_keys


@pytest.mark.parametrize("end_offset", [None, 30])
async def test_ended_contract_without_past_end_date_is_bench_not_active(end_offset):
    """Status `ended` bez daty końca (albo z datą w przyszłości) to nie praca.

    Populacja liczyła osobę jako aktywną po samej dacie końca, a kafel obok
    liczy kontrakty po statusie — w kolejce 23.09 wyszło „3 aktywne kontrakty,
    4 aktywne osoby” (test_contract_analytics::test_utilization_shape).
    """
    pytest.importorskip("asyncpg")
    from app.services.contractor_identity import candidate_identity_key

    today = business_today()
    marker = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"Utylizacja ended {marker}")
        person = Candidate(name="Zakończony", lastname=f"Bezdaty{marker}")
        db.add_all([client, person])
        await db.flush()
        db.add(
            Contract(
                candidate_id=person.id,
                client_id=client.id,
                contract_type=ContractType.b2b,
                status=ContractStatus.ended,
                start_date=today - timedelta(days=200),
                end_date=(
                    None if end_offset is None else today + timedelta(days=end_offset)
                ),
                rate_unit=RateUnit.monthly,
                rate_client=Decimal("20000"),
                rate_candidate=Decimal("15000"),
            )
        )
        await db.commit()
        key = candidate_identity_key(person)
        population = await consultant_population(db)
        # Przeszłość: status mówi o dziś, nie o tamtym dniu — wtedy trwał.
        past = await consultant_population(db, on=today - timedelta(days=100))

    assert key in population.ever_keys
    assert key not in population.active_keys
    assert key in past.active_keys


async def test_utilization_endpoint_counts_people_not_the_whole_cv_database(
    app_client: AsyncClient, app_auth_headers: dict, seeded
):
    resp = await app_client.get(
        "/api/contract-analytics/utilization", headers=app_auth_headers
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()

    assert data["total_candidates"] == (
        data["candidates_active"] + data["candidates_on_bench"]
    )
    assert data["utilization_pct"] is not None

    # Mianownik to liczba OSÓB z kontraktem, a nie wierszy w tabeli kandydatów.
    # Przed poprawką te dwie liczby były sobie równe — i stąd 0,8% zamiast 91,3%.
    async with AsyncSessionLocal() as db:
        candidates_in_database = (
            await db.execute(select(func.count(Candidate.id)))
        ).scalar_one()
        population = await consultant_population(db)

    assert data["total_candidates"] == population.total
    assert data["total_candidates"] < candidates_in_database, (
        "populacja konsultantów równa liczbie wszystkich kandydatów znaczy, "
        "że mianownik znów łapie osoby bez kontraktu"
    )


async def test_totals_do_not_depend_on_how_many_clients_fit_in_the_ranking(
    app_client: AsyncClient, app_auth_headers: dict, seeded
):
    totals = await app_client.get(
        "/api/contract-analytics/margin-totals", headers=app_auth_headers
    )
    assert totals.status_code == 200, totals.text
    body = totals.json()

    ranked = await app_client.get(
        "/api/contract-analytics/margin-by-client?limit=1", headers=app_auth_headers
    )
    assert ranked.status_code == 200, ranked.text
    assert len(ranked.json()) == 1

    # Suma firmowa nie może zależeć od tego, ilu klientów mieści się w rankingu
    # obok — to był dokładnie ten błąd (z kafla przychodu znikało 217 060 zł).
    assert body["clients"] > 1
    ranked_revenue = ranked.json()[0]["total_monthly_revenue"]
    assert float(body["total_monthly_revenue"]) > float(ranked_revenue)


async def test_totals_agree_with_the_full_unlimited_ranking(
    app_client: AsyncClient, app_auth_headers: dict, seeded
):
    totals = (
        await app_client.get(
            "/api/contract-analytics/margin-totals", headers=app_auth_headers
        )
    ).json()
    full = (
        await app_client.get(
            "/api/contract-analytics/margin-by-client?limit=100",
            headers=app_auth_headers,
        )
    ).json()
    if totals["clients"] > 100:
        pytest.skip("baza ma więcej niż 100 klientów — pełny ranking nie mieści się")
    assert float(totals["total_monthly_revenue"]) == pytest.approx(
        sum(float(row["total_monthly_revenue"]) for row in full), abs=0.01
    )
    assert float(totals["total_monthly_margin"]) == pytest.approx(
        sum(float(row["total_monthly_margin"]) for row in full), abs=0.01
    )


async def test_totals_sum_every_client_even_past_the_ranking_limit(monkeypatch):
    """Bez bazy: 25 klientów, ranking oddaje 20 — suma musi objąć wszystkich.

    Na bazie testowej nie ma dziś 20 klientów z żywym kontraktem, więc regresja
    „sumujmy tylko czubek rankingu” przeszłaby tam niezauważona. Na produkcji
    kosztowała 217 060 zł w kaflu przychodu.
    """
    from app.api import contract_analytics as ca

    rows = [
        ca.MarginByClient(
            client_id=i,
            client_name=f"Klient {i}",
            active_contracts=1,
            # Marża maleje z numerem, więc klienci 21-25 wypadają z rankingu…
            total_monthly_margin=Decimal(str(1000 - i)),
            # …choć wnoszą przychód. Dokładnie ten kształt danych ukrywał kwotę.
            total_monthly_revenue=Decimal("100"),
            margin_pct=None,
            fx_missing=False,
        )
        for i in range(1, 26)
    ]

    async def _fake_rows(db):
        return rows

    monkeypatch.setattr(ca, "_margin_by_client_rows", _fake_rows)

    totals = await ca.margin_totals(current_user=object(), db=None)

    assert totals.clients == 25
    assert totals.total_monthly_revenue == Decimal("2500")
    assert totals.active_contracts == 25

    ranked = await ca.margin_by_client(current_user=object(), db=None, limit=20)
    assert len(ranked) == 20
    assert sum((row.total_monthly_revenue for row in ranked), Decimal("0")) == Decimal(
        "2000"
    ), "ranking nadal przycina — to jest właśnie liczba, której kafel NIE może pokazać"


# --- audyt 24.09.2026 -------------------------------------------------------


def test_contract_analytics_folds_money_with_the_board_function():
    """Kopia reguł ``fold_money`` rozjeżdżała się z Radą przy każdej poprawce."""
    from app.api import contract_analytics
    from app.services import insights_board_money

    assert contract_analytics.fold_money is insights_board_money.fold_money


async def test_margin_percent_ignores_revenue_without_a_cost_leg(
    app_client: AsyncClient, app_auth_headers: dict
):
    """Przychód bez stawki kosztowej zaniżał marżę % bez żadnego sygnału.

    3M przychodu z marżą M + M przychodu bez kosztu: marża % to 33,3
    (z kontraktów o znanej marży), a nie 25,0; kontrakt bez kosztu jest
    policzony w ``contracts_without_cost_leg``.
    """
    pytest.importorskip("asyncpg")
    from tests._ranking_anchor import ranking_anchor

    # Marża ponad próg odcięcia okna top-100 — inaczej wiersz wypada
    # z rankingu na zapełnionej bazie (patrz ``tests/_ranking_anchor``).
    anchor = await ranking_anchor(app_client, app_auth_headers, limit=100)
    margin = max(anchor, Decimal("3000000")).to_integral_value(rounding="ROUND_CEILING")
    marker = uuid.uuid4().hex[:8]
    today = business_today()
    async with AsyncSessionLocal() as db:
        client = Client(name=f"Marża bez kosztu {marker}")
        priced = Candidate(name="Wyceniony", lastname=f"Konsultant{marker}")
        unpriced = Candidate(name="Bezkosztowy", lastname=f"Konsultant{marker}")
        db.add_all([client, priced, unpriced])
        await db.flush()
        db.add_all(
            [
                Contract(
                    candidate_id=priced.id,
                    client_id=client.id,
                    contract_type=ContractType.b2b,
                    status=ContractStatus.active,
                    start_date=today - timedelta(days=30),
                    rate_unit=RateUnit.monthly,
                    rate_client=3 * margin,
                    rate_candidate=2 * margin,
                ),
                Contract(
                    candidate_id=unpriced.id,
                    client_id=client.id,
                    contract_type=ContractType.b2b,
                    status=ContractStatus.active,
                    start_date=today - timedelta(days=30),
                    rate_unit=RateUnit.monthly,
                    rate_client=margin,
                ),
            ]
        )
        await db.commit()
        client_id = client.id

    ranking = await app_client.get(
        "/api/contract-analytics/margin-by-client?limit=100", headers=app_auth_headers
    )
    assert ranking.status_code == 200, ranking.text
    row = next(r for r in ranking.json() if r["client_id"] == client_id)
    assert row["total_monthly_revenue"] == float(4 * margin)
    assert row["total_monthly_margin"] == float(margin)
    # 1/3, nie 1/4 — przychód bez kosztu nie wchodzi do mianownika.
    assert row["margin_pct"] == 33.3
    assert row["contracts_without_cost_leg"] == 1

    totals = await app_client.get(
        "/api/contract-analytics/margin-totals", headers=app_auth_headers
    )
    assert totals.status_code == 200, totals.text
    assert totals.json()["contracts_without_cost_leg"] >= 1


async def test_contract_without_a_start_date_counts_as_current_in_utilization():
    """Kafel „aktywne kontrakty" liczy kontrakt bez daty startu, utylizacja nie.

    Reguła z 18.09.2026: pusta data startu = kontrakt obowiązujący.
    """
    pytest.importorskip("asyncpg")
    from app.services.contractor_identity import candidate_identity_key

    marker = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"Bez startu {marker}")
        person = Candidate(name="Bezdaty", lastname=f"Startu{marker}")
        db.add_all([client, person])
        await db.flush()
        db.add(
            Contract(
                candidate_id=person.id,
                client_id=client.id,
                contract_type=ContractType.b2b,
                status=ContractStatus.active,
                start_date=None,
                rate_unit=RateUnit.monthly,
                rate_client=Decimal("20000"),
                rate_candidate=Decimal("15000"),
            )
        )
        await db.commit()
        key = candidate_identity_key(person)
        population = await consultant_population(db)

    assert key in population.active_keys


@pytest.mark.parametrize(
    ("order_offset", "current"),
    [(1, False), (-1, True)],
    ids=["order-starts-tomorrow", "order-started-yesterday"],
)
async def test_dateless_contract_asks_its_orders_whether_it_already_runs(
    order_offset, current
):
    """Audyt 25.09.2026 (reguła S5): kontrakt bez daty startu, którego jedyne
    zamówienie zaczyna się jutro, jest PLANOWANY — tak liczy profil klienta
    i katalog. Analityka (margin-totals, ranking, utylizacja) liczyła go jako
    obecny, więc ten sam klient miał inne MRR w Finansach niż na profilu."""
    pytest.importorskip("asyncpg")
    from app.api.contract_analytics import _load_live_contracts, _started_by
    from app.models.client_order import ClientOrder, ClientOrderStatus
    from app.services.contractor_identity import candidate_identity_key

    marker = uuid.uuid4().hex[:8]
    today = business_today()
    async with AsyncSessionLocal() as db:
        client = Client(name=f"Start z zamówienia {marker}")
        person = Candidate(name="Planowany", lastname=f"Konsultant{marker}")
        db.add_all([client, person])
        await db.flush()
        contract = Contract(
            candidate_id=person.id,
            client_id=client.id,
            contract_type=ContractType.b2b,
            status=ContractStatus.active,
            start_date=None,
            rate_unit=RateUnit.monthly,
            rate_client=Decimal("20000"),
            rate_candidate=Decimal("15000"),
        )
        db.add(contract)
        await db.flush()
        db.add(
            ClientOrder(
                client_id=client.id,
                contract_id=contract.id,
                title=f"ZAM-{marker}",
                status=ClientOrderStatus.active,
                order_type="periodic",
                rate_unit=RateUnit.monthly,
                start_date=today + timedelta(days=order_offset),
            )
        )
        await db.commit()
        contract_id = contract.id
        key = candidate_identity_key(person)

        live_ids = {c.id for c in await _load_live_contracts(db, today)}
        counted = await db.scalar(
            select(func.count(Contract.id)).where(
                Contract.id == contract_id, _started_by(today)
            )
        )
        population = await consultant_population(db)

    assert (contract_id in live_ids) is current
    assert counted == (1 if current else 0)
    assert (key in population.active_keys) is current


async def test_shortened_contract_counts_as_ended_early(
    app_client: AsyncClient, app_auth_headers: dict
):
    """``terminated_at < end_date`` nigdy nie zachodzi — zakończenie ucina
    ``end_date`` do daty zakończenia. Skrócenie zapisuje aneks
    ``early_termination`` i to on jest sygnałem."""
    pytest.importorskip("asyncpg")
    from app.models.contract_amendment import (
        ContractAmendment,
        ContractAmendmentType,
    )
    from app.models.contract import ContractTerminationReason

    marker = uuid.uuid4().hex[:8]
    today = business_today()
    ended_on = today - timedelta(days=10)
    async with AsyncSessionLocal() as db:
        client = Client(name=f"Retencja {marker}")
        cut = Candidate(name="Skrócony", lastname=f"Konsultant{marker}")
        kept = Candidate(name="Dotrwał", lastname=f"Konsultant{marker}")
        db.add_all([client, cut, kept])
        await db.flush()
        shortened = Contract(
            candidate_id=cut.id,
            client_id=client.id,
            contract_type=ContractType.b2b,
            status=ContractStatus.ended,
            start_date=today - timedelta(days=200),
            end_date=ended_on,
            terminated_at=ended_on,
            termination_reason=ContractTerminationReason.project_ended,
        )
        in_time = Contract(
            candidate_id=kept.id,
            client_id=client.id,
            contract_type=ContractType.b2b,
            status=ContractStatus.ended,
            start_date=today - timedelta(days=200),
            end_date=ended_on,
            terminated_at=ended_on,
            termination_reason=ContractTerminationReason.project_ended,
        )
        db.add_all([shortened, in_time])
        await db.flush()
        db.add(
            ContractAmendment(
                contract_id=shortened.id,
                amendment_type=ContractAmendmentType.early_termination,
                old_values={"end_date": (today + timedelta(days=90)).isoformat()},
                new_values={"end_date": ended_on.isoformat()},
                effective_date=ended_on,
            )
        )
        await db.commit()
        client_id = client.id

    resp = await app_client.get(
        "/api/contract-analytics/termination-analysis?window_months=12",
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    row = next(
        r for r in resp.json()["client_retention"] if r["client_id"] == client_id
    )
    assert row["total_ended"] == 2
    assert row["ended_early"] == 1
    assert row["kept_to_end"] == 1
    assert row["retention_pct"] == 50.0


async def test_forecast_month_label_is_polish_whatever_the_locale(
    app_client: AsyncClient, app_auth_headers: dict
):
    """``strftime("%b %Y")`` zależy od locale kontenera — na prodzie „Sep 2026"."""
    from app.services.insights_board_money import MONTH_LABELS_PL

    resp = await app_client.get(
        "/api/contract-analytics/revenue-forecast?horizon_months=1",
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    today = business_today()
    assert resp.json()["months"][0]["month_label"] == (
        f"{MONTH_LABELS_PL[today.month - 1]} {today.year}"
    )


async def test_forecast_starts_a_dateless_contract_with_its_future_order(
    app_client: AsyncClient, app_auth_headers: dict
):
    """Runda 8 (R8-N13-2): kontrakt bez daty startu, którego jedyne zamówienie
    startuje za 60 dni, jest planowany (reguła S5). Prognoza liczyła go od
    bieżącego miesiąca i zawyżała dwa pierwsze miesiące wykresu."""
    pytest.importorskip("asyncpg")
    from app.models.client_order import ClientOrder, ClientOrderStatus

    async def _forecast() -> list[dict]:
        resp = await app_client.get(
            "/api/contract-analytics/revenue-forecast?horizon_months=6",
            headers=app_auth_headers,
        )
        assert resp.status_code == 200, resp.text
        return resp.json()["months"]

    before = await _forecast()
    marker = uuid.uuid4().hex[:8]
    today = business_today()
    order_start = today + timedelta(days=60)
    async with AsyncSessionLocal() as db:
        client = Client(name=f"Prognoza planowana {marker}")
        person = Candidate(name="Prognoza", lastname=f"Planowana{marker}")
        db.add_all([client, person])
        await db.flush()
        contract = Contract(
            candidate_id=person.id,
            client_id=client.id,
            contract_type=ContractType.b2b,
            status=ContractStatus.active,
            start_date=None,
            rate_unit=RateUnit.monthly,
            rate_client=Decimal("20000"),
            rate_candidate=Decimal("15000"),
        )
        db.add(contract)
        await db.flush()
        db.add(
            ClientOrder(
                client_id=client.id,
                contract_id=contract.id,
                title=f"ZAM-{marker}",
                status=ClientOrderStatus.active,
                order_type="periodic",
                rate_unit=RateUnit.monthly,
                start_date=order_start,
            )
        )
        await db.commit()
    after = await _forecast()

    start_key = order_start.strftime("%Y-%m")
    for month_before, month_after in zip(before, after):
        delta = float(month_after["revenue"]) - float(month_before["revenue"])
        if month_after["month"] < start_key:
            assert delta == 0, month_after["month"]
        else:
            assert delta == 20000, month_after["month"]
