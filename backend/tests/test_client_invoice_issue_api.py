"""Wystawianie faktur sprzedaży z NEXUSA do KSeF (E4) — trasy, numeracja, wysyłka.

Zakres: tylko „Moduł Finanse” (rekruter, Delivery Lead — 403), ustawienia
sprzedawcy i serii, szkice z „Do faktury” (brak zużycia MD blokuje),
wyłączona wysyłka (bez numeru), pełna ścieżka z fałszywym KSeF (numer z serii
dopiero przy wysyłce, wpis w ``client_sales_invoices`` z tym samym numerem
KSeF i powiązaniem ``issued``), odrzucenie (numer zostaje, ponowna wysyłka
z tym samym numerem), wycofanie odrzuconej (ostatni numer wraca, wcześniejszy
zostaje jako ślad), równoległe nadanie numeru, korekta, zaliczkowa, EUR
z kursem NBP, logowanie certyfikatem przed tokenem. Dane fikcyjne.
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from lxml import etree
from sqlalchemy import delete, func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError

from app.api import client_issued_invoices as api
from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.app_setting import AppSetting
from app.models.client import Client
from app.models.client_issued_invoice import ClientInvoiceSeries, ClientIssuedInvoice
from app.models.client_sales_invoice import ClientSalesInvoice, ClientSalesInvoiceLink
from app.models.contract import RateUnit
from app.models.fx_rate import FxRate
from app.services.client_invoicing import issue, issue_settings, ksef_send, numbering
from app.services.hr.ksef import numbers
from app.services.hr.ksef.client import forget_sessions
from tests._ksef_fake import Clock
from tests.client_invoicing import helpers as fx
from tests.client_invoicing.ksef_issue_fake import (
    TOKEN,
    UPO,
    FakeKsefIssue,
    factory,
    seal_pem,
)

pytestmark = pytest.mark.asyncio

BASE = "/api/finance/issued-invoices"
TODAY = date(2026, 11, 20)
OCTOBER = {"year": 2026, "month": 10}
SETTINGS = {
    "seller": {
        "name": "Spółka Testowa sp. z o.o.",
        "nip": fx.COMPANY_NIP,
        "address_l1": "ul. Testowa 10, 00-001 Warszawa",
        "issue_place": "Warszawa",
    },
    "accounts": {
        "PLN": {
            "number": "PL61 1090 1014 0000 0712 1981 2874",
            "bank": "Bank Przykładowy",
        },
        "EUR": {"number": "PL27114020040000300201355387", "swift": "BREXPLPW"},
    },
    "payment_days": 14,
    "default_vat": "23",
    "series": {},
    "clients": {},
}
BUYER = {"address_l1": "ul. Przykładowa 5, 00-002 Warszawa"}


@pytest_asyncio.fixture
async def client():
    target = FastAPI()
    target.include_router(api.router, prefix=BASE)
    async with AsyncClient(
        transport=ASGITransport(app=target), base_url="http://testserver"
    ) as http:
        yield http


async def _cleanup(client_ids: list[int]) -> None:
    async with AsyncSessionLocal() as db:
        scope = ClientIssuedInvoice.client_id.in_(client_ids)
        await db.execute(
            delete(ClientIssuedInvoice).where(
                scope, ClientIssuedInvoice.corrects_id.is_not(None)
            )
        )
        await db.execute(delete(ClientIssuedInvoice).where(scope))
        await db.execute(
            delete(ClientInvoiceSeries).where(ClientInvoiceSeries.period_year == 2026)
        )
        await db.execute(
            delete(AppSetting).where(AppSetting.key == issue_settings.SETTING_KEY)
        )
        await db.commit()


@pytest_asyncio.fixture
async def seed(monkeypatch):
    monkeypatch.setattr(api, "business_today", lambda: TODAY)
    monkeypatch.setattr(settings, "KSEF_CONTEXT_NIP", fx.COMPANY_NIP)
    monkeypatch.setattr(settings, "KSEF_SALES_ISSUE_MODE", "test")
    monkeypatch.setattr(settings, "KSEF_SALES_ISSUE_TOKEN", TOKEN)
    monkeypatch.setattr(settings, "KSEF_TOKEN", "")
    for name in (
        "KSEF_CERTIFICATE",
        "KSEF_CERTIFICATE_KEY",
        "KSEF_CERTIFICATE_KEY_PASSWORD",
    ):
        monkeypatch.setattr(settings, name, "")
    forget_sessions()
    fake = FakeKsefIssue(Clock())
    fake.invoice_codes = [200]
    monkeypatch.setattr(ksef_send, "default_client", factory(fake))
    data = await fx.seed_month()
    data.fake = fake  # type: ignore[attr-defined]
    await fx.set_module(True)
    await _cleanup([data.client_id, data.other_client_id])
    yield data
    await _cleanup([data.client_id, data.other_client_id])
    await fx.wipe()
    await fx.set_module(None)
    forget_sessions()


def _h(seed, role: str = "finance") -> dict[str, str]:
    return fx.headers(seed.users[role])


async def _settings(client, seed, **changes) -> None:
    response = await client.put(
        f"{BASE}/settings", json={**SETTINGS, **changes}, headers=_h(seed)
    )
    assert response.status_code == 200, response.text


async def _draft(client, seed, key: str, **body) -> int:
    response = await client.post(
        f"{BASE}/drafts",
        json={**OCTOBER, "keys": [key], **body},
        headers=_h(seed),
    )
    assert response.status_code == 201, response.text
    (invoice_id,) = response.json()["created"]
    ready = await client.put(
        f"{BASE}/{invoice_id}", json={"buyer": BUYER}, headers=_h(seed)
    )
    assert ready.status_code == 200, ready.text
    return invoice_id


async def _send(client, seed, invoice_id: int) -> dict:
    response = await client.post(f"{BASE}/{invoice_id}/send", headers=_h(seed))
    assert response.status_code == 200, response.text
    return response.json()


# ── Dostęp ──────────────────────────────────────────────────────────────────


async def test_only_finance_module_issues_invoices(client, seed):
    for role in ("recruiter", "dl", "tcm"):
        for method, path in (
            ("GET", f"{BASE}/to-issue"),
            ("GET", f"{BASE}/settings"),
            ("GET", BASE),
            ("POST", f"{BASE}/drafts"),
            ("POST", f"{BASE}/1/send"),
        ):
            response = await client.request(
                method,
                path,
                json={**OCTOBER, "keys": ["g1"]} if method == "POST" else None,
                headers=_h(seed, role),
            )
            assert response.status_code == 403, (role, path, response.text)
    assert (
        await client.get(f"{BASE}/to-issue", params=OCTOBER, headers=_h(seed))
    ).status_code == 200
    assert (
        await client.get(f"{BASE}/settings", headers=_h(seed, "admin"))
    ).status_code == 200


async def test_module_off_hides_issuing_except_for_admin(client, seed):
    await fx.set_module(False)
    off = await client.get(f"{BASE}/to-issue", params=OCTOBER, headers=_h(seed))
    assert off.status_code == 404
    assert (
        await client.get(f"{BASE}/to-issue", params=OCTOBER, headers=_h(seed, "admin"))
    ).status_code == 200


# ── Ustawienia i serie ──────────────────────────────────────────────────────


async def test_settings_validate_and_series_continue_numbering(client, seed):
    bad = await client.put(
        f"{BASE}/settings",
        json={**SETTINGS, "seller": {**SETTINGS["seller"], "nip": "1234567890"}},
        headers=_h(seed),
    )
    assert bad.status_code == 422
    assert "sumę kontrolną" in bad.json()["detail"]
    pattern = await client.put(
        f"{BASE}/settings",
        json={**SETTINGS, "series": {"PL": "FV/{n}"}},
        headers=_h(seed),
    )
    assert pattern.status_code == 422

    await _settings(client, seed, clients={str(seed.client_id): {"vat_rate": "8"}})
    got = (await client.get(f"{BASE}/settings", headers=_h(seed))).json()
    assert (
        got["settings"]["accounts"]["PLN"]["number"] == "PL61109010140000071219812874"
    )
    assert got["settings"]["clients"][str(seed.client_id)] == {"vat_rate": "8"}
    assert got["missing"] == []
    assert got["ksef"]["enabled"] is True

    moved = await client.put(
        f"{BASE}/series/PL",
        json={"year": 2026, "month": 11, "next_number": 113},
        headers=_h(seed),
    )
    assert moved.status_code == 200, moved.text
    pl = next(row for row in moved.json()["series"] if row["code"] == "PL")
    assert pl["next_label"] == "113/11/2026"

    # Per-klient 8% trafia do nowego szkicu, a numer z serii — dopiero do wysłanej faktury.
    invoice_id = await _draft(client, seed, f"g{seed.groups['118']}")
    card = (await client.get(f"{BASE}/{invoice_id}", headers=_h(seed))).json()
    assert card["invoice_number"] is None
    assert {line["vat_rate"] for line in card["lines"]} == {"8"}
    sent = await _send(client, seed, invoice_id)
    assert sent["invoice_number"] == "113/11/2026"

    # Nie da się cofnąć „następnego” do numeru już wydanego.
    back = await client.put(
        f"{BASE}/series/PL",
        json={"year": 2026, "month": 11, "next_number": 113},
        headers=_h(seed),
    )
    assert back.status_code == 409


# ── Szkice ──────────────────────────────────────────────────────────────────


async def test_drafts_from_month_and_missing_md_blocks(client, seed):
    async with AsyncSessionLocal() as db:
        waiting, _ = await fx.md_group(
            db,
            seed.client_id,
            "ZAM/2026/140",
            people=[("Ola", "Bezzużycia", "1000", None)],
        )
        await db.commit()
    listing = (
        await client.get(f"{BASE}/to-issue", params=OCTOBER, headers=_h(seed))
    ).json()
    rows = {
        row["key"]: row
        for entry in listing["clients"]
        if entry["client_id"] == seed.client_id
        for row in entry["rows"]
    }
    assert rows[f"g{waiting}"]["blocked"].startswith("Brak kwoty pozycji")
    assert rows[f"g{seed.groups['118']}"]["expected_net"] == "25200.00"

    blocked = await client.post(
        f"{BASE}/drafts",
        json={**OCTOBER, "keys": [f"g{waiting}"]},
        headers=_h(seed),
    )
    assert blocked.status_code == 409
    assert "Ola Bezzużycia" in blocked.json()["detail"]

    invoice_id = await _draft(client, seed, f"g{seed.groups['118']}")
    card = (await client.get(f"{BASE}/{invoice_id}", headers=_h(seed))).json()
    assert card["status"] == "draft"
    assert card["net"] == "25200.00" and card["gross"] == "30996.00"
    assert card["client_order_number"] == "ZAM/2026/118"
    assert card["period_from"] == "2026-10-01" and card["period_to"] == "2026-10-31"
    assert card["due_date"] == "2026-12-04"
    (line,) = card["lines"]
    assert line["consultant"] == "Jan Przykładowy"
    assert (line["quantity"], line["unit"], line["unit_price"]) == ("21", "MD", "1200")
    assert "Jan Przykładowy" in line["name"]

    again = await client.post(
        f"{BASE}/drafts",
        json={**OCTOBER, "keys": [f"g{seed.groups['118']}"]},
        headers=_h(seed),
    )
    assert again.status_code == 409
    assert "ma już fakturę" in again.json()["detail"]

    edited = await client.put(
        f"{BASE}/{invoice_id}",
        json={
            "lines": [
                {**line, "quantity": "20"},
                {
                    "name": "Dodatkowa usługa",
                    "quantity": "1",
                    "unit_price": "500",
                    "vat_rate": "23",
                },
            ],
            "notes": "Uwagi testowe",
        },
        headers=_h(seed),
    )
    assert edited.status_code == 200
    assert edited.json()["net"] == "24500.00"


async def test_deleting_a_draft_leaves_no_gap(client, seed):
    await _settings(client, seed)
    first = await _draft(client, seed, f"g{seed.groups['118']}")
    second = await _draft(client, seed, f"g{seed.groups['124']}")
    deleted = await client.delete(f"{BASE}/{first}", headers=_h(seed))
    assert deleted.json() == {"result": "deleted"}
    sent = await _send(client, seed, second)
    assert sent["invoice_number"] == "1/11/2026"


async def test_send_is_disabled_without_issue_mode(client, seed, monkeypatch):
    await _settings(client, seed)
    monkeypatch.setattr(settings, "KSEF_SALES_ISSUE_MODE", "off")
    invoice_id = await _draft(client, seed, f"g{seed.groups['118']}")
    card = (await client.get(f"{BASE}/{invoice_id}", headers=_h(seed))).json()
    assert card["can_send"] is False
    refused = await client.post(f"{BASE}/{invoice_id}/send", headers=_h(seed))
    assert refused.status_code == 409
    assert "KSEF_SALES_ISSUE_MODE=off" in refused.json()["detail"]
    after = (await client.get(f"{BASE}/{invoice_id}", headers=_h(seed))).json()
    assert after["invoice_number"] is None and after["status"] == "draft"


async def test_incomplete_draft_is_not_numbered(client, seed):
    invoice_id = await _draft(client, seed, f"g{seed.groups['118']}")
    refused = await client.post(f"{BASE}/{invoice_id}/send", headers=_h(seed))
    assert refused.status_code == 422
    assert "Ustawienia wystawiania: brak" in refused.json()["detail"]
    async with AsyncSessionLocal() as db:
        assert (
            await db.scalar(select(func.count()).select_from(ClientInvoiceSeries)) == 0
        )


# ── Wysyłka ─────────────────────────────────────────────────────────────────


async def test_accepted_invoice_joins_ksef_sales_and_order(client, seed):
    await _settings(client, seed)
    invoice_id = await _draft(client, seed, f"g{seed.groups['118']}")
    card = await _send(client, seed, invoice_id)
    assert card["status"] == "accepted", card
    assert card["invoice_number"] == "1/11/2026"
    assert card["has_upo"] is True
    assert card["can_correct"] is True
    ksef_number = card["ksef_number"]
    assert ksef_number.startswith(fx.COMPANY_NIP)

    (xml,) = seed.fake.received
    # Bez certyfikatu po staremu: token.
    assert seed.fake.count("POST", "/auth/ksef-token") == 1
    assert seed.fake.count("POST", "/auth/xades-signature") == 0
    root = etree.fromstring(xml)
    assert root.findtext("{*}Fa/{*}P_2") == "1/11/2026"
    assert root.findtext("{*}Podmiot2/{*}DaneIdentyfikacyjne/{*}NIP") == fx.CLIENT_NIP

    async with AsyncSessionLocal() as db:
        sales = list(
            await db.scalars(
                select(ClientSalesInvoice).where(
                    ClientSalesInvoice.ksef_number == ksef_number
                )
            )
        )
        assert len(sales) == 1
        assert sales[0].id == card["sales_invoice_id"]
        assert sales[0].match_status == "matched"
        assert sales[0].match_method == "issued"
        assert sales[0].client_id == seed.client_id
        links = list(
            await db.scalars(
                select(ClientSalesInvoiceLink).where(
                    ClientSalesInvoiceLink.invoice_id == sales[0].id
                )
            )
        )
        assert [(link.order_group_id, link.period_month) for link in links] == [
            (seed.groups["118"], 10)
        ]
        # Ponowne powiązanie (np. odczyt z KSeF był szybszy) nie robi duplikatu.
        invoice = await db.get(ClientIssuedInvoice, invoice_id)
        await issue.link_sales_invoice(db, invoice, actor_id=None)
        await db.commit()
        assert (
            await db.scalar(
                select(func.count()).where(
                    ClientSalesInvoice.ksef_number == ksef_number
                )
            )
            == 1
        )

    upo = await client.get(f"{BASE}/{invoice_id}/upo", headers=_h(seed))
    assert upo.content == UPO
    xml_file = await client.get(f"{BASE}/{invoice_id}/xml", headers=_h(seed))
    assert xml_file.content == xml
    sent_list = (
        await client.get(BASE, params={"view": "sent"}, headers=_h(seed))
    ).json()
    assert [row["id"] for row in sent_list["invoices"]] == [invoice_id]
    locked = await client.put(
        f"{BASE}/{invoice_id}", json={"notes": "x"}, headers=_h(seed)
    )
    assert locked.status_code == 409


def _certificate(monkeypatch, seed) -> None:
    certificate, key = seal_pem(seed.fake.clock)
    monkeypatch.setattr(settings, "KSEF_CERTIFICATE", certificate)
    monkeypatch.setattr(settings, "KSEF_CERTIFICATE_KEY", key)


async def test_certificate_wins_over_token_when_sending(client, seed, monkeypatch):
    _certificate(monkeypatch, seed)
    await _settings(client, seed)
    invoice_id = await _draft(client, seed, f"g{seed.groups['118']}")
    card = await _send(client, seed, invoice_id)
    assert card["status"] == "accepted", card
    assert seed.fake.count("POST", "/auth/xades-signature") == 1
    assert seed.fake.count("POST", "/auth/ksef-token") == 0
    assert seed.fake.decrypted == []


async def test_certificate_alone_sends_without_token(client, seed, monkeypatch):
    monkeypatch.setattr(settings, "KSEF_SALES_ISSUE_TOKEN", "")
    _certificate(monkeypatch, seed)
    await _settings(client, seed)
    status = (await client.get(f"{BASE}/settings", headers=_h(seed))).json()
    assert status["ksef"]["enabled"] is True
    invoice_id = await _draft(client, seed, f"g{seed.groups['118']}")
    card = await _send(client, seed, invoice_id)
    assert card["status"] == "accepted", card
    assert seed.fake.count("POST", "/auth/ksef-token") == 0


async def test_send_without_token_and_certificate_names_both(client, seed, monkeypatch):
    monkeypatch.setattr(settings, "KSEF_SALES_ISSUE_TOKEN", "")
    await _settings(client, seed)
    invoice_id = await _draft(client, seed, f"g{seed.groups['118']}")
    refused = await client.post(f"{BASE}/{invoice_id}/send", headers=_h(seed))
    assert refused.status_code == 409
    detail = refused.json()["detail"]
    assert "KSEF_CERTIFICATE" in detail and "KSEF_SALES_ISSUE_TOKEN" in detail
    assert seed.fake.calls == []


async def test_rejected_invoice_keeps_number_and_resends_with_it(client, seed):
    await _settings(client, seed)
    invoice_id = await _draft(client, seed, f"g{seed.groups['118']}")
    seed.fake.invoice_codes = [450]
    rejected = await _send(client, seed, invoice_id)
    assert rejected["status"] == "rejected"
    assert rejected["invoice_number"] == "1/11/2026"
    assert "kod 450" in rejected["ksef_status_text"]
    assert rejected["editable"] is True

    seed.fake.invoice_codes = [200]
    accepted = await _send(client, seed, invoice_id)
    assert accepted["status"] == "accepted"
    assert accepted["invoice_number"] == "1/11/2026"
    async with AsyncSessionLocal() as db:
        series = await db.get(ClientInvoiceSeries, ("PL", 2026, 11))
        assert series.next_number == 2


async def test_withdrawing_rejected_invoice_releases_only_the_last_number(client, seed):
    await _settings(client, seed)
    first = await _draft(client, seed, f"g{seed.groups['118']}")
    second = await _draft(client, seed, f"g{seed.groups['124']}")
    third = await _draft(client, seed, f"g{seed.groups['130']}")
    seed.fake.invoice_codes = [450]
    assert (await _send(client, seed, first))["invoice_number"] == "1/11/2026"
    seed.fake.invoice_codes = [200]
    assert (await _send(client, seed, second))["invoice_number"] == "2/11/2026"

    # 1/11/2026 nie jest ostatni — zostaje jako ślad niewykorzystanego numeru.
    cancelled = await client.delete(f"{BASE}/{first}", headers=_h(seed))
    assert cancelled.json() == {"result": "cancelled"}
    card = (await client.get(f"{BASE}/{first}", headers=_h(seed))).json()
    assert card["status"] == "cancelled"
    assert "1/11/2026 niewykorzystany" in card["ksef_status_text"]

    seed.fake.invoice_codes = [450]
    assert (await _send(client, seed, third))["invoice_number"] == "3/11/2026"
    released = await client.delete(f"{BASE}/{third}", headers=_h(seed))
    assert released.json() == {"result": "deleted"}
    async with AsyncSessionLocal() as db:
        series = await db.get(ClientInvoiceSeries, ("PL", 2026, 11))
        assert series.next_number == 3

    accepted = await client.delete(f"{BASE}/{second}", headers=_h(seed))
    assert accepted.status_code == 409


async def test_parallel_numbering_waits_on_series_lock(client, seed):
    ids = [
        await _draft(client, seed, f"g{seed.groups['118']}"),
        await _draft(client, seed, f"g{seed.groups['124']}"),
        await _draft(client, seed, f"g{seed.groups['130']}"),
    ]

    async def number(invoice_id: int) -> int:
        async with AsyncSessionLocal() as db:
            invoice = await db.get(ClientIssuedInvoice, invoice_id)
            invoice.status = "sending"
            await numbering.assign(db, invoice, pattern="{n}/{mm}/{yyyy}")
            # Druga transakcja czeka na blokadę wiersza serii aż do commita.
            await asyncio.sleep(0.2)
            await db.commit()
            return int(invoice.number_seq)

    assigned = await asyncio.gather(*(number(invoice_id) for invoice_id in ids))
    assert sorted(assigned) == [1, 2, 3]

    async with AsyncSessionLocal() as db:
        duplicate = await db.get(ClientIssuedInvoice, ids[0])
        other = await db.get(ClientIssuedInvoice, ids[1])
        other.number_seq = duplicate.number_seq
        other.invoice_number = duplicate.invoice_number
        with pytest.raises(IntegrityError):
            await db.flush()
        await db.rollback()


async def test_parallel_drafts_for_the_same_order_make_one_invoice(seed, monkeypatch):
    # Dwa równoległe „Wystaw za miesiąc” za to samo zamówienie (audyt 24.11.2026):
    # oba czytały istniejące faktury, zanim drugie wstawiło szkic, i do KSeF szły
    # dwie FV VAT za ten sam miesiąc. Bariera trzyma pierwszy odczyt, aż drugi
    # bieg dojdzie do swojego (bez blokady) albo minie sekunda (z blokadą drugi
    # czeka na nią przed odczytem).
    key = f"g{seed.groups['118']}"
    original = issue._existing_by_key
    arrived: list[int] = []
    both = asyncio.Event()

    async def held(db, year, month):
        found = await original(db, year, month)
        arrived.append(1)
        if len(arrived) == 2:
            both.set()
        try:
            await asyncio.wait_for(both.wait(), timeout=1)
        except asyncio.TimeoutError:
            pass
        return found

    monkeypatch.setattr(issue, "_existing_by_key", held)

    async def draft() -> object:
        async with AsyncSessionLocal() as db:
            try:
                created = await issue.create_drafts(
                    db,
                    **OCTOBER,
                    keys=[key],
                    split="order",
                    actor_id=seed.users["finance"].id,
                    today=TODAY,
                )
            except issue.IssueError as exc:
                await db.rollback()
                return exc
            await db.commit()
            return [invoice.id for invoice in created]

    results = await asyncio.gather(draft(), draft())
    refused = [r for r in results if isinstance(r, issue.IssueError)]
    assert len(refused) == 1, results
    assert "ma już fakturę" in str(refused[0])
    async with AsyncSessionLocal() as db:
        drafts = await db.scalar(
            select(func.count()).where(
                ClientIssuedInvoice.client_id == seed.client_id,
                ClientIssuedInvoice.period_year == 2026,
                ClientIssuedInvoice.period_month == 10,
                ClientIssuedInvoice.invoice_type == "VAT",
            )
        )
    assert drafts == 1


async def test_correction_of_accepted_invoice(client, seed):
    await _settings(client, seed)
    original_id = await _draft(client, seed, f"g{seed.groups['118']}")
    original = await _send(client, seed, original_id)
    created = await client.post(
        f"{BASE}/{original_id}/correction",
        json={"reason": "Zużycie MD po weryfikacji klienta"},
        headers=_h(seed),
    )
    assert created.status_code == 201, created.text
    correction = created.json()
    assert correction["invoice_type"] == "KOR"
    assert correction["corrects"] == {"id": original_id, "invoice_number": "1/11/2026"}
    assert "Korekta nie zmienia żadnej pozycji." in correction["problems"]

    line = {**correction["lines"][0], "quantity": "20"}
    await client.put(
        f"{BASE}/{correction['id']}", json={"lines": [line]}, headers=_h(seed)
    )
    sent = await _send(client, seed, correction["id"])
    assert sent["status"] == "accepted", sent
    assert sent["invoice_number"] == "KOR/1/11/2026"
    assert sent["net"] == "-1200.00"
    xml = seed.fake.received[-1]
    data = etree.fromstring(xml).find("{*}Fa/{*}DaneFaKorygowanej")
    assert data.findtext("{*}NrKSeFFaKorygowanej") == original["ksef_number"]
    async with AsyncSessionLocal() as db:
        stored = await db.get(ClientSalesInvoice, sent["sales_invoice_id"])
        assert stored.invoice_kind == "correction"
        assert stored.corrects_invoice_id == original["sales_invoice_id"]
        assert stored.match_method == "correction"


async def test_parallel_corrections_make_one_draft(client, seed, monkeypatch):
    # Dwa równoległe „Wystaw korektę” do tej samej faktury (audyt r5, 25.11.2026):
    # oba czytały „korekta w toku” bez blokady, zanim drugie wstawiło szkic,
    # i powstawały dwa szkice KOR. Bariera na wczytaniu ustawień (zaraz po tym
    # sprawdzeniu) trzyma pierwsze żądanie, aż drugie dojdzie do swojego (bez
    # blokady) albo minie sekunda (z blokadą drugie czeka na fakturę).
    await _settings(client, seed)
    original_id = await _draft(client, seed, f"g{seed.groups['118']}")
    await _send(client, seed, original_id)

    original_load = issue_settings.load
    arrived: list[int] = []
    both = asyncio.Event()

    async def held(db, **kwargs):
        found = await original_load(db, **kwargs)
        arrived.append(1)
        if len(arrived) == 2:
            both.set()
        try:
            await asyncio.wait_for(both.wait(), timeout=1)
        except asyncio.TimeoutError:
            pass
        return found

    monkeypatch.setattr(issue_settings, "load", held)

    async def correct():
        return await client.post(
            f"{BASE}/{original_id}/correction",
            json={"reason": "Zużycie MD po weryfikacji klienta"},
            headers=_h(seed),
        )

    responses = await asyncio.gather(correct(), correct())
    codes = sorted(r.status_code for r in responses)
    assert codes == [201, 409], [r.text for r in responses]
    refused = next(r for r in responses if r.status_code == 409)
    assert "korektę w toku" in refused.json()["detail"]
    async with AsyncSessionLocal() as db:
        corrections = await db.scalar(
            select(func.count()).where(ClientIssuedInvoice.corrects_id == original_id)
        )
    assert corrections == 1


async def test_advance_invoice_minimal(client, seed):
    await _settings(client, seed)
    created = await client.post(
        f"{BASE}/advance",
        json={
            "client_id": seed.client_id,
            "currency": "PLN",
            "received_on": "2026-11-18",
        },
        headers=_h(seed),
    )
    assert created.status_code == 201, created.text
    advance = created.json()
    assert advance["invoice_type"] == "ZAL" and advance["series_code"] == "ZAL"
    line = {**advance["lines"][0], "unit_price": "10000"}
    await client.put(
        f"{BASE}/{advance['id']}",
        json={"lines": [line], "buyer": BUYER},
        headers=_h(seed),
    )
    sent = await _send(client, seed, advance["id"])
    assert sent["invoice_number"] == "ZAL/1/11/2026"
    assert sent["gross"] == "12300.00"
    root = etree.fromstring(seed.fake.received[-1])
    assert root.findtext("{*}Fa/{*}RodzajFaktury") == "ZAL"
    assert root.findtext("{*}Fa/{*}P_6") == "2026-11-18"


async def test_eur_order_takes_nbp_rate_from_day_before_delivery(client, seed):
    async with AsyncSessionLocal() as db:
        order_id = await fx.periodic_order(
            db,
            seed.client_id,
            "ZAM/2026/EUR",
            rate="9000",
            unit=RateUnit.monthly,
            currency="EUR",
        )
        await db.execute(
            insert(FxRate)
            .values(
                currency="EUR",
                effective_date=date(2026, 10, 30),
                rate_to_pln=Decimal("4.2512"),
                source="NBP",
            )
            .on_conflict_do_nothing()
        )
        await db.commit()
        rate = await db.scalar(
            select(FxRate.rate_to_pln).where(
                FxRate.currency == "EUR", FxRate.effective_date == date(2026, 10, 30)
            )
        )
    await _settings(client, seed)
    invoice_id = await _draft(client, seed, f"o{order_id}")
    card = (await client.get(f"{BASE}/{invoice_id}", headers=_h(seed))).json()
    assert card["currency"] == "EUR"
    assert card["fx"]["date"] <= "2026-10-30"
    if card["fx"]["date"] == "2026-10-30":
        assert Decimal(card["fx"]["rate"]) == rate
    sent = await _send(client, seed, invoice_id)
    assert sent["status"] == "accepted", sent
    fa_node = etree.fromstring(seed.fake.received[-1]).find("{*}Fa")
    assert fa_node.findtext("{*}KodWaluty") == "EUR"
    assert fa_node.findtext("{*}P_14_1W") is not None


async def test_failed_link_still_keeps_the_ksef_number(client, seed, monkeypatch):
    async def broken(*_args, **_kwargs):
        raise RuntimeError("awaria powiązania")

    await _settings(client, seed)
    invoice_id = await _draft(client, seed, f"g{seed.groups['118']}")
    monkeypatch.setattr(issue, "link_sales_invoice", broken)
    card = await _send(client, seed, invoice_id)
    assert card["status"] == "accepted"
    assert card["ksef_number"] is not None
    assert card["sales_invoice_id"] is None


# ── Przegląd 13.11: wynik nieznany, duplikat, przerwana wysyłka ─────────────


async def _series_next() -> int:
    async with AsyncSessionLocal() as db:
        series = await db.get(ClientInvoiceSeries, ("PL", 2026, 11))
        return series.next_number


@pytest.mark.parametrize(
    "outcome",
    [lambda: httpx.Response(503), lambda: httpx.ReadTimeout("koniec czasu")],
    ids=["503", "timeout"],
)
async def test_lost_answer_keeps_invoice_in_flight_until_checked(client, seed, outcome):
    await _settings(client, seed)
    invoice_id = await _draft(client, seed, f"g{seed.groups['118']}")
    seed.fake.after_store = [outcome()]
    card = await _send(client, seed, invoice_id)
    # KSeF ma plik — faktura nie wraca do edycji ani do ponownej wysyłki.
    assert card["status"] == "sending"
    assert card["invoice_number"] == "1/11/2026"
    assert card["editable"] is False and card["can_send"] is False
    assert card["can_check"] is True
    assert "nie wysyłaj jej ponownie" in card["ksef_status_text"]
    assert len(seed.fake.received) == 1
    assert (
        await client.delete(f"{BASE}/{invoice_id}", headers=_h(seed))
    ).status_code == 409
    assert (
        await client.post(f"{BASE}/{invoice_id}/send", headers=_h(seed))
    ).status_code == 409
    assert await _series_next() == 2

    checked = await client.post(f"{BASE}/{invoice_id}/check", headers=_h(seed))
    assert checked.status_code == 200, checked.text
    assert checked.json()["status"] == "accepted"
    assert checked.json()["invoice_number"] == "1/11/2026"
    assert len(seed.fake.received) == 1


async def test_duplicate_after_lost_answer_is_not_rejected(client, seed):
    await _settings(client, seed)
    invoice_id = await _draft(client, seed, f"g{seed.groups['118']}")
    seed.fake.after_store = [httpx.Response(503)]
    await _send(client, seed, invoice_id)
    # KSeF przetworzył plik jako duplikat — numeru KSeF pierwszej jeszcze nie zna.
    seed.fake.invoice_codes = [440]
    duplicate = (
        await client.post(f"{BASE}/{invoice_id}/check", headers=_h(seed))
    ).json()
    assert duplicate["status"] == "sent"
    assert duplicate["editable"] is False and duplicate["can_send"] is False
    assert "KSeF ma już fakturę o numerze 1/11/2026" in duplicate["ksef_status_text"]
    assert (
        await client.delete(f"{BASE}/{invoice_id}", headers=_h(seed))
    ).status_code == 409

    known = numbers.make(fx.COMPANY_NIP, date(2026, 11, 20), "E400000D0F01")
    seed.fake.known_numbers["1/11/2026"] = known
    resolved = (
        await client.post(f"{BASE}/{invoice_id}/check", headers=_h(seed))
    ).json()
    assert resolved["status"] == "accepted"
    assert resolved["ksef_number"] == known
    assert await _series_next() == 2


async def test_crash_after_session_open_leaves_a_checkable_invoice(
    client, seed, monkeypatch
):
    await _settings(client, seed)
    invoice_id = await _draft(client, seed, f"g{seed.groups['118']}")
    real = ksef_send.transmit

    async def crashing(config, xml, **kwargs):
        progress = kwargs["on_progress"]

        async def stop_after_send(result):
            await progress(result)
            if result.stage == "status":
                raise RuntimeError("proces padł")

        kwargs["on_progress"] = stop_after_send
        result = await real(config, xml, **kwargs)
        raise RuntimeError("proces padł") from result.error

    monkeypatch.setattr(ksef_send, "transmit", crashing)
    card = await _send(client, seed, invoice_id)
    assert card["status"] in ("sending", "sent")
    assert card["can_check"] is True and card["editable"] is False
    monkeypatch.setattr(ksef_send, "transmit", real)
    checked = (await client.post(f"{BASE}/{invoice_id}/check", headers=_h(seed))).json()
    assert checked["status"] == "accepted"


async def test_crash_before_session_returns_invoice_with_its_number(
    client, seed, monkeypatch
):
    await _settings(client, seed)
    invoice_id = await _draft(client, seed, f"g{seed.groups['118']}")

    async def crashing(*_args, **_kwargs):
        raise RuntimeError("proces padł przed sesją")

    monkeypatch.setattr(ksef_send, "transmit", crashing)
    card = await _send(client, seed, invoice_id)
    assert card["status"] == "failed"
    assert card["invoice_number"] == "1/11/2026"
    assert card["editable"] is True
    monkeypatch.undo()
    monkeypatch.setattr(settings, "KSEF_CONTEXT_NIP", fx.COMPANY_NIP)
    monkeypatch.setattr(settings, "KSEF_SALES_ISSUE_MODE", "test")
    monkeypatch.setattr(settings, "KSEF_SALES_ISSUE_TOKEN", TOKEN)
    monkeypatch.setattr(ksef_send, "default_client", factory(seed.fake))
    monkeypatch.setattr(api, "business_today", lambda: TODAY)
    again = await _send(client, seed, invoice_id)
    assert again["status"] == "accepted"
    assert again["invoice_number"] == "1/11/2026"


async def test_sending_without_session_unlocks_after_a_few_minutes(client, seed):
    await _settings(client, seed)
    invoice_id = await _draft(client, seed, f"g{seed.groups['118']}")
    async with AsyncSessionLocal() as db:
        invoice = await db.get(ClientIssuedInvoice, invoice_id)
        invoice.status = "sending"
        await numbering.assign(db, invoice, pattern="{n}/{mm}/{yyyy}")
        invoice.sent_at = datetime.now(timezone.utc)
        await db.commit()
    fresh = (await client.get(f"{BASE}/{invoice_id}", headers=_h(seed))).json()
    assert fresh["editable"] is False and fresh["can_check"] is False
    assert (
        await client.delete(f"{BASE}/{invoice_id}", headers=_h(seed))
    ).status_code == 409

    async with AsyncSessionLocal() as db:
        invoice = await db.get(ClientIssuedInvoice, invoice_id)
        invoice.sent_at = datetime.now(timezone.utc) - timedelta(minutes=10)
        await db.commit()
    stale = (await client.get(f"{BASE}/{invoice_id}", headers=_h(seed))).json()
    assert stale["editable"] is True and stale["can_send"] is True
    withdrawn = await client.delete(f"{BASE}/{invoice_id}", headers=_h(seed))
    assert withdrawn.json() == {"result": "deleted"}
    assert await _series_next() == 1


# ── Przegląd 13.11: korekta korekty, zaliczkowa ─────────────────────────────


async def _correct(client, seed, invoice_id: int, quantity: str) -> dict:
    created = await client.post(
        f"{BASE}/{invoice_id}/correction",
        json={"reason": "Zużycie MD po weryfikacji klienta"},
        headers=_h(seed),
    )
    assert created.status_code == 201, created.text
    correction = created.json()
    line = {**correction["lines"][0], "quantity": quantity}
    await client.put(
        f"{BASE}/{correction['id']}", json={"lines": [line]}, headers=_h(seed)
    )
    return correction


async def test_second_correction_starts_from_the_first_one(client, seed):
    await _settings(client, seed)
    original_id = await _draft(client, seed, f"g{seed.groups['118']}")
    await _send(client, seed, original_id)  # 21 MD × 1200
    first = await _correct(client, seed, original_id, "20")
    in_progress = await client.post(
        f"{BASE}/{original_id}/correction",
        json={"reason": "Druga korekta za wcześnie"},
        headers=_h(seed),
    )
    assert in_progress.status_code == 409
    assert (await _send(client, seed, first["id"]))["net"] == "-1200.00"

    second = await _correct(client, seed, original_id, "22")
    assert [line["quantity"] for line in second["lines_before"]] == ["20"]
    sent = await _send(client, seed, second["id"])
    assert sent["invoice_number"] == "KOR/2/11/2026"
    # 20 → 22 MD: +2 × 1200, a nie różnica od faktury pierwotnej (+1200).
    assert sent["net"] == "2400.00"
    fa_node = etree.fromstring(seed.fake.received[-1]).find("{*}Fa")
    assert fa_node.findtext("{*}P_13_1") == "2400.00"


async def test_advance_invoice_cannot_be_corrected_as_vat(client, seed):
    await _settings(client, seed)
    created = await client.post(
        f"{BASE}/advance",
        json={
            "client_id": seed.client_id,
            "currency": "PLN",
            "received_on": "2026-11-18",
        },
        headers=_h(seed),
    )
    advance = created.json()
    line = {**advance["lines"][0], "unit_price": "10000"}
    await client.put(
        f"{BASE}/{advance['id']}",
        json={"lines": [line], "buyer": BUYER},
        headers=_h(seed),
    )
    sent = await _send(client, seed, advance["id"])
    assert sent["status"] == "accepted"
    card = (await client.get(f"{BASE}/{advance['id']}", headers=_h(seed))).json()
    assert card["can_correct"] is False
    refused = await client.post(
        f"{BASE}/{advance['id']}/correction",
        json={"reason": "Zmiana zaliczki"},
        headers=_h(seed),
    )
    assert refused.status_code == 409
    assert "KOR_ZAL" in refused.json()["detail"]


# ── Przegląd 13.11: kurs NBP z dokładnego dnia ──────────────────────────────


async def test_missing_nbp_table_on_the_last_workday_is_a_problem(client, seed):
    async with AsyncSessionLocal() as db:
        order_id = await fx.periodic_order(
            db,
            seed.client_id,
            "ZAM/2026/EUR-DZIURA",
            rate="9000",
            unit=RateUnit.monthly,
            currency="EUR",
        )
        await db.execute(
            delete(FxRate).where(
                FxRate.currency == "EUR",
                FxRate.effective_date.between(date(2026, 11, 26), date(2026, 11, 30)),
            )
        )
        db.add(
            FxRate(
                currency="EUR",
                effective_date=date(2026, 11, 26),
                rate_to_pln=Decimal("4.2600"),
                source="NBP",
            )
        )
        await db.commit()
    await _settings(client, seed)
    invoice_id = await _draft(client, seed, f"o{order_id}")
    # Dostawa 30.11 (poniedziałek): kurs z 27.11 (piątek) — w bazie jest tylko 26.11.
    card = (
        await client.put(
            f"{BASE}/{invoice_id}",
            json={"period_from": "2026-11-01", "period_to": "2026-11-30"},
            headers=_h(seed),
        )
    ).json()
    assert card["fx"] is None
    assert any("27.11.2026" in problem for problem in card["problems"])
    assert card["can_send"] is False
    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(FxRate).where(
                FxRate.currency == "EUR", FxRate.effective_date == date(2026, 11, 26)
            )
        )
        await db.commit()


def test_rate_day_skips_weekends_and_holidays():
    assert issue.rate_day(date(2026, 11, 30)) == date(2026, 11, 27)
    # 11.11 to święto: dostawa 12.11 → kurs z 10.11.
    assert issue.rate_day(date(2026, 11, 12)) == date(2026, 11, 10)
    assert issue.rate_day(date(2026, 10, 31)) == date(2026, 10, 30)


async def test_order_invoiced_outside_nexus_is_not_drafted_again(client, seed):
    """Faktura z eBI24 (odczytana z KSeF i powiązana z zamówieniem) blokuje szkic.

    Przeklikanie na stagingu 14.11.2026: „Wystaw za miesiąc” pokazywało zamówienia
    zafakturowane w eBI24 jako „do wystawienia” — w miesiącu przejściowym druga
    faktura za to samo zamówienie.
    """

    group_id = seed.groups["118"]
    async with AsyncSessionLocal() as db:
        outside = ClientSalesInvoice(
            ksef_number=f"{fx.COMPANY_NIP}-20261031-EB1000000077-01",
            xml_sha256="0" * 64,
            client_id=seed.client_id,
            invoice_number="77/10/2026",
            issue_date=date(2026, 10, 31),
            currency="PLN",
            net_amount=Decimal("25200.00"),
            vat_amount=Decimal("5796.00"),
            gross_amount=Decimal("30996.00"),
            items=[],
            order_refs=[],
            match_status="matched",
            match_method="order_number",
            fetched_at=datetime.now(timezone.utc),
        )
        db.add(outside)
        await db.flush()
        db.add(
            ClientSalesInvoiceLink(
                invoice_id=outside.id,
                order_group_id=group_id,
                period_year=2026,
                period_month=10,
            )
        )
        await db.commit()

    listing = (
        await client.get(f"{BASE}/to-issue", params=OCTOBER, headers=_h(seed))
    ).json()
    rows = {
        row["key"]: row
        for entry in listing["clients"]
        if entry["client_id"] == seed.client_id
        for row in entry["rows"]
    }
    assert rows[f"g{group_id}"]["invoiced_in_ksef"] == ["77/10/2026"]

    refused = await client.post(
        f"{BASE}/drafts",
        json={**OCTOBER, "keys": [f"g{group_id}"]},
        headers=_h(seed),
    )
    assert refused.status_code == 409, refused.text
    assert "77/10/2026" in refused.json()["detail"]


# ── Rabat od obrotu rocznego (decyzje Artura 16.11.2026) ───────────────────


def _sales(client_id: int, number: str, issued: date, net: str, *names: str):
    return ClientSalesInvoice(
        ksef_number=f"{fx.COMPANY_NIP}-{issued:%Y%m%d}-EB{number:0>10}-01",
        xml_sha256="0" * 64,
        client_id=client_id,
        invoice_number=f"{number}/RB/{issued.year}",
        issue_date=issued,
        sale_date=issued,
        period_year=issued.year,
        period_month=issued.month,
        period_source="invoice",
        currency="PLN",
        net_amount=Decimal(net),
        vat_amount=Decimal("0.00"),
        gross_amount=Decimal(net),
        items=[{"name": name, "net": net} for name in names],
        order_refs=[],
        match_status="unmatched",
        fetched_at=datetime.now(timezone.utc),
    )


async def test_draft_gets_line_discount_at_rate_from_turnover_before_its_month(
    client, seed
):
    """Szkic za październik ma rabat 3,5% na każdym wierszu usługi (jak w eBI24),
    bo obrót przed rabatem do końca września przekroczył próg; wrzesień ma
    korektę 2% od nadwyżki. Faktura z 2025 i refaktura podróży poza obrotem.
    Złe warunki = 422; edycja pozycji zachowuje rabat. Progi i stawki fikcyjne.
    """

    terms = {
        "threshold_currency": "PLN",
        "periods": [
            {
                "from_year": 2026,
                "tiers": [{"up_to": 100000, "rate": 1.5}, {"up_to": None, "rate": 3.5}],
            }
        ],
        "exclude_words": ["podróż"],
    }
    bad = await client.put(
        f"{BASE}/settings",
        json={
            **SETTINGS,
            "clients": {
                str(seed.client_id): {
                    "rebate": {**terms, "periods": [{"from_year": 2026, "tiers": []}]}
                }
            },
        },
        headers=_h(seed),
    )
    assert bad.status_code == 422
    assert "progów" in bad.json()["detail"]

    await _settings(client, seed, clients={str(seed.client_id): {"rebate": terms}})
    september = _sales(seed.client_id, "1", date(2026, 9, 30), "110320.00", "Usługi")
    # eBI24: cena przed rabatem na wierszu, netto po rabacie 1,5%.
    september.items = [
        {"name": "Usługi", "quantity": "1000", "unit_price": "112", "net": "110320.00"}
    ]
    async with AsyncSessionLocal() as db:
        db.add_all(
            [
                september,
                _sales(seed.client_id, "2", date(2025, 12, 31), "500000.00", "Usługi"),
                _sales(
                    seed.client_id,
                    "3",
                    date(2026, 8, 31),
                    "70000.00",
                    "Podróż służbowa",
                ),
            ]
        )
        await db.commit()

    invoice_id = await _draft(client, seed, f"g{seed.groups['118']}")
    card = (await client.get(f"{BASE}/{invoice_id}", headers=_h(seed))).json()
    assert card["lines"] and all(row["discount_pct"] == "3.5" for row in card["lines"])
    gross = sum(
        (Decimal(row["quantity"]) * Decimal(row["unit_price"])).quantize(
            Decimal("0.01")
        )
        for row in card["lines"]
    )
    net = sum(
        (
            Decimal(row["quantity"])
            * (Decimal(row["unit_price"]) * Decimal("0.965")).quantize(Decimal("0.01"))
        ).quantize(Decimal("0.01"))
        for row in card["lines"]
    )
    assert Decimal(card["net"]) == net < gross

    data = card["rebate"]
    assert (data["year"], data["month"], data["rate"]) == (2026, 10, "3.5")
    # Obrót przed rabatem (1000 × 112), bez podróży i bez 2025.
    assert data["turnover_before"] == "112000.00"
    assert Decimal(data["turnover"]) == Decimal("112000.00") + gross
    assert data["on_invoice"] == str(gross - net)
    assert data["excluded"] == 1
    assert data["corrections"] == [
        {
            "month": 9,
            "rate_diff": "2",
            "excess": "12000.00",
            "amounts": [{"currency": "PLN", "amount": "240.00"}],
            "issued": [],
        }
    ]

    # Edycja ilości zachowuje rabat na wierszu i przelicza netto.
    edited = [dict(row) for row in card["lines"]]
    edited[0]["quantity"] = str(Decimal(edited[0]["quantity"]) * 2)
    saved = await client.put(
        f"{BASE}/{invoice_id}", json={"lines": edited}, headers=_h(seed)
    )
    assert saved.status_code == 200, saved.text
    again = (await client.get(f"{BASE}/{invoice_id}", headers=_h(seed))).json()
    assert all(row["discount_pct"] == "3.5" for row in again["lines"])
    assert Decimal(again["net"]) > Decimal(card["net"])

    # Klient bez warunków: karta bez rabatu.
    await _settings(client, seed)
    plain = (await client.get(f"{BASE}/{invoice_id}", headers=_h(seed))).json()
    assert plain["rebate"] is None


# ── Korekta zbiorcza rabatu od obrotu: „Wystaw korektę” (22.11.2026) ────────

FA3_SCHEMA = Path(__file__).parent / "data" / "fa3_schema" / "schemat.xsd"
REBATE_TERMS = {
    "threshold_currency": "PLN",
    "periods": [
        {
            "from_year": 2026,
            "tiers": [{"up_to": 1000, "rate": 1.5}, {"up_to": None, "rate": 3.5}],
        }
    ],
    "exclude_words": ["podróż"],
}


def _ksef_number(day: date, serial: int) -> str:
    data = f"{fx.COMPANY_NIP}-{day:%Y%m%d}-{serial:012X}"
    return f"{data}-{numbers.checksum(data)}"


def _discounted_sales(client_id: int, serial: int, day: date, price: str):
    """Faktura z KSeF z rabatem 1,5% na wierszu (cena przed rabatem, netto po)."""

    net = (Decimal(price) * Decimal("0.985")).quantize(Decimal("0.01"))
    invoice = _sales(client_id, str(serial), day, str(net), "Usługi IT")
    invoice.ksef_number = _ksef_number(day, 0xEB0000 + serial)
    invoice.items = [
        {
            "name": "Usługi IT",
            "quantity": "1",
            "unit_price": price,
            "net": str(net),
            "vat_rate": "23",
        }
    ]
    return invoice


async def test_rebate_collective_correction_issue_refuse_second_and_send(client, seed):
    """Wrzesień 900 + październik 2 × 150 przed rabatem: próg 1000 przekroczony
    w październiku, nadwyżka 200, korekta 2% = 4,00 zł na obie faktury
    października. „Wystaw korektę” zapisuje szkic KOR bez numeru, druga = 409,
    wysyłka nadaje numer z serii KOR, XML przechodzi XSD, a przyjęta korekta nie
    przypina się do jednej faktury i nie zaniża obrotu do progu.
    """

    await _settings(
        client, seed, clients={str(seed.client_id): {"rebate": REBATE_TERMS}}
    )
    async with AsyncSessionLocal() as db:
        db.add_all(
            [
                _discounted_sales(seed.client_id, 1, date(2026, 9, 30), "900"),
                _discounted_sales(seed.client_id, 2, date(2026, 10, 31), "150"),
                _discounted_sales(seed.client_id, 3, date(2026, 10, 31), "150"),
            ]
        )
        found = await db.get(Client, seed.client_id)
        found.address = BUYER["address_l1"]
        await db.commit()
    query = {"client_id": seed.client_id, **OCTOBER, "currency": "PLN"}

    preview = await client.get(
        f"{BASE}/rebate-correction", params=query, headers=_h(seed)
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["amount"] == "4.00"
    assert preview.json()["issued"] is None

    for role in ("recruiter", "dl"):
        denied = await client.post(
            f"{BASE}/rebate-correction", json=query, headers=_h(seed, role)
        )
        assert denied.status_code == 403, (role, denied.text)

    created = await client.post(
        f"{BASE}/rebate-correction", json=query, headers=_h(seed)
    )
    assert created.status_code == 201, created.text
    card = created.json()
    assert card["invoice_type"] == "KOR" and card["series_code"] == "KOR"
    assert card["status"] == "draft" and card["invoice_number"] is None
    assert card["corrects"] is None and card["rebate"] is None
    assert card["net"] == "-4.00"
    assert card["collective"]["period"] == "01.10.2026-31.10.2026"
    assert card["collective"]["invoice_count"] == 2
    assert card["problems"] == [], card["problems"]

    again = await client.post(f"{BASE}/rebate-correction", json=query, headers=_h(seed))
    assert again.status_code == 409, again.text
    assert "już jest" in again.json()["detail"]
    preview = await client.get(
        f"{BASE}/rebate-correction", params=query, headers=_h(seed)
    )
    assert preview.json()["issued"]["id"] == card["id"]

    sent = await _send(client, seed, card["id"])
    assert sent["status"] == "accepted", sent
    assert sent["invoice_number"] == "KOR/1/11/2026"
    xml = seed.fake.received[-1]
    schema = etree.XMLSchema(etree.parse(str(FA3_SCHEMA)))
    root = etree.fromstring(xml)
    assert schema.validate(root), [str(e) for e in schema.error_log]
    fa = root.find("{*}Fa")
    assert fa.findtext("{*}RodzajFaktury") == "KOR"
    assert fa.findtext("{*}TypKorekty") == "2"
    assert len(fa.findall("{*}DaneFaKorygowanej")) == 2
    async with AsyncSessionLocal() as db:
        stored = await db.get(ClientSalesInvoice, sent["sales_invoice_id"])
        assert stored.invoice_kind == "correction"
        assert stored.corrects_invoice_id is None
        assert stored.match_status == "ignored"

    # Przyjęta korekta nie zmienia obrotu do progu: kwota korekty ta sama,
    # a wysłana korekta dalej blokuje drugą.
    preview = await client.get(
        f"{BASE}/rebate-correction", params=query, headers=_h(seed)
    )
    assert preview.json()["amount"] == "4.00"
    assert preview.json()["issued"]["invoice_number"] == "KOR/1/11/2026"
    again = await client.post(f"{BASE}/rebate-correction", json=query, headers=_h(seed))
    assert again.status_code == 409


async def test_collective_correction_check_and_unique_month_in_database(seed):
    """CHECK 0749: KOR ma albo ``corrects_id``, albo listę faktur; jedna korekta
    zbiorcza na klienta, miesiąc i walutę (wycofana się nie liczy)."""

    from app.services import client_invoice_collective_correction_schema as schema

    def kor(**extra) -> ClientIssuedInvoice:
        return ClientIssuedInvoice(
            client_id=seed.client_id,
            invoice_type="KOR",
            series_code="KOR",
            status="draft",
            period_year=2026,
            period_month=10,
            issue_date=TODAY,
            **{"currency": "PLN", **extra},
        )

    collective = {"invoices": [], "period": "01.10.2026-31.10.2026"}
    async with AsyncSessionLocal() as db:
        # Lustro entrypointu jest idempotentne: drugi przebieg nic nie zmienia.
        for stmt in schema.ALL_DDL:
            await db.execute(text(stmt))
        definition = await db.scalar(
            text(
                "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                "WHERE conname = 'ck_client_issued_invoices_correction'"
            )
        )
        assert "collective_correction" in definition
        await db.commit()

        for bad in (kor(), kor(collective_correction=[1])):
            with pytest.raises(IntegrityError):
                async with db.begin_nested():
                    db.add(bad)
                    await db.flush()

        db.add(kor(collective_correction=collective))
        await db.flush()
        with pytest.raises(IntegrityError):
            async with db.begin_nested():
                db.add(kor(collective_correction=collective))
                await db.flush()
        db.add(kor(collective_correction=collective, currency="EUR"))
        await db.flush()
        await db.rollback()


async def test_rebate_correction_other_integrity_error_is_not_already_exists(
    client, seed, caplog
):
    """Stary CHECK (krok lustra pominięty przez lock_timeout) to 500 z logiem,
    nie „korekta już powstała”."""

    from app.services import client_invoice_collective_correction_schema as schema

    await _settings(
        client, seed, clients={str(seed.client_id): {"rebate": REBATE_TERMS}}
    )
    async with AsyncSessionLocal() as db:
        db.add_all(
            [
                _discounted_sales(seed.client_id, 11, date(2026, 9, 30), "900"),
                _discounted_sales(seed.client_id, 12, date(2026, 10, 31), "300"),
            ]
        )
        found = await db.get(Client, seed.client_id)
        found.address = BUYER["address_l1"]
        await db.execute(text(schema.DOWNGRADE_DDL[1]))
        await db.execute(text(schema.DOWNGRADE_DDL[2]))
        await db.commit()
    query = {"client_id": seed.client_id, **OCTOBER, "currency": "PLN"}
    try:
        # Transport testowy przepuszcza wyjątek aplikacji (w produkcji: 500).
        with pytest.raises(
            IntegrityError, match="ck_client_issued_invoices_correction"
        ):
            await client.post(f"{BASE}/rebate-correction", json=query, headers=_h(seed))
        assert "ck_client_issued_invoices_correction" in caplog.text
    finally:
        async with AsyncSessionLocal() as db:
            for stmt in schema.CONSTRAINT_DDL:
                await db.execute(text(stmt))
            await db.commit()


# ── Wymagania klientów do faktury (reguły ``cl.*``, 23.11.2026) ──────────────


async def _client_rules(client_id: int, rules: dict) -> None:
    from app.models.client_settlement import ClientSettlementRuleSet

    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(ClientSettlementRuleSet).where(
                ClientSettlementRuleSet.client_id == client_id
            )
        )
        if rules:
            db.add(
                ClientSettlementRuleSet(
                    client_id=client_id, effective_from="2026-01", rules=rules
                )
            )
        await db.commit()


@pytest_asyncio.fixture
async def rules(seed):
    yield lambda value: _client_rules(seed.client_id, value)
    await _client_rules(seed.client_id, {})


async def test_several_orders_on_one_invoice_with_contract_and_client_field(
    client, seed, rules
):
    await rules(
        {
            "cl.orders_together": {"level": "block", "params": {}},
            "cl.ksef_contract": {
                "level": "block",
                "params": {"number": "UR/2020/77", "date": "2020-03-02"},
            },
            "cl.ksef_fields": {
                "level": "block",
                "params": {"key": "OSOBA", "value": "koordynator@example.com"},
            },
        }
    )
    await _settings(client, seed)
    keys = [f"g{seed.groups['118']}", f"g{seed.groups['124']}"]
    response = await client.post(
        f"{BASE}/drafts", json={**OCTOBER, "keys": keys}, headers=_h(seed)
    )
    assert response.status_code == 201, response.text
    (invoice_id,) = response.json()["created"]
    await client.put(f"{BASE}/{invoice_id}", json={"buyer": BUYER}, headers=_h(seed))
    card = (await client.get(f"{BASE}/{invoice_id}", headers=_h(seed))).json()
    assert card["order_numbers"] == ["ZAM/2026/118", "ZAM/2026/124"]
    assert [line["order_number"] for line in card["lines"]] == [
        "ZAM/2026/118",
        "ZAM/2026/124",
    ]
    assert card["net"] == "47625.00"
    labels = {item["label"]: item["value"] for item in card["requirements"]}
    assert labels["Numer umowy (KSeF)"] == "UR/2020/77 z 02.03.2020"
    assert labels["OSOBA (KSeF, pole dodatkowe)"] == "koordynator@example.com"

    # Oba zamówienia są już zafakturowane za październik — drugiego szkicu nie ma.
    listing = (
        await client.get(f"{BASE}/to-issue", params=OCTOBER, headers=_h(seed))
    ).json()
    rows = {
        row["key"]: row
        for entry in listing["clients"]
        if entry["client_id"] == seed.client_id
        for row in entry["rows"]
    }
    assert [i["id"] for i in rows[keys[0]]["issued"]] == [invoice_id]
    assert [i["id"] for i in rows[keys[1]]["issued"]] == [invoice_id]
    again = await client.post(
        f"{BASE}/drafts", json={**OCTOBER, "keys": [keys[1]]}, headers=_h(seed)
    )
    assert again.status_code == 409

    sent = await _send(client, seed, invoice_id)
    assert sent["status"] == "accepted", sent
    (xml,) = seed.fake.received
    fa_node = etree.fromstring(xml).find("{*}Fa")
    assert [
        n.text
        for n in fa_node.iterfind("{*}WarunkiTransakcji/{*}Zamowienia/{*}NrZamowienia")
    ] == ["ZAM/2026/118", "ZAM/2026/124"]
    assert fa_node.findtext("{*}WarunkiTransakcji/{*}Umowy/{*}NrUmowy") == "UR/2020/77"
    assert [
        (n.findtext("{*}Klucz"), n.findtext("{*}Wartosc"))
        for n in fa_node.iterfind("{*}DodatkowyOpis")
    ] == [("OSOBA", "koordynator@example.com")]
    async with AsyncSessionLocal() as db:
        links = (
            await db.scalars(
                select(ClientSalesInvoiceLink.order_group_id).where(
                    ClientSalesInvoiceLink.invoice_id == sent["sales_invoice_id"]
                )
            )
        ).all()
    assert sorted(links) == sorted([seed.groups["118"], seed.groups["124"]])


async def test_orders_stay_separate_without_the_rule(client, seed, rules):
    await rules({})
    await _settings(client, seed)
    keys = [f"g{seed.groups['118']}", f"g{seed.groups['124']}"]
    response = await client.post(
        f"{BASE}/drafts", json={**OCTOBER, "keys": keys}, headers=_h(seed)
    )
    assert response.status_code == 201, response.text
    assert len(response.json()["created"]) == 2


async def test_buyer_per_contract_is_chosen_once_and_remembered(client, seed, rules):
    buyers = [
        {
            "name": "Pankki Testi Oyj",
            "number": "FI12345678",
            "address_l1": "Testikatu 1, 00100 Helsinki",
            "country": "FI",
            "delivery_l1": "Testgatan 1, 100 00 Stockholm",
            "delivery_country": "SE",
        },
        {
            "name": "Bank Testowy S.A. Oddział w Polsce",
            "number": fx.CLIENT_NIP,
            "address_l1": "ul. Przykładowa 5, 00-002 Warszawa",
        },
    ]
    await _settings(client, seed, clients={str(seed.client_id): {"buyers": buyers}})
    saved = (await client.get(f"{BASE}/settings", headers=_h(seed))).json()
    codes = [
        b["code"] for b in saved["settings"]["clients"][str(seed.client_id)]["buyers"]
    ]
    assert codes == ["b1", "b2"]

    key = f"g{seed.groups['118']}"
    invoice_id = await _draft(client, seed, key)
    card = (await client.get(f"{BASE}/{invoice_id}", headers=_h(seed))).json()
    assert [o["code"] for o in card["buyer_options"]] == ["b1", "b2"]
    assert any("wybierz nabywcę" in p for p in card["problems"])

    chosen = await client.put(
        f"{BASE}/{invoice_id}", json={"buyer_code": "b1"}, headers=_h(seed)
    )
    assert chosen.status_code == 200, chosen.text
    card = chosen.json()
    assert card["buyer"]["name"] == "Pankki Testi Oyj"
    assert card["series_code"] == "UE"
    assert {line["vat_rate"] for line in card["lines"]} == {"np II"}
    assert not any("wybierz nabywcę" in p for p in card["problems"])

    sent = await _send(client, seed, invoice_id)
    assert sent["status"] == "accepted", sent
    (xml,) = seed.fake.received
    podmiot2 = etree.fromstring(xml).find("{*}Podmiot2")
    assert podmiot2.findtext("{*}DaneIdentyfikacyjne/{*}KodUE") == "FI"
    assert podmiot2.findtext("{*}AdresKoresp/{*}KodKraju") == "SE"

    # Kontrakt zapamiętany: szkic za listopad od razu ma nabywcę z listy.
    async with AsyncSessionLocal() as db:
        from app.models.client_order import ClientOrder

        contract_id = (await db.get(ClientOrder, seed.lines["118"])).contract_id
        data = await issue_settings.load(db)
    assert (
        issue_settings.buyer_for_contract(data, seed.client_id, contract_id, "2026-11")[
            "code"
        ]
        == "b1"
    )


async def test_required_text_and_role_in_line_name(client, seed, rules):
    await rules(
        {
            "cl.item_name": {
                "level": "block",
                "params": {"template": "{usluga} — {rola} — {osoba} — {miesiac}"},
            },
            "cl.item_must_contain": {"level": "block", "params": {"text": "JIRA"}},
        }
    )
    await _settings(client, seed)
    invoice_id = await _draft(client, seed, f"g{seed.groups['118']}")
    card = (await client.get(f"{BASE}/{invoice_id}", headers=_h(seed))).json()
    (line,) = card["lines"]
    assert line["name"] == (
        "Usługi informatyczne — Zamówienie ZAM/2026/118 — Jan Przykładowy — "
        "Jan Przykładowy — październik 2026"
    )
    assert any("JIRA" in p for p in card["problems"])
    assert card["can_send"] is False
    fixed = await client.put(
        f"{BASE}/{invoice_id}",
        json={"lines": [{**line, "name": line["name"] + " — JIRA ABC-1"}]},
        headers=_h(seed),
    )
    assert not any("JIRA" in p for p in fixed.json()["problems"])


async def test_signed_protocol_rule_blocks_the_draft(client, seed, rules):
    await rules(
        {
            "cl.after_signed_document": {"level": "block", "params": {}},
            "cl.client_document": {
                "level": "block",
                "params": {
                    "kind": "protokół",
                    "per": "cały miesiąc",
                    "from": "",
                    "header": "",
                },
            },
        }
    )
    await _settings(client, seed)
    key = f"g{seed.groups['118']}"
    listing = (
        await client.get(f"{BASE}/to-issue", params=OCTOBER, headers=_h(seed))
    ).json()
    row = next(
        row
        for entry in listing["clients"]
        if entry["client_id"] == seed.client_id
        for row in entry["rows"]
        if row["key"] == key
    )
    assert "podpisanego obustronnie protokołu" in row["blocked"]
    assert "Jan Przykładowy" in row["blocked"]
    blocked = await client.post(
        f"{BASE}/drafts", json={**OCTOBER, "keys": [key]}, headers=_h(seed)
    )
    assert blocked.status_code == 409


# ── Zlecenie B-ZONE i protokół odbioru od klienta (24.11.2026) ───────────────

BZONE = "K/2026/100001/AB/1001/26TEST"
BZONE_NEXT = "K/2026/100002/CD/1002/26TEST"


def _row(listing: dict, client_id: int, key: str) -> dict:
    return next(
        row
        for entry in listing["clients"]
        if entry["client_id"] == client_id
        for row in entry["rows"]
        if row["key"] == key
    )


async def _listing(client, seed) -> dict:
    response = await client.get(f"{BASE}/to-issue", params=OCTOBER, headers=_h(seed))
    assert response.status_code == 200, response.text
    return response.json()


async def _bzone_order(
    client_id: int,
    number: str,
    *,
    start: date,
    end: date,
    contract_id: int | None = None,
) -> tuple[int, int]:
    """Zamówienie okresowe ze zleceniem; ``contract_id`` = kolejne zlecenie tej osoby."""

    from app.models.client_order import ClientOrder, ClientOrderStatus

    async with AsyncSessionLocal() as db:
        if contract_id is None:
            order_id = await fx.periodic_order(
                db,
                client_id,
                number,
                rate="1000",
                unit=RateUnit.daily,
                start=start,
                end=end,
                person=("Ola", "Zleceniowa"),
            )
            contract_id = (await db.get(ClientOrder, order_id)).contract_id
        else:
            order = ClientOrder(
                client_id=client_id,
                contract_id=contract_id,
                title=number,
                status=ClientOrderStatus.active,
                start_date=start,
                end_date=end,
                rate_client=Decimal("1000"),
                rate_unit=RateUnit.daily,
                rate_client_currency="PLN",
            )
            db.add(order)
            await db.flush()
            order_id = order.id
        await db.commit()
    return order_id, contract_id


async def test_bzone_rule_blocks_order_without_bzone_number(client, seed, rules):
    await rules({"cl.bzone_order": {"level": "block", "params": {}}})
    await _settings(client, seed)
    key = f"g{seed.groups['118']}"
    row = _row(await _listing(client, seed), seed.client_id, key)
    assert row["blocked"] == (
        "Brak zlecenia B-ZONE na ten okres — poproś KAM o zlecenie: "
        "Jan Przykładowy (01.10–30.10.2026)."
    )
    blocked = await client.post(
        f"{BASE}/drafts", json={**OCTOBER, "keys": [key]}, headers=_h(seed)
    )
    assert blocked.status_code == 409
    assert "Brak zlecenia B-ZONE" in blocked.json()["detail"]


async def test_bzone_quarterly_order_lets_the_invoice_go(client, seed, rules):
    await rules({"cl.bzone_order": {"level": "block", "params": {}}})
    await _settings(client, seed)
    order_id, _ = await _bzone_order(
        seed.client_id, BZONE, start=date(2026, 10, 1), end=date(2026, 12, 31)
    )
    row = _row(await _listing(client, seed), seed.client_id, f"o{order_id}")
    assert row["blocked"] is None
    invoice_id = await _draft(client, seed, f"o{order_id}")
    await client.put(f"{BASE}/{invoice_id}", json={"buyer": BUYER}, headers=_h(seed))
    card = (await client.get(f"{BASE}/{invoice_id}", headers=_h(seed))).json()
    assert not any("B-ZONE" in p for p in card["problems"]), card["problems"]
    labels = {item["label"]: item["value"] for item in card["requirements"]}
    assert labels["Zlecenie B-ZONE"] == "na każdy dzień pracy w miesiącu"


async def test_bzone_order_ending_mid_month_needs_the_next_one(client, seed, rules):
    await rules({"cl.bzone_order": {"level": "block", "params": {}}})
    await _settings(client, seed)
    first, contract_id = await _bzone_order(
        seed.client_id, BZONE, start=date(2026, 7, 1), end=date(2026, 10, 15)
    )
    row = _row(await _listing(client, seed), seed.client_id, f"o{first}")
    assert "Ola Zleceniowa (16.10–30.10.2026)" in row["blocked"]

    # Następne zlecenie tej osoby od 16.10 domyka miesiąc obu wierszy.
    second, _ = await _bzone_order(
        seed.client_id,
        BZONE_NEXT,
        start=date(2026, 10, 16),
        end=date(2026, 12, 31),
        contract_id=contract_id,
    )
    listing = await _listing(client, seed)
    assert _row(listing, seed.client_id, f"o{first}")["blocked"] is None
    assert _row(listing, seed.client_id, f"o{second}")["blocked"] is None


async def test_bzone_rule_is_checked_again_before_sending(client, seed, rules):
    await rules({})
    await _settings(client, seed)
    invoice_id = await _draft(client, seed, f"g{seed.groups['118']}")
    await client.put(f"{BASE}/{invoice_id}", json={"buyer": BUYER}, headers=_h(seed))
    await rules({"cl.bzone_order": {"level": "block", "params": {}}})
    card = (await client.get(f"{BASE}/{invoice_id}", headers=_h(seed))).json()
    assert any(
        p.startswith("Brak zlecenia B-ZONE") and "Jan Przykładowy" in p
        for p in card["problems"]
    ), card["problems"]
    assert card["can_send"] is False
    refused = await client.post(f"{BASE}/{invoice_id}/send", headers=_h(seed))
    assert refused.status_code == 422
    assert seed.fake.received == []


CEZ_DOMAIN = "klient-testowy.example"


def _protocol_text(contract: str, month: str, person: str) -> str:
    return f"""Protokół odbioru
Nr Umowy Wykonawczej {contract}
Zestawienie czasu pracy i wykonanych zadań
w okresie od 01.{month}.2026 do 28.{month}.2026
(Data i podpis osoby uprawnionej) (Data i podpis osoby uprawnionej)
Zestawienie
I Analityk {person} ALFA Rozwój 168
{person} Suma 168
Suma końcowa 168
Podsumowanie projektu/ów
"""


@pytest_asyncio.fixture
async def protocols(seed, monkeypatch):
    """Dokumenty miesiąca osoby z tekstem PDF-a podanym w teście (atrapa odczytu)."""

    from app.models.consultant_portal import CpDocument
    from app.models.contact import Contact
    from app.services.client_invoicing import period_checks
    from app.services.client_settlements import protocol_collective
    from app.services.consultant_portal import identity

    monkeypatch.setattr(
        identity, "_company_domains", lambda: frozenset({"firma-testowa.example"})
    )
    texts: dict[str, str] = {}

    async def fake_protocol(doc):
        return protocol_collective.parse_text(texts[doc.sha256])

    monkeypatch.setattr(period_checks, "_protocol", fake_protocol)
    async with AsyncSessionLocal() as db:
        db.add(
            Contact(
                client_id=seed.client_id,
                name="Koordynator Klienta",
                email=f"koordynator@{CEZ_DOMAIN}",
            )
        )
        await db.commit()
    made: list[int] = []

    async def add(contract_id: int, text_: str, sender: str, month: int = 10) -> int:
        digest = f"{len(made):064d}"
        texts[digest] = text_
        async with AsyncSessionLocal() as db:
            doc = CpDocument(
                contract_id=contract_id,
                kind="report",
                period_year=2026,
                period_month=month,
                channel="mailbox",
                file_path=f"consultant_portal/{contract_id}/{digest}.pdf",
                mime="application/pdf",
                size_bytes=10,
                sha256=digest,
                sender_email=sender,
            )
            db.add(doc)
            await db.commit()
            made.append(doc.id)
            return doc.id

    yield add
    async with AsyncSessionLocal() as db:
        await db.execute(delete(CpDocument).where(CpDocument.id.in_(made)))
        await db.execute(delete(Contact).where(Contact.client_id == seed.client_id))
        await db.commit()


async def _contract_of_line(line_id: int) -> int:
    from app.models.client_order import ClientOrder

    async with AsyncSessionLocal() as db:
        return (await db.get(ClientOrder, line_id)).contract_id


async def _warnings(client, seed, invoice_id: int) -> list[str]:
    card = (await client.get(f"{BASE}/{invoice_id}", headers=_h(seed))).json()
    return card["warnings"]


async def test_client_protocol_warns_but_does_not_block(client, seed, rules, protocols):
    await rules({"cl.client_protocol": {"level": "block", "params": {}}})
    await _settings(client, seed)
    invoice_id = await _draft(client, seed, f"g{seed.groups['118']}")
    await client.put(f"{BASE}/{invoice_id}", json={"buyer": BUYER}, headers=_h(seed))
    card = (await client.get(f"{BASE}/{invoice_id}", headers=_h(seed))).json()
    assert card["warnings"] == [
        "Brak protokołu odbioru od klienta za ten miesiąc — faktura może wymagać "
        "korekty: Jan Przykładowy."
    ]
    assert not any("protokołu" in p for p in card["problems"])
    assert card["can_send"] is True

    contract_id = await _contract_of_line(seed.lines["118"])
    text_ = _protocol_text("CeZ/99/2026", "10", "Jan Przykładowy")
    # Ten sam protokół z adresu firmy bez klienta w wątku się nie liczy.
    await protocols(contract_id, text_, "pm.testowy@firma-testowa.example")
    assert len(await _warnings(client, seed, invoice_id)) == 1
    # Protokół innego miesiąca od klienta (treść: wrzesień) też nie.
    await protocols(
        contract_id,
        _protocol_text("CeZ/99/2026", "09", "Jan Przykładowy"),
        f"koordynator@{CEZ_DOMAIN}",
    )
    assert len(await _warnings(client, seed, invoice_id)) == 1
    await protocols(contract_id, text_, f"koordynator@{CEZ_DOMAIN}")
    assert await _warnings(client, seed, invoice_id) == []
    sent = await _send(client, seed, invoice_id)
    assert sent["status"] == "accepted", sent


async def test_client_protocol_of_another_contract_does_not_count(
    client, seed, rules, protocols
):
    await rules({"cl.client_protocol": {"level": "block", "params": {}}})
    await _settings(client, seed)
    async with AsyncSessionLocal() as db:
        group_id, (line_id,) = await fx.md_group(
            db, seed.client_id, "CeZ/98/2026", people=[("Ola", "Umowna", "1000", "20")]
        )
        await db.commit()
    invoice_id = await _draft(client, seed, f"g{group_id}")
    contract_id = await _contract_of_line(line_id)
    # W wątku umowy CeZ/98 przyszedł protokół CeZ/99 tej samej osoby.
    await protocols(
        contract_id,
        _protocol_text("CeZ/99/2026", "10", "Ola Umowna"),
        f"koordynator@{CEZ_DOMAIN}",
    )
    assert any("Ola Umowna" in w for w in await _warnings(client, seed, invoice_id))
    await protocols(
        contract_id,
        _protocol_text("CeZ/98/2026", "10", "Ola Umowna"),
        f"koordynator@{CEZ_DOMAIN}",
    )
    assert await _warnings(client, seed, invoice_id) == []


@pytest.mark.parametrize("second_person", [False, True])
async def test_client_protocol_with_other_first_name_counts_by_contract_number(
    client, seed, rules, protocols, second_person: bool
):
    # Jak CeZ/177 za X 2026: w protokole inne imię niż w kartotece, nazwisko to samo.
    # Rozliczenie wskazuje osobę numerem umowy (``service._sole_agreements``),
    # faktura ma powiedzieć to samo.
    await rules({"cl.client_protocol": {"level": "block", "params": {}}})
    await _settings(client, seed)
    people = [("Ola", "Protokolarna", "1000", "20")]
    if second_person:
        people.append(("Ewa", "Zastępcza", "1000", "20"))
    async with AsyncSessionLocal() as db:
        group_id, (line_id, *_others) = await fx.md_group(
            db, seed.client_id, "CeZ/97/2026", people=people
        )
        await db.commit()
    invoice_id = await _draft(client, seed, f"g{group_id}")
    await protocols(
        await _contract_of_line(line_id),
        _protocol_text("CeZ/97/2026", "10", "Aleksandra Protokolarna"),
        f"koordynator@{CEZ_DOMAIN}",
    )
    warnings = await _warnings(client, seed, invoice_id)
    if second_person:
        # Na umowie pracują w miesiącu dwie osoby: numer nie wskazuje, czyj to protokół.
        assert len(warnings) == 1 and "Ola Protokolarna" in warnings[0], warnings
    else:
        assert warnings == []
