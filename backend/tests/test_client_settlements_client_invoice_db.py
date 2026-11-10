"""Rozliczenia E5 na bazie: pozycje faktury do klienta, wystawiona faktura,
estymacja (plan miesiąca) i korekta na kolejnej fakturze. Dane fikcyjne."""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import delete, select

from app.core.database import AsyncSessionLocal
from app.core.scheduling import DEFAULT_TZ, business_today, local_now
from app.models.client_order import ClientOrder
from app.models.client_sales_invoice import ClientSalesInvoice, ClientSalesInvoiceLink
from app.models.client_settlement import ClientSettlementRuleSet
from app.models.md_consumption import ClientOrderMdConsumption
from app.services.client_settlements import client_invoice, consultant, service
from app.services.client_settlements.service import SettlementError
from app.services.hr.payroll_periods import add_months
from tests.test_client_settlements_consultant_db import _module, _restore
from tests.test_client_settlements_service_db import _cleanup, _world

pytestmark = pytest.mark.asyncio

ACTOR = SimpleNamespace(id=None)
BASE = "Usługi informatyczne; 999001; Tester, nr zamówienia: ZAM_TEST"


def _month(delta: int) -> str:
    today = business_today()
    year, mon = add_months(today.year, today.month, delta)
    return f"{year}-{mon:02d}"


async def _group(line_id: int) -> int:
    async with AsyncSessionLocal() as db:
        return int((await db.get(ClientOrder, line_id)).order_group_id)


async def _sales_invoice(group_id: int, month: str, items: list[dict]) -> int:
    year, mon = (int(x) for x in month.split("-"))
    async with AsyncSessionLocal() as db:
        invoice = ClientSalesInvoice(
            ksef_number=f"9990000001-{year}{mon:02d}15-{uuid.uuid4().hex[:12].upper()}-AB",
            xml_sha256=uuid.uuid4().hex * 2,
            invoice_number=f"T/{uuid.uuid4().hex[:6]}",
            issue_date=date(year, mon, 15),
            net_amount=Decimal("1.00"),
            vat_amount=Decimal("0.23"),
            gross_amount=Decimal("1.23"),
            items=items,
        )
        db.add(invoice)
        await db.flush()
        db.add(
            ClientSalesInvoiceLink(
                invoice_id=invoice.id,
                order_group_id=group_id,
                period_year=year,
                period_month=mon,
            )
        )
        await db.commit()
        return invoice.id


async def _drop_invoices(ids: list[int]) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(ClientSalesInvoiceLink).where(
                ClientSalesInvoiceLink.invoice_id.in_(ids)
            )
        )
        await db.execute(
            delete(ClientSalesInvoice).where(ClientSalesInvoice.id.in_(ids))
        )
        await db.commit()


async def _rules(client_id: int, extra: dict) -> None:
    async with AsyncSessionLocal() as db:
        rules = await db.scalar(
            select(ClientSettlementRuleSet).where(
                ClientSettlementRuleSet.client_id == client_id
            )
        )
        rules.rules = {**rules.rules, **extra}
        await db.commit()


async def _accept(
    contract_id: int,
    month: str,
    regular: str,
    extra: str | None = None,
    kind: str = "actual",
):
    async with AsyncSessionLocal() as db:
        await service.set_md(
            db,
            contract_id,
            month,
            md_regular=Decimal(regular),
            md_extra=Decimal(extra) if extra else None,
            actor=ACTOR,
            kind=kind,
        )
        s = await service.accept(
            db, contract_id, month, actor=ACTOR, now=local_now(), kind=kind
        )
        await db.commit()
        return s


async def test_pozycje_jak_w_poprzedniej_fakturze_z_nadgodzinami_i_marza() -> None:
    client_id, contract_id, line_id = await _world()
    month = _month(-1)
    invoices: list[int] = []
    try:
        await _rules(
            client_id,
            {
                "cl.overtime_item": {
                    "level": "warn",
                    "params": {"suffix": "_nadgodziny"},
                }
            },
        )
        invoices.append(
            await _sales_invoice(
                await _group(line_id),
                _month(-2),
                [
                    {"name": BASE, "quantity": "14", "unit_price": "1100"},
                    {
                        "name": BASE + "_ nadgodziny",
                        "quantity": "2",
                        "unit_price": "1320",
                    },
                ],
            )
        )
        await _accept(contract_id, month, "17", "4.75")
        async with AsyncSessionLocal() as db:
            data = await client_invoice.invoice_month(
                db, client_id, month, amounts=True
            )
        row = next(r for r in data["rows"] if r["contract_id"] == contract_id)
        assert row["state"] == "ready" and row["template"] is True
        names = [
            (p["name"], p["quantity"], p["unit_price"], p["net"])
            for p in row["positions"]
        ]
        assert names == [
            (BASE, "17", "1100.00", "18700.00"),
            (BASE + "_nadgodziny", "4.75", "1320.00", "6270.00"),
        ]
        # Netto pozycji = przychód z wyliczenia; marża = przychód − koszt.
        assert row["net"] == "24970.00"
        assert row["cost"] == "22700.00"
        assert row["margin"] == "2270.00"

        async with AsyncSessionLocal() as db:
            hidden = await client_invoice.invoice_month(
                db, client_id, month, amounts=False
            )
        row = next(r for r in hidden["rows"] if r["contract_id"] == contract_id)
        assert row["net"] is None and row["positions"][0]["unit_price"] is None
    finally:
        await _drop_invoices(invoices)
        await _cleanup(client_id)


async def test_bez_wzoru_nazwa_zastepcza_a_wystawiona_faktura_zmienia_stan() -> None:
    client_id, contract_id, line_id = await _world()
    month = _month(-1)
    invoices: list[int] = []
    try:
        await _accept(contract_id, month, "10")
        async with AsyncSessionLocal() as db:
            data = await client_invoice.invoice_month(
                db, client_id, month, amounts=True
            )
        row = next(r for r in data["rows"] if r["contract_id"] == contract_id)
        assert row["template"] is False
        assert row["positions"][0]["name"].startswith("Usługi informatyczne; ")
        assert row["state"] == "ready"

        invoices.append(
            await _sales_invoice(await _group(line_id), month, [{"name": BASE}])
        )
        async with AsyncSessionLocal() as db:
            data = await client_invoice.invoice_month(
                db, client_id, month, amounts=True
            )
            view = await service.month_view(db, client_id, month, amounts=True)
        row = next(r for r in data["rows"] if r["contract_id"] == contract_id)
        assert row["state"] == "issued" and row["ksef_number"]
        assert (
            next(r for r in view["rows"] if r["contract_id"] == contract_id)[
                "client_invoice"
            ]
            == "issued"
        )
    finally:
        await _drop_invoices(invoices)
        await _cleanup(client_id)


async def test_estymacja_po_poprzednim_miesiacu_nie_ponad_plan_i_korekta_w_kolejnym() -> (
    None
):
    client_id, contract_id, line_id = await _world(md_total="60")
    before, plan_month, after = _month(-2), _month(-1), _month(0)
    try:
        await _rules(
            client_id,
            {"cl.estimate": {"level": "warn", "params": {"months": plan_month[5:]}}},
        )
        # Plan przed przyjęciem poprzedniego miesiąca: odmowa.
        with pytest.raises(SettlementError, match="Najpierw przyjmij RCP"):
            await _accept(contract_id, plan_month, "20", kind="estimate")

        await _accept(contract_id, before, "18")
        plan = await _accept(contract_id, plan_month, "20", kind="estimate")
        assert plan.status == "accepted" and plan.kind == "estimate"

        # Faktyczne RCP ponad plan: odmowa.
        with pytest.raises(SettlementError, match="ponad estymację o 2 MD"):
            await _accept(contract_id, plan_month, "22")
        # Mniej niż w planie: przyjęte, zejście MD nadpisane w dół.
        await _accept(contract_id, plan_month, "17")
        async with AsyncSessionLocal() as db:
            md = await db.scalar(
                select(ClientOrderMdConsumption.md_reported).where(
                    ClientOrderMdConsumption.order_id == line_id,
                    ClientOrderMdConsumption.period_month == plan_month,
                )
            )
        assert md == Decimal("17")

        async with AsyncSessionLocal() as db:
            planned = await client_invoice.invoice_month(
                db, client_id, plan_month, amounts=True
            )
            screen = await client_invoice.estimates(
                db, client_id, plan_month, amounts=True
            )
        row = next(r for r in planned["rows"] if r["contract_id"] == contract_id)
        assert row["kind"] == "estimate"  # faktura za miesiąc z planem idzie z planu
        assert row["positions"][0]["quantity"] == "20"
        line = next(r for r in screen["rows"] if r["contract_id"] == contract_id)
        assert line["previous_status"] == "accepted" and line["plan_md"] == "20.000"
        assert screen["enabled"] is True

        await _accept(contract_id, after, "15")
        async with AsyncSessionLocal() as db:
            data = await client_invoice.invoice_month(
                db, client_id, after, amounts=True
            )
        row = next(r for r in data["rows"] if r["contract_id"] == contract_id)
        correction = row["positions"][-1]
        assert correction["kind"] == "correction"
        assert correction["quantity"] == "-3" and correction["net"] == "-3300.00"
        assert row["net"] == f"{15 * 1100 - 3300:.2f}"
    finally:
        await _cleanup(client_id)


async def test_plik_w_trwajacym_miesiacu_to_plan_tylko_przy_regule() -> None:
    client_id, contract_id, _line = await _world()
    month = _month(0)
    zone = ZoneInfo(DEFAULT_TZ)
    inside = datetime.now(zone)
    after = service.month_end(month) + timedelta(hours=1)
    try:
        async with AsyncSessionLocal() as db:
            assert (
                await service.kind_for_upload(db, contract_id, month, inside)
                == "actual"
            )
        await _rules(
            client_id,
            {"cl.estimate": {"level": "warn", "params": {"months": month[5:]}}},
        )
        async with AsyncSessionLocal() as db:
            assert (
                await service.kind_for_upload(db, contract_id, month, inside)
                == "estimate"
            )
            assert (
                await service.kind_for_upload(db, contract_id, month, after) == "actual"
            )
    finally:
        await _cleanup(client_id)


async def test_panel_konsultanta_zadanie_planu_do_czasu_wyslania() -> None:
    previous = await _module(True)
    client_id, contract_id, _line = await _world()
    today = business_today()
    month = f"{today.year}-{today.month:02d}"
    try:
        async with AsyncSessionLocal() as db:
            assert (
                await consultant.estimate_todo(db, contract_id, client_id, today)
                is None
            )
        await _rules(
            client_id,
            {"cl.estimate": {"level": "warn", "params": {"months": month[5:]}}},
        )
        async with AsyncSessionLocal() as db:
            task = await consultant.estimate_todo(db, contract_id, client_id, today)
        assert task is not None and task["title"].startswith("Wyślij RCP z planem na ")

        async with AsyncSessionLocal() as db:
            await service.set_md(
                db,
                contract_id,
                month,
                md_regular=Decimal("5"),
                md_extra=None,
                actor=ACTOR,
                kind="estimate",
            )
            await db.commit()
        async with AsyncSessionLocal() as db:
            assert (
                await consultant.estimate_todo(db, contract_id, client_id, today)
                is None
            )
            block = await consultant.view(
                db, contract_id, client_id, today.year, today.month
            )
        assert block["kind"] == "estimate" and block["invoice"] is None
        assert block["label"].startswith("Plan")
    finally:
        await _cleanup(client_id)
        await _restore(previous)


async def test_paczka_zip_bez_plikow_jest_pusta() -> None:
    client_id, contract_id, _line = await _world()
    month = _month(-1)
    try:
        await _accept(contract_id, month, "10")
        async with AsyncSessionLocal() as db:
            content, count = await client_invoice.attachments_zip(db, client_id, month)
        assert count == 0 and content.startswith(b"PK")
    finally:
        await _cleanup(client_id)


async def test_paczka_zip_z_plikiem_z_panelu_nazwanym_numerem_ksef(
    tmp_path, monkeypatch
) -> None:
    from app.services import storage_service
    from app.services.consultant_portal import documents

    monkeypatch.setattr(storage_service, "STORAGE_ROOT", tmp_path)
    client_id, contract_id, line_id = await _world()
    month = _month(-1)
    year, mon = (int(x) for x in month.split("-"))
    eml = b"From: a@bank.example\r\nTo: b@firma.example\r\nSubject: Akceptacja\r\nDate: Mon, 2 Nov 2026 10:00:00 +0100\r\nMIME-Version: 1.0\r\n\r\nOK"
    invoices: list[int] = []
    try:
        await _rules(client_id, {"cl.attachment_name": {"level": "warn", "params": {}}})
        async with AsyncSessionLocal() as db:
            await documents.store(
                db,
                contract_id=contract_id,
                kind="report",
                year=year,
                month=mon,
                content=eml,
                file_name="akceptacja.eml",
                channel="portal",
                now=local_now(),
            )
            await db.commit()
        await _accept(contract_id, month, "10")
        invoices.append(
            await _sales_invoice(await _group(line_id), month, [{"name": BASE}])
        )
        async with AsyncSessionLocal() as db:
            content, count = await client_invoice.attachments_zip(db, client_id, month)
            ksef = (await db.get(ClientSalesInvoice, invoices[0])).ksef_number
        import io
        import zipfile

        names = zipfile.ZipFile(io.BytesIO(content)).namelist()
        assert count == 1 and names == [f"{ksef}.eml"]
    finally:
        await _drop_invoices(invoices)
        await _cleanup(client_id)


async def test_plan_nie_nadpisuje_przyjetego_rcp_faktycznego() -> None:
    client_id, contract_id, line_id = await _world(md_total="60")
    before, plan_month = _month(-2), _month(-1)
    try:
        await _rules(
            client_id,
            {"cl.estimate": {"level": "warn", "params": {"months": plan_month[5:]}}},
        )
        await _accept(contract_id, before, "18")
        await _accept(contract_id, plan_month, "20", kind="estimate")
        await _accept(contract_id, plan_month, "17")
        with pytest.raises(SettlementError, match="RCP faktyczne"):
            async with AsyncSessionLocal() as db:
                await service.accept(
                    db,
                    contract_id,
                    plan_month,
                    actor=ACTOR,
                    now=local_now(),
                    kind="estimate",
                )
        async with AsyncSessionLocal() as db:
            md = await db.scalar(
                select(ClientOrderMdConsumption.md_reported).where(
                    ClientOrderMdConsumption.order_id == line_id,
                    ClientOrderMdConsumption.period_month == plan_month,
                )
            )
        assert md == Decimal("17")
    finally:
        await _cleanup(client_id)


async def test_korekta_planu_zostaje_gdy_kontrakt_skonczyl_sie_w_miesiacu_planu() -> (
    None
):
    from app.models.contract import Contract
    from app.services.client_order_lines import month_bounds

    client_id, contract_id, _line = await _world(md_total="60")
    before, plan_month, after = _month(-2), _month(-1), _month(0)
    try:
        await _rules(
            client_id,
            {"cl.estimate": {"level": "warn", "params": {"months": plan_month[5:]}}},
        )
        await _accept(contract_id, before, "18")
        await _accept(contract_id, plan_month, "20", kind="estimate")
        await _accept(contract_id, plan_month, "17")
        async with AsyncSessionLocal() as db:
            contract = await db.get(Contract, contract_id)
            contract.end_date = month_bounds(plan_month)[1]
            await db.commit()
        async with AsyncSessionLocal() as db:
            data = await client_invoice.invoice_month(
                db, client_id, after, amounts=True
            )
        row = next(r for r in data["rows"] if r["contract_id"] == contract_id)
        assert [p["kind"] for p in row["positions"]] == ["correction"]
        assert row["positions"][0]["quantity"] == "-3"
        assert row["net"] == "-3300.00" and row["state"] == "ready"
    finally:
        await _cleanup(client_id)


async def test_przyjecie_odmawia_gdy_import_podzielil_miesiac_na_dwa_zamowienia() -> (
    None
):
    from app.models.client_order import ClientOrderStatus
    from app.services.client_order_lines import upsert_consumption

    client_id, contract_id, line_id = await _world(md_total="60")
    month = _month(-1)
    try:
        async with AsyncSessionLocal() as db:
            first = await db.get(ClientOrder, line_id)
            other = ClientOrder(
                client_id=client_id,
                contract_id=contract_id,
                order_group_id=first.order_group_id,
                title="linia poprzednia",
                status=ClientOrderStatus.completed,
                start_date=first.start_date - timedelta(days=30),
                md_total=Decimal("60"),
                md_remaining=Decimal("60"),
                md_input_mode="md",
                md_input_value=Decimal("60"),
                md_rate_cost=Decimal("1000"),
                md_rate_revenue=Decimal("1100"),
            )
            db.add(other)
            await db.flush()
            await upsert_consumption(
                db,
                order=other,
                period_month=month,
                md_reported=Decimal("5"),
                source="manual",
            )
            await db.commit()
        with pytest.raises(SettlementError, match="innym zamówieniu"):
            await _accept(contract_id, month, "20")
    finally:
        await _cleanup(client_id)
