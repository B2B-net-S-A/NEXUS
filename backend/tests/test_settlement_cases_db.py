"""Karta sprawy rozliczenia na bazie: trzy typy spraw (konsultant, akceptujący
u klienta, Delivery Lead), ręczna wysyłka po kliknięciu bez dubla, telefon,
samozamknięcie po przyjęciu i odmowy uprawnień. Dane fikcyjne.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import pytest
import pytest_asyncio
from sqlalchemy import delete, select, text

from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today
from app.models.client import Client
from app.models.client_settlement import ClientSettlement
from app.models.client_settlement_feedback import ClientSettlementFeedback
from app.models.contact import Contact
from app.models.contract import Contract
from app.models.hr_ops import HrAuditEvent
from app.models.user import UserRole
from app.services.care.announcement_mail import MailOutcome
from app.services.client_settlements import cases, feedback
from tests.care_announcements_seed import (
    _get_setting,
    _set_setting,
    headers,
    make_client,
    make_consultant,
    make_user,
)

pytestmark = pytest.mark.asyncio

MONTH = "2026-10"
BASE = "/api/finance/settlements/cases"
ADDRESS = "rozliczenia@example.com"


def _group(*checks: dict) -> list[dict]:
    return [{"title": "RCP", "checks": list(checks)}]


SIGNED_PDF = _group(
    {
        "rule": "proof.signed_pdf",
        "state": "fail",
        "title": "PDF bez podpisu elektronicznego",
        "detail": None,
    }
)


def _no_reply(acceptor: str) -> list[dict]:
    return _group(
        {
            "rule": "proof.accept_has_hours",
            "state": "fail",
            "title": "Mail bez odpowiedzi akceptującego",
            "detail": "Jest prośba o akceptację, ale nie ma potwierdzenia.",
            "acceptors": [acceptor],
        }
    )


MD_OVER = [
    {
        "title": "Zamówienie PO-TEST-1",
        "checks": [
            {
                "rule": "order.md_over",
                "state": "warn",
                "title": "Ponad zamówienie o 2 MD",
                "detail": "Zejdzie 19 MD (tyle zostało) i tyle idzie do faktury.",
            }
        ],
    },
    {
        "remaining_after": "0",
        "orders": [
            {"order_id": 987654321, "number": "PO-TEST-1", "remaining_after": "-2"}
        ],
    },
]


@dataclass
class FakeMailer:
    sent: list[dict] = field(default_factory=list)

    async def send(
        self, *, to: str, subject: str, text: str, cc: Optional[str] = None
    ) -> MailOutcome:
        self.sent.append({"to": to, "subject": subject, "text": text, "cc": cc})
        return MailOutcome("accepted")


@pytest.fixture
def mailer(monkeypatch) -> FakeMailer:
    from app.core.config import settings

    fake = FakeMailer()
    monkeypatch.setattr(cases, "mailer_factory", lambda: fake)
    monkeypatch.setattr(settings, "CONSULTANT_PORTAL_SETTLEMENTS_ADDRESSES", ADDRESS)
    return fake


@pytest_asyncio.fixture
async def module_on():
    module = await _get_setting("client_settlements")
    switch = await _get_setting(feedback.SETTING_KEY)
    await _set_setting("client_settlements", {"enabled": True})
    await _set_setting(feedback.SETTING_KEY, {"mode": "dry_run", "external": "off"})
    yield
    await _set_setting("client_settlements", module)
    await _set_setting(feedback.SETTING_KEY, switch)


@dataclass
class World:
    client_id: int
    consultant: int
    consultant_email: str
    client_case: int
    acceptor: str
    dl_case: int
    clean: int
    accepted: int
    owner_id: int
    owner_email: str
    dl_id: int
    dl_email: str
    settlements: dict[int, int] = field(default_factory=dict)
    users: list[int] = field(default_factory=list)


async def _world() -> World:
    dl = await make_user(UserRole.delivery_lead, name="Lider")
    owner = await make_user(UserRole.delivery_lead, name="Opiekun")
    client_id = await make_client(dl=dl)
    email = f"konsultant-a-{client_id}@example.com"
    acceptor = f"akceptujacy-{client_id}@example.com"
    consultant, _ = await make_consultant(
        client_id, contract_email=email, owner_id=owner.id
    )
    client_case, _ = await make_consultant(
        client_id,
        contract_email=f"konsultant-b-{client_id}@example.com",
        owner_id=owner.id,
    )
    dl_case, _ = await make_consultant(client_id, owner_id=owner.id)
    clean, _ = await make_consultant(client_id, owner_id=owner.id)
    accepted, _ = await make_consultant(client_id, owner_id=owner.id)
    world = World(
        client_id=client_id,
        consultant=consultant,
        consultant_email=email,
        client_case=client_case,
        acceptor=acceptor,
        dl_case=dl_case,
        clean=clean,
        accepted=accepted,
        owner_id=owner.id,
        owner_email=owner.email,
        dl_id=dl.id,
        dl_email=dl.email,
        users=[dl.id, owner.id],
    )
    async with AsyncSessionLocal() as db:
        await db.execute(
            text("UPDATE contracts SET candidate_phone = :p WHERE id = :id"),
            {"p": "+48 600 000 001", "id": consultant},
        )
        # Akceptujący jest w kontaktach klienta, ale bez numeru.
        db.add(
            Contact(client_id=client_id, name="Kierownik Przykładowy", email=acceptor)
        )
        rows = {
            consultant: ("warnings", SIGNED_PDF),
            client_case: ("warnings", _no_reply(acceptor)),
            dl_case: ("warnings", MD_OVER),
            clean: ("ok", _group({"state": "ok", "title": "Podpis ważny"})),
            accepted: ("accepted", SIGNED_PDF),
        }
        for contract_id, (status, checks) in rows.items():
            row = ClientSettlement(
                contract_id=contract_id,
                client_id=client_id,
                period_month=MONTH,
                status=status,
                checks=checks,
            )
            db.add(row)
            await db.flush()
            world.settlements[contract_id] = row.id
        await db.commit()
    return world


async def _cleanup(world: World, *users: int) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(HrAuditEvent).where(
                HrAuditEvent.entity_type == cases.ENTITY,
                HrAuditEvent.entity_id.in_(
                    [str(i) for i in world.settlements.values()]
                ),
            )
        )
        await db.execute(
            delete(ClientSettlementFeedback).where(
                ClientSettlementFeedback.client_id == world.client_id
            )
        )
        await db.execute(
            delete(ClientSettlement).where(
                ClientSettlement.client_id == world.client_id
            )
        )
        await db.execute(delete(Contact).where(Contact.client_id == world.client_id))
        await db.execute(delete(Contract).where(Contract.client_id == world.client_id))
        await db.execute(
            text("DELETE FROM delivery_lead_client_assignments WHERE client_id = :c"),
            {"c": world.client_id},
        )
        await db.execute(delete(Client).where(Client.id == world.client_id))
        ids = [*world.users, *users]
        if ids:
            await db.execute(
                text("DELETE FROM users WHERE id = ANY(:ids)"), {"ids": ids}
            )
        await db.commit()


async def _contract_cases(app_client, user, contract_id: int) -> list[dict]:
    response = await app_client.get(
        f"{BASE}/contract/{contract_id}", params={"month": MONTH}, headers=headers(user)
    )
    assert response.status_code == 200, response.text
    return response.json()["cases"]


async def test_trzy_typy_spraw_na_liscie_i_karcie(app_client, module_on) -> None:
    world = await _world()
    finance = await make_user(UserRole.finance, name="Finanse")
    try:
        listing = await app_client.get(
            BASE,
            params={"month": MONTH, "client_id": world.client_id},
            headers=headers(finance),
        )
        assert listing.status_code == 200, listing.text
        body = listing.json()
        by_contract = {(c["contract_id"], c["actor"]) for c in body["cases"]}
        assert by_contract == {
            (world.consultant, "consultant"),
            (world.client_case, "client"),
            (world.dl_case, "dl"),
        }
        # „Bez uwag” i przyjęte nie mają sprawy; lista bez treści maili.
        assert body["counts"]["all"] == 3
        assert all("mail" not in c for c in body["cases"])

        (consultant,) = await _contract_cases(app_client, finance, world.consultant)
        assert consultant["recipient"]["kind"] == "consultant"
        assert (consultant["mail"]["to"], consultant["mail"]["cc"]) == (
            world.consultant_email,
            world.owner_email,
        )
        assert "bez podpisu elektronicznego" in consultant["mail"]["subject"]
        assert consultant["phones"][0]["number"] == "+48 600 000 001"
        assert consultant["current"]["key"] == "mail"
        assert [s["key"] for s in consultant["steps"]] == [
            "mail",
            "reminder",
            "call",
            "escalation",
        ]
        assert consultant["escalation"]["mail"]["to"] == world.owner_email

        (client,) = await _contract_cases(app_client, finance, world.client_case)
        assert client["recipient"]["kind"] == "client"
        assert client["mail"]["to"] == world.acceptor
        acceptor_phone = client["phones"][0]
        assert acceptor_phone["name"] == "Kierownik Przykładowy"
        assert acceptor_phone["number"] is None  # ekran pisze „brak numeru”

        (dl,) = await _contract_cases(app_client, finance, world.dl_case)
        assert dl["recipient"]["label"] == "Delivery Lead klienta"
        assert dl["mail"]["to"] == world.dl_email
        assert dl["reasons"][0]["title"] == "2 MD ponad pulę zamówienia PO-TEST-1"
        assert "zł" not in dl["mail"]["text"]

        assert await _contract_cases(app_client, finance, world.clean) == []
        assert await _contract_cases(app_client, finance, world.accepted) == []
    finally:
        await _cleanup(world, finance.id)


async def test_wyslij_po_kliknieciu_bez_dubla_i_slad(
    app_client, module_on, mailer
) -> None:
    world = await _world()
    finance = await make_user(UserRole.finance, name="Finanse")
    settlement = world.settlements[world.consultant]
    try:
        today = business_today()
        async with AsyncSessionLocal() as db:
            await feedback.sync_month(db, MONTH, today, client_ids={world.client_id})
            await db.commit()
        switch_before = await _get_setting(feedback.SETTING_KEY)

        sent = await app_client.post(
            f"{BASE}/{settlement}/send",
            json={"actor": "consultant"},
            headers=headers(finance),
        )
        assert sent.status_code == 200, sent.text
        assert sent.json()["outcome"] == "sent"
        assert len(mailer.sent) == 1
        assert mailer.sent[0]["to"] == world.consultant_email
        assert mailer.sent[0]["cc"] == world.owner_email
        (case,) = sent.json()["cases"]
        assert case["steps"][0]["state"] == "done"
        assert case["steps"][0]["done_on"] == today.isoformat()
        assert case["mail_step"] == "reminder"
        assert case["mail"]["subject"].startswith("Przypomnienie: ")

        again = await app_client.post(
            f"{BASE}/{settlement}/send",
            json={"actor": "consultant"},
            headers=headers(finance),
        )
        assert again.status_code == 409
        assert "już dziś" in again.json()["detail"]
        assert len(mailer.sent) == 1

        async with AsyncSessionLocal() as db:
            events = (
                await db.scalars(
                    select(HrAuditEvent).where(
                        HrAuditEvent.entity_type == cases.ENTITY,
                        HrAuditEvent.entity_id == str(settlement),
                    )
                )
            ).all()
            assert [e.action for e in events] == [cases.ACTION_MAIL]
            assert events[0].actor_user_id == finance.id
            assert events[0].details["outcome"] == "sent"
            row = await db.scalar(
                select(ClientSettlementFeedback).where(
                    ClientSettlementFeedback.contract_id == world.consultant,
                    ClientSettlementFeedback.code == "proof.signed_pdf",
                )
            )
            assert row is not None and row.last_sent_on == today
            assert row.sends[-1]["mode"] == "manual"
            assert row.sends[-1]["by_user_id"] == finance.id
        # Ręczna wysyłka nie zmienia trybu automatu (zostaje na sucho).
        assert await _get_setting(feedback.SETTING_KEY) == switch_before

        escalated = await app_client.post(
            f"{BASE}/{settlement}/send",
            json={"actor": "consultant", "escalation": True},
            headers=headers(finance),
        )
        assert escalated.status_code == 200, escalated.text
        assert mailer.sent[-1]["to"] == world.owner_email
        assert mailer.sent[-1]["subject"].startswith("Eskalacja: ")
    finally:
        await _cleanup(world, finance.id)


async def test_bez_nadawcy_nic_nie_wychodzi(app_client, module_on, monkeypatch) -> None:
    world = await _world()
    finance = await make_user(UserRole.finance, name="Finanse")
    monkeypatch.setattr(cases, "mailer_factory", lambda: None)
    try:
        response = await app_client.post(
            f"{BASE}/{world.settlements[world.consultant]}/send",
            json={"actor": "consultant"},
            headers=headers(finance),
        )
        assert response.status_code == 409
        assert "Skopiuj treść" in response.json()["detail"]
        (case,) = await _contract_cases(app_client, finance, world.consultant)
        assert case["steps"][0]["state"] != "done"
        assert case["log"] == []
    finally:
        await _cleanup(world, finance.id)


async def test_zadzwonilem_zapisuje_wynik(app_client, module_on) -> None:
    world = await _world()
    finance = await make_user(UserRole.finance, name="Finanse")
    settlement = world.settlements[world.client_case]
    try:
        bad = await app_client.post(
            f"{BASE}/{settlement}/call",
            json={"actor": "client", "result": "maybe"},
            headers=headers(finance),
        )
        assert bad.status_code == 422
        saved = await app_client.post(
            f"{BASE}/{settlement}/call",
            json={"actor": "client", "result": "no_answer", "note": "Oddzwoni jutro"},
            headers=headers(finance),
        )
        assert saved.status_code == 200, saved.text
        (case,) = saved.json()["cases"]
        call = next(s for s in case["steps"] if s["key"] == "call")
        assert call["state"] == "done"
        assert call["note"] == "nie odebrał(a)"
        assert case["log"][-1]["note"] == "Oddzwoni jutro"
        assert case["log"][-1]["result"] == "no_answer"
        # Sprawy konsultanta przy tym rozliczeniu nie ma: nie ma do kogo dzwonić.
        missing = await app_client.post(
            f"{BASE}/{settlement}/call",
            json={"actor": "consultant", "result": "reached"},
            headers=headers(finance),
        )
        assert missing.status_code == 409
    finally:
        await _cleanup(world, finance.id)


async def test_sprawa_znika_po_przyjeciu(app_client, module_on, mailer) -> None:
    world = await _world()
    finance = await make_user(UserRole.finance, name="Finanse")
    try:
        assert len(await _contract_cases(app_client, finance, world.consultant)) == 1
        async with AsyncSessionLocal() as db:
            await db.execute(
                text(
                    "UPDATE client_settlements SET status = 'accepted' WHERE id = :id"
                ),
                {"id": world.settlements[world.consultant]},
            )
            await db.commit()
        assert await _contract_cases(app_client, finance, world.consultant) == []
        refused = await app_client.post(
            f"{BASE}/{world.settlements[world.consultant]}/send",
            json={"actor": "consultant"},
            headers=headers(finance),
        )
        assert refused.status_code == 409
        assert mailer.sent == []
    finally:
        await _cleanup(world, finance.id)


async def test_odmowa_bez_modulu_finanse(app_client, module_on, mailer) -> None:
    world = await _world()
    recruiter = await make_user(UserRole.recruiter, name="Rekruter")
    lead = await make_user(UserRole.delivery_lead, name="DL")
    admin = await make_user(UserRole.admin, name="Admin")
    finance = await make_user(UserRole.finance, name="Finanse")
    settlement = world.settlements[world.consultant]
    try:
        for user in (recruiter, lead):
            listing = await app_client.get(
                BASE, params={"month": MONTH}, headers=headers(user)
            )
            assert listing.status_code == 403, (user.role, listing.text)
            send = await app_client.post(
                f"{BASE}/{settlement}/send",
                json={"actor": "consultant"},
                headers=headers(user),
            )
            assert send.status_code == 403
            call = await app_client.post(
                f"{BASE}/{settlement}/call",
                json={"actor": "consultant", "result": "reached"},
                headers=headers(user),
            )
            assert call.status_code == 403
        assert mailer.sent == []

        await _set_setting("client_settlements", {"enabled": False})
        closed = await app_client.get(
            BASE, params={"month": MONTH}, headers=headers(finance)
        )
        assert closed.status_code == 404
        as_admin = await app_client.get(
            BASE, params={"month": MONTH}, headers=headers(admin)
        )
        assert as_admin.status_code == 200, as_admin.text
    finally:
        await _cleanup(world, recruiter.id, lead.id, admin.id, finance.id)
