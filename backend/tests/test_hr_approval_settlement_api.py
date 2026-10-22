"""Rozliczenie zgód w Finansach (etap 3, 0486) — trasy autora i Finansów.

Decyzje Artura 20.10.2026: faktura z KSeF pasująca do zgody przypina się sama,
„Rozliczone” klika osoba z Finansów (nie autor); faktura wyższa o ponad 10%
czeka na dopłatę od zatwierdzającego; zgoda bez dokumentu wygasa po 30 dniach;
niedopasowana faktura kosztowa trafia do „Faktur bez zgody”, chyba że
sprzedawca jest na liście stałych kosztów; premie w Finansach tylko sumą.
Testy stawiają własną aplikację z dwoma routerami. Dane fikcyjne.
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.api import hr_approval_finance, hr_approvals
from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today
from app.core.security import create_access_token
from app.models.app_setting import AppSetting
from app.models.client import Client
from app.models.critical_event import CriticalEvent
from app.models.hr_approval import ApprovalDocument, ApprovalRequest
from app.models.hr_profile import EmployeeProfile
from app.models.hr_time import AttendanceDay
from app.models.notification import Notification, NotificationType
from app.models.user import User, UserRole
from app.services import storage_service
from app.services.hr.approvals import cost_invoices, reader, settlement
from app.services.hr_approvals_schema import RULES_SETTING
from app.services.hr_foundation_schema import HR_MODULE_KEYS, HR_MODULES_SETTING

BASE = "/api/hr/approval-requests"
FIN = "/api/finance/approved-expenses"
PDF = b"%PDF-1.4\n% faktura testowa\n"


def _nip(seed: int) -> str:
    """Fikcyjny NIP z poprawną sumą kontrolną (inny w każdym teście)."""

    weights = (6, 5, 7, 2, 3, 4, 5, 6, 7)
    for offset in range(1000):
        base = f"{(seed + offset) % 10**9:09d}"
        check = sum(int(d) * w for d, w in zip(base, weights)) % 11
        if check != 10:
            return base + str(check)
    raise AssertionError("brak NIP-u")


def _headers(user: User) -> dict[str, str]:
    token = create_access_token(subject=user.id, role=user.role.value)
    return {"Authorization": f"Bearer {token}"}


async def _user(
    db, role: str = "employee", *, manager: User | None = None, profile: bool = True
) -> User:
    marker = uuid.uuid4().hex[:10]
    user = User(
        email=f"hr-settle-{marker}@example.com",
        name=f"Osoba {marker}",
        role=UserRole(role),
        roles=[role],
        is_active=True,
    )
    db.add(user)
    await db.flush()
    if profile:
        db.add(
            EmployeeProfile(
                user_id=user.id, manager_user_id=manager.id if manager else None
            )
        )
        await db.flush()
    return user


async def _put_setting(key: str, value) -> None:
    async with AsyncSessionLocal() as db:
        row = await db.get(AppSetting, key)
        if row is None:
            if value is not None:
                db.add(AppSetting(key=key, value=value))
        elif value is None:
            await db.delete(row)
        else:
            row.value = value
        await db.commit()


async def _get_setting(key: str):
    async with AsyncSessionLocal() as db:
        return await db.scalar(select(AppSetting.value).where(AppSetting.key == key))


@pytest_asyncio.fixture
async def team(tmp_path, monkeypatch):
    """Zatwierdzający (admin), przełożony, autor, osoba z Finansów i obcy;
    moduł „Zgody” włączony; magazyn plików w katalogu testu; odczyt AI bez modelu."""

    monkeypatch.setattr(storage_service, "STORAGE_ROOT", str(tmp_path))

    @asynccontextmanager
    async def no_quota(*_args, **_kwargs):
        yield None

    monkeypatch.setattr("app.services.ai_quota.ai_feature", no_quota)
    previous_modules = await _get_setting(HR_MODULES_SETTING)
    previous_rules = await _get_setting(RULES_SETTING)
    async with AsyncSessionLocal() as db:
        ceo = await _user(db, "admin", profile=False)
        boss = await _user(db, "recruiter")
        worker = await _user(db, manager=boss)
        accountant = await _user(db, "finance")
        stranger = await _user(db)
        await db.commit()
    await _put_setting(HR_MODULES_SETTING, {key: True for key in HR_MODULE_KEYS})
    await _put_setting(
        RULES_SETTING, {"final_approver_user_id": ceo.id, "supervisor_limits": {}}
    )
    yield {
        "ceo": ceo,
        "boss": boss,
        "worker": worker,
        "accountant": accountant,
        "stranger": stranger,
    }
    await _put_setting(
        HR_MODULES_SETTING, previous_modules or {key: False for key in HR_MODULE_KEYS}
    )
    await _put_setting(RULES_SETTING, previous_rules)


@pytest_asyncio.fixture
async def client():
    app = FastAPI()
    app.include_router(hr_approvals.router, prefix=BASE)
    app.include_router(hr_approval_finance.router, prefix=FIN)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as c:
        yield c


def _read(
    gross: str,
    *,
    nip: str | None = None,
    number: str = "FV 1/10/2026",
    currency: str = "PLN",
):
    async def fake(_content, _mime):
        return reader.ReadResult(
            "read",
            {
                "doc_type": "invoice",
                "seller_name": "Sprzedawca Testowy",
                "seller_nip": nip,
                "invoice_number": number,
                "issue_date": business_today().isoformat(),
                "currency": currency,
                "net_amount": None,
                "vat_amount": None,
                "gross_amount": gross,
            },
        )

    return fake


async def _approved(client, team, payload: dict) -> dict:
    created = await client.post(BASE, json=payload, headers=_headers(team["worker"]))
    assert created.status_code == 201, created.text
    decided = await client.post(
        f"{BASE}/{created.json()['id']}/decide",
        json={"action": "approve"},
        headers=_headers(team["ceo"]),
    )
    assert decided.status_code == 200, decided.text
    return decided.json()


def _training(amount: str = "1000", **extra) -> dict:
    return {
        "kind": "training",
        "title": "Konferencja testowa — bilet",
        "purpose": "Wiedza dla zespołu.",
        "amount": amount,
        "payer": "company_invoice",
        **extra,
    }


async def _upload(client, user: User, request_id: int, content: bytes = PDF):
    return await client.post(
        f"{BASE}/{request_id}/documents",
        files={"file": ("faktura.pdf", content, "application/pdf")},
        headers=_headers(user),
    )


async def _notifications(user: User, ntype: NotificationType) -> list[Notification]:
    async with AsyncSessionLocal() as db:
        return list(
            await db.scalars(
                select(Notification).where(
                    Notification.user_id == user.id,
                    Notification.notification_type == ntype,
                )
            )
        )


@pytest.mark.asyncio
async def test_invoice_within_ten_percent_is_settled_by_finance(
    client, team, monkeypatch
) -> None:
    approved = await _approved(client, team, _training("1000"))
    assert approved["settlement"]["status"] == "open"
    assert approved["settlement"]["can_add_document"] is True

    monkeypatch.setattr(reader, "read_document", _read("1080.00"))
    uploaded = await _upload(client, team["worker"], approved["id"])
    assert uploaded.status_code == 201, uploaded.text
    block = uploaded.json()["settlement"]
    assert block["status"] == "documented"
    (doc,) = block["documents"]
    assert doc["gross_amount"] == "1080.00"
    assert block["comparison"]["status"] == "fits"
    assert doc["can_settle"] is False  # autor nie rozlicza

    # Ten sam plik drugi raz = 409.
    again = await _upload(client, team["worker"], approved["id"])
    assert again.status_code == 409

    queue = (
        await client.get(f"{FIN}/to-settle", headers=_headers(team["accountant"]))
    ).json()
    assert approved["id"] in [row["id"] for row in queue["to_settle"]]

    settled = await client.post(
        f"{FIN}/documents/{doc['id']}/settle",
        json={},
        headers=_headers(team["accountant"]),
    )
    assert settled.status_code == 200, settled.text
    after = (
        await client.get(f"{BASE}/{approved['id']}", headers=_headers(team["worker"]))
    ).json()
    assert after["settlement"]["status"] == "settled"
    # Rozliczona zgoda nie przyjmuje dokumentów.
    assert (
        await _upload(client, team["worker"], approved["id"], PDF + b"2")
    ).status_code == 409


@pytest.mark.asyncio
async def test_invoice_over_ten_percent_needs_a_topup_from_the_approver(
    client, team, monkeypatch
) -> None:
    approved = await _approved(client, team, _training("1000"))
    monkeypatch.setattr(reader, "read_document", _read("1250.00"))
    body = (await _upload(client, team["worker"], approved["id"])).json()
    (doc,) = body["settlement"]["documents"]
    assert doc["comparison"]["status"] == "over"
    assert doc["can_request_topup"] is True

    blocked = await client.post(
        f"{FIN}/documents/{doc['id']}/settle",
        json={"note": "test"},
        headers=_headers(team["accountant"]),
    )
    assert blocked.status_code == 409

    asked = await client.post(
        f"{BASE}/{approved['id']}/documents/{doc['id']}/topup",
        headers=_headers(team["worker"]),
    )
    assert asked.status_code == 200, asked.text
    assert (
        len(
            await _notifications(
                team["ceo"], NotificationType.hr_approval_topup_requested
            )
        )
        == 1
    )
    topups = (await client.get(f"{BASE}/topups", headers=_headers(team["ceo"]))).json()[
        "items"
    ]
    assert [item["request_id"] for item in topups] == [approved["id"]]
    assert topups[0]["document"]["topup"]["amount"] == "250.00"
    # Zatwierdzający widzi dopłatę w liczniku zakładki.
    assert (await client.get(f"{BASE}/count", headers=_headers(team["ceo"]))).json()[
        "inbox"
    ] >= 1

    # Autor nie decyduje o swojej dopłacie.
    own = await client.post(
        f"{BASE}/{approved['id']}/documents/{doc['id']}/topup/decide",
        json={"action": "approve"},
        headers=_headers(team["worker"]),
    )
    assert own.status_code == 403
    decided = await client.post(
        f"{BASE}/{approved['id']}/documents/{doc['id']}/topup/decide",
        json={"action": "approve"},
        headers=_headers(team["ceo"]),
    )
    assert decided.status_code == 200, decided.text
    # Ten sam dzień co „Zgoda zatwierdzona” — dzienny dedup powiadomień nie
    # połyka decyzji o dopłacie (audyt 22.10, F19).
    titles = [
        n.title
        for n in await _notifications(
            team["worker"], NotificationType.hr_approval_decided
        )
    ]
    assert any(t.startswith("Zgoda zatwierdzona") for t in titles), titles
    assert any(t.startswith("Dopłata zatwierdzona") for t in titles), titles
    second = await client.post(
        f"{BASE}/{approved['id']}/documents/{doc['id']}/topup/decide",
        json={"action": "approve"},
        headers=_headers(team["ceo"]),
    )
    assert second.status_code == 409

    settled = await client.post(
        f"{FIN}/documents/{doc['id']}/settle",
        json={},
        headers=_headers(team["accountant"]),
    )
    assert settled.status_code == 200, settled.text


@pytest.mark.asyncio
async def test_nobody_settles_own_expense_and_strangers_see_nothing(
    client, team, monkeypatch
) -> None:
    created = await client.post(
        BASE, json=_training("500"), headers=_headers(team["accountant"])
    )
    assert created.status_code == 201, created.text
    await client.post(
        f"{BASE}/{created.json()['id']}/decide",
        json={"action": "approve"},
        headers=_headers(team["ceo"]),
    )
    monkeypatch.setattr(reader, "read_document", _read("500.00"))
    body = (await _upload(client, team["accountant"], created.json()["id"])).json()
    (doc,) = body["settlement"]["documents"]
    own = await client.post(
        f"{FIN}/documents/{doc['id']}/settle",
        json={},
        headers=_headers(team["accountant"]),
    )
    assert own.status_code == 403

    # Obcy: 404 na dokumentach, 403 na trasach Finansów.
    assert (
        await _upload(client, team["stranger"], created.json()["id"])
    ).status_code == 404
    assert (
        await client.get(f"{FIN}/summary", headers=_headers(team["stranger"]))
    ).status_code == 403


@pytest.mark.asyncio
async def test_ksef_cost_invoice_pins_to_the_request_with_its_seller(
    client, team
) -> None:
    nip = _nip(int(uuid.uuid4().int % 10**8))
    approved = await _approved(
        client,
        team,
        {
            **_training("240"),
            "kind": "subscription",
            "recurrence": "monthly",
            "seller_nip": nip,
        },
    )
    assert approved["settlement"]["status"] == "active"
    item = {
        "invoiceNumber": f"FV {uuid.uuid4().hex[:6]}",
        "issueDate": business_today().isoformat(),
        "seller": {"nip": nip, "name": "Dostawca Testowy"},
        "netAmount": 195.12,
        "vatAmount": 44.88,
        "grossAmount": 240.0,
        "currency": "PLN",
        "invoiceType": "Vat",
    }
    async with AsyncSessionLocal() as db:
        state = await cost_invoices.store(
            db,
            item,
            ksef_number=f"{nip}-20261020-{uuid.uuid4().hex[:12].upper()}-AA",
            now=datetime.now(timezone.utc),
        )
        await db.commit()
    assert state == "pinned"

    stranger_nip = _nip(int(uuid.uuid4().int % 10**8))
    unknown = {
        **item,
        "seller": {"nip": stranger_nip, "name": "Inny"},
        "invoiceNumber": "X/1",
    }
    async with AsyncSessionLocal() as db:
        state = await cost_invoices.store(
            db,
            unknown,
            ksef_number=f"{stranger_nip}-20261020-{uuid.uuid4().hex[:12].upper()}-AB",
            now=datetime.now(timezone.utc),
        )
        await db.commit()
    assert state == "unmatched"
    queue = (
        await client.get(f"{FIN}/invoices", headers=_headers(team["accountant"]))
    ).json()["items"]
    assert any(row["seller_nip"] == stranger_nip for row in queue)

    # „Stały koszt”: kolejne faktury tego sprzedawcy nie trafiają do kolejki.
    added = await client.post(
        f"{FIN}/fixed-sellers",
        json={"seller_nip": stranger_nip, "note": "czynsz"},
        headers=_headers(team["accountant"]),
    )
    assert added.status_code == 200, added.text
    assert added.json()["moved"] == 1
    queue = (
        await client.get(f"{FIN}/invoices", headers=_headers(team["accountant"]))
    ).json()["items"]
    assert not any(row["seller_nip"] == stranger_nip for row in queue)

    subs = (
        await client.get(f"{FIN}/subscriptions", headers=_headers(team["accountant"]))
    ).json()["items"]
    (row,) = [r for r in subs if r["id"] == approved["id"]]
    assert row["last_document"]["comparison"]["status"] == "fits"


def _ksef_item(nip: str, issue_date, gross: float = 240.0) -> dict:
    return {
        "invoiceNumber": f"FV {uuid.uuid4().hex[:6]}",
        "issueDate": issue_date.isoformat(),
        "seller": {"nip": nip, "name": "Dostawca Testowy"},
        "netAmount": round(gross / 1.23, 2),
        "vatAmount": round(gross - gross / 1.23, 2),
        "grossAmount": gross,
        "currency": "PLN",
        "invoiceType": "Vat",
    }


async def _store_ksef(item: dict) -> str:
    nip = item["seller"]["nip"]
    async with AsyncSessionLocal() as db:
        state = await cost_invoices.store(
            db,
            item,
            ksef_number=f"{nip}-20261020-{uuid.uuid4().hex[:12].upper()}-AC",
            now=datetime.now(timezone.utc),
        )
        await db.commit()
    return state


@pytest.mark.asyncio
async def test_ksef_match_window_is_thirty_days_before_the_request_not_after(
    client, team
) -> None:
    """Prośba nie później niż 30 dni po wystawieniu faktury (audyt 22.10, F18):
    kolejna faktura subskrypcji przypina się sama, stara faktura sprzedawcy
    z kolejki nie przypina się do świeżej zgody."""

    nip = _nip(int(uuid.uuid4().int % 10**8))
    await _approved(
        client,
        team,
        {
            **_training("240"),
            "kind": "subscription",
            "recurrence": "monthly",
            "seller_nip": nip,
        },
    )
    later = business_today() + timedelta(days=40)
    assert await _store_ksef(_ksef_item(nip, later)) == "pinned"

    old_nip = _nip(int(uuid.uuid4().int % 10**8))
    old = _ksef_item(old_nip, business_today() - timedelta(days=40))
    assert await _store_ksef(old) == "unmatched"
    await _approved(
        client,
        team,
        {
            **_training("240"),
            "kind": "subscription",
            "recurrence": "monthly",
            "seller_nip": old_nip,
        },
    )
    async with AsyncSessionLocal() as db:
        doc = await db.scalar(
            select(ApprovalDocument).where(
                ApprovalDocument.seller_nip == old_nip,
                ApprovalDocument.invoice_number == old["invoiceNumber"],
            )
        )
    assert doc is not None
    assert (doc.status, doc.match_reason, doc.approval_request_id) == (
        "unmatched",
        "no_approval",
        None,
    )


@pytest.mark.asyncio
async def test_request_without_document_expires_after_thirty_days(client, team) -> None:
    approved = await _approved(client, team, _training("300"))
    async with AsyncSessionLocal() as db:
        request = await db.get(ApprovalRequest, approved["id"])
        request.expires_on = business_today() - timedelta(days=1)
        await db.commit()
    async with AsyncSessionLocal() as db:
        expired = await settlement.expire_stale(db, business_today())
        await db.commit()
    assert expired >= 1
    after = (
        await client.get(f"{BASE}/{approved['id']}", headers=_headers(team["worker"]))
    ).json()
    assert after["settlement"]["status"] == "expired"
    assert (await _upload(client, team["worker"], approved["id"])).status_code == 409


@pytest.mark.asyncio
async def test_gift_lands_in_client_history_and_trip_in_attendance(
    client, team
) -> None:
    async with AsyncSessionLocal() as db:
        customer = Client(name=f"Bank Przykładowy {uuid.uuid4().hex[:6]}")
        db.add(customer)
        await db.commit()
    gift = await _approved(
        client,
        team,
        {
            "kind": "gift",
            "title": "Kosz świąteczny",
            "purpose": "Podziękowanie.",
            "amount": "180",
            "payer": "company_card",
            "client_id": customer.id,
        },
    )
    async with AsyncSessionLocal() as db:
        events = list(
            await db.scalars(
                select(CriticalEvent).where(
                    CriticalEvent.client_id == customer.id,
                    CriticalEvent.event_type == "client.gift",
                )
            )
        )
    assert len(events) == 1 and events[0].details["approval_request_id"] == gift["id"]

    # Klient tylko przy prezencie.
    wrong = await client.post(
        BASE,
        json={**_training(), "client_id": customer.id},
        headers=_headers(team["worker"]),
    )
    assert wrong.status_code == 422

    start = business_today() + timedelta(days=14)
    while start.weekday() != 0:
        start += timedelta(days=1)
    await _approved(
        client,
        team,
        {
            "kind": "trip",
            "title": "Delegacja Gdańsk",
            "purpose": "Warsztat.",
            "amount": "900",
            "payer": "reimbursement",
            "starts_on": start.isoformat(),
            "ends_on": (start + timedelta(days=6)).isoformat(),
        },
    )
    async with AsyncSessionLocal() as db:
        days = list(
            await db.scalars(
                select(AttendanceDay.day).where(
                    AttendanceDay.user_id == team["worker"].id,
                    AttendanceDay.status == "business_trip",
                )
            )
        )
    # Poniedziałek–niedziela: tylko dni robocze (bez weekendu i świąt).
    assert days and all(day.weekday() < 5 for day in days) and len(days) <= 5


@pytest.mark.asyncio
async def test_yearly_subscription_asks_owner_once_before_renewal(client, team) -> None:
    approved = await _approved(
        client,
        team,
        {**_training("1200"), "kind": "subscription", "recurrence": "yearly"},
    )
    async with AsyncSessionLocal() as db:
        request = await db.get(ApprovalRequest, approved["id"])
        request.renews_on = business_today() + timedelta(days=10)
        await db.commit()
    for _ in range(2):
        async with AsyncSessionLocal() as db:
            await settlement.renewal_reminders(db, business_today())
            await db.commit()
    assert (
        len(
            await _notifications(
                team["worker"], NotificationType.hr_subscription_renewal
            )
        )
        == 1
    )
    kept = await client.post(
        f"{BASE}/{approved['id']}/renewal",
        json={"keep": True},
        headers=_headers(team["worker"]),
    )
    assert kept.status_code == 200, kept.text
    assert (
        kept.json()["settlement"]["renewal_confirmed_for"]
        == kept.json()["settlement"]["renews_on"]
    )
    ended = await client.post(
        f"{BASE}/{approved['id']}/renewal",
        json={"keep": False},
        headers=_headers(team["worker"]),
    )
    assert ended.json()["settlement"]["status"] == "ended"


@pytest.mark.asyncio
async def test_finance_summary_shows_bonuses_only_as_a_sum(client, team) -> None:
    today = business_today()
    bonus = await client.post(
        BASE,
        json={
            "kind": "bonus",
            "title": "Premia testowa",
            "purpose": "Wyjątkowa praca.",
            "amount": "700",
            "beneficiary_user_id": team["worker"].id,
            "payout_year": today.year,
            "payout_month": today.month,
            # Kartoteka testowa ma domyślnie formę B2B — premia wymaga podstawy.
            "contract_basis": "§ 6 ust. 2 umowy z 01.03.2025",
        },
        headers=_headers(team["boss"]),
    )
    assert bonus.status_code == 201, bonus.text
    await client.post(
        f"{BASE}/{bonus.json()['id']}/decide",
        json={"action": "approve"},
        headers=_headers(team["ceo"]),
    )
    summary = await client.get(f"{FIN}/summary", headers=_headers(team["accountant"]))
    assert summary.status_code == 200, summary.text
    body = summary.json()
    (bonus_row,) = [row for row in body["by_kind"] if row["kind"] == "bonus"]
    assert Decimal(bonus_row["amount"]) >= Decimal("700")
    assert team["worker"].name not in summary.text
    # Premia nie trafia do list rozliczeń.
    queue = (
        await client.get(f"{FIN}/to-settle", headers=_headers(team["accountant"]))
    ).json()
    assert bonus.json()["id"] not in [row["id"] for row in queue["awaiting"]]
    async with AsyncSessionLocal() as db:
        request = await db.get(ApprovalRequest, bonus.json()["id"])
        assert request.settlement_status is None
        docs = await db.scalar(
            select(ApprovalDocument.id).where(
                ApprovalDocument.approval_request_id == request.id
            )
        )
        assert docs is None


@pytest.mark.asyncio
async def test_ksef_amounts_and_seller_are_binding(client, team) -> None:
    nip = _nip(int(uuid.uuid4().int % 10**8))
    approved = await _approved(
        client, team, {**_training("500"), "kind": "other", "seller_nip": nip}
    )
    item = {
        "invoiceNumber": f"FV {uuid.uuid4().hex[:6]}",
        "issueDate": business_today().isoformat(),
        "seller": {"nip": nip, "name": "Dostawca Testowy"},
        "grossAmount": 500.0,
        "currency": "PLN",
        "invoiceType": "Vat",
    }
    async with AsyncSessionLocal() as db:
        await cost_invoices.store(
            db,
            item,
            ksef_number=f"{nip}-20261020-{uuid.uuid4().hex[:12].upper()}-AC",
            now=datetime.now(timezone.utc),
        )
        await db.commit()
    body = (
        await client.get(f"{BASE}/{approved['id']}", headers=_headers(team["worker"]))
    ).json()
    (doc,) = body["settlement"]["documents"]
    for change in ({"seller_nip": ""}, {"gross_amount": "1"}):
        resp = await client.patch(
            f"{BASE}/{approved['id']}/documents/{doc['id']}",
            json=change,
            headers=_headers(team["accountant"]),
        )
        assert resp.status_code == 409, resp.text


@pytest.mark.asyncio
async def test_future_subscription_does_not_expire_before_its_start(
    client, team
) -> None:
    start = business_today() + timedelta(days=90)
    approved = await _approved(
        client,
        team,
        {
            **_training("1200"),
            "kind": "subscription",
            "recurrence": "yearly",
            "starts_on": start.isoformat(),
        },
    )
    assert (
        approved["settlement"]["expires_on"] == (start + timedelta(days=30)).isoformat()
    )
    async with AsyncSessionLocal() as db:
        await settlement.expire_stale(db, business_today() + timedelta(days=45))
        await db.commit()
    after = (
        await client.get(f"{BASE}/{approved['id']}", headers=_headers(team["worker"]))
    ).json()
    assert after["settlement"]["status"] == "active"
