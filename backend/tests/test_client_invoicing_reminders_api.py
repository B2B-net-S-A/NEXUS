"""„Przygotuj monit” i lista na zamknięcie miesiąca — trasy Finansów (z bazą).

Szkic nic nie wysyła; wysyłka tylko na adres z listy szkicu i tylko przez
``services.email.send_email``; ślad w Historii zdarzeń. Lista dla księgowej na
ostatni dzień miesiąca. Reguła: ``docs/claude/zamowienia/monity-i-naleznosci-po-terminie.md``.
Dane fikcyjne.
"""

from __future__ import annotations

import io
import uuid
from datetime import date, datetime, timezone

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from openpyxl import load_workbook
from sqlalchemy import delete, select

from app.api import client_sales_invoices as api
from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.app_setting import AppSetting
from app.models.contact import Contact
from app.models.critical_event import CriticalEvent
from app.models.ledger import LedgerBankStatement
from app.services import email as email_service
from app.services.client_invoicing import payment_reminders, sync
from app.services.hr.bank.accounts import iban_check_digits
from tests.client_invoicing import helpers as fx

pytestmark = pytest.mark.asyncio

FINANCE = "/api/finance/sales-invoices"
TODAY = date(2026, 11, 20)


@pytest_asyncio.fixture
async def client():
    target = FastAPI()
    target.include_router(api.finance_router, prefix=FINANCE)
    async with AsyncClient(
        transport=ASGITransport(app=target), base_url="http://testserver"
    ) as http:
        yield http


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


@pytest_asyncio.fixture
async def seed(monkeypatch):
    """Październik z fixture E8 i ciągłe wyciągi rachunku PLN od 02.11 do 19.11."""

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
    bban = "10901056" + f"{uuid.uuid4().int % 10**16:016d}"
    account = iban_check_digits(bban) + bban
    previous = {key: await _setting(key) for key in ("client_invoice_issue", "ledger")}
    await _put_setting(
        "client_invoice_issue",
        {
            "accounts": {"PLN": {"number": f"PL{account}"}},
            "seller": {"name": "Spółka Testowa"},
        },
    )
    await _put_setting(
        "ledger",
        {
            "bank": {
                "accounts": [{"number": account, "account": "130-1", "currency": "PLN"}]
            }
        },
    )
    ids = []
    async with AsyncSessionLocal() as db:
        for start, end, opening, closing in (
            (date(2026, 11, 2), date(2026, 11, 12), 0, 50_000),
            (date(2026, 11, 13), date(2026, 11, 19), 50_000, 90_000),
        ):
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
        db.add_all(
            [
                Contact(
                    client_id=data.client_id,
                    name="Dział płatności",
                    email="ap@example.com",
                    department="Finanse",
                ),
                Contact(
                    client_id=data.client_id,
                    name="Kierownik projektu",
                    email="pm@example.com",
                    department="IT",
                ),
            ]
        )
        await db.commit()
    data.account = account
    yield data
    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(LedgerBankStatement).where(LedgerBankStatement.id.in_(ids))
        )
        await db.execute(delete(Contact).where(Contact.client_id == data.client_id))
        await db.execute(
            delete(CriticalEvent).where(
                CriticalEvent.event_type == payment_reminders.EVENT_TYPE,
                CriticalEvent.client_id == data.client_id,
            )
        )
        await db.commit()
    for key, value in previous.items():
        await _put_setting(key, value)
    await fx.wipe()
    await fx.set_module(None)


async def test_draft_lists_overdue_invoices_with_finance_contacts(client, seed):
    finance = fx.headers(seed.users["finance"])
    response = await client.get(
        f"{FINANCE}/overdue/reminder",
        params={"client_id": seed.client_id},
        headers=finance,
    )
    assert response.status_code == 200, response.text
    draft = response.json()

    # Terminy 10, 17 i 18.11, wyciągi do 19.11: 9, 2 i 1 dzień — poziom z 9 dni.
    assert [(i["invoice_number"], i["overdue_days"]) for i in draft["invoices"]] == [
        ("FS 10/121/2026", 9),
        ("FS 10/118/2026", 2),
        ("FS 10/124/2026", 1),
    ]
    assert draft["level"] == "first"
    assert [r["email"] for r in draft["recipients"]] == ["ap@example.com"]
    assert draft["subject"].startswith("Przypomnienie o płatności — 3 faktury")
    assert "FS 10/121/2026" in draft["text"]
    assert f"PLN: PL{seed.account}" in draft["text"]
    assert draft["text"].rstrip().endswith("Spółka Testowa")
    assert draft["last_sent_at"] is None


async def test_only_finance_reads_and_sends_reminders(client, seed):
    for role in ("dl", "recruiter"):
        response = await client.get(
            f"{FINANCE}/overdue/reminder",
            params={"client_id": seed.client_id},
            headers=fx.headers(seed.users[role]),
        )
        assert response.status_code == 403, role
        response = await client.post(
            f"{FINANCE}/overdue/reminder",
            json={
                "client_id": seed.client_id,
                "to": ["ap@example.com"],
                "subject": "x" * 5,
                "text": "x" * 5,
            },
            headers=fx.headers(seed.users[role]),
        )
        assert response.status_code == 403, role


async def test_send_goes_only_to_listed_recipients_and_leaves_a_trace(
    client, seed, monkeypatch
):
    sent: list[tuple[str, str, str | None]] = []

    def fake_send(to, subject, text_body, html_body=None, reply_to=None, **_):
        sent.append((to, subject, reply_to))
        return True

    monkeypatch.setattr(email_service, "send_email", fake_send)
    finance_user = seed.users["finance"]
    finance = fx.headers(finance_user)
    draft = (
        await client.get(
            f"{FINANCE}/overdue/reminder",
            params={"client_id": seed.client_id},
            headers=finance,
        )
    ).json()
    body = {
        "client_id": seed.client_id,
        "subject": draft["subject"],
        "text": draft["text"] + "\nDopisek osoby z Finansów.",
    }

    # Kontakt spoza działu finansów nie jest na liście — serwer odmawia.
    refused = await client.post(
        f"{FINANCE}/overdue/reminder",
        json={**body, "to": ["pm@example.com"]},
        headers=finance,
    )
    assert refused.status_code == 422
    assert sent == []

    response = await client.post(
        f"{FINANCE}/overdue/reminder",
        json={**body, "to": ["AP@example.com"]},
        headers=finance,
    )
    assert response.status_code == 200, response.text
    assert response.json() == {"sent": 1, "failed": 0, "level": "first"}
    assert sent == [("ap@example.com", draft["subject"], finance_user.email)]

    async with AsyncSessionLocal() as db:
        events = list(
            await db.scalars(
                select(CriticalEvent).where(
                    CriticalEvent.event_type == payment_reminders.EVENT_TYPE,
                    CriticalEvent.client_id == seed.client_id,
                )
            )
        )
    assert len(events) == 1
    assert events[0].details["level"] == "first"
    assert events[0].details["recipients"] == 1
    again = (
        await client.get(
            f"{FINANCE}/overdue/reminder",
            params={"client_id": seed.client_id},
            headers=finance,
        )
    ).json()
    assert again["last_sent_at"] is not None
    assert again["last_level"] == "first"


async def test_failed_channel_is_reported_without_a_trace(client, seed, monkeypatch):
    monkeypatch.setattr(email_service, "send_email", lambda *a, **k: False)
    finance = fx.headers(seed.users["finance"])
    draft = (
        await client.get(
            f"{FINANCE}/overdue/reminder",
            params={"client_id": seed.client_id},
            headers=finance,
        )
    ).json()
    response = await client.post(
        f"{FINANCE}/overdue/reminder",
        json={
            "client_id": seed.client_id,
            "to": ["ap@example.com"],
            "subject": draft["subject"],
            "text": draft["text"],
        },
        headers=finance,
    )
    assert response.json() == {"sent": 0, "failed": 1, "level": "first"}
    async with AsyncSessionLocal() as db:
        assert (
            await db.scalar(
                select(CriticalEvent.id).where(
                    CriticalEvent.event_type == payment_reminders.EVENT_TYPE,
                    CriticalEvent.client_id == seed.client_id,
                )
            )
        ) is None


async def test_client_without_proven_overdue_gets_no_reminder(client, seed):
    finance = fx.headers(seed.users["finance"])
    draft = (
        await client.get(
            f"{FINANCE}/overdue/reminder",
            params={"client_id": seed.other_client_id},
            headers=finance,
        )
    ).json()
    assert (draft["invoices"], draft["level"], draft["text"]) == ([], None, "")
    response = await client.post(
        f"{FINANCE}/overdue/reminder",
        json={
            "client_id": seed.other_client_id,
            "to": ["ap@example.com"],
            "subject": "Monit",
            "text": "Treść monitu",
        },
        headers=finance,
    )
    assert response.status_code == 409


async def test_month_close_list_for_the_accountant(client, seed):
    finance = fx.headers(seed.users["finance"])

    november = await client.get(
        f"{FINANCE}/overdue/month-close",
        params={"month": "2026-11", "format": "xlsx"},
        headers=finance,
    )
    assert november.status_code == 200, november.text
    # Miesiąc trwa: stan na dziś (20.11).
    assert (
        "naleznosci-po-terminie-2026-11-20.xlsx"
        in november.headers["content-disposition"]
    )
    sheet = load_workbook(io.BytesIO(november.content)).active
    rows = list(sheet.iter_rows(values_only=True))
    assert rows[0][2] == "Faktura"
    ours = {"FS 10/121/2026", "FS 10/118/2026", "FS 10/124/2026"}
    # Baza testów jest wspólna: plik ma całą firmę (np. FS 11/7 bez klienta NEXUSA).
    assert [(row[2], row[11]) for row in rows[1:] if row[2] in ours] == [
        ("FS 10/121/2026", 9),
        ("FS 10/118/2026", 2),
        ("FS 10/124/2026", 1),
    ]
    # Najpierw zaległości z dowodem, potem faktury bez danych o zapłacie — bez dni.
    days = [row[11] for row in rows[1:]]
    proven = [d for d in days if d is not None]
    assert days[: len(proven)] == proven
    for row in rows[1:]:
        if row[11] is None:
            assert str(row[13]).startswith("brak danych o zapłacie")
    assert "FS 11/7/2026" in {row[2] for row in rows[1:] if row[11] is None}

    # Na 31.10 żaden termin naszych faktur jeszcze nie minął.
    october = await client.get(
        f"{FINANCE}/overdue/month-close",
        params={"month": "2026-10", "format": "csv"},
        headers=finance,
    )
    assert october.status_code == 200
    lines = october.content.decode("utf-8-sig").strip().splitlines()
    assert lines[0].startswith("Klient;")
    assert not any(number in line for line in lines[1:] for number in ours)

    bad = await client.get(
        f"{FINANCE}/overdue/month-close",
        params={"month": "2026-13"},
        headers=finance,
    )
    assert bad.status_code == 422
    forbidden = await client.get(
        f"{FINANCE}/overdue/month-close",
        params={"month": "2026-11"},
        headers=fx.headers(seed.users["dl"]),
    )
    assert forbidden.status_code == 403
