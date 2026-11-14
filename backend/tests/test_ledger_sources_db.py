"""Źródła księgi (K2) — „Zaksięguj miesiąc” z bazą.

Koszty: dekret E2 jako FVZ raz na fakturę, przebudowa szkicu po zmianie
dekretu, zatwierdzony zapis zmienionej faktury jako problem do storna,
cofnięta faktura usuwa szkic, faktury osób zespołu poza zasięgiem osoby bez
Płac (D2). Sprzedaż: FVS z kontem odbiorcy ze słownikiem, waluta po kursie
NBP, korekta in minus, nabywca spoza kartoteki i zaliczka jako problemy.
Zamknięty okres i brak roku odmawiają, konta sprzedaży zmienia tylko admin.
Rok obrotowy losowy z przyszłości, konta z losowym prefiksem, kwoty i NIP-y
fikcyjne.
"""

from __future__ import annotations

import hashlib
import random
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select, update

from app.api import ledger as ledger_api
from app.core.database import AsyncSessionLocal
from app.models.app_setting import AppSetting
from app.models.client_sales_invoice import ClientSalesInvoice
from app.models.finance_ledger import FinanceCostEntry, FinanceCounterparty
from app.models.finance_posting import FinanceAccount
from app.models.fx_rate import FxRate
from app.models.hr_profile import EmployeeProfile
from app.models.ledger import LedgerDocument, LedgerLine, LedgerYear
from app.services.finance_ledger.posting import rate_day
from app.services.ledger import settings as ledger_settings
from app.services.ledger import sources
from app.services.ledger import years as ledger_years
from tests.test_finance_ledger_db import (  # noqa: F401  (fixture ``world``)
    _entry,
    _headers,
    _ksef_number,
    _nip,
    world,
)
from tests.test_finance_posting_db import _expense
from tests.test_ledger_db import _purge_years, _set_ledger

ACC = "/api/accounting"


@pytest_asyncio.fixture
async def client():
    app = FastAPI()
    app.include_router(ledger_api.router, prefix=ACC)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as c:
        yield c


def _decree(acc: dict[str, str], *, net: int, vat: int, payable: str, text: str):
    return {
        "manual": False,
        "currency": "PLN",
        "description": text,
        "doc_type": "FVZ",
        "positions": [
            {"kind": "cost", "account": acc["cost"], "side": "debit", "amount": net},
            {"kind": "vat", "account": acc["vat_in"], "side": "debit", "amount": vat},
            {
                "kind": "counterparty",
                "account": payable,
                "side": "credit",
                "amount": net + vat,
            },
        ],
        "problems": [],
    }


async def _ready(entry_id: int, *, received: datetime, counterparty_id: int, decree):
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(FinanceCostEntry)
            .where(FinanceCostEntry.id == entry_id)
            .values(
                stage="ready",
                received_at=received,
                counterparty_id=counterparty_id,
                decree=decree,
            )
        )
        await db.commit()


def _sales_invoice(nip: str, **values) -> ClientSalesInvoice:
    ksef = f"{nip}-20501231-{uuid.uuid4().hex[:12].upper()}-AB"
    return ClientSalesInvoice(
        ksef_number=ksef,
        xml_sha256=hashlib.sha256(ksef.encode()).hexdigest(),
        invoice_number=values.pop("number"),
        **values,
    )


@pytest_asyncio.fixture
async def books(world):
    year = random.randint(2050, 2099)
    prefix = f"S{random.randint(10_000, 99_999)}"
    async with AsyncSessionLocal() as db:
        while await db.scalar(select(LedgerYear.id).where(LedgerYear.year == year)):
            year = random.randint(2050, 2099)
        previous = await db.scalar(
            select(AppSetting.value).where(
                AppSetting.key == ledger_settings.SETTING_KEY
            )
        )
        acc = {
            "cost": (f"{prefix}-402", "Usługi obce", "cost", None),
            "vat_in": (f"{prefix}-221", "VAT naliczony", "vat", None),
            "payable": (f"{prefix}-201", "Dostawcy", "settlement", "counterparty"),
            "receivable": (f"{prefix}-200", "Odbiorcy", "settlement", "counterparty"),
            "revenue": (f"{prefix}-701", "Przychody", "revenue", None),
            "vat_out": (f"{prefix}-222", "VAT należny", "vat", None),
            "alloc_client": (f"{prefix}-501", "Koszty klientów", "other", None),
            "alloc_fo": (f"{prefix}-502", "Koszty Front office", "other", None),
            "alloc_bo": (f"{prefix}-503", "Koszty Back office", "other", None),
            "alloc_og": (f"{prefix}-550", "Koszty ogólne", "other", None),
            "settle": (f"{prefix}-490", "Rozliczenie kosztów", "other", None),
        }
        for number, name, kind, dictionary in acc.values():
            db.add(
                FinanceAccount(number=number, name=name, kind=kind, dictionary=dictionary)
            )
        partner = {key: str(random.randint(10_000, 99_999)) for key in ("s", "c", "p")}
        nips = world["nips"]
        supplier = FinanceCounterparty(
            id_type="nip",
            id_value=nips["supplier"],
            name="Dostawca Testowy",
            symfonia_partner_id=partner["s"],
            cost_account=f"{prefix}-201-{partner['s']}",
        )
        buyer = FinanceCounterparty(
            id_type="nip",
            id_value=nips["client"],
            name="Klient Testowy",
            symfonia_partner_id=partner["c"],
        )
        person = FinanceCounterparty(
            id_type="nip",
            id_value=nips["person"],
            name="Osoba Testowa",
            symfonia_partner_id=partner["p"],
            cost_account=f"{prefix}-201-{partner['p']}",
        )
        db.add_all([supplier, buyer, person])
        await db.commit()
        await ledger_years.ensure_year(db, year, actor_id=world["admin"].id)
        await db.commit()
    numbers = {key: value[0] for key, value in acc.items()}
    await _set_ledger(
        {
            "modules": {"ledger": True},
            "accountants": [world["accountant"].id],
            "sales": {
                "receivable_account": numbers["receivable"],
                "revenue_account": numbers["revenue"],
                "vat_account": numbers["vat_out"],
            },
        }
    )
    march = datetime(year, 3, 15, 10, 0, tzinfo=timezone.utc)
    expense = await _expense(
        world, number="FV 7/03", net="1000.00", vat="230.00", gross="1230.00"
    )
    await _ready(
        expense,
        received=march,
        counterparty_id=supplier.id,
        decree=_decree(
            numbers,
            net=100_000,
            vat=23_000,
            payable=supplier.cost_account,
            text="Usługi marzec",
        ),
    )
    payroll = (await _entry("payroll_invoice", world["person_invoice"].id)).id
    await _ready(
        payroll,
        received=march,
        counterparty_id=person.id,
        decree=_decree(
            numbers,
            net=1_000_000,
            vat=230_000,
            payable=person.cost_account,
            text="Faktura osoby zespołu",
        ),
    )
    rate_date = rate_day(date(year, 3, 20))
    stranger = _nip(random.randint(10_000_000, 900_000_000))
    async with AsyncSessionLocal() as db:
        db.add(
            FxRate(
                effective_date=rate_date,
                currency="EUR",
                rate_to_pln=Decimal("4.300000"),
                source="NBP",
            )
        )
        plain = _sales_invoice(
            nips["client"],
            number="FS 1/03",
            buyer_nip=nips["client"],
            buyer_name="Klient Testowy",
            issue_date=date(year, 4, 2),
            sale_date=date(year, 3, 31),
            net_amount=Decimal("1000.00"),
            vat_amount=Decimal("230.00"),
            gross_amount=Decimal("1230.00"),
        )
        euro = _sales_invoice(
            nips["client"],
            number="FS 2/03",
            buyer_nip=nips["client"],
            buyer_name="Klient Testowy",
            issue_date=date(year, 3, 20),
            sale_date=date(year, 3, 20),
            currency="EUR",
            net_amount=Decimal("500.00"),
            vat_amount=Decimal("0"),
            gross_amount=Decimal("500.00"),
        )
        unknown = _sales_invoice(
            stranger,
            number="FS 3/03",
            buyer_nip=stranger,
            buyer_name="Nabywca Spoza Kartoteki",
            issue_date=date(year, 3, 10),
            sale_date=date(year, 3, 10),
            net_amount=Decimal("100.00"),
            vat_amount=Decimal("23.00"),
            gross_amount=Decimal("123.00"),
        )
        advance = _sales_invoice(
            nips["client"],
            number="FZ 1/03",
            buyer_nip=nips["client"],
            invoice_type="ZAL",
            issue_date=date(year, 3, 11),
            sale_date=date(year, 3, 11),
            net_amount=Decimal("100.00"),
            vat_amount=Decimal("23.00"),
            gross_amount=Decimal("123.00"),
        )
        db.add_all([plain, euro, unknown, advance])
        await db.flush()
        correction = _sales_invoice(
            nips["client"],
            number="FK 1/03",
            buyer_nip=nips["client"],
            buyer_name="Klient Testowy",
            invoice_type="KOR",
            invoice_kind="correction",
            corrects_invoice_id=plain.id,
            corrected_invoice_number="FS 1/03",
            issue_date=date(year, 3, 25),
            sale_date=date(year, 3, 31),
            net_amount=Decimal("-100.00"),
            vat_amount=Decimal("-23.00"),
            gross_amount=Decimal("-123.00"),
        )
        db.add(correction)
        await db.commit()
        sales_ids = {
            "plain": plain.id,
            "euro": euro.id,
            "unknown": unknown.id,
            "advance": advance.id,
            "correction": correction.id,
        }
    yield {
        "year": year,
        "acc": numbers,
        "supplier": supplier,
        "buyer": buyer,
        "partner": partner,
        "expense": expense,
        "payroll": payroll,
        "sales": sales_ids,
        "rate_date": rate_date,
    }
    await _purge_years([year])
    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(ClientSalesInvoice).where(
                ClientSalesInvoice.id.in_(list(sales_ids.values()))
            )
        )
        await db.execute(
            delete(FxRate).where(
                FxRate.effective_date == rate_date, FxRate.currency == "EUR"
            )
        )
        await db.execute(
            delete(FinanceCounterparty).where(
                FinanceCounterparty.id.in_([supplier.id, buyer.id, person.id])
            )
        )
        await db.execute(
            delete(FinanceAccount).where(FinanceAccount.number.like(f"{prefix}-%"))
        )
        await db.commit()
    await _set_ledger(previous)


async def _sync(client, world, books, kind: str, user: str = "admin", month: int = 3):
    return await client.post(
        f"{ACC}/sources/sync",
        json={"kind": kind, "year": books["year"], "month": month},
        headers=_headers(world[user]),
    )


async def _summary(client, world, books, user: str = "admin") -> dict:
    response = await client.get(
        f"{ACC}/sources",
        params={"year": books["year"], "month": 3},
        headers=_headers(world[user]),
    )
    assert response.status_code == 200, response.text
    return {item["kind"]: item for item in response.json()["items"]}


async def _document(source_type: str, source_id: int) -> LedgerDocument | None:
    async with AsyncSessionLocal() as db:
        return await db.scalar(
            select(LedgerDocument).where(
                LedgerDocument.source_type == source_type,
                LedgerDocument.source_id == str(source_id),
                LedgerDocument.reversed_by_id.is_(None),
            )
        )


async def _lines(doc_id: int) -> list[tuple[str, str, int]]:
    async with AsyncSessionLocal() as db:
        rows = await db.scalars(
            select(LedgerLine)
            .where(LedgerLine.document_id == doc_id)
            .order_by(LedgerLine.line_no)
        )
        return [(row.side, row.account, row.amount) for row in rows]


# ── Koszty ───────────────────────────────────────────────────────────────────


async def test_costs_month_books_each_e2_decree_once(client, world, books):
    before = await _summary(client, world, books)
    assert before["costs"]["to_post"] == 2
    first = await _sync(client, world, books, "costs")
    assert first.status_code == 200, first.text
    assert first.json()["created"] == 2 and first.json()["problems"] == []
    again = await _sync(client, world, books, "costs")
    assert again.json()["created"] == 0 and again.json()["unchanged"] == 2
    doc = await _document("finance_cost_entry", books["expense"])
    assert doc.doc_type == "FVZ" and doc.status == "draft"
    assert doc.number == "FV 7/03" and doc.op_date == date(books["year"], 3, 15)
    assert doc.counterparty_id == books["supplier"].id
    acc = books["acc"]
    assert await _lines(doc.id) == [
        ("debit", acc["cost"], 100_000),
        ("debit", acc["vat_in"], 23_000),
        ("credit", books["supplier"].cost_account, 123_000),
    ]
    payroll = await _document("finance_cost_entry", books["payroll"])
    assert payroll.sensitivity == "payroll"


async def test_changed_decree_rebuilds_draft_and_flags_approved(client, world, books):
    await _sync(client, world, books, "costs")
    acc = books["acc"]
    changed = _decree(
        acc,
        net=100_000,
        vat=23_000,
        payable=books["supplier"].cost_account,
        text="Usługi marzec — poprawiony opis",
    )
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(FinanceCostEntry)
            .where(FinanceCostEntry.id == books["expense"])
            .values(decree=changed)
        )
        await db.commit()
    rebuilt = await _sync(client, world, books, "costs")
    assert rebuilt.json()["rebuilt"] == 1
    doc = await _document("finance_cost_entry", books["expense"])
    assert doc.description == "Usługi marzec — poprawiony opis"
    approved = await client.post(
        f"{ACC}/documents/approve",
        json={"ids": [doc.id]},
        headers=_headers(world["accountant"]),
    )
    assert approved.json()["approved"][0]["journal_no"] == 1
    changed["description"] = "Usługi marzec — jeszcze raz"
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(FinanceCostEntry)
            .where(FinanceCostEntry.id == books["expense"])
            .values(decree=changed)
        )
        await db.commit()
    flagged = await _sync(client, world, books, "costs")
    assert flagged.json()["rebuilt"] == 0
    [problem] = flagged.json()["problems"]
    assert "storno zapisu nr 1" in problem["problems"][0]


async def test_withdrawn_cost_invoice_removes_its_draft(client, world, books):
    await _sync(client, world, books, "costs")
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(FinanceCostEntry)
            .where(FinanceCostEntry.id == books["expense"])
            .values(stage="verified")
        )
        await db.commit()
    summary = await _summary(client, world, books)
    assert summary["costs"]["changed"] == 1
    result = await _sync(client, world, books, "costs")
    assert result.json()["deleted"] == 1
    assert await _document("finance_cost_entry", books["expense"]) is None


async def test_team_invoices_stay_out_of_reach_without_payroll(client, world, books):
    await _sync(client, world, books, "costs")
    summary = await _summary(client, world, books, user="module_only")
    costs = summary["costs"]
    assert costs["payroll_hidden"] is True
    assert costs["total"] == 1 and costs["draft"] == 1
    assert "Osoba" not in str(costs["problems"])
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(FinanceCostEntry)
            .where(FinanceCostEntry.id == books["payroll"])
            .values(stage="verified")
        )
        await db.commit()
    result = await _sync(client, world, books, "costs", user="module_only")
    assert result.status_code == 200, result.text
    assert result.json()["deleted"] == 0
    assert await _document("finance_cost_entry", books["payroll"]) is not None


# ── Sprzedaż ─────────────────────────────────────────────────────────────────


async def test_sales_month_books_invoices_with_rate_and_corrections(
    client, world, books
):
    summary = await _summary(client, world, books)
    sales = summary["sales"]
    assert sales["to_post"] == 3
    reasons = {item["source_id"]: item["problems"][0] for item in sales["problems"]}
    ids = books["sales"]
    assert reasons[str(ids["unknown"])] == sources.NO_BUYER
    assert reasons[str(ids["advance"])] == sources.ADVANCE
    result = await _sync(client, world, books, "sales")
    assert result.status_code == 200, result.text
    assert result.json()["created"] == 3 and result.json()["problems_total"] == 2
    acc = books["acc"]
    receivable = f"{acc['receivable']}-{books['partner']['c']}"
    plain = await _document("client_sales_invoice", ids["plain"])
    assert plain.doc_type == "FVS" and plain.op_date == date(books["year"], 3, 31)
    assert await _lines(plain.id) == [
        ("debit", receivable, 123_000),
        ("credit", acc["revenue"], 100_000),
        ("credit", acc["vat_out"], 23_000),
    ]
    euro = await _document("client_sales_invoice", ids["euro"])
    assert euro.currency == "EUR" and euro.fx_rate == Decimal("4.300000")
    assert euro.fx_date == books["rate_date"]
    assert await _lines(euro.id) == [
        ("debit", receivable, 215_000),
        ("credit", acc["revenue"], 215_000),
    ]
    correction = await _document("client_sales_invoice", ids["correction"])
    assert correction.op_date == date(books["year"], 3, 25)
    assert await _lines(correction.id) == [
        ("credit", receivable, 12_300),
        ("debit", acc["revenue"], 10_000),
        ("debit", acc["vat_out"], 2_300),
    ]
    again = await _sync(client, world, books, "sales")
    assert again.json()["created"] == 0 and again.json()["unchanged"] == 3


async def test_correction_of_advance_waits_with_the_advance(client, world, books):
    ids = books["sales"]
    async with AsyncSessionLocal() as db:
        correction = _sales_invoice(
            world["nips"]["client"],
            number="FZK 1/03",
            buyer_nip=world["nips"]["client"],
            invoice_type="KOR_ZAL",
            invoice_kind="correction",
            corrects_invoice_id=ids["advance"],
            corrected_invoice_number="FZ 1/03",
            issue_date=date(books["year"], 3, 20),
            sale_date=date(books["year"], 3, 11),
            net_amount=Decimal("-100.00"),
            vat_amount=Decimal("-23.00"),
            gross_amount=Decimal("-123.00"),
        )
        db.add(correction)
        await db.commit()
        correction_id = correction.id
    try:
        result = await _sync(client, world, books, "sales")
        reasons = {item["source_id"]: item["problems"][0] for item in result.json()["problems"]}
        assert reasons[str(correction_id)] == sources.ADVANCE
        assert await _document("client_sales_invoice", correction_id) is None
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(
                delete(ClientSalesInvoice).where(ClientSalesInvoice.id == correction_id)
            )
            await db.commit()


async def test_sales_wait_for_revenue_account(client, world, books):
    await _set_ledger(
        {
            "modules": {"ledger": True},
            "accountants": [world["accountant"].id],
            "sales": {"receivable_account": books["acc"]["receivable"]},
        }
    )
    summary = await _summary(client, world, books)
    reasons = {item["problems"][0] for item in summary["sales"]["problems"]}
    assert sources.NO_REVENUE_ACCOUNT in reasons
    assert summary["sales"]["to_post"] == 0


async def test_sync_needs_open_period_of_existing_year(client, world, books):
    async with AsyncSessionLocal() as db:
        year = await db.scalar(
            select(LedgerYear).where(LedgerYear.year == books["year"])
        )
        periods = await ledger_years.list_years(db, include_payroll=True)
    march = next(
        period["id"]
        for item in periods
        if item["id"] == year.id
        for period in item["periods"]
        if period["month"] == 3
    )
    async with AsyncSessionLocal() as db:
        await ledger_years.close_period(
            db, march, actor_id=world["admin"].id, now=datetime.now(timezone.utc)
        )
        await db.commit()
    closed = await _sync(client, world, books, "costs")
    assert closed.status_code == 409 and "zamknięty" in closed.json()["detail"]
    missing = await client.post(
        f"{ACC}/sources/sync",
        json={"kind": "sales", "year": 2031, "month": 1},
        headers=_headers(world["admin"]),
    )
    assert missing.status_code == 409


async def test_sales_accounts_are_set_by_admin_from_the_plan(client, world, books):
    acc = books["acc"]
    body = {
        "receivable_account": acc["receivable"],
        "revenue_account": acc["revenue"],
        "vat_account": acc["vat_out"],
    }
    by_accountant = await client.put(
        f"{ACC}/config/sales", json=body, headers=_headers(world["accountant"])
    )
    assert by_accountant.status_code == 403
    unknown = await client.put(
        f"{ACC}/config/sales",
        json={**body, "revenue_account": "999-999"},
        headers=_headers(world["admin"]),
    )
    assert unknown.status_code == 422
    saved = await client.put(
        f"{ACC}/config/sales", json=body, headers=_headers(world["admin"])
    )
    assert saved.status_code == 200, saved.text
    config = await client.get(f"{ACC}/config", headers=_headers(world["accountant"]))
    assert config.json()["sales_accounts"] == body
    assert config.json()["accountants"] is None


# ── Rozliczenie kosztów na „5” ──────────────────────────────────────────────


def _ledger_settings(world, books, *, allocation: bool) -> dict:
    acc = books["acc"]
    value = {
        "modules": {"ledger": True},
        "accountants": [world["accountant"].id],
        "sales": {
            "receivable_account": acc["receivable"],
            "revenue_account": acc["revenue"],
            "vat_account": acc["vat_out"],
        },
    }
    if allocation:
        value["allocation"] = {
            "settlement_account": acc["settle"],
            "client_account": acc["alloc_client"],
            "front_office_account": acc["alloc_fo"],
            "back_office_account": acc["alloc_bo"],
            "overhead_account": acc["alloc_og"],
        }
    return value


async def _approved_costs(client, world, books) -> None:
    synced = await _sync(client, world, books, "costs")
    assert synced.json()["created"] == 2, synced.text
    ids = [
        (await _document("finance_cost_entry", books[key])).id
        for key in ("expense", "payroll")
    ]
    approved = await client.post(
        f"{ACC}/documents/approve",
        json={"ids": ids},
        headers=_headers(world["accountant"]),
    )
    assert len(approved.json()["approved"]) == 2, approved.text


async def test_allocation_books_approved_costs_by_cost_centre(client, world, books):
    await _set_ledger(_ledger_settings(world, books, allocation=True))
    async with AsyncSessionLocal() as db:
        db.add(EmployeeProfile(user_id=world["person"].id, division="back_office"))
        await db.commit()
    try:
        await _approved_costs(client, world, books)
        summary = await _summary(client, world, books)
        alloc = summary["allocation"]
        assert alloc["to_post"] == 2 and alloc["pending_costs"] == 0
        assert {(d["code"], d["amount"], d["payroll"]) for d in alloc["details"]} == {
            ("OG", 100_000, False),
            ("BO", 1_000_000, True),
        }
        result = await _sync(client, world, books, "allocation")
        assert result.json()["created"] == 2, result.text
        acc = books["acc"]
        year = books["year"]
        general = await _document("cost_allocation", f"{year}-03")
        assert general.doc_type == "PK" and general.sensitivity is None
        assert general.op_date == date(year, 3, 31)
        assert await _lines(general.id) == [
            ("debit", acc["alloc_og"], 100_000),
            ("credit", acc["settle"], 100_000),
        ]
        team = await _document("cost_allocation", f"{year}-03-payroll")
        assert team.sensitivity == "payroll"
        assert await _lines(team.id) == [
            ("debit", acc["alloc_bo"], 1_000_000),
            ("credit", acc["settle"], 1_000_000),
        ]
        hidden = await _summary(client, world, books, user="module_only")
        assert hidden["allocation"]["payroll_hidden"] is True
        assert hidden["allocation"]["total"] == 1
        assert [d["code"] for d in hidden["allocation"]["details"]] == ["OG"]
        again = await _sync(client, world, books, "allocation", user="module_only")
        assert again.json()["unchanged"] == 1 and again.json()["deleted"] == 0
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(
                delete(EmployeeProfile).where(
                    EmployeeProfile.user_id == world["person"].id
                )
            )
            await db.commit()


async def test_allocation_waits_for_accounts_and_for_approval(client, world, books):
    await _sync(client, world, books, "costs")
    drafts_only = await _summary(client, world, books)
    assert drafts_only["allocation"]["pending_costs"] == 2
    assert drafts_only["allocation"]["to_post"] == 0
    await _approved_costs_after_drafts(client, world, books)
    waiting = await _summary(client, world, books)
    reasons = {item["problems"][0] for item in waiting["allocation"]["problems"]}
    assert reasons == {sources.NO_ALLOCATION_ACCOUNTS}


async def _approved_costs_after_drafts(client, world, books) -> None:
    ids = [
        (await _document("finance_cost_entry", books[key])).id
        for key in ("expense", "payroll")
    ]
    approved = await client.post(
        f"{ACC}/documents/approve",
        json={"ids": ids},
        headers=_headers(world["accountant"]),
    )
    assert len(approved.json()["approved"]) == 2, approved.text
