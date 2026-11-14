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
import io
import random
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest_asyncio
from fastapi import FastAPI
from openpyxl import load_workbook
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, func, select, update

from app.api import ledger as ledger_api
from app.core.database import AsyncSessionLocal
from app.models.app_setting import AppSetting
from app.models.client_sales_invoice import ClientSalesInvoice
from app.models.finance_ledger import FinanceCostEntry, FinanceCounterparty
from app.models.finance_posting import FinanceAccount
from app.models.fx_rate import FxRate
from app.models.candidate import Candidate
from app.models.client_settlement import ClientContractorInvoice
from app.models.hr_profile import EmployeeProfile
from app.models.ledger import (
    LedgerDocument,
    LedgerLine,
    LedgerPrepayment,
    LedgerRecurring,
    LedgerYear,
)
from app.services.finance_ledger import costs as cost_queue
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
from tests.test_client_audit_2026_09_24 import _candidate, _client, _contract
from tests.test_client_audit_2026_09_24 import _cleanup as _cleanup_client
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
        # Rok bez księgi, kursów EUR i faktur kosztowych z wpływem w tym roku —
        # resztki przerwanego biegu (sprzątanie nie doszło do końca) blokowały
        # wstawienie kursu albo dokładały faktury do liczników miesiąca.
        while await db.scalar(
            select(LedgerYear.id).where(LedgerYear.year == year)
        ) or await db.scalar(
            select(func.count())
            .select_from(FxRate)
            .where(
                FxRate.currency == "EUR",
                FxRate.effective_date.between(date(year, 1, 1), date(year, 12, 31)),
            )
        ) or await db.scalar(
            select(func.count())
            .select_from(FinanceCostEntry)
            .where(
                FinanceCostEntry.received_at
                >= datetime(year, 1, 1, tzinfo=timezone.utc),
                FinanceCostEntry.received_at
                < datetime(year + 1, 1, 1, tzinfo=timezone.utc),
            )
        ):
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
            "alloc_team": (f"{prefix}-504", "Koszty zespołu", "other", None),
            "prepaid": (f"{prefix}-640", "RMK czynne", "other", None),
            "settle": (f"{prefix}-490", "Rozliczenie kosztów", "other", None),
            "wages": (f"{prefix}-404", "Wynagrodzenia", "cost", None),
            "insurance": (f"{prefix}-405", "Ubezpieczenia i świadczenia", "cost", None),
            "payroll_settle": (f"{prefix}-231", "Rozrachunki z tytułu wynagrodzeń", "other", None),
            "zus": (f"{prefix}-229", "Rozrachunki z ZUS", "other", None),
            "pit": (f"{prefix}-225", "Rozrachunki z US", "other", None),
            "ppk": (f"{prefix}-234", "Rozrachunki PPK", "other", None),
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
        authors = [world[key].id for key in ("admin", "accountant", "module_only")]
        await db.execute(
            delete(LedgerRecurring).where(LedgerRecurring.created_by.in_(authors))
        )
        await db.execute(
            delete(LedgerPrepayment).where(LedgerPrepayment.created_by.in_(authors))
        )
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


async def _summary(
    client, world, books, user: str = "admin", month: int = 3
) -> dict:
    response = await client.get(
        f"{ACC}/sources",
        params={"year": books["year"], "month": month},
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
            "team_account": acc["alloc_team"],
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
        # D2: jedno konto zespołu dla wszystkich pionów, pion tylko w MPK pozycji —
        # obroty kont „5” nie pokazują sumy pionu (bywa pensją jednej osoby).
        assert await _lines(team.id) == [
            ("debit", acc["alloc_team"], 1_000_000),
            ("credit", acc["settle"], 1_000_000),
        ]
        async with AsyncSessionLocal() as db:
            mpk = await db.scalar(
                select(LedgerLine.mpk).where(
                    LedgerLine.document_id == team.id, LedgerLine.line_no == 1
                )
            )
        assert mpk == "BO"
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


# ── Bilans otwarcia z Symfonii ──────────────────────────────────────────────


def _opening_csv(books, *, extra: str = "", amount: str = "1 230,00") -> bytes:
    acc, partner = books["acc"], books["partner"]
    return (
        "Konto;Nazwa;BO Wn;BO Ma\n"
        f"{acc['receivable']}-{partner['c']};Klient Testowy;{amount};\n"
        f"{acc['payable']}-{partner['s']};Dostawca Testowy;;1 230,00\n"
        f"{extra}"
        "Razem;;1 230,00;1 230,00\n"
    ).encode("utf-8")


async def _import(client, world, books, content: bytes, *, save: bool, user="accountant"):
    return await client.post(
        f"{ACC}/opening/import",
        params={"year": books["year"], "save": save},
        files={"file": ("zois.csv", content, "text/csv")},
        headers=_headers(world[user]),
    )


async def test_opening_preview_lists_missing_accounts_and_imbalance(client, world, books):
    missing = await _import(
        client, world, books, _opening_csv(books, extra="999-1;Nieznane;5,00;\n"), save=False
    )
    assert missing.status_code == 200, missing.text
    body = missing.json()
    assert body["missing_accounts"] == ["999-1"] and not body["saved"]
    assert any("999-1" in problem for problem in body["problems"])
    refused = await _import(
        client, world, books, _opening_csv(books, extra="999-1;Nieznane;5,00;\n"), save=True
    )
    assert refused.status_code == 422
    unbalanced = await _import(client, world, books, _opening_csv(books, amount="1 000,00"), save=False)
    assert unbalanced.json()["balanced"] is False
    assert any("nie bilansuje" in problem for problem in unbalanced.json()["problems"])


async def test_opening_saves_one_draft_per_year_with_counterparties(client, world, books):
    preview = await _import(client, world, books, _opening_csv(books), save=False)
    assert preview.json()["problems"] == [] and preview.json()["counterparties_matched"] == 2
    saved = await _import(client, world, books, _opening_csv(books), save=True)
    assert saved.status_code == 200, saved.text
    first_id = saved.json()["document_id"]
    doc = await _document("opening_import", books["year"])
    assert doc.id == first_id and doc.doc_type == "BO" and doc.status == "draft"
    assert doc.op_date == date(books["year"], 1, 1)
    async with AsyncSessionLocal() as db:
        lines = (
            await db.scalars(
                select(LedgerLine).where(LedgerLine.document_id == doc.id).order_by(LedgerLine.line_no)
            )
        ).all()
    assert {(line.side, line.counterparty_id) for line in lines} == {
        ("debit", books["buyer"].id),
        ("credit", books["supplier"].id),
    }
    again = await _import(client, world, books, _opening_csv(books), save=True)
    assert again.status_code == 200 and again.json()["document_id"] != first_id
    assert (await _document("opening_import", books["year"])).id == again.json()["document_id"]
    approved = await client.post(
        f"{ACC}/documents/approve",
        json={"ids": [again.json()["document_id"]]},
        headers=_headers(world["accountant"]),
    )
    assert approved.json()["approved"], approved.text
    locked = await _import(client, world, books, _opening_csv(books), save=True)
    assert locked.status_code == 409 and "stornem" in locked.json()["detail"]


async def test_opening_import_needs_accountants_list(client, world, books):
    refused = await _import(client, world, books, _opening_csv(books), save=False, user="module_only")
    assert refused.status_code == 403
    broken = await _import(client, world, books, b"A;B\n1;2\n", save=False)
    assert broken.status_code == 422

async def _approve_ids(client, world, ids: list[int]) -> None:
    response = await client.post(
        f"{ACC}/documents/approve",
        json={"ids": ids},
        headers=_headers(world["accountant"]),
    )
    assert len(response.json()["approved"]) == len(ids), response.text


async def _reverse(client, world, doc_id: int, day: date) -> None:
    response = await client.post(
        f"{ACC}/documents/{doc_id}/reverse",
        json={"op_date": day.isoformat(), "reason": "faktura wycofana"},
        headers=_headers(world["accountant"]),
    )
    assert response.status_code == 200, response.text


async def _contractor_entry(world, books, contract_id: int) -> tuple[int, int]:
    """Faktura kontraktora z kontraktem klienta, gotowa do księgowania w marcu."""

    year, acc = books["year"], books["acc"]
    nip = world["nips"]["supplier"]
    async with AsyncSessionLocal() as db:
        invoice = ClientContractorInvoice(
            ksef_number=f"{nip}-20501231-{uuid.uuid4().hex[:12].upper()}-AB",
            seller_nip=nip,
            seller_name="Kontraktor Testowy",
            invoice_number=f"K/{random.randint(1, 99999)}/03",
            issue_date=date(year, 3, 2),
            gross_amount=Decimal("1230.00"),
            net_amount=Decimal("1000.00"),
            vat_amount=Decimal("230.00"),
            contract_id=contract_id,
            period_month=f"{year}-02",
            nip_state="known",
        )
        db.add(invoice)
        await db.commit()
        await cost_queue.catch_up(db)
        await db.commit()
        entry_id = await db.scalar(
            select(FinanceCostEntry.id).where(
                FinanceCostEntry.source_type == "contractor_invoice",
                FinanceCostEntry.source_id == invoice.id,
            )
        )
        invoice_id = invoice.id
    await _ready(
        entry_id,
        received=datetime(year, 3, 16, 10, 0, tzinfo=timezone.utc),
        counterparty_id=books["supplier"].id,
        decree=_decree(
            acc,
            net=100_000,
            vat=23_000,
            payable=books["supplier"].cost_account,
            text="Kontraktor",
        ),
    )
    return entry_id, invoice_id


async def _drop_contractor(invoice_id, client_id, candidate_id) -> None:
    async with AsyncSessionLocal() as db:
        if invoice_id:
            await db.execute(
                delete(FinanceCostEntry).where(
                    FinanceCostEntry.source_type == "contractor_invoice",
                    FinanceCostEntry.source_id == invoice_id,
                )
            )
            await db.execute(
                delete(ClientContractorInvoice).where(
                    ClientContractorInvoice.id == invoice_id
                )
            )
        await db.commit()
    await _cleanup_client(client_id)
    async with AsyncSessionLocal() as db:
        await db.execute(delete(Candidate).where(Candidate.id == candidate_id))
        await db.commit()


async def test_allocation_follows_postings_of_each_month(client, world, books):
    """Storno FVZ w kwietniu zostawia zamknięty marzec i odejmuje koszt w kwietniu."""

    year, acc = books["year"], books["acc"]
    await _set_ledger(_ledger_settings(world, books, allocation=True))
    client_id = await _client()
    candidate_id = await _candidate()
    contract_id = await _contract(client_id, candidate_id)
    invoice_id = None
    try:
        entry_id, invoice_id = await _contractor_entry(world, books, contract_id)
        await _sync(client, world, books, "costs")
        await _approve_ids(
            client,
            world,
            [
                (await _document("finance_cost_entry", key)).id
                for key in (books["expense"], books["payroll"], entry_id)
            ],
        )
        march = await _summary(client, world, books)
        assert {(d["code"], d["amount"]) for d in march["allocation"]["details"]} >= {
            (f"K{client_id}", 100_000),
            ("OG", 100_000),
        }
        await _sync(client, world, books, "allocation")
        general = await _document("cost_allocation", f"{year}-03")
        team = await _document("cost_allocation", f"{year}-03-payroll")
        await _approve_ids(client, world, [general.id, team.id])
        closed = await client.post(
            f"{ACC}/periods/{general.period_id}/close",
            headers=_headers(world["accountant"]),
        )
        assert closed.status_code == 200, closed.text
        expense = await _document("finance_cost_entry", books["expense"])
        await _reverse(client, world, expense.id, date(year, 4, 10))
        after = await _summary(client, world, books)
        assert after["allocation"]["problems_total"] == 0
        assert after["allocation"]["changed"] == 0
        april = await _summary(client, world, books, month=4)
        assert [(d["code"], d["amount"]) for d in april["allocation"]["details"]] == [
            ("OG", -100_000)
        ]
        synced = await _sync(client, world, books, "allocation", month=4)
        assert synced.json()["created"] == 1, synced.text
        april_pk = await _document("cost_allocation", f"{year}-04")
        assert await _lines(april_pk.id) == [
            ("credit", acc["alloc_og"], 100_000),
            ("debit", acc["settle"], 100_000),
        ]
        await _approve_ids(client, world, [april_pk.id])
        balance = await client.get(
            f"{ACC}/trial-balance",
            params={"year": year, "level": "synthetic"},
            headers=_headers(world["admin"]),
        )
        rows = {row["account"]: row for row in balance.json()["items"]}
        cost = rows[acc["cost"]]["ytd_wn"] - rows[acc["cost"]]["ytd_ma"]
        settled = rows[acc["settle"]]["ytd_ma"] - rows[acc["settle"]]["ytd_wn"]
        assert cost == settled == 1_100_000
    finally:
        await _drop_contractor(invoice_id, client_id, candidate_id)


async def test_approved_allocation_of_a_month_without_costs_is_reported(
    client, world, books
):
    year = books["year"]
    await _set_ledger(_ledger_settings(world, books, allocation=True))
    await _approved_costs(client, world, books)
    await _sync(client, world, books, "allocation")
    draft = await _document("cost_allocation", f"{year}-03")
    await _approve_ids(client, world, [draft.id])
    general = await _document("cost_allocation", f"{year}-03")
    expense = await _document("finance_cost_entry", books["expense"])
    await _reverse(client, world, expense.id, date(year, 3, 20))
    summary = await _summary(client, world, books)
    hints = [item["problems"][0] for item in summary["allocation"]["problems"]]
    assert any(f"storno zapisu nr {general.journal_no}" in hint for hint in hints), hints
    synced = await _sync(client, world, books, "allocation")
    assert synced.json()["problems_total"] == 1, synced.text
    assert (await _document("cost_allocation", f"{year}-03")).status == "approved"


async def test_chart_change_keeps_posted_costs_in_allocation(client, world, books):
    acc = books["acc"]
    await _set_ledger(_ledger_settings(world, books, allocation=True))
    await _approved_costs(client, world, books)
    before = (await _summary(client, world, books))["allocation"]["details"]
    assert before
    created = await client.post(
        f"{ACC}/chart",
        json={
            "number": f"{acc['cost']}-1",
            "name": "Usługi obce — analityka",
            "kind": "cost",
            "parent_number": acc["cost"],
        },
        headers=_headers(world["admin"]),
    )
    assert created.status_code == 201, created.text
    after = (await _summary(client, world, books))["allocation"]["details"]
    assert after == before


# ── PK cykliczne i RMK (K3a) ────────────────────────────────────────────────


def _automation_settings(world, books) -> dict:
    value = _ledger_settings(world, books, allocation=False)
    value["modules"] = {"ledger": True, "automations": True}
    return value


async def _automation_post(client, world, path: str, body: dict, user="accountant"):
    return await client.post(f"{ACC}/automations/{path}", json=body, headers=_headers(world[user]))


def _rent(books, *, start: str) -> dict:
    acc = books["acc"]
    return {
        "name": "Najem biura",
        "lines": [
            {"side": "debit", "account": acc["cost"], "amount": "1000.00", "mpk": "OG"},
            {
                "side": "credit",
                "account": books["supplier"].cost_account,
                "amount": "1000.00",
                "counterparty_id": books["supplier"].id,
            },
        ],
        "start_month": start,
    }


def _policy(books, *, start: str) -> dict:
    acc = books["acc"]
    return {
        "name": "Polisa OC",
        "reference": "PL-1",
        "cost_account": acc["cost"],
        "prepaid_account": acc["prepaid"],
        "total_amount": "1000.00",
        "start_month": start,
        "months": 3,
    }


async def test_recurring_and_prepayment_post_each_month(client, world, books):
    year, acc = books["year"], books["acc"]
    await _set_ledger(_automation_settings(world, books))
    rent = await _automation_post(client, world, "recurring", _rent(books, start=f"{year}-03-01"))
    assert rent.status_code == 201, rent.text
    policy = await _automation_post(client, world, "prepayments", _policy(books, start=f"{year}-03-01"))
    assert policy.status_code == 201, policy.text
    template_id = max(item["id"] for item in rent.json()["recurring"])
    policy_id = max(item["id"] for item in policy.json()["prepayments"])
    created = next(i for i in policy.json()["prepayments"] if i["id"] == policy_id)
    assert created["installment"] == 33_333
    summary = await _summary(client, world, books)
    assert summary["recurring"]["to_post"] == 1 and summary["prepayments"]["to_post"] == 1
    for kind in ("recurring", "prepayments"):
        synced = await _sync(client, world, books, kind)
        assert synced.json()["created"] == 1, synced.text
    march_rent = await _document("ledger_recurring", f"{template_id}:{year}-03")
    march_policy = await _document("ledger_prepayment", f"{policy_id}:{year}-03")
    assert march_rent.op_date == date(year, 3, 31)
    assert await _lines(march_policy.id) == [
        ("debit", acc["cost"], 33_333),
        ("credit", acc["prepaid"], 33_333),
    ]
    may = await _sync(client, world, books, "prepayments", month=5)
    assert may.json()["created"] == 1
    last = await _document("ledger_prepayment", f"{policy_id}:{year}-05")
    assert (await _lines(last.id))[0][2] == 33_334
    await _approve_ids(client, world, [march_rent.id, march_policy.id])
    headers = _headers(world["accountant"])
    locked = await client.patch(
        f"{ACC}/automations/recurring/{template_id}",
        json={"lines": _rent(books, start=f"{year}-03-01")["lines"]},
        headers=headers,
    )
    assert locked.status_code == 409 and "Zakończ" in locked.json()["detail"]
    too_early = await client.patch(
        f"{ACC}/automations/recurring/{template_id}",
        json={"end_month": f"{year}-02-01"},
        headers=headers,
    )
    assert too_early.status_code == 409
    ended = await client.patch(
        f"{ACC}/automations/recurring/{template_id}",
        json={"end_month": f"{year}-04-01"},
        headers=headers,
    )
    assert ended.status_code == 200, ended.text
    june = await _summary(client, world, books, month=6)
    assert june["recurring"]["total"] == 0
    removed = await client.delete(f"{ACC}/automations/prepayments/{policy_id}", headers=headers)
    assert removed.status_code == 409


async def test_automations_need_module_and_accountants_list(client, world, books):
    year = books["year"]
    await _set_ledger(_ledger_settings(world, books, allocation=False))
    hidden = await client.get(f"{ACC}/automations", headers=_headers(world["module_only"]))
    assert hidden.status_code == 404
    summary = await _summary(client, world, books, user="module_only")
    assert "recurring" not in summary
    await _set_ledger(_automation_settings(world, books))
    seen = await client.get(f"{ACC}/automations", headers=_headers(world["module_only"]))
    assert seen.status_code == 200
    refused = await _automation_post(
        client, world, "recurring", _rent(books, start=f"{year}-03-01"), user="module_only"
    )
    assert refused.status_code == 403
    unbalanced = _rent(books, start=f"{year}-03-01")
    unbalanced["lines"][1]["amount"] = "999.99"
    bad = await _automation_post(client, world, "recurring", unbalanced)
    assert bad.status_code == 422


async def test_draft_of_removed_template_is_withdrawn(client, world, books):
    year = books["year"]
    await _set_ledger(_automation_settings(world, books))
    rent = await _automation_post(client, world, "recurring", _rent(books, start=f"{year}-03-01"))
    template_id = max(item["id"] for item in rent.json()["recurring"])
    first = await _sync(client, world, books, "recurring")
    assert first.json()["created"] == 1, first.text
    removed = await client.delete(
        f"{ACC}/automations/recurring/{template_id}", headers=_headers(world["accountant"])
    )
    assert removed.status_code == 200, removed.text
    # Szkic znika od razu — inaczej do następnego księgowania dałoby się go
    # zatwierdzić i dostać problem „zrób storno” (przegląd K3a 14.11.2026).
    assert await _document("ledger_recurring", f"{template_id}:{year}-03") is None
    again = await _sync(client, world, books, "recurring")
    assert again.json()["deleted"] == 0


async def test_ending_template_withdraws_later_drafts(client, world, books):
    year = books["year"]
    await _set_ledger(_automation_settings(world, books))
    rent = await _automation_post(client, world, "recurring", _rent(books, start=f"{year}-03-01"))
    template_id = max(item["id"] for item in rent.json()["recurring"])
    for month in (3, 4):
        synced = await _sync(client, world, books, "recurring", month=month)
        assert synced.json()["created"] == 1, synced.text
    march = await _document("ledger_recurring", f"{template_id}:{year}-03")
    await _approve_ids(client, world, [march.id])
    ended = await client.patch(
        f"{ACC}/automations/recurring/{template_id}",
        json={"end_month": f"{year}-03-01"},
        headers=_headers(world["accountant"]),
    )
    assert ended.status_code == 200, ended.text
    assert await _document("ledger_recurring", f"{template_id}:{year}-04") is None
    kept = await _document("ledger_recurring", f"{template_id}:{year}-03")
    assert kept is not None and kept.status == "approved"


async def test_changed_prepayment_withdraws_its_drafts(client, world, books):
    year = books["year"]
    await _set_ledger(_automation_settings(world, books))
    body = _policy(books, start=f"{year}-03-01")
    policy = await _automation_post(client, world, "prepayments", body)
    policy_id = max(item["id"] for item in policy.json()["prepayments"])
    synced = await _sync(client, world, books, "prepayments")
    assert synced.json()["created"] == 1, synced.text
    changed = await client.patch(
        f"{ACC}/automations/prepayments/{policy_id}",
        json={**body, "total_amount": "1200.00"},
        headers=_headers(world["accountant"]),
    )
    assert changed.status_code == 200, changed.text
    assert await _document("ledger_prepayment", f"{policy_id}:{year}-03") is None
    rebuilt = await _sync(client, world, books, "prepayments")
    assert rebuilt.json()["created"] == 1, rebuilt.text
    doc = await _document("ledger_prepayment", f"{policy_id}:{year}-03")
    assert (await _lines(doc.id))[0][2] == 40_000


# ── Paczki do Symfonii (K3b) ────────────────────────────────────────────────


async def _exports(client, world, books, user: str = "accountant") -> dict:
    response = await client.get(
        f"{ACC}/exports",
        params={"year": books["year"], "month": 3},
        headers=_headers(world[user]),
    )
    assert response.status_code == 200, response.text
    return response.json()


async def _export(client, world, books, kinds, user: str = "accountant", **extra):
    return await client.post(
        f"{ACC}/exports",
        json={"year": books["year"], "month": 3, "kinds": kinds, **extra},
        headers=_headers(world[user]),
    )


async def _approved_automations(client, world, books) -> list[int]:
    """Najem (1 000 zł) i rata polisy (333,33 zł) za marzec, zatwierdzone."""

    year = books["year"]
    await _set_ledger(_automation_settings(world, books))
    rent = await _automation_post(client, world, "recurring", _rent(books, start=f"{year}-03-01"))
    assert rent.status_code == 201, rent.text
    policy = await _automation_post(client, world, "prepayments", _policy(books, start=f"{year}-03-01"))
    assert policy.status_code == 201, policy.text
    for kind in ("recurring", "prepayments"):
        synced = await _sync(client, world, books, kind)
        assert synced.json()["created"] == 1, synced.text
    template_id = max(item["id"] for item in rent.json()["recurring"])
    policy_id = max(item["id"] for item in policy.json()["prepayments"])
    ids = [
        (await _document("ledger_recurring", f"{template_id}:{year}-03")).id,
        (await _document("ledger_prepayment", f"{policy_id}:{year}-03")).id,
    ]
    await _approve_ids(client, world, ids)
    return ids


async def test_export_packs_each_approved_document_once(client, world, books):
    rent_id, policy_id = await _approved_automations(client, world, books)
    year, acc = books["year"], books["acc"]
    preview = await _exports(client, world, books)
    assert preview["exportable"] is True and preview["drafts"] == 0
    kinds = {item["key"]: item for item in preview["kinds"]}
    assert kinds["recurring"]["count"] == 1 and kinds["prepayments"]["count"] == 1
    assert kinds["recurring"]["default"] and not kinds["costs"]["default"]
    numbers = {doc["id"]: doc["number"] for doc in preview["documents"]}
    assert set(numbers) == {rent_id, policy_id}
    created = await _export(client, world, books, ["recurring", "prepayments"])
    assert created.status_code == 201, created.text
    first = created.json()
    assert first["number"] == f"K/{year}-03/1" and first["status"] == "exported"
    assert first["document_count"] == 2 and first["debit_total"] == 100_000 + 33_333
    # Dokument jest najwyżej w jednej aktywnej paczce.
    again = await _export(client, world, books, ["recurring", "prepayments"])
    assert again.status_code == 409
    after = await _exports(client, world, books)
    assert after["documents"] == []
    assert [item["number"] for item in after["exports"]] == [first["number"]]
    # Plik pobiera też osoba z „Modułem Finanse” spoza listy — ten sam, co zapisany.
    file = await client.get(
        f"{ACC}/exports/{first['id']}/file", headers=_headers(world["module_only"])
    )
    assert file.status_code == 200
    assert hashlib.sha256(file.content).hexdigest() == first["file_sha256"]
    rows = list(load_workbook(io.BytesIO(file.content)).active.iter_rows(values_only=True))
    header = list(rows[0])
    body = [dict(zip(header, row)) for row in rows[1:]]
    assert len(body) == 4
    assert round(sum(row["Wn"] or 0 for row in body), 2) == 1333.33
    assert round(sum(row["Ma"] or 0 for row in body), 2) == 1333.33
    supplier = books["supplier"]
    rent_credit = next(row for row in body if row["Konto"] == supplier.cost_account)
    assert rent_credit["ID Symfonii kontrahenta"] == supplier.symfonia_partner_id
    assert {row["Konto"] for row in body} == {acc["cost"], supplier.cost_account, acc["prepaid"]}
    # Anulowana paczka zwalnia dokumenty; numer rośnie dalej.
    headers = _headers(world["accountant"])
    cancelled = await client.post(f"{ACC}/exports/{first['id']}/cancel", headers=headers)
    assert cancelled.status_code == 200 and cancelled.json()["status"] == "cancelled"
    second = await _export(client, world, books, ["recurring"])
    assert second.status_code == 201, second.text
    assert second.json()["number"] == f"K/{year}-03/2"
    assert second.json()["document_count"] == 1
    booked = await client.post(f"{ACC}/exports/{second.json()['id']}/book", headers=headers)
    assert booked.status_code == 200 and booked.json()["status"] == "booked"
    late = await client.post(f"{ACC}/exports/{second.json()['id']}/cancel", headers=headers)
    assert late.status_code == 409
    # Storno idzie z rodzajem dokumentu, który odwraca, i z jego numerem w pliku.
    await _reverse(client, world, rent_id, date(year, 3, 31))
    left = await _exports(client, world, books)
    assert sorted(doc["kind"] for doc in left["documents"]) == ["prepayments", "recurring"]
    storno = next(doc for doc in left["documents"] if doc["doc_type"] == "ST")
    assert storno["kind"] == "recurring"
    third = await _export(client, world, books, ["recurring"], file_format="neutral_csv")
    assert third.status_code == 201, third.text
    csv_file = await client.get(f"{ACC}/exports/{third.json()['id']}/file", headers=headers)
    assert csv_file.headers["content-type"].startswith("text/csv")
    assert numbers[rent_id] in csv_file.content.decode("utf-8-sig")


async def test_payroll_documents_go_in_a_separate_package(client, world, books):
    settings = _ledger_settings(world, books, allocation=False)
    settings["accountants"] = [world["accountant"].id, world["module_only"].id]
    await _set_ledger(settings)
    await _approved_costs(client, world, books)
    outside = await _exports(client, world, books, user="module_only")
    costs = next(item for item in outside["kinds"] if item["key"] == "costs")
    assert costs["count"] == 1 and costs["payroll_count"] == 0
    assert [doc["payroll"] for doc in outside["documents"]] == [False]
    inside = await _exports(client, world, books)
    costs = next(item for item in inside["kinds"] if item["key"] == "costs")
    assert costs["count"] == 1 and costs["payroll_count"] == 1
    refused = await _export(client, world, books, ["costs"], user="module_only", payroll=True)
    assert refused.status_code == 403
    plain = await _export(client, world, books, ["costs"], user="module_only")
    assert plain.status_code == 201, plain.text
    assert plain.json()["has_payroll"] is False and plain.json()["document_count"] == 1
    team = await _export(client, world, books, ["costs"], payroll=True)
    assert team.status_code == 201, team.text
    assert team.json()["has_payroll"] is True and team.json()["document_count"] == 1
    assert team.json()["file_name"].endswith("-place.xlsx")
    seen = await _exports(client, world, books, user="module_only")
    assert [item["id"] for item in seen["exports"]] == [plain.json()["id"]]
    hidden = await client.get(
        f"{ACC}/exports/{team.json()['id']}/file", headers=_headers(world["module_only"])
    )
    assert hidden.status_code == 404
    both = await _exports(client, world, books)
    assert {item["id"] for item in both["exports"]} == {plain.json()["id"], team.json()["id"]}


async def test_export_needs_symfonia_year_and_accountants_list(client, world, books):
    await _approved_automations(client, world, books)
    refused = await _export(client, world, books, ["recurring"], user="module_only")
    assert refused.status_code == 403
    unknown = await _export(client, world, books, ["salary"])
    assert unknown.status_code == 422
    async with AsyncSessionLocal() as db:
        year_id = await db.scalar(
            select(LedgerYear.id).where(LedgerYear.year == books["year"])
        )
    mode = await client.patch(
        f"{ACC}/years/{year_id}", json={"mode": "nexus"}, headers=_headers(world["admin"])
    )
    assert mode.status_code == 200, mode.text
    preview = await _exports(client, world, books)
    assert preview["exportable"] is False and "NEXUS" in preview["refusal"]
    blocked = await _export(client, world, books, ["recurring"])
    assert blocked.status_code == 409


# ── Lista zamknięcia miesiąca (K3d) ─────────────────────────────────────────


async def _closing(client, world, books, user: str = "accountant") -> dict:
    response = await client.get(
        f"{ACC}/closing",
        params={"year": books["year"], "month": 3},
        headers=_headers(world[user]),
    )
    assert response.status_code == 200, response.text
    return response.json()


async def test_closing_checklist_follows_sources_buffer_and_symfonia(client, world, books):
    await _approved_automations(client, world, books)
    year = books["year"]
    data = await _closing(client, world, books)
    items = {item["key"]: item for item in data["items"]}
    assert data["period_status"] == "open"
    assert items["source:recurring"]["state"] == "ok"
    assert items["source:costs"]["state"] == "todo"
    assert items["source:costs"]["detail"] == "do zaksięgowania: 2"
    assert items["drafts"]["state"] == "ok"
    symfonia = items["symfonia"]
    assert symfonia["state"] == "todo" and symfonia["detail"] == "zatwierdzone poza paczką: 2"
    assert symfonia["href"] == f"/accounting/symfonia?year={year}&month=3"
    assert items["later:bank"]["state"] == "later"
    assert [item["key"] for item in data["deadlines"]] == ["zus", "ppk", "pit", "vat"]
    assert data["deadlines"][0]["nominal"] == f"{year}-04-15"
    created = await _export(client, world, books, ["recurring", "prepayments"])
    assert created.status_code == 201, created.text
    waiting = {item["key"]: item for item in (await _closing(client, world, books))["items"]}
    assert waiting["symfonia"]["detail"] == (
        f"czeka na „Zaksięgowana w Symfonii”: K/{year}-03/1"
    )
    booked = await client.post(
        f"{ACC}/exports/{created.json()['id']}/book", headers=_headers(world["accountant"])
    )
    assert booked.status_code == 200, booked.text
    done = {item["key"]: item for item in (await _closing(client, world, books))["items"]}
    assert done["symfonia"]["state"] == "ok"
    # Rok w trybie NEXUS nie ma paczek — pozycji „Paczka do Symfonii” nie ma na liście.
    async with AsyncSessionLocal() as db:
        year_id = await db.scalar(select(LedgerYear.id).where(LedgerYear.year == year))
    mode = await client.patch(
        f"{ACC}/years/{year_id}", json={"mode": "nexus"}, headers=_headers(world["admin"])
    )
    assert mode.status_code == 200, mode.text
    nexus = {item["key"] for item in (await _closing(client, world, books))["items"]}
    assert "symfonia" not in nexus and "drafts" in nexus


# ── Lista płac z Enovy (K3c) ────────────────────────────────────────────────

PAYROLL_CSV = "\r\n".join(
    [
        "Pracownik;Wydział;Razem brutto;Emerytalne prac.;Rentowe prac.;Chorobowe;Zdrowotne;"
        "Zaliczka podatku;PPK pracownika;Do wypłaty;Emerytalne pracodawca;Rentowe pracodawca;"
        "Wypadkowe;FP;FGŚP;PPK pracodawcy",
        "Osoba A;FO;10000,00;976,00;150,00;245,00;776,61;588,00;200,00;7064,39;976,00;650,00;"
        "167,00;245,00;10,00;150,00",
        "Osoba B;BO;8000,00;780,80;120,00;196,00;621,29;470,00;0;5811,91;780,80;520,00;"
        "133,60;196,00;8,00;0",
        "Razem;;18000,00;;;;;;;;;;;;;",
    ]
).encode("utf-8")


def _payroll_settings(world, books) -> dict:
    acc = books["acc"]
    value = _automation_settings(world, books)
    value["payroll"] = {
        "wages_account": acc["wages"],
        "insurance_account": acc["insurance"],
        "settlement_account": acc["payroll_settle"],
        "zus_account": acc["zus"],
        "pit_account": acc["pit"],
        "ppk_account": acc["ppk"],
        "deductions_account": "",
    }
    return value


async def _payroll_import(client, world, books, *, save: bool, user="accountant"):
    return await client.post(
        f"{ACC}/payroll-lists/import",
        params={"year": books["year"], "month": 3, "list": "LP 03", "save": save},
        files={"file": ("lista.csv", PAYROLL_CSV, "text/csv")},
        headers=_headers(world[user]),
    )


async def test_payroll_list_from_enova_goes_to_buffer_for_payroll_only(client, world, books):
    year, acc = books["year"], books["acc"]
    await _set_ledger(_payroll_settings(world, books))
    outsider = await _payroll_import(client, world, books, save=False, user="module_only")
    assert outsider.status_code == 403
    preview = await _payroll_import(client, world, books, save=False)
    assert preview.status_code == 200, preview.text
    data = preview.json()
    assert data["rows"] == 2 and data["skipped"] == 1 and data["problems"] == []
    assert data["totals"]["gross"] == 1_800_000 and data["totals"]["net"] == 1_287_630
    assert data["saved"] is False and data["warnings"] == []
    before = {item["key"]: item for item in (await _closing(client, world, books))["items"]}
    assert before["payroll"]["state"] == "todo"
    saved = await _payroll_import(client, world, books, save=True)
    assert saved.status_code == 200, saved.text
    after = {item["key"]: item for item in (await _closing(client, world, books))["items"]}
    assert after["payroll"]["state"] == "ok" and after["payroll"]["detail"] == "w księdze: 1"
    # Osoba bez Płac widzi tylko, kto wczytuje listę — bez liczby (D2).
    hidden = await _closing(client, world, books, user="module_only")
    payroll_item = next(item for item in hidden["items"] if item["key"] == "payroll")
    assert payroll_item["state"] == "later" and "w księdze" not in payroll_item["detail"]
    first = await _document("payroll_list", f"{year}-03:lp03")
    assert first.doc_type == "LP" and first.sensitivity == "payroll"
    assert first.op_date == date(year, 3, 31)
    lines = await _lines(first.id)
    assert (("debit", acc["wages"], 1_000_000)) in lines
    assert sum(amount for side, _, amount in lines if side == "debit") == sum(
        amount for side, _, amount in lines if side == "credit"
    )
    # Ponowny import tej samej listy przebudowuje szkic.
    again = await _payroll_import(client, world, books, save=True)
    assert again.status_code == 200, again.text
    rebuilt = await _document("payroll_list", f"{year}-03:lp03")
    assert rebuilt.id != first.id
    await _approve_ids(client, world, [rebuilt.id])
    locked = await _payroll_import(client, world, books, save=True)
    assert locked.status_code == 409 and "storn" in locked.json()["detail"]
    # Osoba bez Płac nie widzi listy w dokumentach (D2).
    listed = await client.get(
        f"{ACC}/documents",
        params={"year": year, "month": 3, "doc_type": "LP"},
        headers=_headers(world["module_only"]),
    )
    assert listed.status_code == 200 and listed.json()["items"] == []


async def test_payroll_list_needs_accounts_and_automations_module(client, world, books):
    await _set_ledger(_ledger_settings(world, books, allocation=False))
    closed = await _payroll_import(client, world, books, save=False)
    assert closed.status_code == 404
    await _set_ledger(_automation_settings(world, books))
    preview = await _payroll_import(client, world, books, save=False)
    assert preview.status_code == 200, preview.text
    assert "Wynagrodzenia (koszt)" in preview.json()["problems"][0]
    refused = await _payroll_import(client, world, books, save=True)
    assert refused.status_code == 422

