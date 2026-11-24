"""Faktury do klientów (E8) — trasy: dostęp, zakładka klienta, Finanse, wyciąg, eksport.

Zakres: rekruter, TCM i DL cudzego klienta nie widzą kwot (403), DL widzi
swojego klienta, Finanse wszystkich; wyłączony moduł = 404 (admin przechodzi);
„do faktury” obok faktur z KSeF ze stanem; przypisanie, pominięcie, uznanie
różnicy i ręczne „opłacono” tylko Finanse; uznania z wyciągu opłacają faktury
(także z importu Płac, bez wpływu na obciążenia). Dane fikcyjne.
"""

from __future__ import annotations

import io
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from openpyxl import load_workbook
from sqlalchemy import delete, func, select, update

from app.api import client_sales_invoices as api
from app.api import hr_payments
from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.app_setting import AppSetting
from app.models.client_sales_invoice import ClientSalesInvoicePayment
from app.models.ledger import LedgerBankLine, LedgerBankStatement
from app.models.section_permission import UserActionOverride
from app.services.client_invoicing import payments, sync
from app.services.client_invoicing.views import ROW_STATUS_LABELS
from app.services.hr.bank import statements
from app.services.hr.bank.accounts import iban_check_digits
from app.services.hr_foundation_schema import HR_MODULE_KEYS, HR_MODULES_SETTING
from tests.client_invoicing import helpers as fx

pytestmark = pytest.mark.asyncio

CLIENTS = "/api/clients"
FINANCE = "/api/finance/sales-invoices"
STATEMENT = (
    Path(__file__).parent / "data" / "bank" / "sales" / "camt053_wplaty_klientow.xml"
)
TODAY = date(2026, 11, 20)
OCTOBER = {"year": 2026, "month": 10}


@pytest_asyncio.fixture
async def client():
    from app.main import app

    mounted = any(getattr(r, "path", "").startswith(FINANCE) for r in app.routes)
    target = app
    if not mounted:
        target = FastAPI()
        target.include_router(api.router, prefix=CLIENTS)
        target.include_router(api.finance_router, prefix=FINANCE)
    async with AsyncClient(
        transport=ASGITransport(app=target), base_url="http://testserver"
    ) as http:
        yield http


@pytest_asyncio.fixture
async def payroll_client():
    """Trasy faktur do klientów i wyciągu Płac (``/api/hr/payments``) razem."""

    target = FastAPI()
    target.include_router(api.router, prefix=CLIENTS)
    target.include_router(api.finance_router, prefix=FINANCE)
    target.include_router(hr_payments.router, prefix="/api/hr/payments")
    async with AsyncClient(
        transport=ASGITransport(app=target), base_url="http://testserver"
    ) as http:
        yield http


@pytest_asyncio.fixture
async def seed(monkeypatch):
    monkeypatch.setattr(api, "business_today", lambda: TODAY)
    monkeypatch.setattr(settings, "KSEF_MODE", "simulate")
    monkeypatch.setattr(settings, "KSEF_CONTEXT_NIP", fx.COMPANY_NIP)
    monkeypatch.setattr(settings, "KSEF_SIMULATE_DIR", str(fx.DATA_DIR.parent))
    data = await fx.seed_month()
    await fx.set_module(True)
    async with AsyncSessionLocal() as db:
        result = await sync.run_once(
            db, now=datetime(2026, 11, 20, 12, 0, tzinfo=timezone.utc)
        )
    assert result["saved"] == 5, result
    yield data
    await fx.wipe()
    await fx.set_module(None)


async def _tab(client, user, seed, **params):
    return await client.get(
        f"{CLIENTS}/{seed.client_id}/invoicing",
        params={**OCTOBER, **params},
        headers=fx.headers(user),
    )


async def _upload(client, user, raw: bytes):
    return await client.post(
        f"{FINANCE}/statements",
        files={"file": ("wyciag.xml", io.BytesIO(raw), "application/xml")},
        headers=fx.headers(user),
    )


# ── Dostęp ────────────────────────────────────────────────────────────────────


async def test_amounts_only_for_finance_and_the_clients_delivery_lead(client, seed):
    users = seed.users
    assert (await _tab(client, users["finance"], seed)).status_code == 200
    assert (await _tab(client, users["dl"], seed)).status_code == 200
    assert (await _tab(client, users["admin"], seed)).status_code == 200

    foreign = await _tab(client, users["other_dl"], seed)
    assert foreign.status_code == 403
    assert "poza Twoim portfelem" in foreign.text
    for role in ("recruiter", "tcm"):
        denied = await _tab(client, users[role], seed)
        assert denied.status_code == 403, role
        assert "25200" not in denied.text

    # Delivery Lead nie wchodzi do ekranu Finansów ani nie przypisuje faktur.
    invoice = await fx.invoice(fx.KSEF_UNKNOWN)
    listing = await client.get(FINANCE, params=OCTOBER, headers=fx.headers(users["dl"]))
    assert listing.status_code == 403
    assign = await client.post(
        f"{FINANCE}/{invoice.id}/ignore",
        json={"reason": "sprzedaż sprzętu"},
        headers=fx.headers(users["dl"]),
    )
    assert assign.status_code == 403


async def test_module_off_hides_screens_except_for_admin(client, seed):
    await fx.set_module(False)
    off = await _tab(client, seed.users["finance"], seed)
    assert off.status_code == 404
    assert off.json()["detail"] == "Moduł faktur do klientów jest wyłączony."
    admin = await _tab(client, seed.users["admin"], seed)
    assert admin.status_code == 200
    assert admin.json()["module_enabled"] is False
    # Przełącznik zmienia tylko admin.
    finance_toggle = await client.put(
        f"{FINANCE}/module",
        json={"enabled": True},
        headers=fx.headers(seed.users["finance"]),
    )
    assert finance_toggle.status_code == 403
    toggle = await client.put(
        f"{FINANCE}/module",
        json={"enabled": True},
        headers=fx.headers(seed.users["admin"]),
    )
    assert toggle.status_code == 200 and toggle.json() == {"enabled": True}


async def test_unknown_client_is_404(client, seed):
    response = await client.get(
        f"{CLIENTS}/999999999/invoicing",
        params=OCTOBER,
        headers=fx.headers(seed.users["finance"]),
    )
    assert response.status_code == 404


# ── Zakładka klienta ──────────────────────────────────────────────────────────


async def test_client_tab_compares_orders_with_ksef_invoices(client, seed):
    response = await _tab(client, seed.users["dl"], seed)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["period"] == "2026-10"
    assert body["can_manage"] is False
    rows = fx.as_dict(body["rows"], "order_number")
    assert rows["ZAM/2026/118"]["status"] == "ok"
    assert rows["ZAM/2026/118"]["expected_net"] == "25200.00"
    assert rows["ZAM/2026/121"]["status"] == "ok"
    assert rows["ZAM/2026/121"]["lines"][0]["unit"] == "h"
    # 22 500 z faktury − 75 z korekty = 22 425 do faktury.
    assert rows["ZAM/2026/124"]["status"] == "ok"
    assert rows["ZAM/2026/124"]["invoiced_net"] == "22425.00"
    assert rows["ZAM/2026/130"]["status"] == "not_invoiced"
    assert rows["ZAM/2026/130"]["status_label"] == ROW_STATUS_LABELS["not_invoiced"]
    assert body["summary"]["rows"] == 4
    assert body["summary"]["not_invoiced"] == 1
    invoices = fx.as_dict(body["invoices"], "invoice_number")
    corrected = invoices["FS 10/124/2026"]
    assert corrected["net"] == "22425.00"
    assert corrected["corrections"][0]["net"] == "-75.00"
    assert corrected["check"] == "ok"
    # Termin 10.11 minął, ale NEXUS nie wie, czy zapłacono — to nie zaległość.
    unpaid = invoices["FS 10/121/2026"]
    assert (unpaid["overdue_days"], unpaid["payment_unknown"]) == (0, True)
    assert body["overdue"] == []
    # Faktura dla nabywcy spoza NEXUSA nie trafia do zakładki klienta.
    assert "FS 11/7/2026" not in invoices

    finance = (await _tab(client, seed.users["finance"], seed)).json()
    assert finance["can_manage"] is True


async def test_overdue_without_payment_data_is_a_count_not_arrears(client, seed):
    """Brak zapisanej zapłaty to brak danych, nie zaległość.

    19.11.2026 jeden klient miał „62 po terminie”, a cała firma 2 741 faktur,
    żadna z datą zapłaty: NEXUS miał wyciągi z jednego dnia (12.11.2026).
    """

    dl = seed.users["dl"]
    tab = (await _tab(client, dl, seed)).json()
    # FS 10/118, 10/121 i 10/124 mają termin 10–18.11, a „dziś” to 20.11.
    assert (tab["summary"]["overdue"], tab["summary"]["payment_unknown"]) == (0, 3)
    assert tab["overdue"] == []
    late = fx.as_dict(tab["invoices"], "invoice_number")
    assert all(item["overdue_days"] == 0 for item in late.values())
    assert late["FS 10/118/2026"]["payment_unknown"] is True

    scope = (
        await client.get(f"{CLIENTS}/sales-invoices/overdue", headers=fx.headers(dl))
    ).json()
    assert (scope["invoices"], scope["payment_unknown"]) == ([], 3)
    # Bez wyciągów rachunku odbioru w Księdze każda z nich ma powód braku danych.
    assert sum(r["count"] for r in scope["payment_unknown_reasons"]) == 3
    other = await client.get(
        f"{CLIENTS}/sales-invoices/overdue", headers=fx.headers(seed.users["other_dl"])
    )
    assert other.json() == {
        "invoices": [],
        "payment_unknown": 0,
        "payment_unknown_reasons": [],
        "vat_pln_unpaid": {"count": 0, "total_pln": None, "without_rate": 0},
    }
    finance = await client.get(
        f"{FINANCE}/overdue", headers=fx.headers(seed.users["finance"])
    )
    # Do tego FS 11/7 (nabywca spoza NEXUSA, termin 19.11); baza testów jest wspólna.
    assert finance.json()["invoices"] == []
    assert finance.json()["payment_unknown"] >= 4


def _fake_nrb() -> str:
    """Fikcyjny rachunek (losowy, z poprawną sumą kontrolną) — baza testów jest wspólna."""

    bban = "10901056" + f"{uuid.uuid4().int % 10**16:016d}"
    return iban_check_digits(bban) + bban


async def _put_setting(key: str, value) -> None:
    async with AsyncSessionLocal() as db:
        row = await db.get(AppSetting, key)
        if value is None:
            if row is not None:
                await db.delete(row)
        elif row is None:
            db.add(AppSetting(key=key, value=value))
        else:
            row.value = value
        await db.commit()


async def _setting(key: str):
    async with AsyncSessionLocal() as db:
        row = await db.get(AppSetting, key)
        return None if row is None else row.value


async def _statements(account: str, spans) -> list[int]:
    """Wyciągi w Księdze z saldami — jak po imporcie przez Finanse (E8 przeszło)."""

    ids = []
    async with AsyncSessionLocal() as db:
        for start, end, opening, closing in spans:
            statement = LedgerBankStatement(
                sha256=uuid.uuid4().hex + uuid.uuid4().hex,
                format="mt940",
                bank_account=account,
                ledger_account="130-1",
                currency="PLN",
                first_day=start,
                last_day=end,
                line_count=1,
                debit_total=0,
                credit_total=closing - opening,
                opening_balance=opening,
                opening_day=start,
                closing_balance=closing,
                closing_day=end,
                credits_matched=True,
            )
            db.add(statement)
            await db.flush()
            ids.append(statement.id)
        await db.commit()
    return ids


async def test_overdue_needs_continuous_statements_of_the_receiving_account(
    client, seed
):
    """„Po terminie” z wyciągów (19.11.2026): rachunek odbioru jest w Księdze,
    a łańcuch sald jego wyciągów idzie od dnia przed wystawieniem do dnia po
    terminie. Przerwa w łańcuchu = brak danych o zapłacie z powodem."""

    account = _fake_nrb()
    previous = {key: await _setting(key) for key in ("client_invoice_issue", "ledger")}
    await _put_setting(
        "client_invoice_issue", {"accounts": {"PLN": {"number": f"PL{account}"}}}
    )
    await _put_setting(
        "ledger",
        {
            "bank": {
                "accounts": [{"number": account, "account": "130-1", "currency": "PLN"}]
            }
        },
    )
    ids = await _statements(
        account,
        [
            (date(2026, 11, 2), date(2026, 11, 12), 0, 50_000),
            (date(2026, 11, 13), date(2026, 11, 19), 50_000, 90_000),
        ],
    )
    dl = fx.headers(seed.users["dl"])
    try:
        scope = (
            await client.get(f"{CLIENTS}/sales-invoices/overdue", headers=dl)
        ).json()
        # Terminy 10, 17 i 18.11, ciągłość do 19.11 — dni do 19.11, nie do „dziś”.
        late = fx.as_dict(scope["invoices"], "invoice_number")
        assert {number: item["overdue_days"] for number, item in late.items()} == {
            "FS 10/121/2026": 9,
            "FS 10/118/2026": 2,
            "FS 10/124/2026": 1,
        }
        assert [item["invoice_number"] for item in scope["invoices"]][0] == (
            "FS 10/121/2026"
        )
        assert late["FS 10/121/2026"]["statements_until"] == "2026-11-19"
        assert late["FS 10/121/2026"]["payment_account"] == account[-4:]
        assert (scope["payment_unknown"], scope["payment_unknown_reasons"]) == (0, [])
        tab = (await _tab(client, seed.users["dl"], seed)).json()
        assert (tab["summary"]["overdue"], tab["summary"]["payment_unknown"]) == (3, 0)
        assert (
            fx.as_dict(tab["invoices"], "invoice_number")["FS 10/118/2026"][
                "overdue_days"
            ]
            == 2
        )

        # Drugi wyciąg nie otwiera się saldem zamknięcia pierwszego: łańcuch
        # kończy się 12.11, więc po terminie jest tylko faktura z terminem 10.11.
        async with AsyncSessionLocal() as db:
            await db.execute(
                update(LedgerBankStatement)
                .where(LedgerBankStatement.id == ids[1])
                .values(opening_balance=49_999)
            )
            await db.commit()
        scope = (
            await client.get(f"{CLIENTS}/sales-invoices/overdue", headers=dl)
        ).json()
        assert [
            (item["invoice_number"], item["overdue_days"]) for item in scope["invoices"]
        ] == [("FS 10/121/2026", 2)]
        assert scope["payment_unknown"] == 2
        assert [
            (r["reason"], r["account"], r["count"])
            for r in scope["payment_unknown_reasons"]
        ] == [("statements", account[-4:], 2)]
        tab = (await _tab(client, seed.users["dl"], seed)).json()
        unknown = fx.as_dict(tab["invoices"], "invoice_number")["FS 10/118/2026"]
        assert (unknown["payment_unknown"], unknown["payment_unknown_reason"]) == (
            True,
            "statements",
        )
        assert unknown["statements_until"] == "2026-11-12"
        other = await client.get(
            f"{CLIENTS}/sales-invoices/overdue",
            headers=fx.headers(seed.users["other_dl"]),
        )
        assert other.json()["invoices"] == []
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(
                delete(LedgerBankStatement).where(LedgerBankStatement.id.in_(ids))
            )
            await db.commit()
        for key, value in previous.items():
            await _put_setting(key, value)


async def test_overdue_waits_while_a_credit_nexus_did_not_assign_may_be_the_payment(
    client, seed
):
    """Przegląd 19.11.2026: wpłata, której E8 nie przypisało, blokuje „po terminie”.

    * duplikat E8 (ta sama operacja z drugiego pliku) bez oryginału — „Usuń
      wyciąg” skasował plik, w którym operacja opłaciła fakturę;
    * operacja Księgi bez konta w kwocie, która została do zapłaty — E8 jej nie
      zapisało (np. ta sama kwota u kilku faktur, bez numeru w tytule).
    """

    account = _fake_nrb()
    previous = {key: await _setting(key) for key in ("client_invoice_issue", "ledger")}
    await _put_setting(
        "client_invoice_issue", {"accounts": {"PLN": {"number": f"PL{account}"}}}
    )
    await _put_setting(
        "ledger",
        {
            "bank": {
                "accounts": [{"number": account, "account": "130-1", "currency": "PLN"}]
            }
        },
    )
    ids = await _statements(
        account, [(date(2026, 11, 2), date(2026, 11, 19), 0, 90_000)]
    )
    dl = fx.headers(seed.users["dl"])
    try:
        async with AsyncSessionLocal() as db:
            db.add(
                ClientSalesInvoicePayment(
                    kind="statement_line",
                    match_status="ignored",
                    reason=payments.DUPLICATE_REASON,
                    amount=Decimal("100.00"),
                    currency="PLN",
                    booked_on=date(2026, 11, 12),
                    title="Zapłata FS 10/118/2026",
                    statement_sha256=uuid.uuid4().hex + uuid.uuid4().hex,
                    statement_format="mt940",
                    statement_line_ref="1:ORPHAN",
                )
            )
            # FS 10/124 minus korekta: 27 675,00 − 92,25 zł.
            db.add(
                LedgerBankLine(
                    statement_id=ids[0],
                    line_ref="1:LOOSE",
                    position=1,
                    booked_on=date(2026, 11, 10),
                    direction="credit",
                    amount=2_758_275,
                    currency="PLN",
                    amount_pln=2_758_275,
                    kind="unmatched",
                )
            )
            await db.commit()
        scope = (
            await client.get(f"{CLIENTS}/sales-invoices/overdue", headers=dl)
        ).json()
        assert [item["invoice_number"] for item in scope["invoices"]] == [
            "FS 10/121/2026"
        ]
        assert [
            (r["reason"], r["count"]) for r in scope["payment_unknown_reasons"]
        ] == [("credit_pending", 2)]
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(
                delete(LedgerBankStatement).where(LedgerBankStatement.id.in_(ids))
            )
            await db.commit()
        for key, value in previous.items():
            await _put_setting(key, value)


async def test_export_has_every_position_with_polish_decimals(client, seed):
    csv_response = await client.get(
        f"{CLIENTS}/{seed.client_id}/invoicing/export",
        params={**OCTOBER, "format": "csv"},
        headers=fx.headers(seed.users["dl"]),
    )
    assert csv_response.status_code == 200
    assert "do-faktury-klient" in csv_response.headers["content-disposition"]
    text_ = csv_response.content.decode("utf-8-sig")
    assert "ZAM/2026/130" in text_ and "Tomasz Wzorcowy" in text_
    assert "24000,00" in text_
    assert fx.CLIENT_NIP in text_

    xlsx = await client.get(
        f"{CLIENTS}/{seed.client_id}/invoicing/export",
        params=OCTOBER,
        headers=fx.headers(seed.users["finance"]),
    )
    sheet = load_workbook(io.BytesIO(xlsx.content)).active
    assert sheet.max_row == 5
    nets = sorted(row[10] for row in sheet.iter_rows(min_row=2, values_only=True))
    assert nets == [22425.0, 24000.0, 25200.0, 31920.0]

    denied = await client.get(
        f"{CLIENTS}/{seed.client_id}/invoicing/export",
        params=OCTOBER,
        headers=fx.headers(seed.users["other_dl"]),
    )
    assert denied.status_code == 403


# ── Finanse: przypisanie, pominięcie, różnica ─────────────────────────────────


async def test_finance_resolves_unmatched_and_accepts_a_difference(client, seed):
    finance = fx.headers(seed.users["finance"])
    november = await client.get(
        FINANCE, params={"year": 2026, "month": 11}, headers=finance
    )
    assert november.status_code == 200
    unknown = fx.as_dict(november.json()["invoices"], "invoice_number")["FS 11/7/2026"]
    assert unknown["match_status"] == "unmatched"
    assert unknown["match_reason_text"].startswith("NIP nabywcy")

    short = await client.post(
        f"{FINANCE}/{unknown['id']}/ignore", json={"reason": "x"}, headers=finance
    )
    assert short.status_code == 422
    ignored = await client.post(
        f"{FINANCE}/{unknown['id']}/ignore",
        json={"reason": "Sprzedaż sprzętu spoza zamówień"},
        headers=finance,
    )
    assert ignored.json()["match_status"] == "ignored"
    reopened = await client.post(f"{FINANCE}/{unknown['id']}/reopen", headers=finance)
    assert reopened.json()["match_status"] == "unmatched"

    # Faktura 118 przypięta do 130: różnica 1 200 do sprawdzenia, potem uznana.
    first = await fx.invoice(fx.KSEF_118)
    moved = await client.post(
        f"{FINANCE}/{first.id}/assign",
        json={"targets": [{"group_id": seed.groups["130"]}], **OCTOBER},
        headers=finance,
    )
    assert moved.status_code == 200, moved.text
    assert (moved.json()["check"], moved.json()["difference"]) == (
        "difference",
        "1200.00",
    )
    options = await client.get(f"{FINANCE}/{first.id}/options", headers=finance)
    labels = {o["label"] for o in options.json()["options"]}
    assert "ZAM/2026/130 · Tomasz Wzorcowy" in labels

    accepted = await client.post(
        f"{FINANCE}/{first.id}/accept-difference",
        json={"reason": "Klient zapłaci za dodatkowy dzień"},
        headers=finance,
    )
    assert accepted.json()["check"] == "accepted"
    tab = (await _tab(client, seed.users["finance"], seed)).json()
    rows = fx.as_dict(tab["rows"], "order_number")
    assert rows["ZAM/2026/130"]["status"] == "accepted"
    assert rows["ZAM/2026/118"]["status"] == "not_invoiced"

    other = await client.post(
        f"{FINANCE}/{first.id}/assign",
        json={"targets": [{"order_id": 999999999}], **OCTOBER},
        headers=finance,
    )
    assert other.status_code == 404
    correction = await fx.invoice(fx.KSEF_CORRECTION)
    refused = await client.post(
        f"{FINANCE}/{correction.id}/assign",
        json={"targets": [{"group_id": seed.groups["124"]}], **OCTOBER},
        headers=finance,
    )
    assert refused.status_code == 409
    no_diff = await client.post(
        f"{FINANCE}/{(await fx.invoice(fx.KSEF_121)).id}/accept-difference",
        json={"reason": "bez różnicy"},
        headers=finance,
    )
    assert no_diff.status_code == 409


async def test_assign_to_another_clients_order_is_refused(client, seed):
    async with AsyncSessionLocal() as db:
        foreign = await fx.periodic_order(
            db, seed.other_client_id, "PO-INNY", rate="100", unit=fx.RateUnit.monthly
        )
        await db.commit()
    first = await fx.invoice(fx.KSEF_118)
    response = await client.post(
        f"{FINANCE}/{first.id}/assign",
        json={"targets": [{"order_id": foreign}], **OCTOBER},
        headers=fx.headers(seed.users["finance"]),
    )
    assert response.status_code == 422
    assert "innego klienta" in response.text


# ── Zapłata ───────────────────────────────────────────────────────────────────


async def test_statement_credits_pay_invoices_and_reimport_changes_nothing(
    client, seed
):
    finance = seed.users["finance"]
    raw = STATEMENT.read_bytes()
    response = await _upload(client, finance, raw)
    assert response.status_code == 200, response.text
    result = response.json()
    assert (
        result["credits"],
        result["matched"],
        result["unmatched"],
        result["skipped"],
    ) == (
        5,
        3,
        1,
        1,
    )
    # Wynik bez kwot i nazw klientów.
    assert "30996" not in response.text and "Bank Testowy" not in response.text

    again = (await _upload(client, finance, raw)).json()
    assert (again["matched"], again["known"]) == (0, 4)

    tab = (await _tab(client, finance, seed)).json()
    invoices = fx.as_dict(tab["invoices"], "invoice_number")
    assert invoices["FS 10/118/2026"]["payment_status"] == "paid"
    assert (
        invoices["FS 10/124/2026"]["payment_status"] == "paid"
    )  # MPP: VAT na rachunku VAT
    partial = invoices["FS 10/121/2026"]
    assert (partial["payment_status"], partial["to_pay"]) == ("partial", "19261.60")
    # Część zapłaty jest z wyciągu, o reszcie NEXUS nie wie — to nie zaległość.
    assert (partial["overdue_days"], partial["payment_unknown"]) == (0, True)

    # Po wyciągu termin za sobą bez pełnej zapłaty ma tylko FS 10/121 (118 i 124
    # opłacone); drugi DL nie widzi faktur cudzego klienta.
    late = await client.get(
        f"{CLIENTS}/sales-invoices/overdue", headers=fx.headers(seed.users["dl"])
    )
    assert (late.json()["invoices"], late.json()["payment_unknown"]) == ([], 1)
    nobody = await client.get(
        f"{CLIENTS}/sales-invoices/overdue", headers=fx.headers(seed.users["other_dl"])
    )
    assert (nobody.json()["invoices"], nobody.json()["payment_unknown"]) == ([], 0)
    recruiter = await client.get(
        f"{CLIENTS}/sales-invoices/overdue", headers=fx.headers(seed.users["recruiter"])
    )
    assert recruiter.status_code == 403

    credits = (
        await client.get(f"{FINANCE}/credits", headers=fx.headers(finance))
    ).json()
    (pending,) = credits["credits"]
    assert pending["hints"][0]["invoice_number"] == "FS 11/7/2026"
    assigned = await client.post(
        f"{FINANCE}/credits/{pending['id']}/assign",
        json={"invoice_id": pending["hints"][0]["invoice_id"]},
        headers=fx.headers(finance),
    )
    assert assigned.status_code == 200
    detail = (
        await client.get(
            f"{FINANCE}/{pending['hints'][0]['invoice_id']}",
            headers=fx.headers(finance),
        )
    ).json()
    assert detail["payment_status"] == "paid"
    twice = await client.post(
        f"{FINANCE}/credits/{pending['id']}/assign",
        json={"invoice_id": pending["hints"][0]["invoice_id"]},
        headers=fx.headers(finance),
    )
    assert twice.status_code == 409


async def _payroll_upload(client, user, raw: bytes):
    """Wyciąg przez Płace (``/api/hr/payments/statements``) przy włączonych modułach HR."""

    async with AsyncSessionLocal() as db:
        row = await db.get(fx.AppSetting, HR_MODULES_SETTING)
        before = None if row is None else dict(row.value)
        if row is None:
            db.add(
                fx.AppSetting(
                    key=HR_MODULES_SETTING, value={k: True for k in HR_MODULE_KEYS}
                )
            )
        else:
            row.value = {k: True for k in HR_MODULE_KEYS}
        await db.commit()
    try:
        return await client.post(
            "/api/hr/payments/statements",
            files={"file": ("wyciag.xml", io.BytesIO(raw), "application/xml")},
            headers=fx.headers(user),
        )
    finally:
        async with AsyncSessionLocal() as db:
            row = await db.get(fx.AppSetting, HR_MODULES_SETTING)
            if before is None:
                await db.delete(row)
            else:
                row.value = before
            await db.commit()


async def test_payroll_without_finance_only_counts_client_credits(payroll_client, seed):
    """Płace bez modułu Finanse nie opłacają faktur klientów i nie widzą, co pasuje."""

    async with AsyncSessionLocal() as db:
        payroll = await fx.make_user(db, "recruiter", name="Paula Płacowa")
        db.add(
            UserActionOverride(user_id=payroll.id, action="payroll", access="manage")
        )
        await db.commit()
    raw = STATEMENT.read_bytes()
    response = await _payroll_upload(payroll_client, payroll, raw)
    assert response.status_code == 200, response.text
    async with AsyncSessionLocal() as db:
        stored = await db.scalar(
            select(func.count()).select_from(ClientSalesInvoicePayment)
        )
    assert stored == 0
    tab = (await _tab(payroll_client, seed.users["finance"], seed)).json()
    invoices = fx.as_dict(tab["invoices"], "invoice_number")
    assert invoices["FS 10/118/2026"]["payment_status"] == "unpaid"
    credits = response.json()["credits"]
    # Odpowiedź nie mówi, czy numer faktury z tytułu istnieje — tylko ile uznań.
    assert (
        credits["matched"],
        credits["unmatched"],
        credits["skipped"],
        credits["known"],
    ) == (0, 0, 0, 0)
    assert credits["credits"] == 5
    assert credits["restricted"] is True

    # Ten sam plik wgrany potem przez Finanse dopasowuje uznania normalnie.
    finance = (await _upload(payroll_client, seed.users["finance"], raw)).json()
    assert (finance["matched"], finance["unmatched"]) == (3, 1)


async def test_payroll_with_finance_books_client_credits_through_the_payroll_route(
    payroll_client, seed
):
    response = await _payroll_upload(
        payroll_client, seed.users["finance"], STATEMENT.read_bytes()
    )
    assert response.status_code == 200, response.text
    credits = response.json()["credits"]
    assert credits["restricted"] is False
    assert (credits["matched"], credits["unmatched"]) == (3, 1)


async def test_payroll_statement_import_also_books_client_credits(seed, monkeypatch):
    raw = STATEMENT.read_bytes()
    async with AsyncSessionLocal() as db:
        result = await statements.import_statement(
            db, raw, actor_id=seed.users["finance"].id, match_credits=True
        )
        await db.commit()
    # Obciążenia: czynsz nie dotyczy zespołu — jak dotąd tylko licznik.
    assert result.debits == 1
    assert result.matched == 0
    assert result.credits["matched"] == 3 and result.credits["unmatched"] == 1
    async with AsyncSessionLocal() as db:
        stored = list(
            await db.scalars(
                select(ClientSalesInvoicePayment).where(
                    ClientSalesInvoicePayment.match_status == "matched"
                )
            )
        )
    assert sum((p.amount for p in stored), Decimal("0")) == Decimal("78578.75")


async def test_payroll_import_survives_a_failure_on_the_client_side(seed, monkeypatch):
    async def broken(*_args, **_kwargs):
        raise RuntimeError("awaria testowa")

    monkeypatch.setattr(statements.client_payments, "import_credits", broken)
    async with AsyncSessionLocal() as db:
        result = await statements.import_statement(
            db,
            STATEMENT.read_bytes(),
            actor_id=seed.users["finance"].id,
            match_credits=True,
        )
        await db.commit()
    assert result.credits["error"] is True
    assert result.debits == 1


async def test_payroll_import_skips_credits_when_module_is_off(seed):
    await fx.set_module(False)
    async with AsyncSessionLocal() as db:
        result = await statements.import_statement(
            db,
            STATEMENT.read_bytes(),
            actor_id=seed.users["finance"].id,
            match_credits=True,
        )
        await db.commit()
    assert result.credits["disabled"] is True
    assert result.credits["matched"] == 0


async def test_manual_paid_needs_reason_and_a_past_date(client, seed):
    finance = fx.headers(seed.users["finance"])
    invoice = await fx.invoice(fx.KSEF_121)
    future = await client.post(
        f"{FINANCE}/{invoice.id}/mark-paid",
        json={"amount": "100.00", "paid_on": "2026-12-01", "reason": "kompensata"},
        headers=finance,
    )
    assert future.status_code == 422
    paid = await client.post(
        f"{FINANCE}/{invoice.id}/mark-paid",
        json={
            "amount": "39261.60",
            "paid_on": "2026-11-19",
            "reason": "Kompensata z notą",
        },
        headers=finance,
    )
    assert paid.status_code == 200
    assert paid.json()["payment_status"] == "paid"
    again = await client.post(
        f"{FINANCE}/{invoice.id}/mark-paid",
        json={"amount": "1.00", "paid_on": "2026-11-19", "reason": "Kompensata z notą"},
        headers=finance,
    )
    assert again.status_code == 409


async def test_module_state_tells_the_profile_whether_to_show_the_tab(client, seed):
    path = f"{CLIENTS}/sales-invoices/module"
    assert (await client.get(path, headers=fx.headers(seed.users["dl"]))).json() == {
        "enabled": True,
        "open": True,
    }
    await fx.set_module(False)
    assert (await client.get(path, headers=fx.headers(seed.users["dl"]))).json() == {
        "enabled": False,
        "open": False,
    }
    admin = await client.get(path, headers=fx.headers(seed.users["admin"]))
    assert admin.json() == {"enabled": False, "open": True}
    denied = await client.get(path, headers=fx.headers(seed.users["recruiter"]))
    assert denied.status_code == 403


# ── Zapłaty z eBI24 ───────────────────────────────────────────────────────────


def _ebi24_header(ksef_number: str, **extra: object) -> dict[str, object]:
    return {
        "_id": "ebi24doc118",
        "_ksefReferenceNumber": ksef_number,
        "grossAmount": 3099600,
        "paid": False,
        **extra,
    }


async def _apply_ebi24(*headers: dict[str, object]):
    from app.services.client_invoicing import ebi24_payments

    async with AsyncSessionLocal() as db:
        counts = await ebi24_payments.apply(
            db, list(headers), today=TODAY, dry_run=False
        )
        await db.commit()
    return counts


async def _invoice_118():
    async with AsyncSessionLocal() as db:
        from app.models.client_sales_invoice import ClientSalesInvoice

        return await db.scalar(
            select(ClientSalesInvoice).where(
                ClientSalesInvoice.invoice_number == "FS 10/118/2026"
            )
        )


async def test_ebi24_payment_mirrors_state_and_is_revoked_when_withdrawn(client, seed):
    finance = seed.users["finance"]
    invoice = await _invoice_118()
    paid = _ebi24_header(
        invoice.ksef_number, paid=True, paidDate="2026-11-14T00:00:00.000"
    )
    counts = await _apply_ebi24(
        paid, _ebi24_header("9999999999-20261101-0100AAAAAAAA-00", _id="obcy")
    )
    assert (counts["create"], counts["not_in_nexus"]) == (1, 1)

    tab = (await _tab(client, finance, seed)).json()
    row = fx.as_dict(tab["invoices"], "invoice_number")["FS 10/118/2026"]
    assert (row["payment_status"], row["paid_on"]) == ("paid", "2026-11-14")

    assert (await _apply_ebi24(paid))["keep"] == 1
    assert (await _apply_ebi24(_ebi24_header(invoice.ksef_number)))["revoke"] == 1
    tab = (await _tab(client, finance, seed)).json()
    assert (
        fx.as_dict(tab["invoices"], "invoice_number")["FS 10/118/2026"][
            "payment_status"
        ]
        == "unpaid"
    )
    async with AsyncSessionLocal() as db:
        mirror = await db.scalar(
            select(ClientSalesInvoicePayment).where(
                ClientSalesInvoicePayment.kind == "ebi24"
            )
        )
    assert (mirror.match_status, mirror.ebi24_document_id) == ("ignored", "ebi24doc118")


async def test_statement_credit_replaces_ebi24_payment_without_double_count(
    client, seed
):
    finance = seed.users["finance"]
    invoice = await _invoice_118()
    await _apply_ebi24(
        _ebi24_header(invoice.ksef_number, paid=True, paidDate="2026-11-14")
    )

    result = (await _upload(client, finance, STATEMENT.read_bytes())).json()
    # Uznanie dopasowane jak bez eBI24 — nie „już opłacona”.
    assert (result["matched"], result["unmatched"]) == (3, 1)

    tab = (await _tab(client, finance, seed)).json()
    assert (
        fx.as_dict(tab["invoices"], "invoice_number")["FS 10/118/2026"][
            "payment_status"
        ]
        == "paid"
    )
    async with AsyncSessionLocal() as db:
        mirror = await db.scalar(
            select(ClientSalesInvoicePayment).where(
                ClientSalesInvoicePayment.kind == "ebi24"
            )
        )
    assert mirror.match_status == "ignored"
    # Kolejny przebieg eBI24 nie wraca z zapłatą, bo NEXUS ma własny zapis.
    assert (
        await _apply_ebi24(
            _ebi24_header(invoice.ksef_number, paid=True, paidDate="2026-11-14")
        )
    )["skip"] == 1


async def test_ebi24_run_once_writes_only_in_prod_and_claims_the_hour(
    seed, monkeypatch
):
    from app.services.client_invoicing import ebi24_payments
    from app.services.ebi24.client import DocumentPage
    from app.services.ebi24.environment import Ebi24Config

    invoice = await _invoice_118()
    rows = (_ebi24_header(invoice.ksef_number, paid=True, paidDate="2026-11-14"),)

    class FakeClient:
        def __init__(self, config):
            self.config = config

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return None

        async def list_documents(self, criteria, *, start_row, end_row, sort_by=None):
            return DocumentPage(documents=rows if start_row == 0 else (), total=1)

    def config(mode: str) -> Ebi24Config:
        return Ebi24Config(
            mode=mode,
            user_uuid="00000000-0000-0000-0000-000000000001",  # gitleaks:allow
            account_uuid="00000000-0000-0000-0000-000000000002",  # gitleaks:allow
            communication_key="AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8=",  # gitleaks:allow
            secret_phrase="fikcyjny",
        )

    moment = datetime(2026, 11, 20, 12, 5, tzinfo=timezone.utc)
    monkeypatch.setattr(ebi24_payments, "load_config", lambda: config("uat"))
    async with AsyncSessionLocal() as db:
        assert (await ebi24_payments.run_once(db, client_factory=FakeClient))[
            "reason"
        ] == "not_prod"
        preview = await ebi24_payments.run_once(
            db, dry_run=True, now=moment, client_factory=FakeClient
        )
    assert preview["counts"]["create"] == 1
    async with AsyncSessionLocal() as db:
        assert not await db.scalar(
            select(func.count())
            .select_from(ClientSalesInvoicePayment)
            .where(ClientSalesInvoicePayment.kind == "ebi24")
        )

    monkeypatch.setattr(ebi24_payments, "load_config", lambda: config("prod"))
    async with AsyncSessionLocal() as db:
        done = await ebi24_payments.run_once(db, now=moment, client_factory=FakeClient)
        again = await ebi24_payments.run_once(db, now=moment, client_factory=FakeClient)
        # ``claimed_at`` stawia baza (now()), więc sonda liczy od bieżącej chwili.
        health = await ebi24_payments.health_state(db)
    assert (done["status"], done["counts"]["create"]) == ("done", 1)
    assert again == {"status": "skipped", "reason": "already_ran"}
    assert health == "healthy"


async def _ebi24_rows(kind_status: str = "matched") -> list[ClientSalesInvoicePayment]:
    async with AsyncSessionLocal() as db:
        return list(
            await db.scalars(
                select(ClientSalesInvoicePayment).where(
                    ClientSalesInvoicePayment.kind == "ebi24",
                    ClientSalesInvoicePayment.match_status == kind_status,
                )
            )
        )


async def test_new_ebi24_document_for_same_invoice_replaces_the_old_one(client, seed):
    invoice = await _invoice_118()
    await _apply_ebi24(_ebi24_header(invoice.ksef_number, _id="stary", paid=True))
    counts = await _apply_ebi24(
        _ebi24_header(invoice.ksef_number, _id="nowy", paid=True)
    )
    assert (counts["create"], counts["replaced"]) == (1, 1)
    assert [row.ebi24_document_id for row in await _ebi24_rows()] == ["nowy"]
    tab = (await _tab(client, seed.users["finance"], seed)).json()
    assert (
        fx.as_dict(tab["invoices"], "invoice_number")["FS 10/118/2026"][
            "payment_status"
        ]
        == "paid"
    )


async def test_manual_paid_overrides_ebi24_payment(client, seed):
    finance = fx.headers(seed.users["finance"])
    invoice = await fx.invoice(fx.KSEF_121)
    await _apply_ebi24(
        _ebi24_header(invoice.ksef_number, _id="ebi121", grossAmount=3926160, paid=True)
    )
    paid = await client.post(
        f"{FINANCE}/{invoice.id}/mark-paid",
        json={"amount": "39261.60", "paid_on": "2026-11-19", "reason": "Kompensata"},
        headers=finance,
    )
    assert paid.status_code == 200, paid.text
    assert paid.json()["payment_status"] == "paid"
    assert await _ebi24_rows() == []


async def test_assigning_a_credit_replaces_ebi24_payment_and_keeps_the_hint(
    client, seed
):
    finance = seed.users["finance"]
    await _upload(client, finance, STATEMENT.read_bytes())
    (pending,) = (
        await client.get(f"{FINANCE}/credits", headers=fx.headers(finance))
    ).json()["credits"]
    hint = pending["hints"][0]
    async with AsyncSessionLocal() as db:
        from app.models.client_sales_invoice import ClientSalesInvoice

        target = await db.get(ClientSalesInvoice, hint["invoice_id"])
    await _apply_ebi24(
        _ebi24_header(
            target.ksef_number,
            _id="ebi-hint",
            paid=True,
            grossAmount=int(Decimal(hint["to_pay"]) * 100),
        )
    )
    (still,) = (
        await client.get(f"{FINANCE}/credits", headers=fx.headers(finance))
    ).json()["credits"]
    assert [h["invoice_id"] for h in still["hints"]] == [hint["invoice_id"]]
    assigned = await client.post(
        f"{FINANCE}/credits/{pending['id']}/assign",
        json={"invoice_id": hint["invoice_id"]},
        headers=fx.headers(finance),
    )
    assert assigned.status_code == 200
    detail = (
        await client.get(f"{FINANCE}/{hint['invoice_id']}", headers=fx.headers(finance))
    ).json()
    assert detail["payment_status"] == "paid"
    assert await _ebi24_rows() == []
