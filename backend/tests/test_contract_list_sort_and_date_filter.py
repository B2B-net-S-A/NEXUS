"""Lista kontraktów: sortowanie po kolumnach i filtr końca zamówienia.

Lista jest stronicowana i grupowana po osobie NA SERWERZE, więc sortowanie
musi też być serwerowe — posortowanie jednej strony we froncie pokazywałoby
porządek, którego nie ma. Grupa (osoba z N umowami) sortuje się rosnąco po
swojej najmniejszej wartości, malejąco po największej; puste wartości zawsze
na końcu. Seedy niosą unikalny marker, a asercje idą przez ``?q=<marker>``.
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest
from httpx import AsyncClient

from app.core.database import AsyncSessionLocal
from app.models.contract import Contract, ContractStatus
from app.core.scheduling import business_today
from tests.test_contractor_consolidation import (
    _seed_candidate,
    _seed_client,
    _role_headers,
    _seed_contract,
)

pytestmark = pytest.mark.asyncio


async def _set_dates(
    contract_id: int,
    *,
    start: date | None,
    order_end: date | None,
) -> None:
    async with AsyncSessionLocal() as db:
        contract = await db.get(Contract, contract_id)
        contract.start_date = start
        contract.end_date = None
        contract.client_order_start_date = start if order_end else None
        contract.client_order_end_date = order_end
        await db.commit()


async def _list(app_client, headers, **params) -> dict:
    resp = await app_client.get(
        "/api/contracts", params={"page_size": 50, **params}, headers=headers
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _seed_three(marker: str) -> dict[str, int]:
    """Trzy osoby u trzech klientów, każda z inną datą i stawką."""
    ids: dict[str, int] = {}
    rows = [
        ("Adam", "Łukasz Bank", date(2026, 1, 10), date(2026, 12, 31), 100, 150),
        ("Zenon", "Alfa Bank", date(2025, 6, 1), None, 120, 200),
        ("Marek", "Zeta Bank", date(2026, 3, 1), date(2026, 6, 30), 90, 110),
    ]
    for first, client, start, order_end, cost, revenue in rows:
        cand = await _seed_candidate(
            marker,
            email=f"{first.lower()}-{marker.lower()}@example.com",
            first_name=first,
        )
        cli = await _seed_client(f"{client} {marker}")
        cid = await _seed_contract(cand, cli, rate_candidate=cost, rate_client=revenue)
        await _set_dates(cid, start=start, order_end=order_end)
        ids[first] = cid
        ids[f"client:{first}"] = cli
    return ids


def _first_names(body: dict) -> list[str]:
    return [row["candidate_name"].split(" ")[0] for row in body["items"]]


@pytest.mark.parametrize("grouped", ["true", "false"])
async def test_sort_by_candidate_and_client_both_directions(
    app_client: AsyncClient, app_auth_headers: dict, grouped: str
):
    marker = f"Srt{uuid.uuid4().hex[:6]}"
    await _seed_three(marker)
    base = {"q": marker, "group_by_candidate": grouped}

    asc = await _list(app_client, app_auth_headers, **base, sort_by="candidate")
    assert _first_names(asc) == ["Adam", "Marek", "Zenon"]
    desc = await _list(
        app_client, app_auth_headers, **base, sort_by="candidate", sort_dir="desc"
    )
    assert _first_names(desc) == ["Zenon", "Marek", "Adam"]

    # „Łukasz" bez foldu polskich znaków lądowałby za „Zeta" (brak kolacji).
    by_client = await _list(app_client, app_auth_headers, **base, sort_by="client")
    assert [r["client_name"].split(" ")[0] for r in by_client["items"]] == [
        "Alfa",
        "Łukasz",
        "Zeta",
    ]


async def test_sort_by_dates_puts_empty_values_last(
    app_client: AsyncClient, app_auth_headers: dict
):
    marker = f"Srd{uuid.uuid4().hex[:6]}"
    await _seed_three(marker)
    base = {"q": marker, "group_by_candidate": "true"}

    start_asc = await _list(app_client, app_auth_headers, **base, sort_by="start_date")
    assert _first_names(start_asc) == ["Zenon", "Adam", "Marek"]

    end_asc = await _list(
        app_client, app_auth_headers, **base, sort_by="order_end_date"
    )
    assert _first_names(end_asc) == ["Marek", "Adam", "Zenon"]
    end_desc = await _list(
        app_client,
        app_auth_headers,
        **base,
        sort_by="order_end_date",
        sort_dir="desc",
    )
    # Bezterminowe zamówienie nie jest „najpóźniejsze" — zostaje na końcu.
    assert _first_names(end_desc) == ["Adam", "Marek", "Zenon"]


async def test_sort_by_rates_and_margin(
    app_client: AsyncClient, app_auth_headers: dict
):
    marker = f"Srr{uuid.uuid4().hex[:6]}"
    await _seed_three(marker)
    base = {"q": marker, "group_by_candidate": "true"}

    cost = await _list(app_client, app_auth_headers, **base, sort_by="rate_candidate")
    assert _first_names(cost) == ["Marek", "Adam", "Zenon"]
    revenue = await _list(
        app_client, app_auth_headers, **base, sort_by="rate_client", sort_dir="desc"
    )
    assert _first_names(revenue) == ["Zenon", "Adam", "Marek"]
    margin = await _list(app_client, app_auth_headers, **base, sort_by="margin")
    # Marże: Marek 20, Adam 50, Zenon 80.
    assert _first_names(margin) == ["Marek", "Adam", "Zenon"]


async def test_rate_sort_is_ignored_for_role_without_finance(
    app_client: AsyncClient,
):
    """Delivery Lead bez VIEW_FINANCE: kolejność po stawce byłaby wyrocznią."""
    from sqlalchemy import select

    from app.models.team_structure import DeliveryLeadClientAssignment

    marker = f"Srf{uuid.uuid4().hex[:6]}"
    ids = await _seed_three(marker)
    first_client = ids["client:Adam"]
    headers = await _role_headers(
        app_client, "delivery_lead", assigned_client_id=first_client
    )
    async with AsyncSessionLocal() as db:
        dl_user_id = (
            await db.execute(
                select(DeliveryLeadClientAssignment.delivery_lead_user_id).where(
                    DeliveryLeadClientAssignment.client_id == first_client
                )
            )
        ).scalar_one()
        for name in ("Zenon", "Marek"):
            db.add(
                DeliveryLeadClientAssignment(
                    delivery_lead_user_id=dl_user_id,
                    client_id=ids[f"client:{name}"],
                )
            )
        await db.commit()
    body = await _list(
        app_client,
        headers,
        q=marker,
        group_by_candidate="true",
        sort_by="rate_client",
        sort_dir="desc",
    )
    # Kolejność domyślna (najnowszy kontrakt najpierw), nie po ukrytej stawce.
    expected = sorted((ids["Adam"], ids["Zenon"], ids["Marek"]), reverse=True)
    assert [row["id"] for row in body["items"]] == expected


async def test_unknown_sort_key_is_rejected(
    app_client: AsyncClient, app_auth_headers: dict
):
    resp = await app_client.get(
        "/api/contracts",
        params={"sort_by": "id; DROP TABLE contracts"},
        headers=app_auth_headers,
    )
    assert resp.status_code == 422


async def test_date_filters_combine_with_status_and_search(
    app_client: AsyncClient, app_auth_headers: dict
):
    marker = f"Srw{uuid.uuid4().hex[:6]}"
    ids = await _seed_three(marker)
    base = {"q": marker, "group_by_candidate": "true"}

    ending = await _list(
        app_client,
        app_auth_headers,
        **base,
        order_end_from="2026-06-01",
        order_end_to="2026-07-31",
    )
    assert [row["id"] for row in ending["items"]] == [ids["Marek"]]

    started = await _list(
        app_client,
        app_auth_headers,
        **base,
        start_from="2026-01-01",
        sort_by="start_date",
    )
    assert _first_names(started) == ["Adam", "Marek"]

    async with AsyncSessionLocal() as db:
        contract = await db.get(Contract, ids["Adam"])
        contract.status = ContractStatus.draft
        await db.commit()
    active_only = await _list(
        app_client,
        app_auth_headers,
        **base,
        status="active",
        start_from="2026-01-01",
    )
    assert [row["id"] for row in active_only["items"]] == [ids["Marek"]]


async def test_rate_sort_follows_the_displayed_schedule_rate_not_the_cache(
    app_client: AsyncClient, app_auth_headers: dict
):
    """Produkcja 21.09: kolumna cache ``rate_client`` różniła się od stawki
    z harmonogramu, więc wiersze stały nie po kolei względem tego, co widać."""
    from datetime import timedelta

    from app.models.contract_client_rate import ContractClientRate

    marker = f"Srs{uuid.uuid4().hex[:6]}"
    ids = await _seed_three(marker)
    today = business_today()
    async with AsyncSessionLocal() as db:
        # Zenon: cache 200, ale od wczoraj obowiązuje 90 (najniższa ze wszystkich),
        # a przyszły krok 500 nie może jeszcze liczyć się do sortowania.
        db.add(
            ContractClientRate(
                contract_id=ids["Zenon"],
                rate=90,
                effective_from=today - timedelta(days=1),
            )
        )
        db.add(
            ContractClientRate(
                contract_id=ids["Zenon"],
                rate=500,
                effective_from=today + timedelta(days=30),
            )
        )
        await db.commit()

    body = await _list(
        app_client,
        app_auth_headers,
        q=marker,
        group_by_candidate="true",
        sort_by="rate_client",
    )
    assert _first_names(body) == ["Zenon", "Marek", "Adam"]
    shown = [row["rate_client"] for row in body["items"]]
    assert shown == sorted(shown)
