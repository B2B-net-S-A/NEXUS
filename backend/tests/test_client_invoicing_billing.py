"""„Do faktury” z zamówień (E8): MD × stawka, okresowe wg jednostki, kosztowe, pula MD.

Dane fikcyjne (``tests/client_invoicing/helpers.py``).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.core.database import AsyncSessionLocal
from app.models.client_order import ClientOrderStatus
from app.models.client_order_group import (
    ClientOrderGroup,
    ClientOrderGroupMdConsumption,
)
from app.models.contract import Contract, ContractStatus, RateUnit
from app.models.md_consumption import ClientOrderInvoiceConsumption
from app.services.client_invoicing.billing import billing_rows, order_refs
from tests.client_invoicing import helpers as fx

pytestmark = pytest.mark.asyncio


async def _rows(client_id: int, year: int = 2026, month: int = 10):
    async with AsyncSessionLocal() as db:
        rows = await billing_rows(db, year=year, month=month, client_ids=[client_id])
    return {row.order_number: row for row in rows}


async def test_month_rows_follow_orders_md_and_hours():
    seed = await fx.seed_month()
    rows = await _rows(seed.client_id)
    assert set(rows) == {"ZAM/2026/118", "ZAM/2026/121", "ZAM/2026/124", "ZAM/2026/130"}
    assert rows["ZAM/2026/118"].expected_net == Decimal("25200.00")
    assert rows["ZAM/2026/124"].expected_net == Decimal("22425.00")
    hourly = rows["ZAM/2026/121"]
    assert hourly.kind == "periodic"
    (line,) = hourly.lines
    assert (line.quantity, line.unit, line.net) == (
        Decimal("168.00"),
        "h",
        Decimal("31920.00"),
    )
    assert "168 h" in (line.note or "")
    # Innego klienta wiersze nie wchodzą.
    assert await _rows(seed.other_client_id) == {}


async def test_person_without_md_usage_makes_the_amount_unknown_not_lower():
    seed = await fx.seed_month()
    async with AsyncSessionLocal() as db:
        await fx.md_group(
            db,
            seed.client_id,
            "445",
            people=[
                ("Ola", "Wzorcowa", "1000", "10"),
                ("Piotr", "Przykładowy", "900", None),
            ],
        )
        await db.commit()
    row = (await _rows(seed.client_id))["445"]
    assert row.expected_net is None
    assert row.missing == 1
    waiting = [line for line in row.lines if line.net is None]
    assert waiting[0].note == "czeka na zużycie MD za miesiąc"


async def test_partial_month_daily_and_monthly_rates():
    seed = await fx.seed_month()
    async with AsyncSessionLocal() as db:
        await fx.periodic_order(
            db,
            seed.other_client_id,
            "PO-MIES",
            rate="21000",
            unit=RateUnit.monthly,
            start=date(2026, 11, 16),
        )
        await fx.periodic_order(
            db, seed.other_client_id, "PO-DZIEN", rate="1000", unit=RateUnit.daily
        )
        await fx.periodic_order(
            db,
            seed.other_client_id,
            "PO-WSTRZYMANE",
            rate="1000",
            unit=RateUnit.daily,
            status=ClientOrderStatus.paused,
        )
        await fx.periodic_order(
            db,
            seed.other_client_id,
            "PO-PRZESZLE",
            rate="1000",
            unit=RateUnit.daily,
            end=date(2026, 10, 31),
        )
        await db.commit()
    rows = await _rows(seed.other_client_id, 2026, 11)
    assert set(rows) == {"PO-MIES", "PO-DZIEN"}
    (monthly,) = rows["PO-MIES"].lines
    # 11 z 20 dni roboczych listopada × 21 000.
    assert monthly.net == Decimal("11550.00")
    assert monthly.note == "częściowy miesiąc: 11 z 20 dni roboczych"
    (daily,) = rows["PO-DZIEN"].lines
    assert (daily.quantity, daily.net) == (Decimal("21.00"), Decimal("21000.00"))


async def test_void_contract_and_cancelled_group_are_not_invoiced():
    seed = await fx.seed_month()
    async with AsyncSessionLocal() as db:
        group = await db.get(ClientOrderGroup, seed.groups["130"])
        group.status = "cancelled"
        group.status_before_cancel = "active"
        order = await db.get(fx.ClientOrder, seed.orders["121"])
        contract = await db.get(Contract, order.contract_id)
        contract.status = ContractStatus.void
        await db.commit()
    rows = await _rows(seed.client_id)
    assert set(rows) == {"ZAM/2026/118", "ZAM/2026/124"}


async def test_cost_order_keeps_finance_sheet_amount_as_fallback():
    seed = await fx.seed_month()
    async with AsyncSessionLocal() as db:
        group_id, (line_id,) = await fx.md_group(
            db,
            seed.other_client_id,
            "SAP 4500000001",
            people=[("Marta", "Kosztowa", "1100", "10")],
            cost=True,
        )
        db.add(
            ClientOrderInvoiceConsumption(
                order_id=line_id,
                period_month="2026-10",
                invoice_amount=Decimal("11000"),
                settled_amount=Decimal("11000"),
                source="import",
            )
        )
        await db.commit()
        refs = await order_refs(db, [seed.other_client_id])
    row = (await _rows(seed.other_client_id))["SAP 4500000001"]
    assert row.kind == "cost"
    assert row.expected_net == Decimal("11000.00")
    assert row.sheet_invoiced == Decimal("11000.00")
    ref = next(r for r in refs if r.group_id == group_id)
    assert ref.variants() == ("SAP 4500000001", "4500000001")


async def test_shared_pool_uses_breakdown_or_single_rate():
    seed = await fx.seed_month()
    async with AsyncSessionLocal() as db:
        group_id, (first, second) = await fx.md_group(
            db,
            seed.other_client_id,
            "PULA-1",
            people=[("Ala", "Pulowa", "1000", None), ("Ola", "Pulowa", "1000", None)],
        )
        group = await db.get(ClientOrderGroup, group_id)
        group.is_md_budget_based = True
        group.md_budget_mode = "shared"
        group.md_budget_total = Decimal("100")
        group.md_budget_remaining = Decimal("70")
        pool = ClientOrderGroupMdConsumption(
            group_id=group_id,
            period_month="2026-10",
            md_reported=Decimal("30"),
            source="import",
        )
        db.add(pool)
        await db.commit()
    row = (await _rows(seed.other_client_id))["PULA-1"]
    (line,) = row.lines
    assert line.consultant.startswith("wspólna pula MD")
    assert row.expected_net == Decimal("30000.00")

    async with AsyncSessionLocal() as db:
        stored = await db.get(ClientOrderGroupMdConsumption, pool.id)
        stored.breakdown = [
            {"order_id": first, "md": "12"},
            {"order_id": second, "md": "18"},
        ]
        await db.commit()
    row = (await _rows(seed.other_client_id))["PULA-1"]
    assert [line.net for line in row.lines] == [
        Decimal("12000.00"),
        Decimal("18000.00"),
    ]
