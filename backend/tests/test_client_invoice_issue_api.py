"""Wystawianie faktur sprzedaży z NEXUSA do KSeF (E4) — trasy, numeracja, wysyłka.

Zakres: tylko „Moduł Finanse” (rekruter, Delivery Lead — 403), ustawienia
sprzedawcy i serii, szkice z „Do faktury” (brak zużycia MD blokuje),
wyłączona wysyłka (bez numeru), pełna ścieżka z fałszywym KSeF (numer z serii
dopiero przy wysyłce, wpis w ``client_sales_invoices`` z tym samym numerem
KSeF i powiązaniem ``issued``), odrzucenie (numer zostaje, ponowna wysyłka
z tym samym numerem), wycofanie odrzuconej (ostatni numer wraca, wcześniejszy
zostaje jako ślad), równoległe nadanie numeru, korekta, zaliczkowa, EUR
z kursem NBP. Dane fikcyjne.
"""

from __future__ import annotations

import asyncio
from datetime import date
from decimal import Decimal

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from lxml import etree
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError

from app.api import client_issued_invoices as api
from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.app_setting import AppSetting
from app.models.client_issued_invoice import ClientInvoiceSeries, ClientIssuedInvoice
from app.models.client_sales_invoice import ClientSalesInvoice, ClientSalesInvoiceLink
from app.models.contract import RateUnit
from app.models.fx_rate import FxRate
from app.services.client_invoicing import issue, issue_settings, ksef_send, numbering
from app.services.hr.ksef.client import forget_sessions
from tests._ksef_fake import Clock
from tests.client_invoicing import helpers as fx
from tests.client_invoicing.ksef_issue_fake import TOKEN, UPO, FakeKsefIssue, factory

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

    numbers = await asyncio.gather(*(number(invoice_id) for invoice_id in ids))
    assert sorted(numbers) == [1, 2, 3]

    async with AsyncSessionLocal() as db:
        duplicate = await db.get(ClientIssuedInvoice, ids[0])
        other = await db.get(ClientIssuedInvoice, ids[1])
        other.number_seq = duplicate.number_seq
        other.invoice_number = duplicate.invoice_number
        with pytest.raises(IntegrityError):
            await db.flush()
        await db.rollback()


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
