"""Zamówienia MD w obcej walucie: „do faktury” w walucie stawki, bez kursu.

``md_rate_revenue`` linii jest zawsze w PLN/MD (materializator przelicza kursem
z dnia startu), a stawkę z zamówienia niesie ``rate_client``. Faktura w EUR
porównana z wierszem „PLN” czekała na Finanse z powodem ``currency_differs``.

Dane fikcyjne (``tests/client_invoicing/helpers.py``).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.core.database import AsyncSessionLocal
from app.models.client_order import ClientOrder
from app.models.client_order_group import (
    ClientOrderGroup,
    ClientOrderGroupMdConsumption,
)
from app.models.client_sales_invoice import ClientSalesInvoice
from app.models.contract import RateUnit
from app.models.md_consumption import (
    IMPORT_ROW_APPLIED,
    MdConsumptionImport,
    MdConsumptionImportRow,
)
from app.services.client_invoicing import matching
from app.services.client_invoicing.billing import billing_rows
from app.services.client_invoicing.matching import Target, auto_match
from tests.client_invoicing import helpers as fx

pytestmark = pytest.mark.asyncio

_KSEF_TAIL = "C0570C0FFEE1"


async def _foreign_group(
    client_id: int,
    number: str,
    *,
    people: list[tuple[str, str, str, str | None, str | None, str]],
    unit: RateUnit = RateUnit.daily,
) -> tuple[int, list[int]]:
    """(imię, nazwisko, stawka PLN/MD, zużycie MD, stawka klienta, waluta)."""

    async with AsyncSessionLocal() as db:
        group_id, line_ids = await fx.md_group(
            db,
            client_id,
            number,
            people=[(first, last, pln, md) for first, last, pln, md, _r, _c in people],
        )
        for line_id, (*_person, rate, currency) in zip(line_ids, people):
            line = await db.get(ClientOrder, line_id)
            line.rate_client = Decimal(rate) if rate is not None else None
            line.rate_client_currency = currency
            line.currency = currency
            line.rate_unit = unit
        await db.commit()
    return group_id, line_ids


async def _row(client_id: int, number: str):
    async with AsyncSessionLocal() as db:
        rows = await billing_rows(db, year=2026, month=10, client_ids=[client_id])
    return next(row for row in rows if row.order_number == number)


def _invoice(
    net: str, *, suffix: str, refs: list[str], currency: str
) -> ClientSalesInvoice:
    return ClientSalesInvoice(
        ksef_number=f"{fx.COMPANY_NIP}-20261103-{_KSEF_TAIL}-{suffix}",
        xml_sha256="b" * 64,
        buyer_nip=fx.OTHER_CLIENT_NIP,
        invoice_number=f"FS 10/{suffix}/2026",
        issue_date=date(2026, 11, 3),
        period_year=2026,
        period_month=10,
        period_source="invoice",
        currency=currency,
        net_amount=Decimal(net),
        vat_amount=Decimal("0"),
        gross_amount=Decimal(net),
        items=[{"name": "IT services"}],
        order_refs=refs,
    )


async def _match(invoice: ClientSalesInvoice):
    async with AsyncSessionLocal() as db:
        db.add(invoice)
        await db.flush()
        decision = await auto_match(db, invoice)
        await db.commit()
    return decision


async def test_eur_line_is_billed_in_eur_from_the_client_rate():
    seed = await fx.seed_month()
    await _foreign_group(
        seed.other_client_id,
        "EUR-1",
        people=[("Ala", "Walutowa", "1075.250", "20.5", "250", "EUR")],
    )
    row = await _row(seed.other_client_id, "EUR-1")
    assert row.currency == "EUR"
    (line,) = row.lines
    assert line.currency == "EUR"
    assert line.unit_price == Decimal("250")
    assert line.net == Decimal("5125.00")
    assert row.expected_net == Decimal("5125.00")


async def test_eur_invoice_matches_the_eur_order_by_number():
    seed = await fx.seed_month()
    group_id, _lines = await _foreign_group(
        seed.other_client_id,
        "90000011",
        people=[("Ala", "Walutowa", "1075.250", "20.5", "250", "EUR")],
    )
    decision = await _match(
        _invoice("5125.00", suffix="01", refs=["PO Number 90000011"], currency="EUR")
    )
    assert decision.targets == (Target(group_id=group_id),)
    assert decision.method == "order_number"


async def test_eur_invoice_matches_by_amount_without_a_number():
    seed = await fx.seed_month()
    group_id, _lines = await _foreign_group(
        seed.other_client_id,
        "90000012",
        people=[("Ala", "Walutowa", "1075.250", "20.5", "250", "EUR")],
    )
    decision = await _match(_invoice("5125.00", suffix="02", refs=[], currency="EUR"))
    assert decision.targets == (Target(group_id=group_id),)
    assert decision.method == "amount"


async def test_pln_invoice_for_an_eur_order_still_waits_for_finance():
    """Równowartość w PLN nie jest kwotą zamówienia: bez kursu, bez zgadywania."""

    seed = await fx.seed_month()
    await _foreign_group(
        seed.other_client_id,
        "90000013",
        people=[("Ala", "Walutowa", "1075.250", "20.5", "250", "EUR")],
    )
    decision = await _match(
        _invoice("22042.63", suffix="03", refs=["PO 90000013"], currency="PLN")
    )
    assert not decision.matched
    assert decision.reason == "currency_differs"


async def test_eur_line_without_client_rate_has_no_amount_and_no_pln_fallback():
    seed = await fx.seed_month()
    await _foreign_group(
        seed.other_client_id,
        "EUR-2",
        people=[("Ala", "Walutowa", "1075.250", "20.5", None, "EUR")],
    )
    row = await _row(seed.other_client_id, "EUR-2")
    assert row.currency == "EUR"
    (line,) = row.lines
    assert (line.unit_price, line.net) == (None, None)
    assert row.expected_net is None


async def test_eur_hourly_rate_becomes_a_rate_per_md():
    seed = await fx.seed_month()
    await _foreign_group(
        seed.other_client_id,
        "EUR-3",
        people=[("Ala", "Walutowa", "400", "10", "10", "EUR")],
        unit=RateUnit.hourly,
    )
    (line,) = (await _row(seed.other_client_id, "EUR-3")).lines
    assert (line.unit_price, line.net) == (Decimal("80"), Decimal("800.00"))


async def test_eur_line_waiting_for_md_keeps_the_eur_rate():
    seed = await fx.seed_month()
    await _foreign_group(
        seed.other_client_id,
        "EUR-4",
        people=[("Ala", "Walutowa", "1075.250", None, "250", "EUR")],
    )
    row = await _row(seed.other_client_id, "EUR-4")
    (line,) = row.lines
    assert (line.currency, line.unit_price, line.net) == (
        "EUR",
        Decimal("250"),
        None,
    )


async def test_pln_line_keeps_the_md_rate_even_when_client_rate_differs():
    """Linia w PLN: dalej ``md_rate_revenue``, zachowanie bez zmian."""

    seed = await fx.seed_month()
    await _foreign_group(
        seed.other_client_id,
        "PLN-1",
        people=[("Ala", "Krajowa", "1000", "10", "950", "PLN")],
    )
    row = await _row(seed.other_client_id, "PLN-1")
    assert row.currency == "PLN"
    assert row.expected_net == Decimal("10000.00")


async def test_order_with_lines_in_two_currencies_stays_in_pln():
    """Suma EUR + PLN nie ma sensu: wiersz zostaje na stawkach PLN/MD."""

    seed = await fx.seed_month()
    await _foreign_group(
        seed.other_client_id,
        "MIX-1",
        people=[
            ("Ala", "Walutowa", "1000", "10", "250", "EUR"),
            ("Ola", "Krajowa", "900", "10", "900", "PLN"),
        ],
    )
    row = await _row(seed.other_client_id, "MIX-1")
    assert row.currency == "PLN"
    assert {line.currency for line in row.lines} == {"PLN"}
    assert row.expected_net == Decimal("19000.00")


async def _pool(group_id: int, md: str, breakdown: list[dict] | None) -> None:
    async with AsyncSessionLocal() as db:
        group = await db.get(ClientOrderGroup, group_id)
        group.is_md_budget_based = True
        group.md_budget_mode = "shared"
        group.md_budget_total = Decimal("100")
        group.md_budget_remaining = Decimal("70")
        db.add(
            ClientOrderGroupMdConsumption(
                group_id=group_id,
                period_month="2026-10",
                md_reported=Decimal(md),
                source="import",
                breakdown=breakdown,
            )
        )
        await db.commit()


async def test_shared_pool_with_breakdown_is_billed_in_eur():
    seed = await fx.seed_month()
    group_id, (first, second) = await _foreign_group(
        seed.other_client_id,
        "POOL-1",
        people=[
            ("Ala", "Pulowa", "1100.500", None, "260", "EUR"),
            ("Ola", "Pulowa", "1100.500", None, "260", "EUR"),
        ],
    )
    await _pool(
        group_id,
        "16",
        [{"order_id": first, "md": "6.5"}, {"order_id": second, "md": "9.5"}],
    )
    row = await _row(seed.other_client_id, "POOL-1")
    assert row.currency == "EUR"
    assert [line.net for line in row.lines] == [
        Decimal("1690.00"),
        Decimal("2470.00"),
    ]


async def test_shared_pool_without_breakdown_needs_one_eur_rate():
    seed = await fx.seed_month()
    same, _lines = await _foreign_group(
        seed.other_client_id,
        "POOL-2",
        people=[
            ("Ala", "Pulowa", "1100.500", None, "260", "EUR"),
            ("Ola", "Pulowa", "1100.500", None, "260", "EUR"),
        ],
    )
    await _pool(same, "10", None)
    row = await _row(seed.other_client_id, "POOL-2")
    assert row.currency == "EUR"
    (line,) = row.lines
    assert (line.currency, line.unit_price, line.net) == (
        "EUR",
        Decimal("260"),
        Decimal("2600.00"),
    )

    # Ta sama stawka PLN przy różnych stawkach EUR: kwoty nie da się policzyć.
    different, _lines = await _foreign_group(
        seed.other_client_id,
        "POOL-3",
        people=[
            ("Iga", "Pulowa", "1100.500", None, "260", "EUR"),
            ("Eda", "Pulowa", "1100.500", None, "240", "EUR"),
        ],
    )
    await _pool(different, "10", None)
    row = await _row(seed.other_client_id, "POOL-3")
    assert row.currency == "EUR"
    (line,) = row.lines
    assert line.net is None


async def _import_rows(group_id: int, rows: list[tuple[int, str]]) -> None:
    """Zastosowane wiersze importu MD za październik: (linia, MD)."""

    async with AsyncSessionLocal() as db:
        batch = MdConsumptionImport(period_month="2026-10", filename="md.xlsx")
        db.add(batch)
        await db.flush()
        db.add_all(
            MdConsumptionImportRow(
                import_id=batch.id,
                row_number=number,
                consultant_name="Osoba z arkusza",
                md_reported=Decimal(md),
                status=IMPORT_ROW_APPLIED,
                matched_order_id=line_id,
                matched_group_id=group_id,
            )
            for number, (line_id, md) in enumerate(rows, start=1)
        )
        await db.commit()


async def _imported_pool(client_id: int, number: str, md: str, rows: list[str]):
    """Pula z importu bez ``breakdown``; wiersze importu po kolei na osoby."""

    group_id, line_ids = await _foreign_group(
        client_id,
        number,
        people=[
            ("Ala", "Pulowa", "1100.500", None, "300", "EUR"),
            ("Ola", "Pulowa", "1100.500", None, "300", "EUR"),
        ],
    )
    await _pool(group_id, md, None)
    await _import_rows(group_id, list(zip(line_ids, rows)))
    return group_id, line_ids


async def test_shared_pool_from_import_is_billed_per_person():
    """Ta sama reguła co ekran zamówienia: podział z wierszy importu."""

    seed = await fx.seed_month()
    _group, (first, second) = await _imported_pool(
        seed.other_client_id, "POOL-4", "18", ["10", "8"]
    )
    row = await _row(seed.other_client_id, "POOL-4")
    assert [(line.order_id, line.net) for line in row.lines] == [
        (first, Decimal("3000.00")),
        (second, Decimal("2400.00")),
    ]


async def test_import_rows_not_adding_up_stay_one_pool_line():
    """Suma wierszy inna niż zejście puli: osobom nie przypisujemy tych liczb."""

    seed = await fx.seed_month()
    await _imported_pool(seed.other_client_id, "POOL-5", "18", ["10", "7"])
    row = await _row(seed.other_client_id, "POOL-5")
    (line,) = row.lines
    assert (line.order_id, line.net) == (None, Decimal("5400.00"))


async def test_person_invoice_binds_to_import_split_when_number_is_on_two_groups():
    """Numer na dwóch grupach, kwota jednej osoby z miesiąca z importu."""

    seed = await fx.seed_month()
    _group, (first, _second) = await _imported_pool(
        seed.other_client_id, "90000033", "18", ["10", "8"]
    )
    other, (third,) = await _foreign_group(
        seed.other_client_id,
        "90000033",
        people=[("Iga", "Pulowa", "1100.500", None, "220", "EUR")],
    )
    await _pool(other, "5", [{"order_id": third, "md": "5"}])

    decision = await _match(
        _invoice("3000.00", suffix="33", refs=["PO 90000033"], currency="EUR")
    )
    assert decision.targets == (Target(order_id=first),)
    assert decision.method == "order_number"


async def test_invoices_stuck_on_currency_get_another_try():
    """Po poprawce albo zmianie waluty zamówienia faktura wraca do automatu."""

    await fx.seed_month()
    invoice = _invoice("100.00", suffix="04", refs=[], currency="EUR")
    invoice.match_status = "unmatched"
    invoice.match_reason = "currency_differs"
    async with AsyncSessionLocal() as db:
        db.add(invoice)
        await db.commit()
        waiting = await matching._rematch_batch(db, 0, 10_000)
    assert invoice.id in waiting
