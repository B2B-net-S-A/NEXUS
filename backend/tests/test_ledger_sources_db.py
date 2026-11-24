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

import pytest
import pytest_asyncio
from fastapi import FastAPI
from openpyxl import load_workbook
from httpx import ASGITransport, AsyncClient
from sqlalchemy import case, delete, func, select, update

from app.api import ledger as ledger_api
from app.api import ledger_settlements as ledger_settlements_api
from app.api import ledger_vat as ledger_vat_api
from app.core.database import AsyncSessionLocal
from app.models.app_setting import AppSetting
from app.models.client_sales_invoice import (
    ClientSalesInvoice,
    ClientSalesInvoicePayment,
)
from app.models.finance_archive import FinanceArchiveDocument
from app.models.finance_ledger import FinanceCostEntry, FinanceCounterparty
from app.models.finance_payments import FinanceCostPayment, FinanceCostPaymentRecord
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
    LedgerBankLine,
    LedgerBankStatement,
    LedgerDocument,
    LedgerSettlement,
    LedgerLine,
    LedgerPrepayment,
    LedgerRecurring,
    LedgerYear,
)
from app.services.finance_ledger import costs as cost_queue
from app.services.finance_ledger import payments as cost_payments
from app.services.finance_ledger.posting import rate_day
from app.services.ledger import settings as ledger_settings
from app.services.ledger import revenue, sources
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
    app.include_router(ledger_settlements_api.router, prefix=ACC)
    app.include_router(ledger_vat_api.router, prefix=ACC)
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
    # Do 2090: JPK_V7M(3) przyjmuje rok najwyżej 2090 (etd:TRok).
    year = random.randint(2050, 2090)
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
            year = random.randint(2050, 2090)
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
            "vat_import": (f"{prefix}-226", "VAT należny import usług", "vat", None),
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
            "vat_due": (f"{prefix}-224", "VAT do zapłaty", "other", None),
            "other_income": (f"{prefix}-760", "Pozostałe przychody operacyjne", "other", None),
            "other_cost": (f"{prefix}-761", "Pozostałe koszty operacyjne", "other", None),
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
    # Kontrahenci założeni w teście (K5b-2: dostawcy z formularza zakupu).
    extra_parties: list[int] = []
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
        "extra_parties": extra_parties,
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
                FinanceCounterparty.id.in_(
                    [supplier.id, buyer.id, person.id, *extra_parties]
                )
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


async def test_sales_without_revenue_account_wait_for_buyer_history(
    client, world, books
):
    """Puste konto przychodów = jak w Symfonii; nabywca bez historii w archiwum
    eBI24 i w księdze czeka w „Do sprawdzenia”, bez konta zapasowego."""

    await _set_ledger(
        {
            "modules": {"ledger": True},
            "accountants": [world["accountant"].id],
            "sales": {"receivable_account": books["acc"]["receivable"]},
        }
    )
    summary = await _summary(client, world, books)
    reasons = {item["problems"][0] for item in summary["sales"]["problems"]}
    assert revenue.NO_HISTORY in reasons
    assert summary["sales"]["to_post"] == 0


async def test_accountant_chooses_revenue_account_for_buyer_without_history(
    client, world, books
):
    """Nabywca bez historii: księgowa wskazuje konto na problemie w „Źródłach”,
    a następne „Zaksięguj miesiąc” robi FVS na to konto (decyzja 18.11.2026)."""

    acc, buyer = books["acc"], books["buyer"]
    await _set_ledger(
        {
            "modules": {"ledger": True},
            "accountants": [world["accountant"].id],
            "sales": {
                "receivable_account": acc["receivable"],
                "vat_account": acc["vat_out"],
            },
        }
    )
    summary = await _summary(client, world, books)
    waiting = [
        item
        for item in summary["sales"]["problems"]
        if item["problems"][0] == revenue.NO_HISTORY
    ]
    assert waiting
    assert waiting[0]["revenue_buyer"] == {
        "counterparty_id": buyer.id,
        "name": "Klient Testowy",
        "account": None,
    }
    url = f"{ACC}/sources/revenue-accounts/{buyer.id}"
    denied = await client.put(
        url, json={"account": acc["other_income"]}, headers=_headers(world["module_only"])
    )
    assert denied.status_code == 403
    for wrong in (acc["receivable"], "999-999"):
        refused = await client.put(
            url, json={"account": wrong}, headers=_headers(world["accountant"])
        )
        assert refused.status_code == 422, refused.text
    missing = await client.put(
        f"{ACC}/sources/revenue-accounts/{2**31 - 1}",
        json={"account": acc["other_income"]},
        headers=_headers(world["accountant"]),
    )
    assert missing.status_code == 404
    chosen = await client.put(
        url, json={"account": acc["other_income"]}, headers=_headers(world["accountant"])
    )
    assert chosen.status_code == 200, chosen.text
    listed = await client.get(
        f"{ACC}/sources/revenue-accounts", headers=_headers(world["module_only"])
    )
    assert [
        (item["counterparty_id"], item["account"], item["problem"], bool(item["by"]))
        for item in listed.json()["items"]
    ] == [(buyer.id, acc["other_income"], None, True)]

    synced = await _sync(client, world, books, "sales")
    assert synced.status_code == 200, synced.text
    doc = await _document("client_sales_invoice", books["sales"]["plain"])
    assert doc.meta["revenue_from"] == revenue.CHOSEN
    assert (await _lines(doc.id))[1][1] == acc["other_income"]
    after = await _summary(client, world, books)
    assert not [
        item
        for item in after["sales"]["problems"]
        if (item.get("revenue_buyer") or {}).get("counterparty_id") == buyer.id
    ]

    removed = await client.put(
        url, json={"account": ""}, headers=_headers(world["accountant"])
    )
    assert removed.status_code == 200 and removed.json()["account"] is None
    listed = await client.get(
        f"{ACC}/sources/revenue-accounts", headers=_headers(world["admin"])
    )
    assert listed.json()["items"] == []


def _archive_sale(*, ksef: str | None, nip: str, day: date, account: str):
    """Faktura sprzedaży z archiwum eBI24 z dekretem, który poszedł do Symfonii."""

    key = uuid.uuid4().hex
    return FinanceArchiveDocument(
        source="ebi24",
        source_id=f"test-{key[:24]}",
        schema_name="INCOME_INVOICE",
        kind="sale",
        ksef_number=ksef,
        issue_date=day,
        file_type="ebi",
        file_path=f"test/{key}.json",
        file_sha256=hashlib.sha256(key.encode()).hexdigest(),
        meta={
            "_partner": {"officialId": f"PL{nip}", "officialIdType": "NIP"},
            "externalData": {
                "symfonia": {
                    "registryCode": "Sprzedaż",
                    "accountNumberNet": account,
                    "accountNumberTax": "222",
                }
            },
        },
    )


async def test_sales_revenue_follows_symfonia_decrees_from_ebi24_archive(
    client, world, books
):
    acc, ids, year = books["acc"], books["sales"], books["year"]
    nip = world["nips"]["client"]
    await _set_ledger(
        {
            "modules": {"ledger": True},
            "accountants": [world["accountant"].id],
            "sales": {
                "receivable_account": acc["receivable"],
                "revenue_account": "",
                "vat_account": acc["vat_out"],
            },
        }
    )
    async with AsyncSessionLocal() as db:
        plain = await db.get(ClientSalesInvoice, ids["plain"])
        await db.execute(
            update(ClientSalesInvoice)
            .where(ClientSalesInvoice.id == ids["correction"])
            .values(corrected_ksef_number=plain.ksef_number)
        )
        archived = [
            # Dekret tej faktury w Symfonii — wygrywa z historią nabywcy.
            _archive_sale(
                ksef=plain.ksef_number,
                nip=nip,
                day=plain.issue_date,
                account=acc["revenue"],
            ),
            # Wcześniejsza faktura nabywcy spoza NEXUSA (bez numeru KSeF).
            _archive_sale(
                ksef=None, nip=nip, day=date(year, 3, 1), account=acc["other_income"]
            ),
        ]
        db.add_all(archived)
        await db.commit()
        archive_ids = [item.id for item in archived]
    try:
        synced = await _sync(client, world, books, "sales")
        assert synced.status_code == 200, synced.text
        plain_doc = await _document("client_sales_invoice", ids["plain"])
        euro_doc = await _document("client_sales_invoice", ids["euro"])
        correction_doc = await _document("client_sales_invoice", ids["correction"])
        assert (plain_doc.meta["revenue_from"], (await _lines(plain_doc.id))[1][1]) == (
            revenue.EBI24,
            acc["revenue"],
        )
        # Faktura spoza archiwum: konto poprzedniej faktury nabywcy.
        assert euro_doc.meta["revenue_from"] == revenue.PREVIOUS
        assert (await _lines(euro_doc.id))[1][1] == acc["other_income"]
        # Korekta: konto faktury korygowanej z archiwum, nie poprzedniej.
        assert correction_doc.meta["revenue_from"] == revenue.ORIGINAL
        assert (await _lines(correction_doc.id))[1][:2] == ("debit", acc["revenue"])
        again = await _sync(client, world, books, "sales")
        assert again.json()["created"] == 0, again.text
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(
                delete(FinanceArchiveDocument).where(
                    FinanceArchiveDocument.id.in_(archive_ids)
                )
            )
            await db.commit()


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
    # Rozrachunki z odbiorcami idą na konto-ID kontrahenta: konto bez słownika
    # kontrahentów odpada przy zapisie, nie dopiero przy dekrecie FVS.
    no_dictionary = await client.put(
        f"{ACC}/config/sales",
        json={**body, "receivable_account": acc["revenue"]},
        headers=_headers(world["admin"]),
    )
    assert no_dictionary.status_code == 422
    assert "nie prowadzi słownika kontrahentów" in no_dictionary.json()["detail"]
    saved = await client.put(
        f"{ACC}/config/sales", json=body, headers=_headers(world["admin"])
    )
    assert saved.status_code == 200, saved.text
    config = await client.get(f"{ACC}/config", headers=_headers(world["accountant"]))
    assert config.json()["sales_accounts"] == body
    problems = config.json()["account_problems"]
    assert not [item for item in problems if item["group"] == "sales"]
    assert config.json()["accountants"] is None
    # Puste konto przychodów = konto jak w Symfonii; reszta pól dalej wymagana.
    symfonia = await client.put(
        f"{ACC}/config/sales",
        json={**body, "revenue_account": ""},
        headers=_headers(world["admin"]),
    )
    assert symfonia.status_code == 200, symfonia.text
    assert symfonia.json()["sales"]["revenue_account"] == ""
    no_vat = await client.put(
        f"{ACC}/config/sales",
        json={**body, "vat_account": ""},
        headers=_headers(world["admin"]),
    )
    assert no_vat.status_code == 422


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


async def test_symfonia_template_4_takes_invoices_and_refuses_what_has_no_sample(
    client, world, books
):
    ids = books["sales"]
    synced = await _sync(client, world, books, "sales")
    assert synced.status_code == 200, synced.text
    year, partner = books["year"], books["partner"]["c"]
    plain = await _document("client_sales_invoice", ids["plain"])
    await _approve_ids(client, world, [plain.id])
    created = await _export(
        client, world, books, ["sales"], file_format="symfonia_fk_txt4"
    )
    assert created.status_code == 201, created.text
    package = created.json()
    assert package["file_name"].endswith(".txt") and package["document_count"] == 1
    file = await client.get(
        f"{ACC}/exports/{package['id']}/file", headers=_headers(world["accountant"])
    )
    assert file.status_code == 200
    assert file.headers["content-type"].startswith("text/plain")
    assert hashlib.sha256(file.content).hexdigest() == package["file_sha256"]
    text = file.content.decode("cp1250")
    assert text.startswith("INFO{\r\n") and text.endswith("}\r\n")
    for expected in (
        "\tkod =FS 1/03\r\n",
        "\tsymbol FK =FVS\r\n",
        f"\tkhnip ={world['nips']['client']}\r\n",
        f"\t\tfk_ident ={partner}\r\n",
        f"\t\tokres ={year}-03-31\r\n",
        f"\t\tkonto ={books['acc']['receivable']}-{partner}\r\n",
    ):
        assert expected in text, expected
    # Korekta (FKS) i faktura w EUR nie mają próbki — paczka nie powstaje.
    others = [
        (await _document("client_sales_invoice", ids[key])).id
        for key in ("euro", "correction")
    ]
    await _approve_ids(client, world, others)
    refused = await _export(
        client, world, books, ["sales"], file_format="symfonia_fk_txt4"
    )
    assert refused.status_code == 422, refused.text
    assert "FS 2/03" in refused.text and "FK 1/03" in refused.text
    after = await _exports(client, world, books)
    assert [item["number"] for item in after["exports"]] == [package["number"]]


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
    balance = Decimal("100000.00")
    for direction, amount, title, account, ref in operations:
        body += f":61:{yy}03{day}03{day}{direction}{amount}NTRFNONREF//{ref}\r\n"
        body += f":86:020~00TR~20{title}~32Kontrahent Testowy"
        body += (f"~38PL{account}" if account else "") + "\r\n"
        balance += _signed(direction, amount)
    return (body + f":62F:{_mt940_balance(yy, '03' + day, 'PLN', balance)}\r\n-").encode()


def _signed(direction: str, amount: str) -> Decimal:
    """Kwota operacji MT940 ze znakiem (``D``/``RC`` obciąża rachunek)."""

    value = Decimal(amount.replace(",", "."))
    return -value if direction in ("D", "RC") else value


def _mt940_balance(yy: str, mmdd: str, currency: str, balance: Decimal) -> str:
    """Saldo końcowe zgodne z operacjami — Księga odrzuca plik z innym saldem."""

    mark = "D" if balance < 0 else "C"
    return f"{mark}{yy}{mmdd}{currency}{abs(balance):.2f}".replace(".", ",")


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


async def test_bank_statement_keeps_its_balances_and_whether_e8_saw_the_credits(
    client, world, books
):
    """Saldo otwarcia i zamknięcia z datami (ciągłość dla „po terminie”, 0742):
    zapisane przy imporcie, a plik sprzed migracji dostaje je przy ponownym
    wgraniu — bez drugiego importu operacji. ``credits_matched`` mówi, czy
    uznania przeszły przez E8 (moduł faktur do klientów wyłączony = nie)."""

    from tests.client_invoicing.helpers import set_module

    year = books["year"]
    await _set_ledger(_bank_settings(world, books))
    marker = uuid.uuid4().hex[:6].upper()
    content = _statement(
        year,
        ("C", "250,00", "Wpłata bez faktury", OTHER_ACCOUNT, f"C{marker}"),
        ("D", "12,50", "Opłata za prowadzenie rachunku", "", f"F{marker}"),
    )
    off = _statement(
        year, ("C", "10,00", "Odsetki", "", f"O{marker}"), day="21"
    )
    await set_module(True)
    try:
        imported = await _bank_import(client, world, content)
        await set_module(False)
        unchecked = await _bank_import(client, world, off)
    finally:
        await set_module(None)
    assert imported.status_code == 201, imported.text
    assert unchecked.status_code == 201, unchecked.text
    async with AsyncSessionLocal() as db:
        statement = await db.get(LedgerBankStatement, imported.json()["id"])
        other = await db.get(LedgerBankStatement, unchecked.json()["id"])
    assert (
        statement.opening_balance,
        statement.opening_day,
        statement.closing_balance,
        statement.closing_day,
    ) == (10_000_000, date(year, 3, 1), 10_023_750, date(year, 3, 20))
    assert (statement.credits_matched, other.credits_matched) == (True, False)

    async with AsyncSessionLocal() as db:
        await db.execute(
            update(LedgerBankStatement)
            .where(LedgerBankStatement.id == statement.id)
            .values(
                opening_balance=None,
                opening_day=None,
                closing_balance=None,
                closing_day=None,
            )
        )
        await db.commit()
    again = await _bank_import(client, world, content)
    assert again.status_code == 201, again.text
    assert again.json()["already_imported"] is True
    assert len(again.json()["lines"]) == 2
    async with AsyncSessionLocal() as db:
        refreshed = await db.get(LedgerBankStatement, statement.id)
    assert (refreshed.opening_balance, refreshed.closing_day) == (
        10_000_000,
        date(year, 3, 20),
    )


async def test_admin_deletes_statement_with_its_e3_e8_matches(client, world, books):
    """Cofnięcie importu wyciągu (17.11.2026: E8 wziął nogi VAT MPP za wpłaty
    klientów): znika wyciąg, jego linie i zapłaty E3/E8 z tego pliku, stan
    zapłaty faktury kosztowej liczy się od nowa; z WB — odmowa."""

    year, acc = books["year"], books["acc"]
    await _set_ledger(_bank_settings(world, books))
    marker = uuid.uuid4().hex[:6].upper()
    content = _statement(
        year,
        ("D", "300,00", "Faktura spoza NEXUSA", OTHER_ACCOUNT, f"U{marker}"),
        ("C", "250,00", "Wpłata bez faktury", OTHER_ACCOUNT, f"C{marker}"),
    )
    imported = await _bank_import(client, world, content)
    assert imported.status_code == 201, imported.text
    data = imported.json()
    sha = hashlib.sha256(content).hexdigest()
    entry_id = books["expense"]
    async with AsyncSessionLocal() as db:
        # Zapłaty z tego pliku tak, jak zapisują je E3 i E8 przy imporcie.
        db.add(
            FinanceCostPaymentRecord(
                kind="statement_line",
                entry_id=entry_id,
                match_status="matched",
                amount=Decimal("300.00"),
                currency="PLN",
                booked_on=date(year, 3, 20),
                statement_sha256=sha,
                statement_format="mt940",
                statement_line_ref=f"1:U{marker}",
            )
        )
        db.add(
            ClientSalesInvoicePayment(
                kind="statement_line",
                match_status="unmatched",
                amount=Decimal("250.00"),
                currency="PLN",
                booked_on=date(year, 3, 20),
                statement_sha256=sha,
                statement_format="mt940",
                statement_line_ref=f"2:C{marker}",
            )
        )
        await db.flush()
        await cost_payments.refresh(db, [entry_id], actor_id=None)
        await db.commit()
    async with AsyncSessionLocal() as db:
        paid = await db.get(FinanceCostPayment, entry_id)
        assert paid is not None and paid.paid_amount > 0

    url = f"{ACC}/bank/statements/{data['id']}"
    refused = await client.delete(url, headers=_headers(world["accountant"]))
    assert refused.status_code == 403
    deleted = await client.delete(url, headers=_headers(world["admin"]))
    assert deleted.status_code == 200, deleted.text
    assert deleted.json() == {
        "lines": 2,
        "cost_records": 1,
        "cost_matched": 1,
        "sales_records": 1,
        "sales_matched": 0,
    }
    async with AsyncSessionLocal() as db:
        assert await db.get(LedgerBankStatement, data["id"]) is None
        left = await db.scalar(
            select(func.count())
            .select_from(LedgerBankLine)
            .where(LedgerBankLine.statement_id == data["id"])
        )
        assert left == 0
        for model in (FinanceCostPaymentRecord, ClientSalesInvoicePayment):
            count = await db.scalar(
                select(func.count())
                .select_from(model)
                .where(model.statement_sha256 == sha)
            )
            assert count == 0
        paid = await db.get(FinanceCostPayment, entry_id)
        assert (paid.state, paid.paid_amount, paid.paid_on) == (
            "unpaid",
            Decimal("0.00"),
            None,
        )
    gone = await client.delete(url, headers=_headers(world["admin"]))
    assert gone.status_code == 404
    # Ten sam plik wchodzi od nowa (nowy wyciąg, bez „already_imported”).
    again = await _bank_import(client, world, content)
    assert again.status_code == 201 and again.json()["already_imported"] is False
    # Wyciąg z WB w buforze — najpierw dokument, potem wyciąg.
    headers = _headers(world["accountant"])
    for line in again.json()["lines"]:
        assigned = await client.patch(
            f"{ACC}/bank/lines/{line['id']}", json={"account": acc["cost"]}, headers=headers
        )
        assert assigned.status_code == 200, assigned.text
    posted = await client.post(
        f"{ACC}/bank/statements/{again.json()['id']}/post", headers=headers
    )
    assert posted.status_code == 200, posted.text
    blocked = await client.delete(
        f"{ACC}/bank/statements/{again.json()['id']}", headers=_headers(world["admin"])
    )
    assert blocked.status_code == 409 and "WB" in blocked.json()["detail"]


async def test_delete_statement_refuses_when_another_file_holds_its_duplicates(
    client, world, books
):
    """Ta sama operacja w wyciągu dziennym D i miesięcznym M: E3/E8 zapisują
    zapłatę pod D, a pod M duplikat (``ignored``). Usunięcie D zostawiłoby
    fakturę bez zapłaty (koszt wraca na „Do zapłaty” — ryzyko drugiego
    przelewu), więc odmowa 409; najpierw M, potem D (decyzja Artura 24.11.2026)."""

    from app.services.finance_ledger.payments import DUPLICATE_REASON

    year = books["year"]
    await _set_ledger(_bank_settings(world, books))
    marker = uuid.uuid4().hex[:6].upper()
    cost_op = ("D", "300,00", "Faktura FV 7/03", OTHER_ACCOUNT, f"U{marker}")
    client_op = ("C", "250,00", "Wpłata za fakturę", OTHER_ACCOUNT, f"C{marker}")
    daily = _statement(year, cost_op, client_op)
    monthly = _statement(year, cost_op, client_op, ("D", "12,50", "Opłata", "", f"F{marker}"))
    first = await _bank_import(client, world, daily)
    assert first.status_code == 201, first.text
    second = await _bank_import(client, world, monthly)
    assert second.status_code == 201, second.text
    assert [line["kind"] for line in second.json()["lines"]][:2] == ["duplicate", "duplicate"]
    entry_id = books["expense"]
    shas = {"D": hashlib.sha256(daily).hexdigest(), "M": hashlib.sha256(monthly).hexdigest()}
    async with AsyncSessionLocal() as db:
        # Import zapisał oba pliki w E3: pod M duplikat, pod D operację, która
        # tu opłaca fakturę kosztową (dopasowanie jak po decyzji Finansów).
        rows = {
            row.statement_sha256: row
            for row in await db.scalars(
                select(FinanceCostPaymentRecord).where(
                    FinanceCostPaymentRecord.statement_sha256.in_(list(shas.values())),
                    FinanceCostPaymentRecord.statement_line_ref.like(f"%U{marker}"),
                )
            )
        }
        assert (rows[shas["M"]].match_status, rows[shas["M"]].reason) == (
            "ignored",
            DUPLICATE_REASON,
        )
        rows[shas["D"]].match_status = "matched"
        rows[shas["D"]].entry_id = entry_id
        # E8 (rachunek bez faktur do klientów) — wiersze tak, jak zapisuje je import.
        for key, status, reason in (("D", "unmatched", None), ("M", "ignored", DUPLICATE_REASON)):
            db.add(
                ClientSalesInvoicePayment(
                    kind="statement_line",
                    match_status=status,
                    reason=reason,
                    amount=Decimal("250.00"),
                    currency="PLN",
                    booked_on=date(year, 3, 20),
                    statement_sha256=shas[key],
                    statement_format="mt940",
                    statement_line_ref=f"2:C{marker}",
                )
            )
        await db.flush()
        await cost_payments.refresh(db, [entry_id], actor_id=None)
        await db.commit()

    admin = _headers(world["admin"])
    refused = await client.delete(f"{ACC}/bank/statements/{first.json()['id']}", headers=admin)
    assert refused.status_code == 409, refused.text
    assert "duplikat" in refused.json()["detail"] and "Najpierw usuń" in refused.json()["detail"]
    async with AsyncSessionLocal() as db:
        assert await db.get(LedgerBankStatement, first.json()["id"]) is not None
        paid = await db.get(FinanceCostPayment, entry_id)
        assert paid.state != "unpaid" and paid.paid_amount > 0
    # Najpierw M (same duplikaty i opłata), potem D.
    removed = await client.delete(f"{ACC}/bank/statements/{second.json()['id']}", headers=admin)
    assert removed.status_code == 200, removed.text
    removed = await client.delete(f"{ACC}/bank/statements/{first.json()['id']}", headers=admin)
    assert removed.status_code == 200, removed.text


async def test_delete_statement_refuses_when_e3_holds_a_duplicate_from_another_file(
    client, world, books
):
    """Duplikat E3 z pliku spoza Księgi (stary import Płac, bez linii wyciągu):
    usunięcie oryginału też dostaje 409."""

    from app.services.finance_ledger.payments import DUPLICATE_REASON

    year = books["year"]
    await _set_ledger(_bank_settings(world, books))
    marker = uuid.uuid4().hex[:6].upper()
    content = _statement(year, ("D", "300,00", "Faktura FV 7/03", OTHER_ACCOUNT, f"U{marker}"))
    imported = await _bank_import(client, world, content)
    assert imported.status_code == 201, imported.text
    other = hashlib.sha256(f"inny plik {marker}".encode()).hexdigest()
    async with AsyncSessionLocal() as db:
        db.add(
            FinanceCostPaymentRecord(
                kind="statement_line",
                match_status="ignored",
                reason=DUPLICATE_REASON,
                amount=Decimal("300.00"),
                currency="PLN",
                booked_on=date(year, 3, 20),
                statement_sha256=other,
                statement_format="mt940",
                statement_line_ref=f"7:U{marker}",
            )
        )
        await db.commit()
    try:
        refused = await client.delete(
            f"{ACC}/bank/statements/{imported.json()['id']}", headers=_headers(world["admin"])
        )
        assert refused.status_code == 409, refused.text
        assert "duplikat" in refused.json()["detail"]
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(
                delete(FinanceCostPaymentRecord).where(FinanceCostPaymentRecord.statement_sha256 == other)
            )
            await db.commit()


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
        balance = Decimal("100000.00")
        for mmdd, sign, amount, title, party, ref in ops:
            out += f":61:{yy}{mmdd}{mmdd}{sign}{amount}NTRFNONREF//{ref}\r\n"
            out += f":86:~00TR~20{title}~32Kontrahent Testowy" + (f"~38PL{party}" if party else "") + "\r\n"
            balance += _signed(sign, amount)
        out += f":62F:{_mt940_balance(yy, '0430', currency, balance)}\r\n-\r\n"
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
    # Ten sam rachunek, operacje w PLN i w EUR — plik ma jedną walutę (K4c-1).
    euro = _mt940_blocks(
        year,
        (COMPANY, "PLN", [("0320", "D", "12,50", "Opłata za przelew", "", f"G{marker}")]),
        (COMPANY, "EUR", [("0321", "D", "100,00", "Faktura w EUR", STRANGER_ACCOUNT, f"H{marker}")]),
    )
    refused = await _bank_import(client, world, euro)
    assert refused.status_code == 422 and "kilku walutach" in refused.json()["detail"]
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
                    # Bank odsyła wypłatę z zamkniętego rachunku: ten sam KSeF w tytule.
                    ("0311", "C", "8000,00", f"ZWROT FV/77/02 {ksef}", STRANGER_ACCOUNT, f"Z{marker}"),
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


# ── Rozrachunki z rozliczaniem pozycji (K4b) ────────────────────────────────


async def _as_matched(
    line_id: int, *, kind: str, ref_id: int, account: str, counterparty_id: int
) -> None:
    """Operacja wyciągu jak po dopasowaniu w E3/E8 (ich reguły testują K4a, E3, E8)."""

    async with AsyncSessionLocal() as db:
        await db.execute(
            update(LedgerBankLine)
            .where(LedgerBankLine.id == line_id)
            .values(
                kind=kind,
                ref_id=ref_id,
                counter_account=account,
                counterparty_id=counterparty_id,
                note="",
            )
        )
        await db.commit()


async def _settled_march(client, world, books) -> dict:
    """Marzec w księdze: FVS (faktura, korekta, EUR), FVZ i zatwierdzony WB zapłat."""

    year, acc = books["year"], books["acc"]
    await _set_ledger(_bank_settings(world, books))
    for kind in ("sales", "costs"):
        synced = await _sync(client, world, books, kind)
        assert synced.status_code == 200, synced.text
    sales = books["sales"]
    docs = {
        key: await _document("client_sales_invoice", sales[key])
        for key in ("plain", "correction", "euro")
    }
    docs["cost"] = await _document("finance_cost_entry", books["expense"])
    await _approve_ids(client, world, [doc.id for doc in docs.values()])
    marker = uuid.uuid4().hex[:6].upper()
    content = _statement(
        year,
        ("C", "1107,00", "Zapłata FS 1/03 po korekcie", OTHER_ACCOUNT, f"A{marker}"),
        ("D", "1230,00", "Zapłata FV 7/03", OTHER_ACCOUNT, f"B{marker}"),
        ("C", "2150,00", "Zapłata FS 2/03", OTHER_ACCOUNT, f"E{marker}"),
    )
    imported = await _bank_import(client, world, content)
    assert imported.status_code == 201, imported.text
    statement = imported.json()
    lines = statement["lines"]
    receivable = f"{acc['receivable']}-{books['partner']['c']}"
    payable = books["supplier"].cost_account
    await _as_matched(
        lines[0]["id"],
        kind="sales_invoice",
        ref_id=sales["plain"],
        account=receivable,
        counterparty_id=books["buyer"].id,
    )
    await _as_matched(
        lines[1]["id"],
        kind="cost_invoice",
        ref_id=books["expense"],
        account=payable,
        counterparty_id=books["supplier"].id,
    )
    headers = _headers(world["accountant"])
    assigned = await client.patch(
        f"{ACC}/bank/lines/{lines[2]['id']}", json={"account": receivable}, headers=headers
    )
    assert assigned.status_code == 200, assigned.text
    posted = await client.post(
        f"{ACC}/bank/statements/{statement['id']}/post", headers=headers
    )
    assert posted.status_code == 200, posted.text
    wb = await _document("bank_statement", statement["id"])
    await _approve_ids(client, world, [wb.id])
    return {"receivable": receivable, "payable": payable, "docs": docs, "wb": wb}


async def _account_card(client, world, account: str, user: str = "accountant", **params):
    response = await client.get(
        f"{ACC}/settlements/accounts/{account}",
        params=params,
        headers=_headers(world[user]),
    )
    assert response.status_code == 200, response.text
    return response.json()


def _open(card: dict) -> list[tuple[str, str, int]]:
    return sorted(
        (item["doc_type"], item["direction"], item["remaining"]) for item in card["open"]
    )


async def test_settlements_pair_bank_correction_and_zero_balance(client, world, books):
    march = await _settled_march(client, world, books)
    receivable, payable, year = march["receivable"], march["payable"], books["year"]
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(ClientSalesInvoice)
            .where(ClientSalesInvoice.id == books["sales"]["plain"])
            .values(due_date=date(year, 4, 14))
        )
        await db.commit()
    as_of = date(year, 4, 30).isoformat()
    card = await _account_card(client, world, receivable, as_of=as_of)
    assert card["name"] == "Klient Testowy"
    assert _open(card) == [
        ("FVS", "credit", 12_300),
        ("FVS", "debit", 123_000),
        ("FVS", "debit", 215_000),
        ("WB", "credit", 110_700),
        ("WB", "credit", 215_000),
    ]
    plain = next(item for item in card["open"] if item["remaining"] == 123_000)
    assert (plain["due_on"], plain["overdue_days"]) == (f"{year}-04-14", 16)
    assert (card["debit_open"], card["credit_open"], card["balance"]) == (338_000, 338_000, 0)
    headers = _headers(world["accountant"])
    prefix = books["acc"]["receivable"].rsplit("-", 1)[0]
    listed = await client.get(
        f"{ACC}/settlements", params={"as_of": as_of, "q": prefix}, headers=headers
    )
    assert listed.status_code == 200, listed.text
    rows = {row["account"]: row for row in listed.json()["accounts"]}
    assert set(rows) == {receivable, payable}
    assert (rows[receivable]["debit_overdue"], rows[receivable]["max_overdue_days"]) == (
        123_000,
        16,
    )
    assert (rows[payable]["debit_open"], rows[payable]["credit_open"]) == (123_000, 123_000)
    assert rows[payable]["name"] == "Dostawca Testowy"
    overdue = await client.get(
        f"{ACC}/settlements",
        params={"as_of": as_of, "q": prefix, "overdue": "true"},
        headers=headers,
    )
    assert [row["account"] for row in overdue.json()["accounts"]] == [receivable]
    items = {item["key"]: item for item in (await _closing(client, world, books))["items"]}
    assert items["settlements"]["href"] == f"/accounting/settlements?year={year}&month=3"

    auto = await client.post(
        f"{ACC}/settlements/auto", params={"account": receivable}, headers=headers
    )
    assert auto.status_code == 200, auto.text
    assert {key: auto.json()[key] for key in ("bank", "correction", "zero", "created")} == {
        "bank": 1,
        "correction": 1,
        "zero": 1,
        "created": 3,
    }
    card = await _account_card(client, world, receivable, as_of=as_of)
    assert card["open"] == [] and card["settled_total"] == 5
    methods = {s["method"] for item in card["settled"] for s in item["settlements"]}
    assert methods == {"bank", "correction", "zero"}
    again = await client.post(
        f"{ACC}/settlements/auto", params={"account": receivable}, headers=headers
    )
    assert again.json()["created"] == 0
    supplier = await client.post(
        f"{ACC}/settlements/auto", params={"account": payable}, headers=headers
    )
    assert (supplier.json()["bank"], supplier.json()["created"]) == (1, 1)
    # Na dzień przed zapłatą faktury: rozliczenie z datą 31.03 jeszcze się nie liczy.
    early = await _account_card(client, world, receivable, as_of=date(year, 3, 30).isoformat())
    assert _open(early) == [("FVS", "credit", 12_300), ("WB", "credit", 110_700)]

    bank_row = next(
        s for item in card["settled"] for s in item["settlements"] if s["method"] == "bank"
    )
    removed = await client.delete(f"{ACC}/settlements/{bank_row['id']}", headers=headers)
    assert removed.status_code == 204
    gone = await client.delete(f"{ACC}/settlements/{bank_row['id']}", headers=headers)
    assert gone.status_code == 404
    card = await _account_card(client, world, receivable, as_of=as_of)
    assert _open(card) == [("FVS", "debit", 110_700), ("WB", "credit", 110_700)]
    debit = next(item for item in card["open"] if item["direction"] == "debit")
    credit = next(item for item in card["open"] if item["direction"] == "credit")
    pair = {"debit_ids": [debit["line_id"]], "credit_ids": [credit["line_id"]]}
    part = await client.post(
        f"{ACC}/settlements", json={**pair, "amount": "100.00"}, headers=headers
    )
    assert part.status_code == 201 and part.json()["amount"] == 10_000, part.text
    too_much = await client.post(
        f"{ACC}/settlements", json={**pair, "amount": "2000.00"}, headers=headers
    )
    assert too_much.status_code == 422
    rest = await client.post(f"{ACC}/settlements", json=pair, headers=headers)
    assert rest.status_code == 201 and rest.json()["amount"] == 100_700
    done = await client.post(f"{ACC}/settlements", json=pair, headers=headers)
    assert done.status_code == 409 and "rozliczona" in done.json()["detail"]
    swapped = await client.post(
        f"{ACC}/settlements",
        json={"debit_ids": [credit["line_id"]], "credit_ids": [debit["line_id"]]},
        headers=headers,
    )
    assert swapped.status_code == 422 and "stronie Ma" in swapped.json()["detail"]
    supplier_card = await _account_card(client, world, payable, as_of=as_of)
    other_line = supplier_card["settled"][0]["line_id"]
    mixed = await client.post(
        f"{ACC}/settlements",
        json={"debit_ids": [debit["line_id"]], "credit_ids": [other_line]},
        headers=headers,
    )
    assert mixed.status_code == 422 and "jednego konta" in mixed.json()["detail"]
    outsider = await client.post(
        f"{ACC}/settlements/auto", headers=_headers(world["module_only"])
    )
    assert outsider.status_code == 403
    # Storno WB: wpłaty wypadają, a faktury znów czekają (korekta zostaje rozliczona).
    await _reverse(client, world, march["wb"].id, date(year, 3, 31))
    card = await _account_card(client, world, receivable, as_of=as_of)
    assert _open(card) == [("FVS", "debit", 110_700), ("FVS", "debit", 215_000)]


async def test_settlements_as_of_before_a_later_storno_keep_the_old_state(
    client, world, books
):
    """Storno z 05.05 nie zmienia rozrachunków na 30.04 (przegląd K4b 14.11.2026)."""

    march = await _settled_march(client, world, books)
    receivable, year = march["receivable"], books["year"]
    headers = _headers(world["accountant"])
    auto = await client.post(
        f"{ACC}/settlements/auto", params={"account": receivable}, headers=headers
    )
    assert auto.json()["created"] == 3, auto.text
    await _reverse(client, world, march["docs"]["plain"].id, date(year, 5, 5))
    before = await _account_card(client, world, receivable, as_of=f"{year}-04-30")
    assert before["open"] == [] and before["balance"] == 0
    assert before["settled_total"] == 5
    after = await _account_card(client, world, receivable, as_of=f"{year}-05-31")
    assert _open(after) == [("FVS", "credit", 12_300), ("WB", "credit", 110_700)]
    assert after["balance"] == -123_000


async def test_settlements_refuse_ids_beyond_the_database_range(client, world, books):
    """Identyfikator ponad bigint to 422, nie błąd bazy (przegląd K4b 14.11.2026)."""

    await _set_ledger(_bank_settings(world, books))
    headers = _headers(world["accountant"])
    huge = 10**20
    removed = await client.delete(f"{ACC}/settlements/{huge}", headers=headers)
    assert removed.status_code == 422
    posted = await client.post(
        f"{ACC}/settlements",
        json={"debit_ids": [huge], "credit_ids": [1]},
        headers=headers,
    )
    assert posted.status_code == 422


async def test_settlements_keep_payroll_documents_to_payroll(client, world, books):
    year, acc = books["year"], books["acc"]
    settings = _bank_settings(world, books)
    settings["accountants"] = [world["accountant"].id, world["module_only"].id]
    await _set_ledger(settings)
    synced = await _sync(client, world, books, "costs")
    assert synced.status_code == 200, synced.text
    team_doc = await _document("finance_cost_entry", books["payroll"])
    assert team_doc.sensitivity == "payroll"
    await _approve_ids(client, world, [team_doc.id])
    account = f"{acc['payable']}-{books['partner']['p']}"
    headers = _headers(world["accountant"])
    manual = []
    for amount in ("1000.00", "-300.00"):
        created = await client.post(
            f"{ACC}/documents",
            json={
                "op_date": f"{year}-03-28",
                "description": "Rozrachunek ręczny",
                "lines": [
                    {"side": "debit", "account": account, "amount": amount},
                    {"side": "credit", "account": acc["bank"], "amount": amount},
                ],
            },
            headers=headers,
        )
        assert created.status_code == 201, created.text
        manual.append(created.json()["id"])
    await _approve_ids(client, world, manual)
    as_of = f"{year}-12-31"
    seen = await _account_card(client, world, account, as_of=as_of)
    assert _open(seen) == [
        ("FVZ", "credit", 1_230_000),
        ("PK", "credit", 30_000),
        ("PK", "debit", 100_000),
    ]
    team_line = next(item for item in seen["open"] if item["doc_type"] == "FVZ")
    pk_debit = next(item for item in seen["open"] if item["direction"] == "debit")
    red = next(
        item
        for item in seen["open"]
        if item["doc_type"] == "PK" and item["direction"] == "credit"
    )
    # Osoba bez Płac nie widzi wypłaty ani nazwiska — także w zestawieniu.
    hidden = await _account_card(client, world, account, user="module_only", as_of=as_of)
    assert _open(hidden) == [("PK", "credit", 30_000), ("PK", "debit", 100_000)]
    assert hidden["name"] == ""
    listed = await client.get(
        f"{ACC}/settlements",
        params={"q": account, "as_of": as_of},
        headers=_headers(world["module_only"]),
    )
    assert [row["debit_open"] for row in listed.json()["accounts"]] == [100_000]
    blind = await client.post(
        f"{ACC}/settlements",
        json={"debit_ids": [pk_debit["line_id"]], "credit_ids": [team_line["line_id"]]},
        headers=_headers(world["module_only"]),
    )
    assert blind.status_code == 404
    mixed = await client.post(
        f"{ACC}/settlements",
        json={"debit_ids": [pk_debit["line_id"]], "credit_ids": [team_line["line_id"]]},
        headers=headers,
    )
    assert mixed.status_code == 422 and "płacowego" in mixed.json()["detail"]
    # Storno czerwone (kwota ujemna po Wn) rozlicza się po stronie Ma.
    red_pair = await client.post(
        f"{ACC}/settlements",
        json={"debit_ids": [pk_debit["line_id"]], "credit_ids": [red["line_id"]]},
        headers=_headers(world["module_only"]),
    )
    assert red_pair.status_code == 201 and red_pair.json()["amount"] == 30_000
    # Moduł „Bank” wyłączony: rozrachunki znikają (admin widzi zawsze).
    settings["modules"] = {"ledger": True}
    await _set_ledger(settings)
    closed = await client.get(f"{ACC}/settlements", headers=headers)
    assert closed.status_code == 404
    admin = await client.get(f"{ACC}/settlements", headers=_headers(world["admin"]))
    assert admin.status_code == 200
    plain = await client.get(
        f"{ACC}/settlements/accounts/{acc['bank']}", headers=_headers(world["admin"])
    )
    assert plain.status_code == 404 and "słownikiem" in plain.json()["detail"]


# ── Rachunki walutowe i różnice kursowe (K4c-1) ─────────────────────────────

EUR_COMPANY = _valid_nrb("109010140000071219812877")


async def _eur_setup(world, books, *, fx_accounts: bool) -> tuple[dict, dict]:
    """Rachunek firmy w EUR (konto 131) i konta różnic kursowych w planie."""

    prefix = books["acc"]["bank"].rsplit("-", 1)[0]
    accounts = {
        "eur_bank": f"{prefix}-131",
        "gain": f"{prefix}-750",
        "loss": f"{prefix}-751",
    }
    async with AsyncSessionLocal() as db:
        for key, name in (
            ("eur_bank", "Rachunek walutowy"),
            ("gain", "Przychody finansowe"),
            ("loss", "Koszty finansowe"),
        ):
            db.add(FinanceAccount(number=accounts[key], name=name, kind="other"))
        await db.commit()
    settings = _bank_settings(world, books)
    settings["bank"]["accounts"].append(
        {
            "number": EUR_COMPANY,
            "account": accounts["eur_bank"],
            "name": "Rachunek EUR",
            "currency": "EUR",
        }
    )
    if fx_accounts:
        settings["bank"]["fx_gain_account"] = accounts["gain"]
        settings["bank"]["fx_loss_account"] = accounts["loss"]
    await _set_ledger(settings)
    return accounts, settings


async def _eur_rate(day: date, rate: str) -> None:
    async with AsyncSessionLocal() as db:
        db.add(
            FxRate(
                effective_date=day,
                currency="EUR",
                rate_to_pln=Decimal(rate),
                source="NBP",
            )
        )
        await db.commit()


async def _drop_eur_rate(day: date) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(FxRate).where(FxRate.effective_date == day, FxRate.currency == "EUR")
        )
        await db.commit()


async def test_currency_account_books_wb_at_nbp_rate_and_settles_the_fx_difference(
    client, world, books
):
    year = books["year"]
    receivable = f"{books['acc']['receivable']}-{books['partner']['c']}"
    accounts, settings = await _eur_setup(world, books, fx_accounts=False)
    paid_day = date(year, 3, 25)
    nbp_day = rate_day(paid_day)
    await _eur_rate(nbp_day, "4.250000")
    try:
        synced = await _sync(client, world, books, "sales")
        assert synced.status_code == 200, synced.text
        invoice = await _document("client_sales_invoice", books["sales"]["euro"])
        await _approve_ids(client, world, [invoice.id])
        marker = uuid.uuid4().hex[:6].upper()
        content = _mt940_blocks(
            year,
            (
                EUR_COMPANY,
                "EUR",
                [("0325", "C", "500,00", "Zapłata FS 2/03", OTHER_ACCOUNT, f"X{marker}")],
            ),
        )
        imported = await _bank_import(client, world, content)
        assert imported.status_code == 201, imported.text
        statement = imported.json()
        assert statement["currency"] == "EUR" and statement["credit_total"] == 50_000
        line = statement["lines"][0]
        # 500 EUR po średnim kursie NBP z ostatniego dnia roboczego przed wpłatą.
        assert (line["currency"], line["amount"], line["amount_pln"]) == ("EUR", 50_000, 212_500)
        assert (line["fx_rate"], line["fx_date"]) == ("4.250000", nbp_day.isoformat())
        await _as_matched(
            line["id"],
            kind="sales_invoice",
            ref_id=books["sales"]["euro"],
            account=receivable,
            counterparty_id=books["buyer"].id,
        )
        headers = _headers(world["accountant"])
        posted = await client.post(
            f"{ACC}/bank/statements/{statement['id']}/post", headers=headers
        )
        assert posted.status_code == 200, posted.text
        wb = await _document("bank_statement", statement["id"])
        assert await _lines(wb.id) == [
            ("debit", accounts["eur_bank"], 212_500),
            ("credit", receivable, 212_500),
        ]
        async with AsyncSessionLocal() as db:
            rates = (
                await db.execute(
                    select(LedgerLine.currency, LedgerLine.amount_cur, LedgerLine.fx_rate)
                    .where(LedgerLine.document_id == wb.id)
                )
            ).all()
        assert set(rates) == {("EUR", 50_000, Decimal("4.250000"))}
        await _approve_ids(client, world, [wb.id])
        # Bez konta ujemnych różnic kursowych para czeka (podgląd i automat).
        waiting = await client.post(
            f"{ACC}/settlements/auto", params={"account": receivable}, headers=headers
        )
        assert (waiting.json()["fx_waiting"], waiting.json()["created"]) == (1, 0)
        settings["bank"]["fx_gain_account"] = accounts["gain"]
        settings["bank"]["fx_loss_account"] = accounts["loss"]
        await _set_ledger(settings)
        auto = await client.post(
            f"{ACC}/settlements/auto", params={"account": receivable}, headers=headers
        )
        result = auto.json()
        assert (result["bank"], result["created"]) == (1, 1), auto.text
        assert [doc["amount"] for doc in result["fx_documents"]] == [2_500]
        async with AsyncSessionLocal() as db:
            row = await db.scalar(
                select(LedgerSettlement).where(
                    LedgerSettlement.account == receivable,
                    LedgerSettlement.removed_at.is_(None),
                )
            )
            fx_doc = await db.scalar(
                select(LedgerDocument).where(
                    LedgerDocument.source_type == "fx_difference",
                    LedgerDocument.source_id == str(row.id),
                )
            )
        # 500 EUR: faktura 2 150,00 (kurs 4,30), wpłata 2 125,00 (kurs 4,25).
        assert (row.currency, row.amount_cur, row.amount, row.credit_amount) == (
            "EUR",
            50_000,
            215_000,
            212_500,
        )
        assert await _lines(fx_doc.id) == [
            ("debit", accounts["loss"], 2_500),
            ("credit", receivable, 2_500),
        ]
        card = await _account_card(client, world, receivable, as_of=f"{year}-03-31")
        assert card["open"] == []
        assert [(doc["status"], doc["kind"], doc["amount"], doc["orphan"]) for doc in card["fx_documents"]] == [
            ("draft", "loss", 2_500, False)
        ]
        # Szkicu różnicy nie usuwa się z bufora — saldo konta rozjechałoby się
        # z pozycjami po cichu (przegląd K4c 15.11.2026); zabiera go cofnięcie.
        dropped = await client.delete(f"{ACC}/documents/{fx_doc.id}", headers=headers)
        assert dropped.status_code == 409 and "Rozrachunki" in dropped.json()["detail"]
        # Cofnięcie rozliczenia zabiera szkic różnicy kursowej.
        removed = await client.delete(f"{ACC}/settlements/{row.id}", headers=headers)
        assert removed.status_code == 204
        assert await _document("fx_difference", row.id) is None
        again = await client.post(
            f"{ACC}/settlements/auto", params={"account": receivable}, headers=headers
        )
        assert again.json()["created"] == 1
        fx_id = again.json()["fx_documents"][0]["id"]
        await _approve_ids(client, world, [fx_id])
        async with AsyncSessionLocal() as db:
            live = await db.scalar(
                select(LedgerSettlement.id).where(
                    LedgerSettlement.account == receivable,
                    LedgerSettlement.removed_at.is_(None),
                )
            )
            balance = await db.scalar(
                select(
                    func.sum(
                        case(
                            (LedgerLine.side == "debit", LedgerLine.amount),
                            else_=-LedgerLine.amount,
                        )
                    )
                )
                .join(LedgerDocument, LedgerDocument.id == LedgerLine.document_id)
                .where(
                    LedgerLine.account == receivable,
                    LedgerDocument.status == "approved",
                    LedgerDocument.id.in_([invoice.id, wb.id, fx_id]),
                )
            )
        # Po różnicy kursowej saldo konta zgadza się z pozycjami (zero).
        assert balance == 0
        locked = await client.delete(f"{ACC}/settlements/{live}", headers=headers)
        assert locked.status_code == 409 and "storno" in locked.json()["detail"]
    finally:
        await _drop_eur_rate(nbp_day)


async def test_currency_statement_needs_the_account_currency_and_the_nbp_rate(
    client, world, books
):
    year = books["year"]
    await _eur_setup(world, books, fx_accounts=True)
    marker = uuid.uuid4().hex[:6].upper()
    to_pln_account = _mt940_blocks(
        year,
        (COMPANY, "EUR", [("0326", "C", "10,00", "Wpłata", OTHER_ACCOUNT, f"P{marker}")]),
    )
    refused = await _bank_import(client, world, to_pln_account)
    assert refused.status_code == 422
    assert "jest w PLN, a wyciąg w EUR" in refused.json()["detail"]
    no_rate = _mt940_blocks(
        year,
        (EUR_COMPANY, "EUR", [("0326", "C", "10,00", "Wpłata", OTHER_ACCOUNT, f"Q{marker}")]),
    )
    missing = await _bank_import(client, world, no_rate)
    assert missing.status_code == 422
    assert f"Brak kursu NBP EUR z dnia {rate_day(date(year, 3, 26)):%d.%m.%Y}" in missing.json()["detail"]
    gbp = await client.put(
        f"{ACC}/config/bank",
        json={"accounts": [{"number": EUR_COMPANY, "account": "130", "currency": "GBP"}]},
        headers=_headers(world["admin"]),
    )
    assert gbp.status_code == 422



# ── Wycena walut na koniec miesiąca (K4c-2) ─────────────────────────────────


async def _set_eur_rate(day: date, rate: str) -> None:
    await _drop_eur_rate(day)
    await _eur_rate(day, rate)


async def _valuation(client, world, year: int, month: int, user: str = "accountant") -> dict:
    response = await client.get(
        f"{ACC}/settlements/valuation",
        params={"year": year, "month": month},
        headers=_headers(world[user]),
    )
    assert response.status_code == 200, response.text
    return response.json()


async def _post_valuation(client, world, year: int, month: int, user: str = "accountant"):
    return await client.post(
        f"{ACC}/settlements/valuation",
        json={"year": year, "month": month},
        headers=_headers(world[user]),
    )


async def _valuation_item(client, world, year: int, month: int) -> dict:
    response = await client.get(
        f"{ACC}/closing",
        params={"year": year, "month": month},
        headers=_headers(world["accountant"]),
    )
    assert response.status_code == 200, response.text
    return next(item for item in response.json()["items"] if item["key"] == "valuation")


async def _eur_wb(client, world, books, mmdd: str = "0325") -> int:
    """Zatwierdzony WB z rachunku EUR: wpływ 100 EUR (konto przychodów)."""

    headers = _headers(world["accountant"])
    marker = uuid.uuid4().hex[:6].upper()
    content = _mt940_blocks(
        books["year"],
        (EUR_COMPANY, "EUR", [(mmdd, "C", "100,00", "Wpłata bez faktury", OTHER_ACCOUNT, f"V{marker}")]),
    )
    imported = await _bank_import(client, world, content)
    assert imported.status_code == 201, imported.text
    statement = imported.json()
    assigned = await client.patch(
        f"{ACC}/bank/lines/{statement['lines'][0]['id']}",
        json={"account": books["acc"]["revenue"]},
        headers=headers,
    )
    assert assigned.status_code == 200, assigned.text
    posted = await client.post(f"{ACC}/bank/statements/{statement['id']}/post", headers=headers)
    assert posted.status_code == 200, posted.text
    wb_id = posted.json()["documents"][0]["id"]
    await _approve_ids(client, world, [wb_id])
    return wb_id


async def _euro_invoice(client, world, books) -> None:
    """Zatwierdzona faktura 500 EUR po 4,30 (należność 2 150,00 zł)."""

    synced = await _sync(client, world, books, "sales")
    assert synced.status_code == 200, synced.text
    invoice = await _document("client_sales_invoice", books["sales"]["euro"])
    await _approve_ids(client, world, [invoice.id])


def _bank_row(data: dict, account: str) -> list[tuple]:
    return [
        (p["amount_cur"], p["book"], p["valued"], p["diff"])
        for p in data["positions"]
        if p["account"] == account
    ]


async def _next_year_free(year: int) -> bool:
    async with AsyncSessionLocal() as db:
        return await db.scalar(select(LedgerYear.id).where(LedgerYear.year == year + 1)) is None


async def _open_year(world, year: int) -> None:
    async with AsyncSessionLocal() as db:
        await ledger_years.ensure_year(db, year, actor_id=world["admin"].id)
        await db.commit()


async def _draft(world, *, doc_type: str, day: date, lines, sensitivity=None) -> int:
    from app.services.ledger import documents as ledger_documents
    from app.services.ledger.documents import DocumentSpec

    async with AsyncSessionLocal() as db:
        doc = await ledger_documents.create_draft(
            db,
            DocumentSpec(
                doc_type=doc_type,
                op_date=day,
                doc_date=day,
                description="Dokument testu wyceny",
                sensitivity=sensitivity,
                lines=lines,
            ),
            actor_id=world["accountant"].id,
        )
        await db.commit()
        return doc.id


async def test_month_end_valuation_books_and_reverses_currency_positions(
    client, world, books
):
    year, acc = books["year"], books["acc"]
    receivable = f"{acc['receivable']}-{books['partner']['c']}"
    accounts, _ = await _eur_setup(world, books, fx_accounts=True)
    nbp_day = rate_day(date(year, 3, 25))
    end_day = rate_day(date(year, 4, 1))  # ostatni dzień roboczy marca
    await _eur_rate(nbp_day, "4.250000")
    await _set_eur_rate(end_day, "4.400000")
    headers = _headers(world["accountant"])
    try:
        await _euro_invoice(client, world, books)
        await _eur_wb(client, world, books)

        data = await _valuation(client, world, year, 3)
        assert data["blocker"] is None and data["missing_rates"] == []
        assert data["rate_day"] == end_day.isoformat()
        positions = {(p["account"], p["kind"]): p for p in data["positions"]}
        # Należność 500 EUR po 4,30 = 2 150,00 → po 4,40 = 2 200,00 (+50,00);
        # rachunek EUR 100 EUR po 4,25 = 425,00 → 440,00 (+15,00).
        assert {key: (p["amount_cur"], p["book"], p["valued"], p["diff"]) for key, p in positions.items()} == {
            (receivable, "settlement"): (50_000, 215_000, 220_000, 5_000),
            (accounts["eur_bank"], "bank"): (10_000, 42_500, 44_000, 1_500),
        }
        assert (data["gain"], data["loss"], data["skipped"]) == (6_500, 0, [])
        booked = await _post_valuation(client, world, year, 3)
        assert booked.status_code == 200, booked.text
        [group] = booked.json()["groups"]
        assert group["key"] == f"{year}-03" and not group["payroll"]
        assert (group["valuation"]["outcome"], group["reversal"]["outcome"]) == ("created", "created")
        valued_doc = await _document("fx_valuation", f"{year}-03")
        reversal_doc = await _document("fx_valuation_reversal", f"{year}-03")
        assert valued_doc.op_date == date(year, 3, 31) and reversal_doc.op_date == date(year, 4, 1)
        assert sorted(await _lines(valued_doc.id)) == sorted(
            [
                ("debit", receivable, 5_000),
                ("debit", accounts["eur_bank"], 1_500),
                ("credit", accounts["gain"], 6_500),
            ]
        )
        assert sorted(await _lines(reversal_doc.id)) == sorted(
            [
                ("credit", receivable, 5_000),
                ("credit", accounts["eur_bank"], 1_500),
                ("debit", accounts["gain"], 6_500),
            ]
        )
        again = await _post_valuation(client, world, year, 3)
        [group] = again.json()["groups"]
        assert (group["valuation"]["outcome"], group["reversal"]["outcome"]) == (
            "unchanged",
            "unchanged",
        )
        # Rozrachunki zostają w kursie historycznym — wycena nie jest pozycją.
        card = await _account_card(client, world, receivable, as_of=f"{year}-03-31")
        assert [(i["doc_type"], i["remaining"]) for i in card["open"]] == [("FVS", 215_000)]
        # Inny kurs = przebudowa szkicu (z odwróceniem).
        await _set_eur_rate(end_day, "4.410000")
        rebuilt = await _post_valuation(client, world, year, 3)
        [group] = rebuilt.json()["groups"]
        assert (group["valuation"]["outcome"], group["reversal"]["outcome"]) == (
            "rebuilt",
            "rebuilt",
        ), rebuilt.text
        current = await _document("fx_valuation", f"{year}-03")
        await _approve_ids(client, world, [current.id])
        # Zatwierdzonej się nie podmienia: flaga „zmieniona”, odwrócenie dalej
        # z zaksięgowanej PK (przegląd K4c-2).
        await _set_eur_rate(end_day, "4.420000")
        kept = await _post_valuation(client, world, year, 3)
        assert kept.status_code == 200, kept.text
        [group] = kept.json()["groups"]
        assert (group["valuation"]["outcome"], group["changed"]) == ("approved", True)
        assert group["reversal"]["outcome"] == "unchanged"
        assert (await _valuation(client, world, year, 3))["groups"][0]["changed"] is True
        item = await _valuation_item(client, world, year, 3)
        assert item["state"] == "problem" and "storno" in item["detail"]
        # Kwiecień: odwrócenie marca w buforze — wycena kwietnia czeka.
        april = await _valuation(client, world, year, 4)
        assert "nie ma zaksięgowanego odwrócenia" in april["blocker"]
        outsider = await _post_valuation(client, world, year, 3, user="module_only")
        assert outsider.status_code == 403
    finally:
        await _drop_eur_rate(nbp_day)
        await _drop_eur_rate(end_day)


async def test_valuation_keeps_payroll_bank_activity_to_payroll(client, world, books):
    """Rachunek walutowy z wypłatami dla zespołu wycenia osoba z Płacami, w PK
    płacowej — osoba bez Płac nie widzi jego salda (D2, przegląd K4c-2)."""

    from app.services.ledger.engine import LineIn

    year, acc = books["year"], books["acc"]
    accounts, settings = await _eur_setup(world, books, fx_accounts=True)
    settings["accountants"] = [world["accountant"].id, world["module_only"].id]
    await _set_ledger(settings)
    end_day = rate_day(date(year, 4, 1))
    await _set_eur_rate(end_day, "4.400000")
    try:
        payout = await _draft(
            world,
            doc_type="PK",
            day=date(year, 3, 12),
            sensitivity="payroll",
            lines=[
                LineIn("debit", acc["payroll_settle"], 43_000, "wypłata"),
                LineIn(
                    "credit",
                    accounts["eur_bank"],
                    43_000,
                    "wypłata",
                    currency="EUR",
                    amount_cur=10_000,
                ),
            ],
        )
        await _approve_ids(client, world, [payout])
        blind = await _valuation(client, world, year, 3, user="module_only")
        assert [p for p in blind["positions"] if p["account"] == accounts["eur_bank"]] == []
        assert (blind["payroll_hidden"], blind["groups"], blind["rates"]) == (True, [], [])
        booked = await _post_valuation(client, world, year, 3, user="module_only")
        assert booked.status_code == 200, booked.text
        assert booked.json()["groups"] == []
        assert await _document("fx_valuation", f"{year}-03-payroll") is None
        seen = await _valuation(client, world, year, 3)
        bank = next(p for p in seen["positions"] if p["account"] == accounts["eur_bank"])
        # −100 EUR po 4,30 = −430,00 → po 4,40 = −440,00 (−10,00).
        assert (bank["amount_cur"], bank["book"], bank["diff"], bank["payroll"]) == (
            -10_000,
            -43_000,
            -1_000,
            True,
        )
        assert [(g["key"], g["payroll"]) for g in seen["groups"]] == [(f"{year}-03-payroll", True)]
        payroll = await _post_valuation(client, world, year, 3)
        assert payroll.status_code == 200, payroll.text
        doc = await _document("fx_valuation", f"{year}-03-payroll")
        assert doc is not None and doc.sensitivity == "payroll"
        assert sorted(await _lines(doc.id)) == sorted(
            [("credit", accounts["eur_bank"], 1_000), ("debit", accounts["loss"], 1_000)]
        )
        reversal = await _document("fx_valuation_reversal", f"{year}-03-payroll")
        assert reversal is not None and reversal.sensitivity == "payroll"
    finally:
        await _drop_eur_rate(end_day)


async def test_valuation_skips_a_currency_account_without_currency_amounts(
    client, world, books
):
    """BO z Symfonii (tylko PLN) na rachunku walutowym: rachunek pominięty
    z powodem — wcześniej wycena odpisywała całe saldo (przegląd K4c-2)."""

    year = books["year"]
    accounts, _ = await _eur_setup(world, books, fx_accounts=True)
    nbp_day = rate_day(date(year, 3, 25))
    end_day = rate_day(date(year, 4, 1))
    await _set_eur_rate(nbp_day, "4.250000")
    await _set_eur_rate(end_day, "4.400000")
    try:
        content = (
            "Konto;Nazwa;BO Wn;BO Ma\n"
            f"{accounts['eur_bank']};Rachunek EUR;4 300,00;\n"
            f"{books['acc']['settle']};Rozliczenie;;4 300,00\n"
            "Razem;;4 300,00;4 300,00\n"
        ).encode()
        saved = await _import(client, world, books, content, save=True)
        assert saved.status_code == 200, saved.text
        await _approve_ids(client, world, [saved.json()["document_id"]])
        await _eur_wb(client, world, books)
        data = await _valuation(client, world, year, 3)
        assert _bank_row(data, accounts["eur_bank"]) == []
        [skipped] = data["skipped"]
        assert skipped["account"] == accounts["eur_bank"]
        assert "bez kwoty w EUR" in skipped["reason"] and "ręcznie" in skipped["reason"]
        assert (data["gain"], data["loss"], data["groups"]) == (0, 0, [])
        booked = await _post_valuation(client, world, year, 3)
        assert booked.status_code == 200 and booked.json()["groups"] == [], booked.text
        assert await _document("fx_valuation", f"{year}-03") is None
        # Gdy w księdze jest już jakakolwiek PK wyceny, rachunek dalej jest
        # pominięty (drugi przegląd K4c-2: „NULL IN (…)” wyłączało sprawdzenie).
        await _euro_invoice(client, world, books)
        first = await _post_valuation(client, world, year, 3)
        assert first.status_code == 200, first.text
        assert await _document("fx_valuation", f"{year}-03") is not None
        again = await _valuation(client, world, year, 3)
        assert _bank_row(again, accounts["eur_bank"]) == []
        assert [item["account"] for item in again["skipped"]] == [accounts["eur_bank"]]
        assert (again["gain"], again["loss"]) == (5_000, 0)
    finally:
        await _drop_eur_rate(nbp_day)
        await _drop_eur_rate(end_day)


async def test_valuation_counts_a_shared_ledger_account_once(client, world, books):
    """Dwa rachunki (NRB) na jednym koncie księgi: jedna pozycja i jedna korekta
    (drugi przegląd K4c-2 — korekta szła podwójnie)."""

    year = books["year"]
    accounts, settings = await _eur_setup(world, books, fx_accounts=True)
    settings["bank"]["accounts"].append(
        {
            "number": _valid_nrb("109010140000071219812879"),
            "account": accounts["eur_bank"],
            "name": "Drugi rachunek EUR",
            "currency": "EUR",
        }
    )
    await _set_ledger(settings)
    nbp_day = rate_day(date(year, 3, 25))
    end_day = rate_day(date(year, 4, 1))
    await _set_eur_rate(nbp_day, "4.250000")
    await _set_eur_rate(end_day, "4.400000")
    try:
        await _eur_wb(client, world, books)
        data = await _valuation(client, world, year, 3)
        assert _bank_row(data, accounts["eur_bank"]) == [(10_000, 42_500, 44_000, 1_500)]
        assert data["gain"] == 1_500
        booked = await _post_valuation(client, world, year, 3)
        assert booked.status_code == 200, booked.text
        valued = await _document("fx_valuation", f"{year}-03")
        assert sorted(await _lines(valued.id)) == sorted(
            [("debit", accounts["eur_bank"], 1_500), ("credit", accounts["gain"], 1_500)]
        )
    finally:
        await _drop_eur_rate(nbp_day)
        await _drop_eur_rate(end_day)


async def test_valuation_leaves_out_its_own_storno(client, world, books):
    """Storno wyceny z datą tego miesiąca nie zostaje w saldzie rachunku —
    inaczej ponowna wycena dodałaby różnicę drugi raz (przegląd K4c-2)."""

    year = books["year"]
    accounts, _ = await _eur_setup(world, books, fx_accounts=True)
    nbp_day = rate_day(date(year, 3, 25))
    end_day = rate_day(date(year, 4, 1))
    await _set_eur_rate(nbp_day, "4.250000")
    await _set_eur_rate(end_day, "4.400000")
    try:
        await _eur_wb(client, world, books)
        first = await _post_valuation(client, world, year, 3)
        assert first.status_code == 200, first.text
        valued = await _document("fx_valuation", f"{year}-03")
        reversal = await _document("fx_valuation_reversal", f"{year}-03")
        await _approve_ids(client, world, [valued.id])
        await _reverse(client, world, valued.id, date(year, 3, 31))
        data = await _valuation(client, world, year, 3)
        assert _bank_row(data, accounts["eur_bank"]) == [(10_000, 42_500, 44_000, 1_500)]
        again = await _post_valuation(client, world, year, 3)
        assert again.status_code == 200, again.text
        [group] = again.json()["groups"]
        assert (group["valuation"]["outcome"], group["reversal"]["outcome"]) == (
            "created",
            "unchanged",
        )
        rebuilt = await _document("fx_valuation", f"{year}-03")
        assert rebuilt.id != valued.id
        assert sorted(await _lines(rebuilt.id)) == sorted(
            [("debit", accounts["eur_bank"], 1_500), ("credit", accounts["gain"], 1_500)]
        )
        assert (await _document("fx_valuation_reversal", f"{year}-03")).id == reversal.id
    finally:
        await _drop_eur_rate(nbp_day)
        await _drop_eur_rate(end_day)


async def test_valuation_of_a_new_year_starts_from_its_opening_balance(
    client, world, books
):
    """Saldo rachunku z bieżącego roku obrotowego: BO następnego roku nie dubluje
    obrotów poprzedniego, a bez BO rachunek czeka (przegląd K4c-2)."""

    from app.services.ledger.engine import LineIn

    year = books["year"]
    if not await _next_year_free(year):
        pytest.skip("następny rok zajęty przez inny test")
    accounts, _ = await _eur_setup(world, books, fx_accounts=True)
    nbp_day = rate_day(date(year, 3, 25))
    jan_end = rate_day(date(year + 1, 2, 1))
    await _set_eur_rate(nbp_day, "4.250000")
    await _set_eur_rate(jan_end, "4.400000")
    try:
        await _eur_wb(client, world, books)
        await _open_year(world, year + 1)
        waiting = await _valuation(client, world, year + 1, 1)
        assert _bank_row(waiting, accounts["eur_bank"]) == []
        [skipped] = waiting["skipped"]
        assert f"brak BO {year + 1}" in skipped["reason"]
        opening = await _draft(
            world,
            doc_type="BO",
            day=date(year + 1, 1, 1),
            lines=[
                LineIn("debit", accounts["eur_bank"], 42_500, "BO", currency="EUR", amount_cur=10_000),
                LineIn("credit", books["acc"]["revenue"], 42_500, "BO"),
            ],
        )
        await _approve_ids(client, world, [opening])
        data = await _valuation(client, world, year + 1, 1)
        assert data["skipped"] == []
        assert _bank_row(data, accounts["eur_bank"]) == [(10_000, 42_500, 44_000, 1_500)]
    finally:
        await _purge_years([year + 1])
        await _drop_eur_rate(nbp_day)
        await _drop_eur_rate(jan_end)


async def test_valuation_waits_for_every_earlier_reversal(client, world, books):
    """Maj czeka na odwrócenie marca, nie tylko kwiecień (przegląd K4c-2)."""

    year = books["year"]
    await _eur_setup(world, books, fx_accounts=True)
    march_end = rate_day(date(year, 4, 1))
    may_end = rate_day(date(year, 6, 1))
    await _set_eur_rate(march_end, "4.400000")
    await _set_eur_rate(may_end, "4.400000")
    try:
        await _euro_invoice(client, world, books)
        march = await _post_valuation(client, world, year, 3)
        assert march.status_code == 200, march.text
        valued = await _document("fx_valuation", f"{year}-03")
        reversal = await _document("fx_valuation_reversal", f"{year}-03")
        await _approve_ids(client, world, [valued.id])  # odwrócenie zostaje w buforze
        may = await _valuation(client, world, year, 5)
        assert "nie ma zaksięgowanego odwrócenia" in may["blocker"]
        refused = await _post_valuation(client, world, year, 5)
        assert refused.status_code == 422
        await _approve_ids(client, world, [reversal.id])
        assert (await _valuation(client, world, year, 5))["blocker"] is None
    finally:
        await _drop_eur_rate(march_end)
        await _drop_eur_rate(may_end)


async def test_waiting_reversal_follows_the_booked_valuation(client, world, books):
    """Odwrócenie czekało na nowy rok, a w międzyczasie przyszedł późny dokument:
    odwrócenie powstaje z zaksięgowanej PK, a wycena dostaje flagę „zmieniona”
    (wcześniej 409 i styczeń stał — przegląd K4c-2)."""

    from app.services.ledger.engine import LineIn

    year, acc = books["year"], books["acc"]
    receivable = f"{acc['receivable']}-{books['partner']['c']}"
    if not await _next_year_free(year):
        pytest.skip("następny rok zajęty przez inny test")
    accounts, _ = await _eur_setup(world, books, fx_accounts=True)
    dec_end = rate_day(date(year + 1, 1, 1))
    await _set_eur_rate(dec_end, "4.400000")
    try:
        await _euro_invoice(client, world, books)
        first = await _post_valuation(client, world, year, 12)
        assert first.status_code == 200, first.text
        [group] = first.json()["groups"]
        assert group["reversal"]["outcome"] == "waiting"
        assert "czeka na rok obrotowy" in group["reversal_waiting"]
        valued = await _document("fx_valuation", f"{year}-12")
        await _approve_ids(client, world, [valued.id])
        late = await _draft(
            world,
            doc_type="PK",
            day=date(year, 12, 10),
            lines=[
                LineIn(
                    "debit",
                    receivable,
                    43_000,
                    "późna należność",
                    counterparty_id=books["buyer"].id,
                    currency="EUR",
                    amount_cur=10_000,
                ),
                LineIn("credit", acc["revenue"], 43_000, "późna należność"),
            ],
        )
        await _approve_ids(client, world, [late])
        stale = await _valuation(client, world, year, 12)
        assert stale["groups"][0]["changed"] is True
        item = await _valuation_item(client, world, year, 12)
        assert item["state"] == "problem", item
        await _open_year(world, year + 1)
        again = await _post_valuation(client, world, year, 12)
        assert again.status_code == 200, again.text
        [group] = again.json()["groups"]
        assert (group["valuation"]["outcome"], group["changed"]) == ("approved", True)
        assert group["reversal"]["outcome"] == "created"
        reversal = await _document("fx_valuation_reversal", f"{year}-12")
        # Odwraca to, co zaksięgowano (+50,00), nie dzisiejsze przeliczenie (+60,00).
        assert sorted(await _lines(reversal.id)) == sorted(
            [("credit", receivable, 5_000), ("debit", accounts["gain"], 5_000)]
        )
        january = await _valuation(client, world, year + 1, 1)
        assert "nie ma zaksięgowanego odwrócenia" in january["blocker"]
        await _approve_ids(client, world, [reversal.id])
        january = await _valuation(client, world, year + 1, 1)
        assert "odwrócenia" not in (january["blocker"] or "")
    finally:
        await _purge_years([year + 1])
        await _drop_eur_rate(dec_end)


async def test_valuation_needs_the_exact_nbp_rate_and_keeps_positions_without_it(
    client, world, books
):
    """Kurs z ostatniego dnia roboczego miesiąca, nie sprzed kilku dni; bez kursu
    pozycje zostają, a grudzień zostaje na liście zamknięcia (przegląd K4c-2)."""

    year, acc = books["year"], books["acc"]
    receivable = f"{acc['receivable']}-{books['partner']['c']}"
    await _eur_setup(world, books, fx_accounts=True)
    stale = rate_day(date(year, 3, 27))
    exact = rate_day(date(year, 4, 1))
    await _set_eur_rate(stale, "4.300000")
    try:
        await _euro_invoice(client, world, books)
        data = await _valuation(client, world, year, 3)
        assert data["missing_rates"] == ["EUR"] and data["rates"] == []
        assert f"EUR z dnia {exact:%d.%m.%Y}" in data["blocker"]
        assert [(p["account"], p["valued"], p["diff"]) for p in data["positions"]] == [
            (receivable, None, None)
        ]
        refused = await _post_valuation(client, world, year, 3)
        assert refused.status_code == 422
        assert await _document("fx_valuation", f"{year}-03") is None
        item = await _valuation_item(client, world, year, 12)
        assert item["state"] == "todo" and "EUR" in item["detail"], item
    finally:
        await _drop_eur_rate(stale)


# ── Rejestry VAT (K5a) ──────────────────────────────────────────────────────


async def _vat_registers(client, world, books, user: str = "accountant", month: int = 3):
    return await client.get(
        f"{ACC}/vat",
        params={"year": books["year"], "month": month},
        headers=_headers(world[user]),
    )


async def _vat_books(client, world, books, keep_items: tuple[str, ...] = ()) -> dict:
    """Moduł VAT, pozycje faktur ze stawkami i zatwierdzone FVS/FVZ marca."""

    settings = _ledger_settings(world, books, allocation=False)
    settings["modules"]["vat"] = True
    settings["vat"] = {"input_account": books["acc"]["vat_in"]}
    await _set_ledger(settings)
    items = {
        "plain": [{"name": "Rekrutacja", "net": "1000.00", "vat_rate": "23"}],
        "euro": [{"name": "Usługa", "net": "500.00", "vat_rate": "np II"}],
        "correction": [
            {"name": "Rekrutacja", "net": "1000.00", "vat_rate": "23", "before_correction": True},
            {"name": "Rekrutacja", "net": "900.00", "vat_rate": "23"},
        ],
    }
    async with AsyncSessionLocal() as db:
        for key, value in items.items():
            if key in keep_items:
                continue
            await db.execute(
                update(ClientSalesInvoice)
                .where(ClientSalesInvoice.id == books["sales"][key])
                .values(items=value)
            )
        await db.commit()
    for kind in ("sales", "costs"):
        synced = await _sync(client, world, books, kind)
        assert synced.status_code == 200, synced.text
    docs = {
        key: await _document("client_sales_invoice", books["sales"][key])
        for key in ("plain", "euro", "correction")
    }
    docs["expense"] = await _document("finance_cost_entry", books["expense"])
    docs["payroll"] = await _document("finance_cost_entry", books["payroll"])
    await _approve_ids(client, world, [doc.id for doc in docs.values()])
    return docs


async def test_vat_registers_follow_approved_documents(client, world, books):
    from app.services.ledger.engine import LineIn

    year, acc = books["year"], books["acc"]
    docs = await _vat_books(client, world, books)
    response = await _vat_registers(client, world, books)
    assert response.status_code == 200, response.text
    data = response.json()
    sales = {row["number"]: row for row in data["sales"]}
    # FS 1/03: 23%; FS 2/03: 500 EUR po 4,30 dla podatnika z UE (np II);
    # korekta FK 1/03: −100 zł netto, −23 zł VAT.
    assert {n: (r["net"], r["vat"], [g["key"] for g in r["groups"]], r["correction"]) for n, r in sales.items()} == {
        "FS 1/03": (100_000, 23_000, ["23"], False),
        "FS 2/03": (215_000, 0, ["np_ue"], False),
        "FK 1/03": (-10_000, -2_300, ["23"], True),
    }
    assert sales["FS 1/03"]["date"] == f"{year}-03-31" and sales["FS 1/03"]["issue_date"] == f"{year}-04-02"
    purchases = {row["number"]: (row["net"], row["vat"], row["payroll"]) for row in data["purchases"]}
    assert purchases == {
        docs["expense"].number: (100_000, 23_000, False),
        docs["payroll"].number: (1_000_000, 230_000, True),
    }
    summary = data["summary"]
    assert [(g["key"], g["net"], g["vat"]) for g in summary["groups"]] == [
        ("23", 90_000, 20_700),
        ("np_ue", 215_000, 0),
        ("other", 1_100_000, 253_000),
    ]
    assert (summary["output_vat"], summary["input_vat"], summary["due"]) == (20_700, 253_000, -232_300)
    issues = {issue["kind"]: issue for issue in data["issues"]}
    # Zaliczka i faktura nabywcy spoza kartoteki nie mają FVS — VAT jest należny.
    assert set(issues) == {"missing_sales"}
    missing = {item["number"]: item["detail"] for item in issues["missing_sales"]["items"]}
    assert set(missing) == {"FS 3/03", "FZ 1/03"} and "zaliczka" in missing["FZ 1/03"]
    assert data["payroll_hidden"] is False

    # D2: osoba bez Płac — rejestr zakupu i sumy bez faktury osoby zespołu.
    settings = _ledger_settings(world, books, allocation=False)
    settings["modules"]["vat"] = True
    settings["vat"] = {"input_account": acc["vat_in"]}
    settings["accountants"] = [world["accountant"].id, world["module_only"].id]
    await _set_ledger(settings)
    blind = (await _vat_registers(client, world, books, user="module_only")).json()
    assert [row["number"] for row in blind["purchases"]] == [docs["expense"].number]
    assert (blind["summary"]["input_vat"], blind["payroll_hidden"]) == (23_000, True)
    assert not any(row["payroll"] for row in blind["purchases"])
    assert blind["summary"]["groups"][-1]["vat"] == 23_000

    # PK na koncie VAT należnego poza rejestrem.
    async with AsyncSessionLocal() as db:
        from app.services.ledger import documents as ledger_documents
        from app.services.ledger.documents import DocumentSpec

        manual = await ledger_documents.create_draft(
            db,
            DocumentSpec(
                doc_type="PK",
                op_date=date(year, 3, 28),
                doc_date=date(year, 3, 28),
                description="Korekta VAT ręcznie",
                lines=[
                    LineIn("debit", acc["revenue"], 1_000, "korekta"),
                    LineIn("credit", acc["vat_out"], 1_000, "korekta"),
                ],
            ),
            actor_id=world["accountant"].id,
        )
        await db.commit()
    await _approve_ids(client, world, [manual.id])
    data = (await _vat_registers(client, world, books)).json()
    outside = next(issue for issue in data["issues"] if issue["kind"] == "outside")
    assert [(item["number"], item["amount"]) for item in outside["items"]] == [(manual.number, -1_000)]
    closing_items = (await _closing(client, world, books))["items"]
    registers = next(item for item in closing_items if item["key"] == "vat_registers")
    assert registers["state"] == "problem" and "bez dokumentu w księdze: 2" in registers["detail"]
    # JPK (K5b): do zrobienia, dopóki plik nie jest wysłany.
    jpk_item = next(item for item in closing_items if item["key"] == "jpk")
    assert jpk_item["state"] == "todo"
    assert not any(item["key"] == "later:vat" for item in closing_items)


async def test_vat_module_settings_and_gates(client, world, books):
    settings = _ledger_settings(world, books, allocation=False)
    await _set_ledger(settings)
    closed = await _vat_registers(client, world, books)
    assert closed.status_code == 404
    assert (await _vat_registers(client, world, books, user="admin")).status_code == 200
    settings["modules"]["vat"] = True
    await _set_ledger(settings)
    outsider = await client.put(
        f"{ACC}/vat/settings",
        json={"input_account": books["acc"]["vat_in"]},
        headers=_headers(world["accountant"]),
    )
    assert outsider.status_code == 403
    missing = await client.put(
        f"{ACC}/vat/settings",
        json={"input_account": "9999-999"},
        headers=_headers(world["admin"]),
    )
    assert missing.status_code == 422 and "planie kont" in missing.json()["detail"]
    saved = await client.put(
        f"{ACC}/vat/settings",
        json={"input_account": books["acc"]["vat_in"]},
        headers=_headers(world["admin"]),
    )
    assert saved.status_code == 200 and saved.json() == {
        "input_account": books["acc"]["vat_in"],
        "foreign_account": "",
        "rounding_gain_account": "",
        "rounding_loss_account": "",
    }
    # K5b-2: konto dostawców zagranicznych tylko ze słownikiem kontrahentów;
    # formularz bez tego pola go nie kasuje.
    plain = await client.put(
        f"{ACC}/vat/settings",
        json={"foreign_account": books["acc"]["cost"]},
        headers=_headers(world["admin"]),
    )
    assert plain.status_code == 422 and "słownik" in plain.json()["detail"]
    foreign_saved = await client.put(
        f"{ACC}/vat/settings",
        json={"foreign_account": books["acc"]["payable"]},
        headers=_headers(world["admin"]),
    )
    assert foreign_saved.json()["foreign_account"] == books["acc"]["payable"]
    # K5b-3c: konta różnic z zaokrągleń VAT — tak samo pole pominięte = bez zmiany.
    rounding = await client.put(
        f"{ACC}/vat/settings",
        json={
            "rounding_gain_account": books["acc"]["revenue"],
            "rounding_loss_account": books["acc"]["cost"],
        },
        headers=_headers(world["admin"]),
    )
    assert rounding.status_code == 200, rounding.text
    kept = await client.put(
        f"{ACC}/vat/settings",
        json={"input_account": books["acc"]["vat_in"]},
        headers=_headers(world["admin"]),
    )
    assert kept.json() == {
        "input_account": books["acc"]["vat_in"],
        "foreign_account": books["acc"]["payable"],
        "rounding_gain_account": books["acc"]["revenue"],
        "rounding_loss_account": books["acc"]["cost"],
    }
    # Puste pole wyłącza konto zaokrągleń (jak konto dostawców zagranicznych).
    cleared = await client.put(
        f"{ACC}/vat/settings",
        json={"rounding_loss_account": ""},
        headers=_headers(world["admin"]),
    )
    assert cleared.json()["rounding_loss_account"] == ""
    assert cleared.json()["rounding_gain_account"] == books["acc"]["revenue"]
    assert cleared.json()["foreign_account"] == books["acc"]["payable"]
    data = (await _vat_registers(client, world, books)).json()
    assert data["accounts"]["input_account"] == books["acc"]["vat_in"]
    assert data["accounts"]["foreign_account"] == books["acc"]["payable"]
    assert data["can_edit_accounts"] is False
    bad_month = await client.get(
        f"{ACC}/vat", params={"year": books["year"], "month": 13}, headers=_headers(world["accountant"])
    )
    assert bad_month.status_code == 422


async def test_vat_registers_keep_reverse_charge_and_ignore_storno_pairs(client, world, books):
    """Przegląd K5a: FVZ z VAT należnym (import usług) daje wiersz sprzedaży
    bez pola JPK (problem) i nie zawyża nadwyżki; korekta zmieniająca stawkę
    zostaje w sumach; PK na koncie VAT ze stornem znika z „do sprawdzenia”."""

    from app.services.ledger import documents as ledger_documents
    from app.services.ledger.documents import DocumentSpec
    from app.services.ledger.engine import LineIn

    year, acc = books["year"], books["acc"]
    # Usługa bez VAT u sprzedawcy, VAT rozliczany przez nabywcę (ręczny dekret E2).
    imported = await _expense(world, number="IMP 1/03", net="1000.00", vat="0.00", gross="1000.00")
    decree = _decree(acc, net=100_000, vat=0, payable=books["supplier"].cost_account, text="Import usług")
    decree["manual"] = True
    decree["positions"] = [
        {"kind": "cost", "account": acc["cost"], "side": "debit", "amount": 100_000},
        {"kind": "vat", "account": acc["vat_in"], "side": "debit", "amount": 23_000},
        {"kind": "vat", "account": acc["vat_out"], "side": "credit", "amount": 23_000},
        {"kind": "counterparty", "account": books["supplier"].cost_account, "side": "credit", "amount": 100_000},
    ]
    await _ready(
        imported,
        received=datetime(year, 3, 16, 10, 0, tzinfo=timezone.utc),
        counterparty_id=books["supplier"].id,
        decree=decree,
    )
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(ClientSalesInvoice)
            .where(ClientSalesInvoice.id == books["sales"]["correction"])
            .values(
                items=[
                    {"net": "1000.00", "vat_rate": "23", "before_correction": True},
                    {"net": "1000.00", "vat_rate": "np II"},
                ]
            )
        )
        await db.commit()
    await _vat_books(client, world, books, keep_items=("correction",))
    expense = await _document("finance_cost_entry", imported)
    await _approve_ids(client, world, [expense.id])
    data = (await _vat_registers(client, world, books)).json()
    sales = {row["number"]: row for row in data["sales"]}
    # Korekta 23% → np II: bez podziału, ale z kwotami z dekretu.
    assert (sales["FK 1/03"]["net"], sales["FK 1/03"]["vat"], sales["FK 1/03"]["groups"]) == (-10_000, -2_300, [])
    # Import usług: VAT należny z dokumentu zakupu jako wiersz sprzedaży do przypisania.
    self_row = sales[expense.number]
    assert (self_row["net"], self_row["vat"], self_row["groups"]) == (100_000, 23_000, [])
    assert "odwrotne obciążenie" in self_row["problem"]
    purchase = next(row for row in data["purchases"] if row["number"] == expense.number)
    assert (purchase["net"], purchase["vat"]) == (100_000, 23_000)
    summary = data["summary"]
    # 23% z FS 1/03 (23 000) − korekta (2 300) + import usług (23 000).
    assert summary["output_vat"] == 23_000 - 2_300 + 23_000
    rates = next(issue for issue in data["issues"] if issue["kind"] == "rates")
    assert {item["number"] for item in rates["items"]} == {"FK 1/03", expense.number}
    async with AsyncSessionLocal() as db:
        manual = await ledger_documents.create_draft(
            db,
            DocumentSpec(
                doc_type="PK",
                op_date=date(year, 3, 28),
                doc_date=date(year, 3, 28),
                description="Pomyłka na koncie VAT",
                lines=[
                    LineIn("debit", acc["revenue"], 1_000, "x"),
                    LineIn("credit", acc["vat_out"], 1_000, "x"),
                ],
            ),
            actor_id=world["accountant"].id,
        )
        await db.commit()
    await _approve_ids(client, world, [manual.id])
    await _reverse(client, world, manual.id, date(year, 3, 29))
    data = (await _vat_registers(client, world, books)).json()
    assert [issue["kind"] for issue in data["issues"] if issue["kind"] == "outside"] == []


# ── JPK_V7M (K5b) ───────────────────────────────────────────────────────────


async def _payer(tax_office_code: str | None):
    """Dane płatnika K7a (kod urzędu skarbowego) — zwraca poprzednią wartość."""

    from app.services.hr.payroll_lists.parameters import COMPANY_KEY

    async with AsyncSessionLocal() as db:
        previous = await db.scalar(select(AppSetting.value).where(AppSetting.key == COMPANY_KEY))
        await db.execute(delete(AppSetting).where(AppSetting.key == COMPANY_KEY))
        if tax_office_code is not None:
            db.add(AppSetting(key=COMPANY_KEY, value={"tax_office_code": tax_office_code}))
        await db.commit()
    return previous


async def _restore_payer(previous) -> None:
    from app.services.hr.payroll_lists.parameters import COMPANY_KEY

    async with AsyncSessionLocal() as db:
        await db.execute(delete(AppSetting).where(AppSetting.key == COMPANY_KEY))
        if previous is not None:
            db.add(AppSetting(key=COMPANY_KEY, value=previous))
        await db.commit()


async def _purge_jpk(year: int) -> None:
    from app.models.ledger import LedgerVatFile

    async with AsyncSessionLocal() as db:
        await db.execute(delete(LedgerVatFile).where(LedgerVatFile.year == year))
        await db.commit()


async def _jpk(client, world, books, user: str = "accountant", month: int = 3, **body):
    return await client.post(
        f"{ACC}/vat/jpk",
        json={"year": books["year"], "month": month, **body},
        headers=_headers(world[user]),
    )


async def test_jpk_is_prepared_sent_and_corrected(client, world, books):
    from lxml import etree

    from app.services.ledger import jpk

    year = books["year"]
    previous = await _payer("0202")
    try:
        docs = await _vat_books(client, world, books)
        # Zaliczka i faktura nabywcy spoza kartoteki — poza marcem, żeby rejestr był pełny.
        async with AsyncSessionLocal() as db:
            await db.execute(
                update(ClientSalesInvoice)
                .where(ClientSalesInvoice.id.in_([books["sales"]["unknown"], books["sales"]["advance"]]))
                .values(issue_date=date(year, 5, 10), sale_date=date(year, 5, 10))
            )
            await db.commit()
        missing_email = await _jpk(client, world, books, opening_surplus=0)
        assert missing_email.status_code == 422 and "e-mail do JPK" in missing_email.json()["detail"]
        refused = await client.put(
            f"{ACC}/vat/jpk/settings", json={"email": "vat@example.com"}, headers=_headers(world["accountant"])
        )
        assert refused.status_code == 403
        bad = await client.put(
            f"{ACC}/vat/jpk/settings", json={"email": "bez-malpy"}, headers=_headers(world["admin"])
        )
        assert bad.status_code == 422
        saved = await client.put(
            f"{ACC}/vat/jpk/settings",
            json={"email": "vat@example.com", "phone": "+48 22 000 00 00"},
            headers=_headers(world["admin"]),
        )
        assert saved.status_code == 200 and saved.json()["email"] == "vat@example.com"
        # Pierwszy miesiąc w NEXUSIE: nadwyżka z deklaracji z Symfonii wpisana ręcznie.
        no_surplus = await _jpk(client, world, books)
        assert no_surplus.status_code == 422 and "P_62" in no_surplus.json()["detail"]
        # D2: plik ma faktury osób zespołu — bez Płac ani przygotowanie, ani pobranie.
        settings = _ledger_settings(world, books, allocation=False)
        settings["modules"]["vat"] = True
        settings["vat"] = {"input_account": books["acc"]["vat_in"]}
        settings["jpk"] = {"email": "vat@example.com", "phone": "+48 22 000 00 00"}
        settings["accountants"] = [world["accountant"].id, world["module_only"].id]
        await _set_ledger(settings)
        outsider = await _jpk(client, world, books, user="module_only", opening_surplus=0)
        assert outsider.status_code == 403
        first = await _jpk(client, world, books, opening_surplus=120)
        assert first.status_code == 201, first.text
        v1 = first.json()["file"]
        assert (v1["version"], v1["purpose"], v1["status"]) == (1, "submission", "prepared")
        # Należny: 23% z FS 1/03 (230 zł) − korekta (23 zł); naliczony 230 + 2 300 zł.
        assert (v1["totals"]["P_38"], v1["totals"]["P_39"], v1["totals"]["P_48"]) == (207, 120, 2_650)
        assert v1["totals"]["P_62"] == 2_650 - 207
        download = await client.get(f"{ACC}/vat/jpk/{v1['id']}/file", headers=_headers(world["accountant"]))
        assert download.status_code == 200 and "JPK_V7M_" in download.headers["content-disposition"]
        assert jpk.validate(download.content) == []
        root = etree.fromstring(download.content)
        assert len(root.findall(f".//{{{jpk.NS}}}ZakupWiersz")) == 2
        hidden = await client.get(f"{ACC}/vat/jpk/{v1['id']}/file", headers=_headers(world["module_only"]))
        assert hidden.status_code == 403
        blind = (
            await client.get(
                f"{ACC}/vat/jpk", params={"year": year, "month": 3}, headers=_headers(world["module_only"])
            )
        ).json()
        assert "totals" not in blind["files"][0] and blind["previous_surplus"] is None
        second = await _jpk(client, world, books)
        assert second.status_code == 201 and second.json()["file"]["purpose"] == "submission"
        v2 = second.json()["file"]
        sent = await client.post(
            f"{ACC}/vat/jpk/{v2['id']}/sent", json={"note": "UPO 0000000000000000"}, headers=_headers(world["accountant"])
        )
        assert sent.status_code == 200 and sent.json()["status"] == "sent"
        # Wysłano v2 — v1 jest unieważniona i jej się już nie oznacza.
        stale = await client.post(f"{ACC}/vat/jpk/{v1['id']}/sent", json={}, headers=_headers(world["accountant"]))
        assert stale.status_code == 409
        item = next(i for i in (await _closing(client, world, books))["items"] if i["key"] == "jpk")
        assert item["state"] == "ok" and "UPO" in item["detail"]
        # Po wysłanej wersji kolejna to korekta z uzasadnieniem.
        no_reason = await _jpk(client, world, books)
        assert no_reason.status_code == 422 and "P_ORDZU" in no_reason.json()["detail"]
        third = await _jpk(client, world, books, reason="Korekta po zmianie dekretu faktury.")
        assert third.status_code == 201, third.text
        v3 = third.json()["file"]
        assert (v3["version"], v3["purpose"], v3["reason"]) == (3, "correction", "Korekta po zmianie dekretu faktury.")
        content = (await client.get(f"{ACC}/vat/jpk/{v3['id']}/file", headers=_headers(world["accountant"]))).content
        root = etree.fromstring(content)
        assert root.findtext(f"{{{jpk.NS}}}Naglowek/{{{jpk.NS}}}CelZlozenia") == "2"
        await client.post(f"{ACC}/vat/jpk/{v3['id']}/sent", json={}, headers=_headers(world["accountant"]))
        # Zmiana rejestru po wysłaniu (storno FVS) = lista zamknięcia: problem.
        await _reverse(client, world, docs["plain"].id, date(year, 3, 31))
        item = next(i for i in (await _closing(client, world, books))["items"] if i["key"] == "jpk")
        assert item["state"] == "problem" and "korektę" in item["detail"]
        # Kwiecień bierze P_39 z P_62 marca (ostatnia wysłana wersja).
        april = await _jpk(client, world, books, month=4)
        assert april.status_code == 201, april.text
        assert april.json()["file"]["totals"]["P_39"] == v3["totals"]["P_62"]
    finally:
        await _purge_jpk(year)
        await _restore_payer(previous)


async def _jpk_ready(client, world, books) -> dict:
    """Marzec z pełnym rejestrem (bez zaliczki i nabywcy spoza kartoteki),
    moduł VAT z kontaktem do JPK."""

    year = books["year"]
    docs = await _vat_books(client, world, books)
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(ClientSalesInvoice)
            .where(ClientSalesInvoice.id.in_([books["sales"]["unknown"], books["sales"]["advance"]]))
            .values(issue_date=date(year, 5, 10), sale_date=date(year, 5, 10))
        )
        await db.commit()
    settings = _ledger_settings(world, books, allocation=False)
    settings["modules"]["vat"] = True
    settings["vat"] = {"input_account": books["acc"]["vat_in"]}
    settings["jpk"] = {"email": "vat@example.com", "phone": ""}
    await _set_ledger(settings)
    return docs


async def _jpk_sent(client, world, file_id: int, note: str = "UPO 1"):
    return await client.post(f"{ACC}/vat/jpk/{file_id}/sent", json={"note": note}, headers=_headers(world["accountant"]))


async def _jpk_item(client, world, books, month: int) -> dict:
    response = await client.get(
        f"{ACC}/closing", params={"year": books["year"], "month": month}, headers=_headers(world["accountant"])
    )
    return next(item for item in response.json()["items"] if item["key"] == "jpk")


async def test_jpk_chain_correction_flags_the_next_month(client, world, books):
    """Korekta marca zmienia P_62, więc wysłany kwiecień (P_39) wymaga korekty
    (przegląd K5b)."""

    year = books["year"]
    previous = await _payer("0202")
    try:
        docs = await _jpk_ready(client, world, books)
        march = (await _jpk(client, world, books, opening_surplus=0)).json()["file"]
        assert (await _jpk_sent(client, world, march["id"])).status_code == 200
        april = (await _jpk(client, world, books, month=4)).json()["file"]
        assert april["totals"]["P_39"] == march["totals"]["P_62"]
        assert (await _jpk_sent(client, world, april["id"])).status_code == 200
        assert (await _jpk_item(client, world, books, 4))["state"] == "ok"
        await _reverse(client, world, docs["expense"].id, date(year, 3, 30))
        fixed = await _jpk(client, world, books, reason="Korekta po stornie FVZ.")
        assert fixed.status_code == 201, fixed.text
        assert fixed.json()["file"]["totals"]["P_62"] != march["totals"]["P_62"]
        assert (await _jpk_sent(client, world, fixed.json()["file"]["id"])).status_code == 200
        item = await _jpk_item(client, world, books, 4)
        assert item["state"] == "problem" and "P_39" in item["detail"]
        overview = (
            await client.get(f"{ACC}/vat/jpk", params={"year": year, "month": 4}, headers=_headers(world["accountant"]))
        ).json()
        assert overview["stale"] == "surplus"
    finally:
        await _purge_jpk(year)
        await _restore_payer(previous)


async def test_jpk_filed_older_version_can_be_recorded(client, world, books):
    """Wysłana bramką MF wersja 1, a ktoś przygotował wersję 2: NEXUS zapisuje
    wysłanie v1, a v2 jest unieważniona (przegląd K5b)."""

    year = books["year"]
    previous = await _payer("0202")
    try:
        docs = await _jpk_ready(client, world, books)
        v1 = (await _jpk(client, world, books, opening_surplus=0)).json()["file"]
        await _reverse(client, world, docs["expense"].id, date(year, 3, 30))
        v2 = (await _jpk(client, world, books)).json()["file"]
        filed = await _jpk_sent(client, world, v1["id"], "UPO v1")
        assert filed.status_code == 200, filed.text
        files = (
            await client.get(f"{ACC}/vat/jpk", params={"year": year, "month": 3}, headers=_headers(world["accountant"]))
        ).json()["files"]
        assert [(f["version"], f["status"]) for f in files] == [(1, "sent"), (2, "void")]
        assert (await _jpk_sent(client, world, v2["id"])).status_code == 409
        # Rejestr zmienił się po wysłaniu v1 (storno FVZ) — trzeba korekty.
        assert (await _jpk_item(client, world, books, 3))["state"] == "problem"
        april = (await _jpk(client, world, books, month=4)).json()["file"]
        assert april["totals"]["P_39"] == v1["totals"]["P_62"]
    finally:
        await _purge_jpk(year)
        await _restore_payer(previous)


async def test_jpk_mark_sent_waits_for_prepare(client, world, books, monkeypatch):
    """„Wysłany” bierze tę samą blokadę co „Przygotuj JPK” — nowa wersja nie
    powstaje jako drugie złożenie (przegląd K5b)."""

    import asyncio

    from app.services.ledger import jpk
    from app.services.ledger.documents import Viewer

    year = books["year"]
    previous = await _payer("0202")
    try:
        await _jpk_ready(client, world, books)
        v1 = (await _jpk(client, world, books, opening_surplus=0)).json()["file"]
        entered, release = asyncio.Event(), asyncio.Event()
        original = jpk.previous_surplus

        async def slow(db, y, m):
            entered.set()
            await release.wait()
            return await original(db, y, m)

        monkeypatch.setattr(jpk, "previous_surplus", slow)
        viewer = Viewer(user_id=world["accountant"].id, admin=False, payroll=True, approver=True)

        async def preparer():
            async with AsyncSessionLocal() as db:
                current = await ledger_settings.load(db)
                out = await jpk.prepare(
                    db, viewer, current, year=year, month=3, reason=None, opening_surplus=None,
                    now=datetime.now(timezone.utc),
                )
                await db.commit()
                return out

        async def marker():
            await entered.wait()
            task = asyncio.create_task(_jpk_sent(client, world, v1["id"]))
            await asyncio.sleep(0.5)
            release.set()
            return await task

        prepared, marked = await asyncio.gather(preparer(), marker())
        monkeypatch.setattr(jpk, "previous_surplus", original)
        assert marked.status_code == 200, marked.text
        files = (
            await client.get(f"{ACC}/vat/jpk", params={"year": year, "month": 3}, headers=_headers(world["accountant"]))
        ).json()["files"]
        assert [(f["version"], f["status"]) for f in files] == [(1, "sent"), (2, "void")]
        assert (await _jpk_sent(client, world, prepared["file"]["id"])).status_code == 409
    finally:
        await _purge_jpk(year)
        await _restore_payer(previous)


async def test_jpk_first_month_surplus_can_be_fixed(client, world, books):
    """Literówka w nadwyżce z Symfonii nie zostaje w korektach; przy JPK za
    poprzedni miesiąc w NEXUSIE P_39 nie wpisuje się ręcznie (przegląd K5b)."""

    year = books["year"]
    previous = await _payer("0202")
    try:
        await _jpk_ready(client, world, books)
        v1 = (await _jpk(client, world, books, opening_surplus=120)).json()["file"]
        assert v1["totals"]["P_39"] == 120
        v2 = (await _jpk(client, world, books, opening_surplus=100)).json()["file"]
        assert v2["totals"]["P_39"] == 100
        overview = (
            await client.get(f"{ACC}/vat/jpk", params={"year": year, "month": 3}, headers=_headers(world["accountant"]))
        ).json()
        assert (overview["surplus_editable"], overview["surplus_value"]) == (True, 100)
        april = await _jpk(client, world, books, month=4, opening_surplus=5)
        assert april.status_code == 422 and "P_62" in april.json()["detail"]
    finally:
        await _purge_jpk(year)
        await _restore_payer(previous)


# ── Zakup zagraniczny i znaczniki GTU/TP (K5b-2) ────────────────────────────


async def _foreign_setup(world, books, *, parent: bool = True, allocation: bool = False) -> str:
    """Moduł VAT; ``parent`` — konto dostawców zagranicznych ze słownikiem."""

    number = f"{books['acc']['cost'].rsplit('-', 1)[0]}-202"
    async with AsyncSessionLocal() as db:
        if not await db.scalar(select(FinanceAccount.id).where(FinanceAccount.number == number)):
            db.add(
                FinanceAccount(
                    number=number,
                    name="Dostawcy zagraniczni",
                    kind="settlement",
                    dictionary="counterparty",
                )
            )
            await db.commit()
    settings = _ledger_settings(world, books, allocation=allocation)
    settings["modules"]["vat"] = True
    settings["vat"] = {"input_account": books["acc"]["vat_in"]}
    if parent:
        settings["vat"]["foreign_account"] = number
    await _set_ledger(settings)
    return number


def _foreign_body(books, **extra) -> dict:
    year = books["year"]
    body = {
        "number": "INV-0042",
        "issue_date": f"{year}-03-21",
        "service_date": f"{year}-03-20",
        "currency": "EUR",
        "net": "100.00",
        "vat_rate": "23",
        "deduction": "full",
        "cost_account": books["acc"]["cost"],
    }
    body.update(extra)
    return body


async def _foreign(client, world, body: dict, user: str = "accountant"):
    return await client.post(f"{ACC}/vat/foreign", json=body, headers=_headers(world[user]))


async def _foreign_overview(client, world, books, user: str = "accountant") -> dict:
    response = await client.get(
        f"{ACC}/vat/foreign",
        params={"year": books["year"], "month": 3},
        headers=_headers(world[user]),
    )
    assert response.status_code == 200, response.text
    return response.json()


def _test_company():
    from app.services.hr.payroll_lists.parameters import Company

    return Company(
        nip="1234567890",
        name="Spółka Testowa sp. z o.o.",
        short_name="Testowa",
        regon=None,
        tax_office_code="0202",
        zus_account=None,
        tax_account=None,
    )


def _jpk_file(registers: dict) -> bytes:
    from app.services.ledger import jpk

    content, _ = jpk.build(
        registers,
        company=_test_company(),
        email="ksiegowosc@example.com",
        phone="",
        purpose="submission",
        reason=None,
        surplus=0,
        # DataWytworzeniaJPK w XSD: najwyżej 2050 — chwila prawdziwa, rok testu dowolny.
        now=datetime.now(timezone.utc),
    )
    return content


async def test_foreign_purchase_books_import_of_services_into_both_registers(
    client, world, books, monkeypatch
):
    """Faktura dostawcy z UE (EUR, odliczenie) i spoza UE (PLN, bez odliczenia):
    dostawca do kartoteki z kontem pod kontem z ustawień, FVZ w buforze po
    kursie NBP, rejestr sprzedaży K_29/K_30 i K_27/K_28, rejestr zakupu."""

    from app.services.finance_ledger import counterparties as kartoteka
    from app.services.finance_ledger import counterparty_import as importer
    from app.services.ledger import jpk

    year, acc = books["year"], books["acc"]
    # Lata testów są w przyszłości — „dziś” formularza = koniec roku testu.
    monkeypatch.setattr(ledger_vat_api, "business_today", lambda: date(year, 12, 31))
    parent = await _foreign_setup(world, books)
    tag = parent.split("-")[0]
    vat_no = f"IE{random.randint(1_000_000, 9_999_999)}T"
    overview = await _foreign_overview(client, world, books)
    assert overview["items"] == [] and overview["next_account"] == f"{parent}-1"
    assert "EUR" in overview["currencies"] and overview["missing"] == []
    assert books["supplier"].id not in {item["id"] for item in overview["suppliers"]}

    supplier_form = {"name": f"Dostawca SaaS {tag}", "country": "ie", "tax_id": vat_no[2:]}
    created = await _foreign(client, world, _foreign_body(books, new_supplier=supplier_form))
    assert created.status_code == 201, created.text
    data = created.json()
    supplier = data["supplier"]
    books["extra_parties"].append(supplier["id"])
    assert (
        supplier["tax_id"],
        supplier["country"],
        supplier["account"],
        supplier["group"],
        supplier["from_form"],
    ) == (vat_no, "IE", f"{parent}-1", "imp_28b", True)
    doc = data["document"]
    # 100 EUR po 4,30 (kurs z dnia roboczego przed 20.03) = 430 zł, VAT 23% = 98,90 zł.
    assert (doc["status"], doc["net"], doc["vat"], doc["group"], doc["rate_day"]) == (
        "draft",
        43_000,
        9_890,
        "imp_28b",
        books["rate_date"].isoformat(),
    )
    assert await _lines(doc["id"]) == [
        ("debit", acc["cost"], 43_000),
        ("debit", acc["vat_in"], 9_890),
        ("credit", acc["vat_out"], 9_890),
        ("credit", f"{parent}-1", 43_000),
    ]
    async with AsyncSessionLocal() as db:
        line = await db.scalar(
            select(LedgerLine).where(
                LedgerLine.document_id == doc["id"], LedgerLine.account == f"{parent}-1"
            )
        )
        assert (line.counterparty_id, line.currency, line.amount_cur) == (supplier["id"], "EUR", 10_000)

    # Ta sama faktura drugi raz (inna wielkość liter i spacje) i bliźniak dostawcy.
    again = await _foreign(
        client, world, _foreign_body(books, supplier_id=supplier["id"], number=" inv-0042 ")
    )
    assert again.status_code == 409 and "jest już w księdze" in again.json()["detail"]
    twin = await _foreign(
        client,
        world,
        _foreign_body(
            books,
            number="INV-0043",
            new_supplier={**supplier_form, "name": f"DOSTAWCA saas {tag}", "tax_id": "IE1111111T"},
        ),
    )
    assert twin.status_code == 409 and "jest już kontrahent" in twin.json()["detail"]
    polish = await _foreign(client, world, _foreign_body(books, supplier_id=books["supplier"].id))
    assert polish.status_code == 422 and "z Polski" in polish.json()["detail"]
    both = await _foreign(
        client,
        world,
        _foreign_body(books, supplier_id=supplier["id"], new_supplier=supplier_form),
    )
    assert both.status_code == 422
    outside = await _foreign(
        client,
        world,
        _foreign_body(
            books,
            number="INV-0044",
            new_supplier={"name": f"Inny {tag}", "country": "DE", "tax_id": "DE123456789", "account": acc["cost"]},
        ),
    )
    assert outside.status_code == 422 and "analityka konta" in outside.json()["detail"]
    future = await _foreign(
        client, world, _foreign_body(books, supplier_id=supplier["id"], number="INV-9", service_date=f"{year + 1}-01-02")
    )
    assert future.status_code == 422 and "przyszłości" in future.json()["detail"]

    # Spoza UE: bez kursu USD odmowa (nic nie zostaje), w PLN bez odliczenia.
    american = {
        "name": f"Vendor Inc {tag}",
        "country": "US",
        "tax_id": f"{random.randint(10, 99)}-{random.randint(1_000_000, 9_999_999)}",
    }
    no_rate = await _foreign(
        client, world, _foreign_body(books, number="US-77", currency="USD", net="500", new_supplier=american)
    )
    assert no_rate.status_code == 422 and "Brak kursu NBP USD" in no_rate.json()["detail"]
    pln = await _foreign(
        client,
        world,
        _foreign_body(books, number="US-77", currency="PLN", net="500.00", deduction="none", new_supplier=american),
    )
    assert pln.status_code == 201, pln.text
    us = pln.json()
    books["extra_parties"].append(us["supplier"]["id"])
    assert (us["supplier"]["account"], us["supplier"]["group"]) == (f"{parent}-2", "imp_other")
    assert await _lines(us["document"]["id"]) == [
        ("debit", acc["cost"], 61_500),
        ("credit", acc["vat_out"], 11_500),
        ("credit", f"{parent}-2", 50_000),
    ]

    # Bufor blokuje JPK; po zatwierdzeniu — oba rejestry i plik zgodny z XSD MF.
    drafts = (await _vat_registers(client, world, books)).json()
    assert {item["number"] for item in next(i for i in drafts["issues"] if i["kind"] == "drafts")["items"]} >= {"INV-0042", "US-77"}
    await _approve_ids(client, world, [doc["id"], us["document"]["id"]])
    registers = (await _vat_registers(client, world, books)).json()
    sales = {row["number"]: row for row in registers["sales"]}
    imported = sales["INV-0042"]
    assert [(g["key"], g["net"], g["vat"]) for g in imported["groups"]] == [("imp_28b", 43_000, 9_890)]
    assert (imported["tax_id"], imported["country"], imported["date"], imported["problem"], imported["markers"]) == (
        vat_no,
        "IE",
        f"{year}-03-20",
        None,
        [],
    )
    assert [(g["key"], g["net"], g["vat"]) for g in sales["US-77"]["groups"]] == [("imp_other", 50_000, 11_500)]
    purchases = {row["number"]: row for row in registers["purchases"]}
    # Bez odliczenia nie ma wiersza zakupu; data wiersza zakupu = data faktury.
    assert set(purchases) == {"INV-0042"} and purchases["INV-0042"]["date"] == f"{year}-03-21"
    assert [(g["key"], g["vat"]) for g in purchases["INV-0042"]["groups"]] == [("other", 9_890)]
    assert not any(issue["kind"] in ("rates", "drafts", "outside") for issue in registers["issues"])
    groups = {g["key"]: (g["net"], g["vat"]) for g in registers["summary"]["groups"]}
    assert (groups["imp_28b"], groups["imp_other"], groups["other"]) == (
        (43_000, 9_890),
        (50_000, 11_500),
        (43_000, 9_890),
    )
    assert jpk.validate(_jpk_file(registers)) == []
    listed = await _foreign_overview(client, world, books)
    assert [(item["number"], item["status"]) for item in listed["items"]] == [
        ("INV-0042", "approved"),
        ("US-77", "approved"),
    ]
    assert listed["next_account"] == f"{parent}-3"

    # Import kartoteki z eBI24 nie dubluje dostawcy z formularza (inny numer).
    parsed = importer.ParsedFile(
        rows=[
            importer.ParsedRow(
                line=2,
                id_type="other",
                id_value=f"X{random.randint(10**6, 10**7)}",
                values={"name": f"DOSTAWCA SAAS {tag}"},
            ),
            # Ta sama nazwa z polskim NIP-em to inna firma (np. oddział) — wchodzi.
            importer.ParsedRow(
                line=3,
                id_type="nip",
                id_value=str(random.randint(10**9, 10**10 - 1)),
                values={"name": f"Dostawca SaaS {tag}"},
            ),
        ]
    )
    async with AsyncSessionLocal() as db:
        result = await kartoteka.apply_import(
            db, parsed, save=False, actor_id=world["admin"].id, now=datetime.now(timezone.utc)
        )
    assert result.created == 1 and [error["line"] for error in result.errors] == [2]
    assert "formularza zakupu zagranicznego" in result.errors[0]["message"]


async def test_foreign_purchase_needs_the_suppliers_account_setting(
    client, world, books, monkeypatch
):
    year = books["year"]
    monkeypatch.setattr(ledger_vat_api, "business_today", lambda: date(year, 12, 31))
    await _foreign_setup(world, books, parent=False)
    overview = await _foreign_overview(client, world, books)
    assert overview["next_account"] is None and overview["missing"]
    refused = await _foreign(
        client,
        world,
        _foreign_body(books, new_supplier={"name": "Dostawca Bez Konta", "country": "IE", "tax_id": "IE7654321T"}),
    )
    assert refused.status_code == 422 and "Ustaw konto rozrachunków" in refused.json()["detail"]
    async with AsyncSessionLocal() as db:
        assert await db.scalar(
            select(FinanceCounterparty.id).where(FinanceCounterparty.name == "Dostawca Bez Konta")
        ) is None


async def test_late_foreign_invoice_stays_in_the_service_month_and_flags_its_jpk(
    client, world, books, monkeypatch
):
    """Faktura importu usług otrzymana pół roku po usłudze: VAT należny
    i naliczony w miesiącu usługi (art. 86 ust. 10b pkt 3 — bez terminu
    3 miesięcy od 7.09.2021), data otrzymania = DataWplywu, wysłany JPK
    marca staje się „do korekty”."""

    from lxml import etree

    from app.services.ledger import jpk

    year = books["year"]
    monkeypatch.setattr(ledger_vat_api, "business_today", lambda: date(year, 12, 31))
    previous = await _payer("0202")
    try:
        parent = await _foreign_setup(world, books)
        await _jpk_ready(client, world, books)
        settings = _ledger_settings(world, books, allocation=False)
        settings["modules"]["vat"] = True
        settings["vat"] = {"input_account": books["acc"]["vat_in"], "foreign_account": parent}
        settings["jpk"] = {"email": "vat@example.com", "phone": ""}
        await _set_ledger(settings)
        march = await _jpk(client, world, books, opening_surplus=0)
        assert march.status_code == 201, march.text
        assert (await _jpk_sent(client, world, march.json()["file"]["id"])).status_code == 200
        assert (await _jpk_item(client, world, books, 3))["state"] == "ok"
        assert f"{year}-03" in (await _foreign_overview(client, world, books))["jpk_sent"]

        supplier = {
            "name": f"Dostawca Spozniony {parent.split('-')[0]}",
            "country": "IE",
            "tax_id": f"{random.randint(1_000_000, 9_999_999)}T",
        }
        early = await _foreign(
            client, world, _foreign_body(books, new_supplier=supplier, received_date=f"{year}-03-20")
        )
        assert early.status_code == 422 and "wcześniejsza niż data wystawienia" in early.json()["detail"]
        created = await _foreign(
            client, world, _foreign_body(books, new_supplier=supplier, received_date=f"{year}-09-14")
        )
        assert created.status_code == 201, created.text
        books["extra_parties"].append(created.json()["supplier"]["id"])
        doc = created.json()["document"]
        assert (doc["service_date"], doc["received_date"]) == (f"{year}-03-20", f"{year}-09-14")
        await _approve_ids(client, world, [doc["id"]])

        registers = (await _vat_registers(client, world, books)).json()
        sale = next(row for row in registers["sales"] if row["number"] == "INV-0042")
        bought = next(row for row in registers["purchases"] if row["number"] == "INV-0042")
        assert (sale["date"], [g["key"] for g in sale["groups"]]) == (f"{year}-03-20", ["imp_28b"])
        assert (bought["date"], bought["issue_date"], bought["vat"]) == (f"{year}-09-14", f"{year}-03-21", 9_890)
        content = _jpk_file(registers)
        assert jpk.validate(content) == []
        rows = [
            node
            for node in etree.fromstring(content).iter("{*}ZakupWiersz")
            if node.findtext("{*}DowodZakupu") == "INV-0042"
        ]
        assert [(n.findtext("{*}DataZakupu"), n.findtext("{*}DataWplywu")) for n in rows] == [
            (f"{year}-03-21", f"{year}-09-14")
        ]
        # Wrzesień (miesiąc otrzymania) bez tej faktury — ani należny, ani naliczony.
        september = (await _vat_registers(client, world, books, month=9)).json()
        assert "INV-0042" not in {row["number"] for row in september["sales"] + september["purchases"]}
        assert (await _jpk_item(client, world, books, 3))["state"] == "problem"
        overview = (
            await client.get(f"{ACC}/vat/jpk", params={"year": year, "month": 3}, headers=_headers(world["accountant"]))
        ).json()
        assert overview["stale"] == "registers"
    finally:
        await _purge_jpk(year)
        await _restore_payer(previous)


async def test_vat_markers_go_on_the_buyers_sales_invoices(client, world, books):
    """GTU/TP per kontrahent (decyzja 15.11): na każdej FVS kontrahenta, w pliku
    JPK zgodnym z XSD; zmiana znaczników = inny odcisk rejestru (korekta)."""

    from app.services.ledger import jpk

    await _vat_books(client, world, books)
    buyer = books["buyer"].id
    url = f"{ACC}/vat/markers/{buyer}"
    refused = await client.put(url, json={"markers": ["GTU_12"]}, headers=_headers(world["module_only"]))
    assert refused.status_code == 403
    unknown = await client.put(url, json={"markers": ["GTU_99"]}, headers=_headers(world["accountant"]))
    assert unknown.status_code == 422
    missing = await client.put(
        f"{ACC}/vat/markers/{2**31 - 1}", json={"markers": ["TP"]}, headers=_headers(world["accountant"])
    )
    assert missing.status_code == 404
    # Poza zakresem INTEGER kartoteki = 422, nie 500 z bazy.
    beyond = await client.put(
        f"{ACC}/vat/markers/{2**40}", json={"markers": ["TP"]}, headers=_headers(world["accountant"])
    )
    assert beyond.status_code == 422
    saved = await client.put(url, json={"markers": ["TP", "GTU_12"]}, headers=_headers(world["accountant"]))
    assert saved.status_code == 200, saved.text
    assert (saved.json()["counterparty_id"], saved.json()["markers"]) == (buyer, ["GTU_12", "TP"])
    listed = (await client.get(f"{ACC}/vat/markers", headers=_headers(world["module_only"]))).json()
    assert [item["counterparty_id"] for item in listed["items"]] == [buyer]
    assert listed["can_edit"] is False and len(listed["labels"]) == 14

    registers = (await _vat_registers(client, world, books)).json()
    assert {row["number"]: row["markers"] for row in registers["sales"]} == {
        "FS 1/03": ["GTU_12", "TP"],
        "FS 2/03": ["GTU_12", "TP"],
        "FK 1/03": ["GTU_12", "TP"],
    }
    assert all(row["markers"] == [] for row in registers["purchases"])
    assert jpk.validate(_jpk_file(registers)) == []
    marked = jpk.fingerprint(registers)

    cleared = await client.put(url, json={"markers": []}, headers=_headers(world["accountant"]))
    assert cleared.status_code == 200 and cleared.json()["markers"] == []
    assert (await client.get(f"{ACC}/vat/markers", headers=_headers(world["accountant"]))).json()["items"] == []
    plain = (await _vat_registers(client, world, books)).json()
    assert jpk.fingerprint(plain) != marked


async def test_foreign_purchase_cost_goes_to_overhead_in_the_allocation(
    client, world, books, monkeypatch
):
    """Przegląd K5b-2: koszt FVZ z formularza wchodzi do rozliczenia na „5”
    (koszty ogólne — faktura bez klienta i pionu), a szkic czeka jak FVZ
    z kolejki kosztów — inaczej konta „4” rozjeżdżały się z 490."""

    year = books["year"]
    monkeypatch.setattr(ledger_vat_api, "business_today", lambda: date(year, 12, 31))
    parent = await _foreign_setup(world, books, allocation=True)
    tag = parent.split("-")[0]
    created = await _foreign(
        client,
        world,
        _foreign_body(
            books,
            new_supplier={
                "name": f"Dostawca Koszt {tag}",
                "country": "IE",
                "tax_id": f"IE{random.randint(1_000_000, 9_999_999)}K",
            },
        ),
    )
    assert created.status_code == 201, created.text
    books["extra_parties"].append(created.json()["supplier"]["id"])
    waiting = (await _summary(client, world, books))["allocation"]
    assert waiting["pending_costs"] == 1
    await _approve_ids(client, world, [created.json()["document"]["id"]])
    alloc = (await _summary(client, world, books))["allocation"]
    assert alloc["pending_costs"] == 0
    assert {(d["code"], d["amount"]) for d in alloc["details"]} == {("OG", 43_000)}


# ── VAT-UE(5) (K5b-3a) ──────────────────────────────────────────────────────


async def test_vat_ue_lines_come_from_the_sales_register(client, world, books):
    """Usługa np II dla nabywcy z polskim NIP-em = problem; z numerem VAT UE na
    fakturze = pozycja VAT-UE w pełnych złotych; niepełny rejestr blokuje plik."""

    await _vat_books(client, world, books)
    params = {"year": books["year"], "month": 3}
    headers = _headers(world["accountant"])
    first = (await client.get(f"{ACC}/vat/ue", params=params, headers=headers)).json()
    assert first["lines"] == [] and first["can_download"] is False
    assert [item["number"] for item in first["problems"]] == ["FS 2/03"]
    assert "bez numeru VAT UE" in first["problems"][0]["detail"]
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(ClientSalesInvoice)
            .where(ClientSalesInvoice.id == books["sales"]["euro"])
            .values(buyer_nip=None, buyer_foreign_id="FI28583949")
        )
        await db.commit()
    data = (await client.get(f"{ACC}/vat/ue", params=params, headers=headers)).json()
    assert [(line["section"], line["country"], line["number"], line["amount"], line["documents"]) for line in data["lines"]] == [
        ("services", "FI", "28583949", 2150, ["FS 2/03"])
    ]
    assert data["problems"] == [] and data["totals"]["services"] == 2150
    # Faktury z KSeF bez dokumentu w księdze (fixture) blokują plik jak JPK.
    assert any("bez dokumentu w księdze" in item for item in data["blockers"])
    refused = await client.get(f"{ACC}/vat/ue/file", params=params, headers=headers)
    assert refused.status_code == 422 and "VAT-UE nie powstanie" in refused.json()["detail"]
    closed = await client.get(
        f"{ACC}/vat/ue", params={"year": books["year"], "month": 13}, headers=headers
    )
    assert closed.status_code == 422


# ── Porównanie z JPK z Symfonii (K5b-3b) ────────────────────────────────────


async def test_jpk_compare_with_symfonia_file(client, world, books):
    """Plik „z Symfonii” = JPK z tych samych rejestrów: zero różnic; zmieniona
    kwota wychodzi w wierszu; bez Płac — 403; plik za inny miesiąc — 422."""

    from app.services.ledger import jpk

    await _vat_books(client, world, books)
    registers = (await _vat_registers(client, world, books)).json()
    # Rejestry pełne (D2) dla porównania: księgowa w fixture ma Płace.
    content, _ = jpk.build(
        registers,
        company=_test_company(),
        email="ksiegowosc@example.com",
        phone="",
        purpose="submission",
        reason=None,
        surplus=0,
        now=datetime.now(timezone.utc),
    )
    url = f"{ACC}/vat/jpk/compare"
    params = {"year": books["year"], "month": 3}

    async def send(body: bytes, user: str = "accountant", **extra):
        return await client.post(
            url,
            params={**params, **extra},
            files={"file": ("jpk.xml", body, "application/xml")},
            headers=_headers(world[user]),
        )

    same = await send(content)
    assert same.status_code == 200, same.text
    assert same.json()["differences"] == 0
    changed = await send(content.replace(b"<K_20>230.00</K_20>", b"<K_20>231.00</K_20>", 1))
    sales = changed.json()["rows"][0]
    assert [item["number"] for item in sales["different"]] == ["FS 1/03"]
    other_month = await send(content, month=4)
    assert other_month.status_code == 422 and "za 03." in other_month.json()["detail"]
    blind = await send(content, user="module_only")
    assert blind.status_code == 403 and "Płacami" in blind.json()["detail"]


# ── Rozliczenie VAT (K5b-3c) ────────────────────────────────────────────────


async def _settlement(client, world, books, user: str = "accountant", month: int = 3) -> dict:
    response = await client.get(
        f"{ACC}/vat/settlement",
        params={"year": books["year"], "month": month},
        headers=_headers(world[user]),
    )
    assert response.status_code == 200, response.text
    return response.json()


async def _prepare_settlement(client, world, books, user: str = "accountant", month: int = 3):
    return await client.post(
        f"{ACC}/vat/settlement",
        json={"year": books["year"], "month": month},
        headers=_headers(world[user]),
    )


async def _settlement_item(client, world, books) -> dict:
    items = (await _closing(client, world, books))["items"]
    return next(item for item in items if item["key"] == "vat_settlement")


async def _vat_balances(books) -> tuple[int, int, int]:
    """Saldo Wn − Ma kont 222, 221 i „VAT do zapłaty” po zatwierdzonych dokumentach marca."""

    acc, year = books["acc"], books["year"]
    sign = case((LedgerLine.side == "debit", 1), else_=-1)
    async with AsyncSessionLocal() as db:
        rows = dict(
            (
                await db.execute(
                    select(LedgerLine.account, func.sum(sign * LedgerLine.amount))
                    .join(LedgerDocument, LedgerDocument.id == LedgerLine.document_id)
                    .where(
                        LedgerDocument.status == "approved",
                        LedgerDocument.op_date.between(date(year, 3, 1), date(year, 3, 31)),
                        LedgerLine.account.in_([acc["vat_out"], acc["vat_in"], acc["vat_due"]]),
                    )
                    .group_by(LedgerLine.account)
                )
            ).all()
        )
    return tuple(int(rows.get(acc[key], 0)) for key in ("vat_out", "vat_in", "vat_due"))


async def test_vat_settlement_moves_month_vat_to_the_tax_account(client, world, books):
    from app.services.ledger.engine import LineIn

    year, acc = books["year"], books["acc"]
    previous = await _payer("0202")
    try:
        docs = await _jpk_ready(client, world, books)
        settings = _ledger_settings(world, books, allocation=False)
        settings["modules"]["vat"] = True
        settings["vat"] = {"input_account": acc["vat_in"]}
        settings["jpk"] = {"email": "vat@example.com", "phone": ""}
        settings["accountants"] = [world["accountant"].id, world["module_only"].id]
        await _set_ledger(settings)

        # Bez kont: dokument nie powstaje, lista zamknięcia mówi, czego brakuje.
        blocked = await _settlement(client, world, books)
        assert "VAT do zapłaty" in blocked["blocker"] and "zaokrągleń" in blocked["blocker"]
        item = await _settlement_item(client, world, books)
        assert item["state"] == "todo" and "brakuje kont" in item["detail"]
        refused = await client.put(
            f"{ACC}/vat/settings",
            json={"rounding_gain_account": acc["other_income"]},
            headers=_headers(world["accountant"]),
        )
        assert refused.status_code == 403
        unknown = await client.put(
            f"{ACC}/vat/settings",
            json={"rounding_gain_account": "999-999"},
            headers=_headers(world["admin"]),
        )
        assert unknown.status_code == 422
        saved = await client.put(
            f"{ACC}/vat/settings",
            json={
                "rounding_gain_account": acc["other_income"],
                "rounding_loss_account": acc["other_cost"],
            },
            headers=_headers(world["admin"]),
        )
        assert saved.status_code == 200, saved.text
        assert saved.json()["rounding_loss_account"] == acc["other_cost"]
        assert saved.json()["input_account"] == acc["vat_in"]
        async with AsyncSessionLocal() as db:
            current = await ledger_settings.load(db)
        value = ledger_settings.to_json(current)
        value["bank"]["vat_account"] = acc["vat_due"]
        await _set_ledger(value)

        # Bez JPK: rozliczenie bierze kwoty z JPK.
        waiting = await _settlement(client, world, books)
        assert "przygotuj JPK" in waiting["blocker"]
        first = await _jpk(client, world, books, opening_surplus=120)
        assert first.status_code == 201, first.text
        v1 = first.json()["file"]

        preview = await _settlement(client, world, books)
        assert preview["blocker"] is None and preview["problem"] is None
        assert preview["jpk"]["version"] == 1 and preview["payroll"] is True
        # Należny 207 zł, naliczony 2 530 zł (z fakturą osoby zespołu); P_39 = 120 zł
        # z Symfonii nie zmienia dokumentu — nadwyżka miesiąca 2 323 zł na Wn.
        assert preview["amounts"] == {
            "ledger_output": 20_700,
            "ledger_input": 253_000,
            "output_tax": 20_700,
            "input_tax": 253_000,
            "due": -2_323,
            "rounding": 0,
        }
        assert [(line["side"], line["account"], line["amount"]) for line in preview["lines"]] == [
            ("debit", acc["vat_out"], 20_700),
            ("credit", acc["vat_in"], 253_000),
            ("debit", acc["vat_due"], 232_300),
        ]
        # D2: osoba bez Płac widzi stan, bez kwot, i dokumentu nie przygotuje.
        blind = await _settlement(client, world, books, user="module_only")
        assert blind["amounts"] is None and blind["lines"] == [] and blind["can_prepare"] is False
        assert (await _prepare_settlement(client, world, books, user="module_only")).status_code == 403

        created = await _prepare_settlement(client, world, books)
        assert created.status_code == 200, created.text
        assert created.json()["outcome"] == "created"
        doc_id = created.json()["document"]["id"]
        again = await _prepare_settlement(client, world, books)
        assert again.json()["outcome"] == "unchanged" and again.json()["document"]["id"] == doc_id
        async with AsyncSessionLocal() as db:
            doc = await db.get(LedgerDocument, doc_id)
            assert (doc.doc_type, doc.status, doc.sensitivity) == ("VAT", "draft", "payroll")
            assert (doc.source_type, doc.source_id) == ("vat_settlement", f"{year}-03")
            assert doc.op_date == date(year, 3, 31)
        item = await _settlement_item(client, world, books)
        assert item["state"] == "todo" and "w buforze" in item["detail"]

        await _approve_ids(client, world, [doc_id])
        item = await _settlement_item(client, world, books)
        assert item["state"] == "ok" and "zatwierdzony" in item["detail"]
        # 221 i 222 zerują się, nadwyżka miesiąca zostaje saldem Wn „VAT do zapłaty”.
        assert await _vat_balances(books) == (0, 0, 232_300)
        # Rejestr nie liczy dokumentu rozliczenia jako zapisu spoza rejestru.
        registers = (await _vat_registers(client, world, books)).json()
        assert not any(issue["kind"] == "outside" for issue in registers["issues"])

        # Korekta JPK po rozliczeniu: storno FVZ zmienia kwoty — najpierw księga
        # różni się od wysłanego JPK (problem), po korekcie JPK zatwierdzony
        # dokument jest do storna. (Storno FVS zostawiłoby fakturę z KSeF bez
        # dokumentu, a to blokuje JPK; faktura kosztowa bez FVZ — ostrzeżenie.)
        assert (await _jpk_sent(client, world, v1["id"])).status_code == 200
        await _reverse(client, world, docs["expense"].id, date(year, 3, 31))
        mismatch = await _settlement(client, world, books)
        assert "VAT naliczony" in mismatch["problem"] and "korekta JPK" in mismatch["problem"]
        item = await _settlement_item(client, world, books)
        assert item["state"] == "problem"
        hidden = await _settlement(client, world, books, user="module_only")
        assert "Płacami" in hidden["problem"] and "zł" not in hidden["problem"]
        refused = await _prepare_settlement(client, world, books)
        assert refused.status_code == 422 and "VAT naliczony" in refused.json()["detail"]
        corrected = await _jpk(client, world, books, reason="Storno faktury zakupu.")
        assert corrected.status_code == 201, corrected.text
        assert (await _jpk_sent(client, world, corrected.json()["file"]["id"], "UPO 2")).status_code == 200
        changed = await _settlement(client, world, books)
        assert changed["changed"] is True and changed["jpk"]["version"] == 2
        item = await _settlement_item(client, world, books)
        assert item["state"] == "problem" and "storno" in item["detail"]
        conflict = await _prepare_settlement(client, world, books)
        assert conflict.status_code == 409 and "storno" in conflict.json()["detail"]
        await _reverse(client, world, doc_id, date(year, 3, 31))
        rebuilt = await _prepare_settlement(client, world, books)
        assert rebuilt.status_code == 200 and rebuilt.json()["outcome"] == "created", rebuilt.text
        lines = (await _settlement(client, world, books))["lines"]
        # Bez FVZ kosztu: naliczony 2 300 zł, nadwyżka miesiąca 2 093 zł na Wn.
        assert [(line["side"], line["account"], line["amount"]) for line in lines] == [
            ("debit", acc["vat_out"], 20_700),
            ("credit", acc["vat_in"], 230_000),
            ("debit", acc["vat_due"], 209_300),
        ]
        await _approve_ids(client, world, [rebuilt.json()["document"]["id"]])
        assert (await _vat_balances(books))[:2] == (0, 0)

        # PK na koncie VAT naliczonego poza rejestrem: księga ≠ JPK, bez dokumentu.
        async with AsyncSessionLocal() as db:
            from app.services.ledger import documents as ledger_documents
            from app.services.ledger.documents import DocumentSpec

            manual = await ledger_documents.create_draft(
                db,
                DocumentSpec(
                    doc_type="PK",
                    op_date=date(year, 3, 30),
                    doc_date=date(year, 3, 30),
                    description="Korekta VAT ręcznie",
                    lines=[
                        LineIn("debit", acc["vat_in"], 1_000, "korekta"),
                        LineIn("credit", acc["cost"], 1_000, "korekta"),
                    ],
                ),
                actor_id=world["accountant"].id,
            )
            await db.commit()
        await _approve_ids(client, world, [manual.id])
        problem = (await _settlement(client, world, books))["problem"]
        assert "VAT naliczony" in problem and "spoza rejestru" in problem
    finally:
        await _purge_jpk(year)
        await _restore_payer(previous)


async def test_vat_settlement_counts_import_of_services_on_the_output_account_of_the_decree(
    client, world, books
):
    """FVZ z kolejki kosztów z typem IU księguje VAT należny na koncie z dekretu
    (226, nie konto sprzedaży), a JPK go liczy — rozliczenie bierze obroty 226
    z księgi i zeruje to konto; PK na 226 spoza rejestru to zapis „spoza
    rejestru” (audyt 24.11.2026)."""

    from app.services.ledger.engine import LineIn

    year, acc = books["year"], books["acc"]
    previous = await _payer("0202")
    try:
        # Usługa bez VAT u sprzedawcy, typ IU z kolejki kosztów: VAT należny na 226.
        imported = await _expense(
            world, number="IU 1/03", net="1000.00", vat="0.00", gross="1000.00"
        )
        decree = _decree(
            acc, net=100_000, vat=0, payable=books["supplier"].cost_account, text="Import usług"
        )
        decree["doc_type"] = "IU"
        decree["self_assessed"] = True
        decree["registers"] = [
            {"register": "Import usług VAT naliczony", "rate": 23, "eu": False},
            {"register": "Import usług VAT należny", "rate": 23, "eu": False, "output": True},
        ]
        decree["positions"] = [
            {"kind": "cost", "account": acc["cost"], "side": "debit", "amount": 100_000},
            {"kind": "vat", "account": acc["vat_in"], "side": "debit", "amount": 23_000},
            {"kind": "vat_due", "account": acc["vat_import"], "side": "credit", "amount": 23_000},
            {
                "kind": "counterparty",
                "account": books["supplier"].cost_account,
                "side": "credit",
                "amount": 100_000,
            },
        ]
        await _ready(
            imported,
            received=datetime(year, 3, 16, 10, 0, tzinfo=timezone.utc),
            counterparty_id=books["supplier"].id,
            decree=decree,
        )
        await _jpk_ready(client, world, books)
        expense = await _document("finance_cost_entry", imported)
        assert (expense.meta or {}).get("output_account") == acc["vat_import"]
        await _approve_ids(client, world, [expense.id])
        settings = _ledger_settings(world, books, allocation=False)
        settings["modules"]["vat"] = True
        settings["vat"] = {
            "input_account": acc["vat_in"],
            "rounding_gain_account": acc["other_income"],
            "rounding_loss_account": acc["other_cost"],
        }
        settings["jpk"] = {"email": "vat@example.com", "phone": ""}
        settings["accountants"] = [world["accountant"].id]
        await _set_ledger(settings)
        async with AsyncSessionLocal() as db:
            current = await ledger_settings.load(db)
        value = ledger_settings.to_json(current)
        value["bank"]["vat_account"] = acc["vat_due"]
        await _set_ledger(value)

        created = await _jpk(client, world, books, opening_surplus=0)
        assert created.status_code == 201, created.text

        preview = await _settlement(client, world, books)
        # JPK: należny 207 zł ze sprzedaży + 230 zł z importu usług.
        assert preview["amounts"]["output_tax"] == 43_700
        assert preview["blocker"] is None and preview["problem"] is None, preview
        assert preview["amounts"]["ledger_output"] == 43_700
        lines = [(line["side"], line["account"], line["amount"]) for line in preview["lines"]]
        assert ("debit", acc["vat_out"], 20_700) in lines
        assert ("debit", acc["vat_import"], 23_000) in lines
        prepared = await _prepare_settlement(client, world, books)
        assert prepared.status_code == 200, prepared.text
        await _approve_ids(client, world, [prepared.json()["document"]["id"]])
        sign = case((LedgerLine.side == "debit", 1), else_=-1)
        async with AsyncSessionLocal() as db:
            balance = await db.scalar(
                select(func.sum(sign * LedgerLine.amount))
                .join(LedgerDocument, LedgerDocument.id == LedgerLine.document_id)
                .where(
                    LedgerDocument.status == "approved",
                    LedgerLine.account == acc["vat_import"],
                )
            )
        assert int(balance or 0) == 0

        # PK na koncie VAT należnego importu usług poza rejestrem — „spoza rejestru”.
        async with AsyncSessionLocal() as db:
            from app.services.ledger import documents as ledger_documents
            from app.services.ledger.documents import DocumentSpec

            manual = await ledger_documents.create_draft(
                db,
                DocumentSpec(
                    doc_type="PK",
                    op_date=date(year, 3, 30),
                    doc_date=date(year, 3, 30),
                    description="Korekta VAT importu ręcznie",
                    lines=[
                        LineIn("debit", acc["cost"], 1_000, "korekta"),
                        LineIn("credit", acc["vat_import"], 1_000, "korekta"),
                    ],
                ),
                actor_id=world["accountant"].id,
            )
            await db.commit()
        await _approve_ids(client, world, [manual.id])
        registers = (await _vat_registers(client, world, books)).json()
        outside = next(issue for issue in registers["issues"] if issue["kind"] == "outside")
        assert [item["id"] for item in outside["items"]] == [manual.id]
        problem = (await _settlement(client, world, books))["problem"]
        assert "VAT należny" in problem and "spoza rejestru" in problem
    finally:
        await _purge_jpk(year)
        await _restore_payer(previous)


# ── VAT-UEK(5) (K5b-3c) ─────────────────────────────────────────────────────


async def test_vat_uek_corrects_the_original_period_from_month_k(client, world, books):
    """Korekta z maja faktury np II z marca: VAT-UE maja jej nie liczy (lista
    „do VAT-UEK” z okresem), VAT-UEK za marzec z korekt maja — „było” z rejestru
    marca, „jest” po korekcie; faktura pierwotna spoza księgi = problem."""

    await _vat_books(client, world, books)
    year, nips = books["year"], world["nips"]
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(ClientSalesInvoice)
            .where(ClientSalesInvoice.id == books["sales"]["euro"])
            .values(buyer_nip=None, buyer_foreign_id="FI28583949")
        )
        # Faktura z lutego bez dokumentu w księdze (VAT-UE z Symfonii).
        outside = _sales_invoice(
            nips["client"],
            number="FS 9/02",
            buyer_foreign_id="FI28583949",
            buyer_name="Klient Testowy",
            issue_date=date(year, 2, 20),
            sale_date=date(year, 2, 20),
            net_amount=Decimal("300.00"),
            vat_amount=Decimal("0"),
            gross_amount=Decimal("300.00"),
        )
        db.add(outside)
        await db.flush()
        corrections = [
            _sales_invoice(
                nips["client"],
                number=number,
                # NIP z kartoteki testu — synchronizacja szuka nabywcy po nim;
                # zdejmowany po zatwierdzeniu (niżej), jak w teście VAT-UE.
                buyer_nip=nips["client"],
                buyer_foreign_id="FI28583949",
                buyer_name="Klient Testowy",
                invoice_type="KOR",
                invoice_kind="correction",
                corrects_invoice_id=original,
                corrected_invoice_number=original_number,
                issue_date=date(year, 5, 10),
                sale_date=sale,
                net_amount=Decimal(net),
                vat_amount=Decimal("0"),
                gross_amount=Decimal(net),
                items=[
                    {"name": "Usługa", "net": before, "vat_rate": "np II", "before_correction": True},
                    {"name": "Usługa", "net": after, "vat_rate": "np II"},
                ],
            )
            for number, original, original_number, sale, net, before, after in (
                ("FK 1/05", books["sales"]["euro"], "FS 2/03", date(year, 3, 20), "-430.00", "500.00", "400.00"),
                ("FK 2/05", outside.id, "FS 9/02", date(year, 2, 20), "-100.00", "300.00", "200.00"),
            )
        ]
        db.add_all(corrections)
        await db.commit()
        books["sales"].update(
            uek_outside=outside.id, uek_march=corrections[0].id, uek_feb=corrections[1].id
        )
    synced = await _sync(client, world, books, "sales", month=5)
    assert synced.status_code == 200, synced.text
    docs = [
        await _document("client_sales_invoice", books["sales"][key])
        for key in ("uek_march", "uek_feb")
    ]
    assert all(doc is not None and doc.op_date == date(year, 5, 10) for doc in docs), synced.text
    await _approve_ids(client, world, [doc.id for doc in docs])
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(ClientSalesInvoice)
            .where(
                ClientSalesInvoice.id.in_(
                    [books["sales"]["uek_march"], books["sales"]["uek_feb"]]
                )
            )
            .values(buyer_nip=None)
        )
        await db.commit()
    headers = _headers(world["module_only"])

    may = (await client.get(f"{ACC}/vat/ue", params={"year": year, "month": 5}, headers=headers)).json()
    assert sorted((item["number"], item["kind"], item.get("period")) for item in may["problems"]) == [
        ("FK 1/05", "earlier", f"{year}-03"),
        ("FK 2/05", "earlier", f"{year}-02"),
    ]

    params = {"year": year, "month": 3, "issued_year": year, "issued_month": 5}
    response = await client.get(f"{ACC}/vat/uek", params=params, headers=headers)
    assert response.status_code == 200, response.text
    data = response.json()
    # 500 EUR po 4,30 = 2 150 zł było, po korekcie −430 zł = 1 720 zł.
    assert [
        (line["section"], line["country"], line["number"], line["before"], line["after"], line["documents"])
        for line in data["lines"]
    ] == [("services", "FI", "28583949", 2150, 1720, ["FK 1/05"])]
    assert (data["corrections"], data["earlier_months"], data["problems"]) == (1, [], [])
    # Rok testu (2050–2090) jest poza etd:TRok (do 2030) — plik nie powstaje;
    # schemat sprawdzają testy reguł.
    refused = await client.get(f"{ACC}/vat/uek/file", params=params, headers=headers)
    assert refused.status_code == 422 and "VAT-UEK" in refused.json()["detail"]

    february = (
        await client.get(f"{ACC}/vat/uek", params={**params, "month": 2}, headers=headers)
    ).json()
    assert [item["kind"] for item in february["problems"]] == ["outside"]
    assert february["can_download"] is False

    nothing = (
        await client.get(f"{ACC}/vat/uek", params={**params, "issued_month": 4}, headers=headers)
    ).json()
    assert (nothing["lines"], nothing["corrections"]) == ([], 0)
    empty = await client.get(
        f"{ACC}/vat/uek/file", params={**params, "issued_month": 4}, headers=headers
    )
    assert empty.status_code == 422 and "nie ma korekt" in empty.json()["detail"]
    backwards = await client.get(
        f"{ACC}/vat/uek", params={**params, "issued_month": 3}, headers=headers
    )
    assert backwards.status_code == 422
