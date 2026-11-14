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
from app.models.client_sales_invoice import (
    ClientSalesInvoice,
    ClientSalesInvoicePayment,
)
from app.models.finance_ledger import FinanceCostEntry, FinanceCounterparty
from app.models.finance_payments import FinanceCostPaymentRecord
from app.models.hr_payroll import PayrollPeriod
from app.models.hr_settlement import (
    EmployeeBillingDetails,
    PayrollInvoice,
    PayrollPayment,
    PayrollSettlement,
)
from app.models.finance_posting import FinanceAccount
from app.models.fx_rate import FxRate
from app.models.candidate import Candidate
from app.models.client_settlement import ClientContractorInvoice
from app.models.hr_profile import EmployeeProfile
from app.models.ledger import (
    LedgerBankStatement,
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
        ) or await db.scalar(
            select(func.count())
            .select_from(LedgerBankStatement)
            .where(LedgerBankStatement.first_day.between(date(year, 1, 1), date(year, 12, 31)))
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
            "bank": (f"{prefix}-130", "Rachunek bieżący", "other", None),
            "fees": (f"{prefix}-409", "Opłaty bankowe", "other", None),
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
    await _purge_bank(year)
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


async def _purge_bank(year: int) -> None:
    """Wyciągi roku testu i zapłaty, które ich import zapisał w E3, R9 i E8."""

    async with AsyncSessionLocal() as db:
        shas = list(
            await db.scalars(
                select(LedgerBankStatement.sha256).where(
                    LedgerBankStatement.first_day.between(date(year, 1, 1), date(year, 12, 31))
                )
            )
        )
        if shas:
            for model in (FinanceCostPaymentRecord, PayrollPayment, ClientSalesInvoicePayment):
                await db.execute(delete(model).where(model.statement_sha256.in_(shas)))
            await db.execute(delete(LedgerBankStatement).where(LedgerBankStatement.sha256.in_(shas)))
        await db.commit()


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


async def test_approved_payroll_list_goes_to_the_default_payroll_package(client, world, books):
    # Zatwierdzony LP to dokument dla Symfonii: domyślnie w paczce płacowej,
    # a do czasu paczki lista zamknięcia nie mówi „wszystko w paczkach”.
    year = books["year"]
    await _set_ledger(_payroll_settings(world, books))
    saved = await _payroll_import(client, world, books, save=True)
    assert saved.status_code == 200, saved.text
    doc = await _document("payroll_list", f"{year}-03:lp03")
    await _approve_ids(client, world, [doc.id])
    items = {item["key"]: item for item in (await _closing(client, world, books))["items"]}
    assert items["symfonia"]["state"] == "todo"
    assert items["symfonia"]["detail"] == "zatwierdzone poza paczką: 1"
    preview = await _exports(client, world, books)
    kinds = {item["key"]: item for item in preview["kinds"]}
    assert kinds["payroll"]["default"] and kinds["payroll"]["payroll_count"] == 1
    default = [item["key"] for item in preview["kinds"] if item["default"]]
    package = await _export(client, world, books, default, payroll=True)
    assert package.status_code == 201, package.text
    assert package.json()["document_count"] == 1
    after = {item["key"]: item for item in (await _closing(client, world, books))["items"]}
    assert after["symfonia"]["detail"].startswith("czeka na „Zaksięgowana w Symfonii”")


# ── Bank: jeden import wyciągu (K4a) ────────────────────────────────────────

def _valid_nrb(bban: str) -> str:
    """NRB z poprawną sumą kontrolną (parser wyciągu odrzuca błędne)."""

    check = 98 - int(bban + "252100") % 97
    return f"{check:02d}{bban}"


COMPANY = _valid_nrb("109010140000071219812875")
ZUS_ACCOUNT = _valid_nrb("600000020260000000000000")
TAX_ACCOUNT = _valid_nrb("101000712221234567890123")
OTHER_ACCOUNT = _valid_nrb("109010140000071219812874")
TEAM_ACCOUNT = _valid_nrb("109010140000071219812876")


def _statement(year: int, *operations: tuple[str, str, str, str, str], day: str = "20") -> bytes:
    """MT940: (D/C, kwota, tytuł, rachunek kontrahenta albo „”, referencja banku)."""

    yy = f"{year % 100:02d}"
    body = f":20:K4\r\n:25:/PL{COMPANY}\r\n:60F:C{yy}0301PLN100000,00\r\n"
    for direction, amount, title, account, ref in operations:
        body += f":61:{yy}03{day}03{day}{direction}{amount}NTRFNONREF//{ref}\r\n"
        body += f":86:020~00TR~20{title}~32Kontrahent Testowy"
        body += (f"~38PL{account}" if account else "") + "\r\n"
    return (body + f":62F:C{yy}03{day}PLN0,00\r\n-").encode()


def _bank_settings(world, books) -> dict:
    acc = books["acc"]
    value = _ledger_settings(world, books, allocation=False)
    value["modules"] = {"ledger": True, "bank": True}
    value["bank"] = {
        "accounts": [{"number": COMPANY, "account": acc["bank"], "name": "Konto główne"}],
        "fees_account": acc["fees"],
        "zus_account": acc["zus"],
        "vat_account": acc["vat_out"],
        "pit_account": acc["pit"],
        "cit_account": "",
    }
    return value


async def _bank_import(client, world, content: bytes, user: str = "accountant"):
    return await client.post(
        f"{ACC}/bank/import",
        files={"file": ("wyciag.sta", content, "text/plain")},
        headers=_headers(world[user]),
    )


async def test_bank_statement_is_classified_posted_once_and_deduplicated(client, world, books):
    year, acc = books["year"], books["acc"]
    await _set_ledger(_bank_settings(world, books))
    marker = uuid.uuid4().hex[:6].upper()
    content = _statement(
        year,
        ("D", "1000,00", "Składki ZUS 03", ZUS_ACCOUNT, f"Z{marker}"),
        ("D", "500,00", "/TI/N5260000000/OKR/26M02/SFP/VAT-7M/TXT/VAT", TAX_ACCOUNT, f"T{marker}"),
        ("D", "12,50", "Opłata za prowadzenie rachunku", "", f"F{marker}"),
        ("D", "300,00", "Faktura spoza NEXUSA", OTHER_ACCOUNT, f"U{marker}"),
        ("C", "250,00", "Wpłata bez faktury", OTHER_ACCOUNT, f"C{marker}"),
    )
    imported = await _bank_import(client, world, content)
    assert imported.status_code == 201, imported.text
    data = imported.json()
    assert data["already_imported"] is False
    kinds = [(line["kind"], line["counter_account"]) for line in data["lines"]]
    assert kinds == [
        ("zus", acc["zus"]),
        ("tax", acc["vat_out"]),
        ("fee", acc["fees"]),
        ("unmatched", None),
        ("unmatched", None),
    ]
    assert data["unresolved"] == 2 and data["debit_total"] == 181_250
    items = {item["key"]: item for item in (await _closing(client, world, books))["items"]}
    assert "later:bank" not in items
    assert items["bank"]["state"] == "problem"
    assert items["bank"]["detail"] == "operacje bez konta: 2, wyciągi bez WB: 1"
    assert items["bank"]["href"] == f"/accounting/bank?year={year}&month=3"
    headers = _headers(world["accountant"])
    refused = await client.post(f"{ACC}/bank/statements/{data['id']}/post", headers=headers)
    assert refused.status_code == 422 and "bez konta" in refused.json()["detail"]
    for line, account in ((data["lines"][3], acc["cost"]), (data["lines"][4], acc["revenue"])):
        assigned = await client.patch(
            f"{ACC}/bank/lines/{line['id']}", json={"account": account}, headers=headers
        )
        assert assigned.status_code == 200, assigned.text
    posted = await client.post(f"{ACC}/bank/statements/{data['id']}/post", headers=headers)
    assert posted.status_code == 200, posted.text
    assert posted.json()["created"] == 1
    wb = await _document("bank_statement", data["id"])
    assert wb.doc_type == "WB" and wb.op_date == date(year, 3, 20)
    lines = await _lines(wb.id)
    assert ("credit", acc["bank"], 100_000) in lines and ("debit", acc["bank"], 25_000) in lines
    assert sum(a for s, _, a in lines if s == "debit") == sum(a for s, _, a in lines if s == "credit")
    again = await client.post(f"{ACC}/bank/statements/{data['id']}/post", headers=headers)
    assert again.json()["unchanged"] == 1
    items = {item["key"]: item for item in (await _closing(client, world, books))["items"]}
    assert (items["bank"]["state"], items["bank"]["detail"]) == ("ok", "wyciągi: 1, WB w księdze")
    # Zmiana konta po księgowaniu przebudowuje szkic WB od razu.
    changed = await client.patch(
        f"{ACC}/bank/lines/{data['lines'][3]['id']}", json={"account": acc["fees"]}, headers=headers
    )
    assert changed.status_code == 200, changed.text
    rebuilt = await _document("bank_statement", data["id"])
    assert rebuilt.id != wb.id and rebuilt.status == "draft"
    assert ("debit", acc["fees"], 30_000) in await _lines(rebuilt.id)
    approved = await client.post(
        f"{ACC}/documents/approve", json={"ids": [rebuilt.id]}, headers=headers
    )
    assert approved.json()["approved"], approved.text
    locked = await client.patch(
        f"{ACC}/bank/lines/{data['lines'][3]['id']}", json={"account": acc["cost"]}, headers=headers
    )
    assert locked.status_code == 409 and "storna" in locked.json()["detail"]
    month = await client.get(f"{ACC}/bank", params={"year": year, "month": 3}, headers=headers)
    assert month.status_code == 200, month.text
    row = next(item for item in month.json()["statements"] if item["id"] == data["id"])
    assert (row["operations"], row["unresolved"], row["wb"]) == (5, 0, "approved")
    assert row["to_post"] is False
    assert (row["debit_total"], row["credit_total"]) == (181_250, 25_000)
    other_month = await client.get(
        f"{ACC}/bank", params={"year": year, "month": 4}, headers=headers
    )
    assert data["id"] not in [item["id"] for item in other_month.json()["statements"]]
    half = await client.get(f"{ACC}/bank", params={"year": year}, headers=headers)
    assert half.status_code == 422
    # Ten sam plik drugi raz = ten sam wyciąg.
    same = await _bank_import(client, world, content)
    assert same.status_code == 201 and same.json()["id"] == data["id"]
    assert same.json()["already_imported"] is True
    # Ta sama operacja w innym wyciągu (dzienny i miesięczny) = duplikat, bez WB.
    other = _statement(
        year,
        ("D", "1000,00", "Składki ZUS 03", ZUS_ACCOUNT, f"Z{marker}"),
        ("D", "40,00", "Opłata za przelew", "", f"G{marker}"),
    )
    second = await _bank_import(client, world, other)
    assert second.status_code == 201, second.text
    assert [line["kind"] for line in second.json()["lines"]] == ["duplicate", "fee"]
    items = {item["key"]: item for item in (await _closing(client, world, books))["items"]}
    assert (items["bank"]["state"], items["bank"]["detail"]) == ("todo", "wyciągi bez WB: 1")


async def test_bank_hides_team_payments_without_payroll(client, world, books):
    from app.core.encryption import get_token_cipher

    year = books["year"]
    settings = _bank_settings(world, books)
    settings["accountants"] = [world["accountant"].id, world["module_only"].id]
    await _set_ledger(settings)
    person = world["person"]
    encrypted = get_token_cipher().encrypt(TEAM_ACCOUNT)
    async with AsyncSessionLocal() as db:
        existing = await db.scalar(
            select(EmployeeBillingDetails).where(EmployeeBillingDetails.user_id == person.id)
        )
        created = existing is None
        previous = None if created else (existing.account_encrypted, existing.account_last4)
        if created:
            db.add(
                EmployeeBillingDetails(
                    user_id=person.id,
                    account_encrypted=encrypted,
                    account_last4=TEAM_ACCOUNT[-4:],
                    account_source="manual",
                    payment_terms_days=14,
                )
            )
        else:
            existing.account_encrypted = encrypted
            existing.account_last4 = TEAM_ACCOUNT[-4:]
        await db.commit()
    try:
        marker = uuid.uuid4().hex[:6].upper()
        content = _statement(
            year,
            ("D", "8000,00", "Wynagrodzenie 02", TEAM_ACCOUNT, f"P{marker}"),
            ("D", "12,50", "Opłata za przelew", "", f"F{marker}"),
        )
        outside = await _bank_import(client, world, content, user="module_only")
        assert outside.status_code == 201, outside.text
        data = outside.json()
        # Bez Płac: wypłaty dla zespołu nie widać — ani kwoty, ani pozycji.
        assert [line["kind"] for line in data["lines"]] == ["fee"]
        assert data["payroll_hidden"] is True and data["debit_total"] == 1_250
        # Numeracja w zasięgu osoby — bez luki, która zdradzałaby ukrytą wypłatę.
        assert [line["position"] for line in data["lines"]] == [1]
        inside = await client.get(
            f"{ACC}/bank/statements/{data['id']}", headers=_headers(world["accountant"])
        )
        lines = inside.json()["lines"]
        assert [(line["kind"], line["payroll"]) for line in lines] == [
            ("team", True),
            ("fee", False),
        ]
        assert inside.json()["payroll_hidden"] is False
        assert [line["position"] for line in lines] == [1, 2]
        for user, operations, debit in (("module_only", 1, 1_250), ("accountant", 2, 801_250)):
            listed = await client.get(
                f"{ACC}/bank", params={"year": year, "month": 3}, headers=_headers(world[user])
            )
            row = next(item for item in listed.json()["statements"] if item["id"] == data["id"])
            assert (row["operations"], row["debit_total"]) == (operations, debit)
        # WB zwykły robi osoba bez Płac; płacowy czeka na Płace (konto do przypisania).
        posted = await client.post(
            f"{ACC}/bank/statements/{data['id']}/post", headers=_headers(world["module_only"])
        )
        assert posted.status_code == 200 and posted.json()["created"] == 1
        blocked = await client.post(
            f"{ACC}/bank/statements/{data['id']}/post", headers=_headers(world["accountant"])
        )
        assert blocked.status_code == 422
        # Ta sama wypłata w drugim wyciągu (dzienny i miesięczny) = duplikat, który
        # dziedziczy D2: osoba bez Płac nie widzi nazwiska ani kwoty.
        monthly = _statement(
            year,
            ("D", "8000,00", "Wynagrodzenie 02", TEAM_ACCOUNT, f"P{marker}"),
            ("D", "5,00", "Opłata za przelew", "", f"G{marker}"),
        )
        second = await _bank_import(client, world, monthly, user="module_only")
        assert second.status_code == 201, second.text
        assert [line["kind"] for line in second.json()["lines"]] == ["fee"]
        assert second.json()["payroll_hidden"] is True
        assert second.json()["debit_total"] == 500
        full = await client.get(
            f"{ACC}/bank/statements/{second.json()['id']}",
            headers=_headers(world["accountant"]),
        )
        assert [(line["kind"], line["payroll"]) for line in full.json()["lines"]] == [
            ("duplicate", True),
            ("fee", False),
        ]
    finally:
        async with AsyncSessionLocal() as db:
            if created:
                await db.execute(
                    delete(EmployeeBillingDetails).where(
                        EmployeeBillingDetails.user_id == person.id
                    )
                )
            else:
                await db.execute(
                    update(EmployeeBillingDetails)
                    .where(EmployeeBillingDetails.user_id == person.id)
                    .values(account_encrypted=previous[0], account_last4=previous[1])
                )
            await db.commit()


async def test_bank_needs_module_and_a_known_company_account(client, world, books):
    year = books["year"]
    await _set_ledger(_ledger_settings(world, books, allocation=False))
    closed = await client.get(f"{ACC}/bank", headers=_headers(world["module_only"]))
    assert closed.status_code == 404
    settings = _bank_settings(world, books)
    settings["bank"]["accounts"] = []
    await _set_ledger(settings)
    unknown = await _bank_import(
        client, world, _statement(year, ("D", "1,00", "x", "", "X1"))
    )
    assert unknown.status_code == 422 and "nie ma na liście" in unknown.json()["detail"]
    admin = _headers(world["admin"])
    bad_number = await client.put(
        f"{ACC}/config/bank",
        json={"accounts": [{"number": "123", "account": books["acc"]["bank"]}]},
        headers=admin,
    )
    assert bad_number.status_code == 422
    typo = f"{COMPANY[:-1]}{(int(COMPANY[-1]) + 1) % 10}"
    bad_checksum = await client.put(
        f"{ACC}/config/bank",
        json={"accounts": [{"number": typo, "account": books["acc"]["bank"]}]},
        headers=admin,
    )
    assert bad_checksum.status_code == 422
    assert "sumę kontrolną" in bad_checksum.json()["detail"]
    not_in_plan = await client.put(
        f"{ACC}/config/bank",
        json={"accounts": [{"number": COMPANY, "account": "999-99"}]},
        headers=admin,
    )
    assert not_in_plan.status_code == 422
    ok = await client.put(
        f"{ACC}/config/bank",
        json={"accounts": [{"number": f"PL{COMPANY}", "account": books["acc"]["bank"], "name": "Główny"}]},
        headers=admin,
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["accounts"][0]["number"] == COMPANY
    refused = await client.put(
        f"{ACC}/config/bank", json={"accounts": []}, headers=_headers(world["accountant"])
    )
    assert refused.status_code == 403


# ── K4a: przegląd 14.11.2026 (D2 jak w E3, jeden rachunek/miesiąc/PLN, nazwa) ──

STRANGER_ACCOUNT = _valid_nrb("109010140000071219800022")
OTHER_ACCOUNT_EUR = _valid_nrb("109010140000071219800011")
TEAM_ACCOUNT_2 = _valid_nrb("109010140000071219800033")


def _mt940_blocks(year: int, *blocks) -> bytes:
    """Plik MT940 z kilkoma wyciągami: (rachunek, waluta, [(MMDD, D/C, kwota, tytuł, rachunek, ref)])."""

    yy = f"{year % 100:02d}"
    out = ""
    for account, currency, ops in blocks:
        out += f":20:R{uuid.uuid4().hex[:6]}\r\n:25:/PL{account}\r\n:60F:C{yy}0301{currency}100000,00\r\n"
        for mmdd, sign, amount, title, party, ref in ops:
            out += f":61:{yy}{mmdd}{mmdd}{sign}{amount}NTRFNONREF//{ref}\r\n"
            out += f":86:~00TR~20{title}~32Kontrahent Testowy" + (f"~38PL{party}" if party else "") + "\r\n"
        out += f":62F:C{yy}0430{currency}0,00\r\n-\r\n"
    return out.encode()


async def _swap_team_account(person_id: int, account: str):
    from app.core.encryption import get_token_cipher

    async with AsyncSessionLocal() as db:
        details = await db.scalar(
            select(EmployeeBillingDetails).where(EmployeeBillingDetails.user_id == person_id)
        )
        encrypted = get_token_cipher().encrypt(account)
        if details is None:
            db.add(
                EmployeeBillingDetails(
                    user_id=person_id,
                    account_encrypted=encrypted,
                    account_last4=account[-4:],
                    account_source="manual",
                    payment_terms_days=14,
                )
            )
            previous = None
        else:
            previous = (details.account_encrypted, details.account_last4)
            details.account_encrypted, details.account_last4 = encrypted, account[-4:]
        await db.commit()
    return previous


async def _restore_team_account(person_id: int, previous) -> None:
    async with AsyncSessionLocal() as db:
        if previous is None:
            await db.execute(
                delete(EmployeeBillingDetails).where(EmployeeBillingDetails.user_id == person_id)
            )
        else:
            await db.execute(
                update(EmployeeBillingDetails)
                .where(EmployeeBillingDetails.user_id == person_id)
                .values(account_encrypted=previous[0], account_last4=previous[1])
            )
        await db.commit()


async def test_bank_refuses_files_that_do_not_fit_one_wb(client, world, books):
    year = books["year"]
    await _set_ledger(_bank_settings(world, books))
    marker = uuid.uuid4().hex[:6].upper()
    # Dwa rachunki w jednym pliku: wszystko poszłoby na jedno konto 130-x.
    two_accounts = _mt940_blocks(
        year,
        (OTHER_ACCOUNT_EUR, "EUR", [("0320", "D", "1000,00", "Faktura w EUR", STRANGER_ACCOUNT, f"E{marker}")]),
        (COMPANY, "PLN", [("0320", "D", "12,50", "Opłata za przelew", "", f"F{marker}")]),
    )
    refused = await _bank_import(client, world, two_accounts)
    assert refused.status_code == 422 and "kilku rachunków" in refused.json()["detail"]
    # Ten sam rachunek, ale operacje w EUR — WB jest w PLN (waluty: K4c).
    euro = _mt940_blocks(
        year,
        (COMPANY, "PLN", [("0320", "D", "12,50", "Opłata za przelew", "", f"G{marker}")]),
        (COMPANY, "EUR", [("0321", "D", "100,00", "Faktura w EUR", STRANGER_ACCOUNT, f"H{marker}")]),
    )
    refused = await _bank_import(client, world, euro)
    assert refused.status_code == 422 and "PLN" in refused.json()["detail"]
    # Operacje z dwóch miesięcy — WB ma jeden okres.
    two_months = _mt940_blocks(
        year,
        (
            COMPANY,
            "PLN",
            [
                ("0331", "D", "12,50", "Opłata za prowadzenie rachunku", "", f"M{marker}"),
                ("0402", "D", "7,00", "Opłata za przelew", "", f"A{marker}"),
            ],
        ),
    )
    refused = await _bank_import(client, world, two_months)
    assert refused.status_code == 422 and "miesięcy" in refused.json()["detail"]
    # Pozycja 0,00 (np. kapitalizacja bez odsetek) nie wywraca importu.
    zero = _statement(
        year,
        ("D", "12,50", "Opłata za przelew", "", f"F{marker}"),
        ("C", "0,00", "Kapitalizacja odsetek", "", f"O{marker}"),
    )
    accepted = await _bank_import(client, world, zero)
    assert accepted.status_code == 201, accepted.text
    assert [line["kind"] for line in accepted.json()["lines"]] == ["fee"]


async def test_bank_team_payouts_are_recognized_like_e3(client, world, books):
    """D2: wypłata po numerze KSeF (bez rachunku), wiersz R9 „unmatched” i zwrot wypłaty."""

    year = books["year"]
    await _set_ledger(_bank_settings(world, books))
    person = world["person"]
    nip = world["nips"]["person"]
    ksef = f"{nip}-{year}0228-{uuid.uuid4().hex[:12].upper()}-AB"
    async with AsyncSessionLocal() as db:
        period = PayrollPeriod(
            year=year, month=2, status="closed", closed_at=datetime.now(timezone.utc), close_count=1
        )
        db.add(period)
        await db.flush()
        settlement = PayrollSettlement(
            period_id=period.id,
            user_id=person.id,
            employment_type="b2b",
            currency="PLN",
            expected_amount=Decimal("8000.00"),
            amount_basis="net",
            status="approved",
        )
        db.add(settlement)
        await db.flush()
        invoice = PayrollInvoice(
            source="ksef",
            ksef_number=ksef,
            ksef_acquired_at=datetime(year, 3, 1, 9, 0, tzinfo=timezone.utc),
            seller_nip=nip,
            user_id=person.id,
            invoice_number="FV/77/02",
            invoice_kind="original",
            issue_date=date(year, 2, 28),
            currency="PLN",
            net_amount=Decimal("6504.07"),
            vat_amount=Decimal("1495.93"),
            gross_amount=Decimal("8000.00"),
            items=[],
            xml_sha256=hashlib.sha256(ksef.encode()).hexdigest(),
            settlement_id=settlement.id,
            match_status="matched",
        )
        db.add(invoice)
        await db.commit()
        period_id, settlement_id, invoice_id = period.id, settlement.id, invoice.id
    previous = await _swap_team_account(person.id, TEAM_ACCOUNT_2)
    outside = _headers(world["module_only"])
    try:
        marker = uuid.uuid4().hex[:6].upper()
        # Osoba bez Płac: wypłata z numerem KSeF na rachunek spoza danych do
        # rozliczeń i zwrot wypłaty z rachunku osoby z zespołu.
        first = _mt940_blocks(
            year,
            (
                COMPANY,
                "PLN",
                [
                    ("0310", "D", "8000,00", f"FV/77/02 {ksef}", STRANGER_ACCOUNT, f"K{marker}"),
                    ("0311", "C", "5432,10", "Zwrot przelewu Wynagrodzenie 02", TEAM_ACCOUNT_2, f"R{marker}"),
                    ("0312", "D", "12,50", "Opłata za przelew", "", f"F{marker}"),
                ],
            ),
        )
        imported = await _bank_import(client, world, first, user="module_only")
        assert imported.status_code == 201, imported.text
        data = imported.json()
        assert [line["kind"] for line in data["lines"]] == ["fee"]
        assert data["payroll_hidden"] is True and data["credit_total"] == 0
        full = await client.get(
            f"{ACC}/bank/statements/{data['id']}", headers=_headers(world["accountant"])
        )
        assert [(line["kind"], line["payroll"]) for line in full.json()["lines"]] == [
            ("team", True),
            ("team", True),
            ("fee", False),
        ]
        # Płace wgrywają ten sam numer faktury z inną kwotą: R9 zapisuje „unmatched”,
        # a osoba bez Płac dalej tego nie widzi.
        second = _mt940_blocks(
            year,
            (COMPANY, "PLN", [("0315", "D", "7999,00", f"FV/77/02 {ksef}", STRANGER_ACCOUNT, f"L{marker}")]),
        )
        inside = await _bank_import(client, world, second, user="accountant")
        assert inside.status_code == 201, inside.text
        seen = await client.get(f"{ACC}/bank/statements/{inside.json()['id']}", headers=outside)
        assert seen.json()["lines"] == [] and seen.json()["payroll_hidden"] is True
    finally:
        await _restore_team_account(person.id, previous)
        async with AsyncSessionLocal() as db:
            await db.execute(delete(PayrollPayment).where(PayrollPayment.settlement_id == settlement_id))
            await db.execute(delete(PayrollInvoice).where(PayrollInvoice.id == invoice_id))
            await db.execute(delete(PayrollSettlement).where(PayrollSettlement.id == settlement_id))
            await db.execute(delete(PayrollPeriod).where(PayrollPeriod.id == period_id))
            await db.commit()


async def test_bank_rename_keeps_approved_wb_and_payroll_post(client, world, books):
    year, acc = books["year"], books["acc"]
    settings = _bank_settings(world, books)
    await _set_ledger(settings)
    person = world["person"]
    previous = await _swap_team_account(person.id, TEAM_ACCOUNT_2)
    try:
        marker = uuid.uuid4().hex[:6].upper()
        content = _statement(
            year,
            ("D", "8000,00", "Wynagrodzenie 02", TEAM_ACCOUNT_2, f"P{marker}"),
            ("D", "12,50", "Opłata za przelew", "", f"F{marker}"),
        )
        data = (await _bank_import(client, world, content, user="module_only")).json()
        posted = await client.post(
            f"{ACC}/bank/statements/{data['id']}/post", headers=_headers(world["module_only"])
        )
        approved = await client.post(
            f"{ACC}/documents/approve",
            json={"ids": [posted.json()["documents"][0]["id"]]},
            headers=_headers(world["accountant"]),
        )
        assert approved.json()["approved"], approved.text
        renamed = await client.put(
            f"{ACC}/config/bank",
            json={
                **settings["bank"],
                "accounts": [{"number": COMPANY, "account": acc["bank"], "name": "Rachunek bieżący"}],
            },
            headers=_headers(world["admin"]),
        )
        assert renamed.status_code == 200, renamed.text
        full = await client.get(
            f"{ACC}/bank/statements/{data['id']}", headers=_headers(world["accountant"])
        )
        team = next(line for line in full.json()["lines"] if line["kind"] == "team")
        assigned = await client.patch(
            f"{ACC}/bank/lines/{team['id']}",
            json={"account": acc["payroll_settle"]},
            headers=_headers(world["accountant"]),
        )
        assert assigned.status_code == 200, assigned.text
        payroll = await client.post(
            f"{ACC}/bank/statements/{data['id']}/post", headers=_headers(world["accountant"])
        )
        assert payroll.status_code == 200, payroll.text
        assert (payroll.json()["unchanged"], payroll.json()["created"]) == (1, 1)
    finally:
        await _restore_team_account(person.id, previous)


async def test_bank_import_fails_closed_when_team_accounts_unreadable(
    client, world, books, monkeypatch
):
    from app.services.ledger import bank as ledger_bank

    year = books["year"]
    await _set_ledger(_bank_settings(world, books))

    async def unreadable(db):
        return {}, True

    monkeypatch.setattr(ledger_bank.hr_statements, "account_owners", unreadable)
    marker = uuid.uuid4().hex[:6].upper()
    content = _statement(year, ("D", "12,50", "Opłata za przelew", "", f"F{marker}"))
    refused = await _bank_import(client, world, content, user="module_only")
    assert refused.status_code == 503 and "Płacami" in refused.json()["detail"]
    async with AsyncSessionLocal() as db:
        stored = await db.scalar(
            select(func.count())
            .select_from(LedgerBankStatement)
            .where(LedgerBankStatement.sha256 == hashlib.sha256(content).hexdigest())
        )
    assert stored == 0

