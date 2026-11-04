"""Waluta w dzienniku zmian zamówień i w faktach Finansów (audyt 24.09.2026).

* N1 — sama zmiana waluty stawki (1000 PLN → 1000 EUR) to zmiana pieniędzy;
  dziennik jej nie widział (``old == new`` → ``continue``). Wpis niesie teraz
  walutę przed i po zmianie.
* S14 — linia zamówienia MD w walucie obcej: ``md_rate_*`` to kanoniczne
  PLN/MD, a fakt Finansów i wpis dziennika podpisywały je „PLN" nawet przy
  stawce źródłowej w EUR. Teraz idzie stawka źródłowa w walucie linii.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.models.client_order import ClientOrder, ClientOrderStatus
from app.models.contract import Contract, ContractStatus, ContractType, RateUnit
from app.services.order_facts import fact_from_row


def _row(**overrides) -> SimpleNamespace:
    values = dict(
        id=1,
        order_group_id=7,
        contract_id=2,
        candidate_id=3,
        client_id=4,
        client_name="Klient",
        candidate_first="Jan",
        candidate_last="Nowak",
        status="active",
        eff_start=date(2031, 1, 1),
        eff_end=date(2031, 12, 31),
        title="PO-1",
        order_number="PO-1",
        order_type=None,
        group_order_type="md",
        is_cost_based=False,
        rate_candidate=Decimal("100"),
        rate_client=Decimal("150"),
        md_rate_cost=Decimal("430"),
        md_rate_revenue=Decimal("645"),
        rate_unit=RateUnit.daily,
        rate_candidate_currency="EUR",
        rate_client_currency="EUR",
        currency="EUR",
        created_at=datetime(2031, 1, 1, tzinfo=timezone.utc),
        md_total=Decimal("100"),
        md_remaining=Decimal("50"),
    )
    values.update(overrides)
    return SimpleNamespace(**values)


def test_foreign_md_line_fact_carries_the_source_rate_in_its_currency():
    fact = fact_from_row(_row())
    assert (fact.rate_revenue, fact.currency) == (Decimal("150"), "EUR")
    assert fact.rate_unit == "daily"


def test_pln_md_line_fact_keeps_the_canonical_md_rate():
    fact = fact_from_row(
        _row(rate_candidate_currency="PLN", rate_client_currency="PLN", currency="PLN")
    )
    assert (fact.rate_revenue, fact.currency, fact.rate_unit) == (
        Decimal("645"),
        "PLN",
        "md",
    )


async def _seed_order(**order_fields) -> int:
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from app.models.client import Client

    suffix = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"Waluta {suffix}")
        candidate = Candidate(
            name="Jan", lastname=f"Waluta-{suffix}", email=f"w-{suffix}@example.com"
        )
        db.add_all([client, candidate])
        await db.flush()
        contract = Contract(
            candidate_id=candidate.id,
            client_id=client.id,
            contract_type=ContractType.b2b,
            status=ContractStatus.active,
            start_date=date(2031, 1, 1),
            rate_candidate=Decimal("100.000"),
            rate_unit=RateUnit.hourly,
            currency="PLN",
            rate_candidate_currency="PLN",
        )
        db.add(contract)
        await db.flush()
        group_id = None
        if order_fields.pop("in_group", False):
            from app.models.client_order_group import ClientOrderGroup

            group = ClientOrderGroup(
                client_id=client.id,
                order_number=f"G-{suffix}",
                start_date=date(2031, 1, 1),
                end_date=date(2031, 12, 31),
                status="active",
                order_type="md",
            )
            db.add(group)
            await db.flush()
            group_id = group.id
        order = ClientOrder(
            client_id=client.id,
            contract_id=contract.id,
            order_group_id=group_id,
            title=f"PO-{suffix}",
            status=ClientOrderStatus.active,
            start_date=date(2031, 1, 1),
            end_date=date(2031, 12, 31),
            **order_fields,
        )
        db.add(order)
        await db.commit()
        return order.id


async def _events(order_id: int):
    from app.core.database import AsyncSessionLocal
    from app.models.order_change_event import OrderChangeEvent

    async with AsyncSessionLocal() as db:
        return list(
            (
                await db.scalars(
                    select(OrderChangeEvent)
                    .where(OrderChangeEvent.order_id == order_id)
                    .order_by(OrderChangeEvent.id)
                )
            ).all()
        )


@pytest.mark.asyncio
async def test_currency_only_change_is_recorded_with_both_currencies():
    from app.core.database import AsyncSessionLocal

    order_id = await _seed_order(
        rate_unit=RateUnit.daily,
        rate_client=Decimal("1000.000"),
        rate_client_currency="PLN",
        currency="PLN",
    )
    async with AsyncSessionLocal() as db:
        order = await db.get(ClientOrder, order_id)
        order.rate_client_currency = "EUR"
        order.currency = "EUR"
        await db.commit()

    [event] = [e for e in await _events(order_id) if e.field == "rate_revenue"]
    assert (event.old_amount, event.new_amount) == (Decimal("1000"), Decimal("1000"))
    assert (event.old_currency, event.currency) == ("PLN", "EUR")


@pytest.mark.asyncio
async def test_foreign_md_line_rate_change_is_logged_in_the_line_currency():
    from app.core.database import AsyncSessionLocal

    order_id = await _seed_order(
        in_group=True,
        rate_unit=RateUnit.daily,
        rate_client=Decimal("150.000"),
        rate_client_currency="EUR",
        currency="EUR",
        md_rate_revenue=Decimal("645.000"),
        md_input_mode="md",
        md_input_value=Decimal("100"),
        md_total=Decimal("100"),
        md_remaining=Decimal("100"),
    )
    async with AsyncSessionLocal() as db:
        order = await db.get(ClientOrder, order_id)
        order.rate_client = Decimal("160.000")
        order.md_rate_revenue = Decimal("688.000")
        await db.commit()

    [event] = [e for e in await _events(order_id) if e.field == "rate_revenue"]
    assert (event.old_amount, event.new_amount) == (Decimal("150"), Decimal("160"))
    assert event.currency == "EUR"


# ── Stara strona zmiany w SWOJEJ walucie (audyt 25.09.2026) ─────────────────


def _change_item(**overrides):
    from app.schemas.finance_order_changes import OrderChangeItem

    values = dict(
        client_name="Klient",
        consultant_name="Jan Nowak",
        order_number="PO-1",
        kind="rate_revenue",
        old_amount=Decimal("1000"),
        new_amount=Decimal("1000"),
        old_unit="daily",
        new_unit="daily",
        currency="EUR",
        old_currency="PLN",
    )
    values.update(overrides)
    return OrderChangeItem(**values)


def test_export_renders_the_old_side_in_its_own_currency():
    from app.services.finance_order_changes import _change_description

    label, before, after = _change_description(_change_item())
    assert label == "Zmiana stawki przychodowej"
    assert before == "1 000,00 PLN/dzień"
    assert after == "1 000,00 EUR/dzień"


def test_export_without_old_currency_falls_back_to_the_new_one():
    from app.services.finance_order_changes import _change_description

    _, before, _ = _change_description(_change_item(old_currency=None))
    assert before == "1 000,00 EUR/dzień"


def test_order_history_summary_renders_the_old_side_in_its_own_currency():
    from app.services.order_change_checks import _event_summary

    event = SimpleNamespace(
        field="rate_revenue",
        old_amount=Decimal("1000"),
        new_amount=Decimal("1000"),
        old_unit="daily",
        new_unit="daily",
        currency="EUR",
        old_currency="PLN",
        old_date=None,
        new_date=None,
    )
    assert _event_summary(event) == (
        "Zmiana stawki przychodowej: 1 000,00 PLN/dzień → 1 000,00 EUR/dzień"
    )


@pytest.mark.asyncio
async def test_finance_changes_tab_carries_the_old_currency(
    app_client, app_auth_headers
):
    from app.core.database import AsyncSessionLocal
    from app.core.scheduling import business_today

    order_id = await _seed_order(
        rate_unit=RateUnit.daily,
        rate_client=Decimal("1000.000"),
        rate_client_currency="PLN",
        currency="PLN",
    )
    async with AsyncSessionLocal() as db:
        order = await db.get(ClientOrder, order_id)
        client_id = order.client_id
        order.rate_client_currency = "EUR"
        order.currency = "EUR"
        await db.commit()

    today = business_today()
    resp = await app_client.get(
        "/api/finance/order-changes",
        params={"year": today.year, "month": today.month, "client_id": client_id},
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    [item] = [
        c
        for c in resp.json()["changes"]
        if c["order_id"] == order_id and c["kind"] == "rate_revenue"
    ]
    assert (item["old_currency"], item["currency"]) == ("PLN", "EUR")
