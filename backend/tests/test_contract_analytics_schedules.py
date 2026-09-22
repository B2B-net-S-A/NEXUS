"""AN-01/AN-02 — analityka kontraktów liczy z HARMONOGRAMÓW i tylko obecne kontrakty.

Audyt 22.09.2026: ``/api/contract-analytics/*`` czytało kolumny
``contracts.rate_*`` (cache z ostatniego ZAPISU kontraktu) i każdy kontrakt
``active``/``ending`` — także taki, którego start dopiero nadejdzie. Kokpit
Rady, profil klienta i portal DL liczą inaczej, więc ten sam klient miał dwie
marże na dwóch ekranach. Testy przypinają trzy reguły:

* krok stawki zaplanowany na przyszłość nie zmienia dzisiejszej marży
  (a krok, który już nadszedł — zmienia);
* kontrakt z przyszłą datą startu nie wchodzi do dzisiejszych sum,
  wykorzystania ani obsady ról;
* prognoza wycenia KAŻDY miesiąc stawką obowiązującą w tym miesiącu i liczy
  kontrakt dopiero od miesiąca jego startu.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
from httpx import AsyncClient

from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.contract import Contract, ContractStatus
from app.models.contract_candidate_rate import ContractCandidateRate
from tests._ranking_anchor import anchor_contract, ranking_anchor

pytestmark = pytest.mark.asyncio

_LIMIT = 100


def _add_months(day: date, months: int) -> date:
    month_index = day.month - 1 + months
    return date(day.year + month_index // 12, month_index % 12 + 1, 1)


async def _seed_scheduled_contract(
    *, step_from: date, anchor: Decimal | None = None
) -> tuple[int, int]:
    """Kontrakt PLN: przychód 100 000/mc, koszt 60 000 → 90 000 od ``step_from``.

    Kolumna ``rate_candidate`` niesie już NOWĄ stawkę (90 000) — dokładnie tak,
    jak zostawia ją aneks z datą przyszłą. Kto czyta kolumnę, widzi marżę
    10 000 zamiast 40 000.
    """
    unique = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"Schedule Client {unique}")
        candidate = Candidate(name="Schedule", lastname=f"Contractor-{unique}")
        db.add_all([client, candidate])
        await db.flush()
        contract = Contract(
            candidate_id=candidate.id,
            client_id=client.id,
            status=ContractStatus.active,
            start_date=date(2025, 1, 1),
            end_date=None,
            rate_client=Decimal("100000"),
            rate_candidate=Decimal("90000"),
            currency="PLN",
        )
        db.add(contract)
        await db.flush()
        db.add_all(
            [
                ContractCandidateRate(
                    contract_id=contract.id,
                    rate=Decimal("60000"),
                    effective_from=date(2025, 1, 1),
                ),
                ContractCandidateRate(
                    contract_id=contract.id,
                    rate=Decimal("90000"),
                    effective_from=step_from,
                ),
            ]
        )
        if anchor is not None:
            db.add(
                anchor_contract(
                    candidate_id=candidate.id, client_id=client.id, margin=anchor
                )
            )
        await db.commit()
        return candidate.id, client.id


async def _seed_future_start_contract(
    *, start: date, anchor: Decimal | None = None
) -> tuple[int, int]:
    unique = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"Future Client {unique}")
        candidate = Candidate(name="Future", lastname=f"Contractor-{unique}")
        db.add_all([client, candidate])
        await db.flush()
        db.add(
            Contract(
                candidate_id=candidate.id,
                client_id=client.id,
                status=ContractStatus.active,
                start_date=start,
                end_date=None,
                rate_client=Decimal("50000"),
                rate_candidate=Decimal("20000"),
                currency="PLN",
            )
        )
        if anchor is not None:
            db.add(
                anchor_contract(
                    candidate_id=candidate.id, client_id=client.id, margin=anchor
                )
            )
        await db.commit()
        return candidate.id, client.id


async def _get(app_client: AsyncClient, headers: dict, path: str):
    response = await app_client.get(path, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def _row(rows: list[dict], key: str, value: int) -> dict:
    matches = [row for row in rows if row[key] == value]
    assert matches, f"brak wiersza {key}={value} w odpowiedzi ({len(rows)} wierszy)"
    return matches[0]


async def test_future_cost_step_does_not_change_todays_margin(
    app_client: AsyncClient, app_auth_headers: dict
):
    anchor = await ranking_anchor(app_client, app_auth_headers, limit=_LIMIT)
    today = business_today()
    candidate_id, client_id = await _seed_scheduled_contract(
        step_from=today + timedelta(days=30), anchor=anchor
    )

    by_contractor = await _get(
        app_client,
        app_auth_headers,
        f"/api/contract-analytics/margin-by-contractor?limit={_LIMIT}",
    )
    by_client = await _get(
        app_client,
        app_auth_headers,
        f"/api/contract-analytics/margin-by-client?limit={_LIMIT}",
    )
    for row in (
        _row(by_contractor, "candidate_id", candidate_id),
        _row(by_client, "client_id", client_id),
    ):
        # Dziś obowiązuje 60 000 z harmonogramu, nie 90 000 z kolumny.
        assert row["total_monthly_margin"] == pytest.approx(float(anchor) + 40000)
        assert row["total_monthly_revenue"] == pytest.approx(float(anchor) + 100000)


async def test_cost_step_that_already_took_effect_changes_todays_margin(
    app_client: AsyncClient, app_auth_headers: dict
):
    anchor = await ranking_anchor(app_client, app_auth_headers, limit=_LIMIT)
    today = business_today()
    candidate_id, _ = await _seed_scheduled_contract(
        step_from=today - timedelta(days=1), anchor=anchor
    )
    rows = await _get(
        app_client,
        app_auth_headers,
        f"/api/contract-analytics/margin-by-contractor?limit={_LIMIT}",
    )
    row = _row(rows, "candidate_id", candidate_id)
    assert row["total_monthly_margin"] == pytest.approx(float(anchor) + 10000)


async def test_forecast_prices_each_month_with_the_rate_in_force_that_month(
    app_client: AsyncClient, app_auth_headers: dict
):
    path = "/api/contract-analytics/revenue-forecast?horizon_months=4"
    before = (await _get(app_client, app_auth_headers, path))["months"]
    first = business_today().replace(day=1)
    await _seed_scheduled_contract(step_from=_add_months(first, 2))
    after = (await _get(app_client, app_auth_headers, path))["months"]

    deltas = [a["margin"] - b["margin"] for a, b in zip(after, before)]
    # Miesiące 0 i 1: koszt 60 000 → marża 40 000; od miesiąca kroku: 10 000.
    assert deltas[0] == pytest.approx(40000)
    assert deltas[1] == pytest.approx(40000)
    assert deltas[2] == pytest.approx(10000)
    assert deltas[3] == pytest.approx(10000)
    for a, b in zip(after, before):
        assert a["revenue"] - b["revenue"] == pytest.approx(100000)


async def test_future_start_contract_is_not_in_todays_totals(
    app_client: AsyncClient, app_auth_headers: dict
):
    anchor = await ranking_anchor(app_client, app_auth_headers, limit=_LIMIT)
    totals_path = "/api/contract-analytics/margin-totals"
    utilization_path = "/api/contract-analytics/utilization"
    mix_path = "/api/contract-analytics/role-client-mix"
    totals_before = await _get(app_client, app_auth_headers, totals_path)
    utilization_before = await _get(app_client, app_auth_headers, utilization_path)
    mix_before = await _get(app_client, app_auth_headers, mix_path)

    candidate_id, client_id = await _seed_future_start_contract(
        start=business_today() + timedelta(days=45), anchor=anchor
    )

    rows = await _get(
        app_client,
        app_auth_headers,
        f"/api/contract-analytics/margin-by-contractor?limit={_LIMIT}",
    )
    row = _row(rows, "candidate_id", candidate_id)
    # Tylko kotwica — kontrakt, który zacznie się za 45 dni, nie jest dzisiejszy.
    assert row["active_contracts"] == 1
    assert row["total_monthly_margin"] == pytest.approx(float(anchor))
    clients = await _get(
        app_client,
        app_auth_headers,
        f"/api/contract-analytics/margin-by-client?limit={_LIMIT}",
    )
    assert _row(clients, "client_id", client_id)["active_contracts"] == 1

    totals_after = await _get(app_client, app_auth_headers, totals_path)
    assert totals_after["total_monthly_margin"] - totals_before[
        "total_monthly_margin"
    ] == pytest.approx(float(anchor))
    assert totals_after["active_contracts"] == totals_before["active_contracts"] + 1

    utilization_after = await _get(app_client, app_auth_headers, utilization_path)
    assert (
        utilization_after["active_contracts"]
        == utilization_before["active_contracts"] + 1
    )
    mix_after = await _get(app_client, app_auth_headers, mix_path)
    assert (
        mix_after["total_active_contracts"] == mix_before["total_active_contracts"] + 1
    )


async def test_forecast_counts_a_future_contract_from_its_start_month(
    app_client: AsyncClient, app_auth_headers: dict
):
    path = "/api/contract-analytics/revenue-forecast?horizon_months=4"
    before = (await _get(app_client, app_auth_headers, path))["months"]
    first = business_today().replace(day=1)
    await _seed_future_start_contract(start=_add_months(first, 2))
    after = (await _get(app_client, app_auth_headers, path))["months"]

    counts = [a["active_count"] - b["active_count"] for a, b in zip(after, before)]
    revenue = [a["revenue"] - b["revenue"] for a, b in zip(after, before)]
    assert counts == [0, 0, 1, 1]
    assert revenue == [
        pytest.approx(0),
        pytest.approx(0),
        pytest.approx(50000),
        pytest.approx(50000),
    ]
