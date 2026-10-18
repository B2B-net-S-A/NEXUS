"""„Do faktury” z zamówień (E8): MD × stawka, okresowe wg jednostki, kosztowe, pula MD.

Kosztowe: kwotę faktury ustalają Finanse, NEXUS sprawdza fakturę z KSeF
z resztą budżetu zamówienia.

Dane fikcyjne (``tests/client_invoicing/helpers.py``).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.core.database import AsyncSessionLocal
from app.models.client_order import ClientOrderStatus
from app.models.client_order_group import (
    ClientOrderGroup,
    ClientOrderGroupMdConsumption,
)
from app.models.client_sales_invoice import ClientSalesInvoice
from app.models.contract import Contract, ContractStatus, RateUnit
from app.models.md_consumption import ClientOrderInvoiceConsumption
from app.services.client_invoicing.billing import billing_rows, order_refs
from app.services.client_invoicing.matching import Target, auto_match
from app.services.client_invoicing.views import month_view
from app.services.cost_orders import settle_group
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


async def _cost_order(db, client_id: int, *, sheet: dict[str, str]) -> tuple[int, int]:
    """Zamówienie kosztowe 500 000 zł z fakturami z arkusza Finansów (miesiąc → kwota)."""

    group_id, (line_id,) = await fx.md_group(
        db,
        client_id,
        "SAP 4500000001",
        people=[("Marta", "Kosztowa", "1100", None)],
        cost=True,
    )
    for period, amount in sheet.items():
        db.add(
            ClientOrderInvoiceConsumption(
                order_id=line_id,
                period_month=period,
                invoice_amount=Decimal(amount),
                source="import",
            )
        )
    await db.flush()
    await settle_group(db, await db.get(ClientOrderGroup, group_id))
    return group_id, line_id


async def test_cost_order_shows_its_budget_instead_of_md_times_rate():
    """Kosztowe rozlicza fakturę, nie MD: kwotę ustalają Finanse, NEXUS pokazuje budżet."""

    seed = await fx.seed_month()
    async with AsyncSessionLocal() as db:
        group_id, _line = await _cost_order(
            db,
            seed.other_client_id,
            sheet={"2026-09": "120000", "2026-10": "11000", "2026-11": "5000"},
        )
        await db.commit()
        refs = await order_refs(db, [seed.other_client_id])
    row = (await _rows(seed.other_client_id))["SAP 4500000001"]
    assert row.kind == "cost"
    assert row.expected_net is None
    # Nie „czeka na zużycie MD” — zużycia MD na zamówieniu kosztowym nie będzie.
    assert row.missing == 0
    (line,) = row.lines
    assert (line.basis, line.net, line.quantity) == ("cost", None, None)
    assert line.consultant == "Marta Kosztowa"
    assert line.note == "zamówienie kosztowe — kwotę faktury ustalają Finanse"
    # Budżet przed fakturami za październik: 500 000 − wrzesień (listopad nie liczy się wstecz).
    assert row.budget is not None
    assert (row.budget.amount, row.budget.available) == (
        Decimal("500000.00"),
        Decimal("380000.00"),
    )
    assert row.sheet_invoiced == Decimal("11000.00")
    ref = next(r for r in refs if r.group_id == group_id)
    assert ref.variants() == ("SAP 4500000001", "4500000001")


async def test_cost_budget_counts_manual_adjustment_and_never_goes_negative():
    seed = await fx.seed_month()
    async with AsyncSessionLocal() as db:
        group_id, _line = await _cost_order(
            db, seed.other_client_id, sheet={"2026-08": "450000", "2026-09": "90000"}
        )
        group = await db.get(ClientOrderGroup, group_id)
        group.budget_manual_adjustment = Decimal("20000")
        await settle_group(db, group)
        await db.commit()
    row = (await _rows(seed.other_client_id))["SAP 4500000001"]
    # Pula 520 000 rozliczona w całości przed październikiem — zostaje 0, nie −20 000.
    assert row.budget.available == Decimal("0.00")
    september = (await _rows(seed.other_client_id, 2026, 9))["SAP 4500000001"]
    assert september.budget.available == Decimal("70000.00")


async def test_legacy_md_flag_without_mode_bills_each_person_not_a_pool():
    """Flaga z 0246 bez ``md_budget_mode`` u zwykłego klienta to MD per osoba."""

    seed = await fx.seed_month()
    async with AsyncSessionLocal() as db:
        group_id, _lines = await fx.md_group(
            db,
            seed.other_client_id,
            "MD-STARE",
            people=[("Ala", "Starsza", "1000", "10"), ("Ola", "Starsza", "1200", "5")],
        )
        group = await db.get(ClientOrderGroup, group_id)
        group.order_type = None
        group.md_budget_mode = None
        group.is_md_budget_based = True
        group.md_budget_total = Decimal("100")
        group.md_budget_remaining = Decimal("100")
        await db.commit()
    row = (await _rows(seed.other_client_id))["MD-STARE"]
    assert [line.net for line in row.lines] == [
        Decimal("10000.00"),
        Decimal("6000.00"),
    ]
    assert row.expected_net == Decimal("16000.00")


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


def _sales_invoice(net: str, *, ksef: str, refs: list[str]) -> ClientSalesInvoice:
    return ClientSalesInvoice(
        ksef_number=ksef,
        xml_sha256="a" * 64,
        buyer_nip=fx.OTHER_CLIENT_NIP,
        invoice_number="FS 10/501/2026",
        issue_date=date(2026, 11, 3),
        period_year=2026,
        period_month=10,
        period_source="invoice",
        currency="PLN",
        net_amount=Decimal(net),
        vat_amount=Decimal("0"),
        gross_amount=Decimal(net),
        items=[{"name": "Usługi programistyczne"}],
        order_refs=refs,
    )


async def _month(client_id: int) -> dict:
    async with AsyncSessionLocal() as db:
        return await month_view(
            db, year=2026, month=10, client_ids=[client_id], today=date(2026, 11, 20)
        )


async def test_cost_invoice_bound_by_number_fits_the_remaining_budget_or_waits():
    """Faktura z numerem zamówienia kosztowego: w budżecie = zgodna, ponad = Finanse."""

    seed = await fx.seed_month()
    async with AsyncSessionLocal() as db:
        group_id, _line = await _cost_order(
            db, seed.other_client_id, sheet={"2026-09": "120000", "2026-10": "30000"}
        )
        invoice = _sales_invoice(
            "30000.00",
            ksef=f"{fx.COMPANY_NIP}-20261103-C0570C0FFEE1-01",
            refs=["Zamówienie SAP 4500000001"],
        )
        db.add(invoice)
        await db.flush()
        decision = await auto_match(db, invoice)
        invoice_id = invoice.id
        await db.commit()
    assert decision.targets == (Target(group_id=group_id),)

    view = await _month(seed.other_client_id)
    row = next(item for item in view["rows"] if item["key"] == f"g{group_id}")
    assert (row["status"], row["status_label"]) == ("ok", "mieści się w budżecie")
    assert row["expected_net"] is None and row["missing"] == 0
    assert row["budget"] == {"amount": "500000.00", "available": "380000.00"}
    (paid,) = view["invoices"]
    assert (paid["check"], paid["check_basis"]) == ("ok", "budget")
    assert view["summary"]["unknown"] == 0 and view["summary"]["cost"] == 1

    # 400 000 przy 380 000 do wykorzystania: nadwyżka 20 000 do sprawdzenia.
    async with AsyncSessionLocal() as db:
        stored = await db.get(ClientSalesInvoice, invoice_id)
        stored.net_amount = stored.gross_amount = Decimal("400000.00")
        await db.commit()
    view = await _month(seed.other_client_id)
    row = next(item for item in view["rows"] if item["key"] == f"g{group_id}")
    assert (row["status"], row["difference"]) == ("difference", "20000.00")
    assert row["status_label"] == "ponad budżet — do sprawdzenia"
    (over,) = view["invoices"]
    assert (over["check"], over["difference"]) == ("difference", "20000.00")

    # Faktura z KSeF nie schodzi z budżetu zamówienia (decyzja otwarta).
    async with AsyncSessionLocal() as db:
        sheet_rows = await db.scalar(
            select(func.count())
            .select_from(ClientOrderInvoiceConsumption)
            .join(
                fx.ClientOrder,
                fx.ClientOrder.id == ClientOrderInvoiceConsumption.order_id,
            )
            .where(fx.ClientOrder.order_group_id == group_id)
        )
    assert sheet_rows == 2
