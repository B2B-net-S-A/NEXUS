"""Przypomnienia o brakującym raporcie godzin na bazie.

Kto jest na liście „Brak RCP”, kto dostaje mail (stan panelu), kopia do
opiekuna 5. dnia, dzwonek 7. dnia, bez powtórek tego samego dnia, „bez
adresata” na liście Finansów, przełącznik i przycisk. Dane fikcyjne.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Optional

import pytest
import pytest_asyncio
from sqlalchemy import delete, func, select, text

from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today
from app.models.client import Client
from app.models.client_settlement import ClientSettlement, ClientSettlementRuleSet
from app.models.client_settlement_reminder import ClientSettlementReminder
from app.models.consultant_panel import ClientSettlementRule, CpActivation
from app.models.consultant_portal import CpDocument
from app.models.contract import Contract, ContractStatus
from app.models.notification import Notification, NotificationType
from app.models.user import User, UserRole
from app.services.care.announcement_mail import MailOutcome
from app.services.client_settlements import reminders
from app.services.client_settlements.service import SettlementError
from app.services.consultant_portal import portal_mail
from tests.care_announcements_seed import (
    _get_setting,
    _set_setting,
    headers,
    make_client,
    make_consultant,
    make_user,
)
from tests.consultant_portal_seed import portal_restored, set_portal  # noqa: F401

pytestmark = pytest.mark.asyncio

ADDRESS = "rozliczenia@example.com"


def _previous_month() -> str:
    today = business_today()
    return reminders.period_for(today)


def _day(step: str) -> date:
    """Dzień kroku w bieżącym miesiącu (rozliczany = poprzedni)."""

    return date.fromisoformat(reminders.schedule(_previous_month())[step])


@dataclass
class FakeMailer:
    sent: list[dict] = field(default_factory=list)

    async def send(
        self, *, to: str, subject: str, text: str, cc: Optional[str] = None
    ) -> MailOutcome:
        self.sent.append({"to": to, "subject": subject, "text": text, "cc": cc})
        return MailOutcome("accepted")

    def to(self, address: str) -> list[dict]:
        return [m for m in self.sent if m["to"] == address]


@pytest.fixture
def mailer(monkeypatch) -> FakeMailer:
    from app.core.config import settings

    fake = FakeMailer()
    monkeypatch.setattr(portal_mail, "default_mailer", lambda: fake)
    monkeypatch.setattr(settings, "CONSULTANT_PORTAL_SETTLEMENTS_ADDRESSES", ADDRESS)
    return fake


@pytest_asyncio.fixture
async def switches_on():
    """Moduł rozliczeń i przypomnienia włączone; po teście jak przed."""

    module = await _get_setting("client_settlements")
    switch = await _get_setting(reminders.SETTING_KEY)
    await _set_setting("client_settlements", {"enabled": True})
    await _set_setting(reminders.SETTING_KEY, {"enabled": True})
    yield
    await _set_setting("client_settlements", module)
    await _set_setting(reminders.SETTING_KEY, switch)


@dataclass
class World:
    client_id: int
    #: Kontrakt z aktywnym panelem i opiekunem kontraktu.
    with_panel: int
    panel_email: str
    #: Kontrakt bez panelu, bez opiekuna — DL klienta.
    no_panel: int
    owner_id: int
    owner_email: str
    lead_id: int


async def _world(*, with_lead: bool = True, with_rules: bool = True) -> World:
    owner = await make_user(UserRole.delivery_lead, name="Opiekun")
    lead = await make_user(UserRole.delivery_lead, name="Lider")
    client_id = await make_client(dl=lead if with_lead else None)
    panel_email = f"konsultant-panel-{client_id}@example.com"
    with_panel, _ = await make_consultant(
        client_id, contract_email=panel_email, owner_id=owner.id
    )
    no_panel, _ = await make_consultant(
        client_id, contract_email=f"konsultant-bez-{client_id}@example.com"
    )
    async with AsyncSessionLocal() as db:
        db.add(CpActivation(contract_id=with_panel, email=panel_email))
        if with_rules:
            # Reguły rozliczeń = klient w automacie (``automatic_clients``).
            db.add(
                ClientSettlementRuleSet(
                    client_id=client_id, effective_from="2020-01", rules={}
                )
            )
        await db.commit()
    return World(
        client_id=client_id,
        with_panel=with_panel,
        panel_email=panel_email,
        no_panel=no_panel,
        owner_id=owner.id,
        owner_email=owner.email,
        lead_id=lead.id,
    )


async def _cleanup(client_id: int) -> None:
    async with AsyncSessionLocal() as db:
        ids = select(Contract.id).where(Contract.client_id == client_id)
        await db.execute(delete(CpActivation).where(CpActivation.contract_id.in_(ids)))
        await db.execute(delete(CpDocument).where(CpDocument.contract_id.in_(ids)))
        await db.execute(
            delete(ClientSettlement).where(ClientSettlement.client_id == client_id)
        )
        await db.execute(
            delete(ClientSettlementRule).where(
                ClientSettlementRule.client_id == client_id
            )
        )
        await db.execute(
            delete(ClientSettlementRuleSet).where(
                ClientSettlementRuleSet.client_id == client_id
            )
        )
        await db.execute(
            delete(Notification).where(
                Notification.notification_type
                == NotificationType.settlement_report_missing,
                Notification.related_entity_id == client_id,
            )
        )
        await db.execute(
            text("DELETE FROM delivery_lead_client_assignments WHERE client_id = :id"),
            {"id": client_id},
        )
        await db.execute(delete(Contract).where(Contract.client_id == client_id))
        await db.execute(delete(Client).where(Client.id == client_id))
        await db.commit()


async def _journal(contract_id: int) -> list[ClientSettlementReminder]:
    async with AsyncSessionLocal() as db:
        return list(
            (
                await db.scalars(
                    select(ClientSettlementReminder)
                    .where(ClientSettlementReminder.contract_id == contract_id)
                    .order_by(ClientSettlementReminder.id)
                )
            ).all()
        )


async def _bells(user_id: int, client_id: int) -> list[Notification]:
    async with AsyncSessionLocal() as db:
        return list(
            (
                await db.scalars(
                    select(Notification).where(
                        Notification.user_id == user_id,
                        Notification.notification_type
                        == NotificationType.settlement_report_missing,
                        Notification.related_entity_id == client_id,
                    )
                )
            ).all()
        )


async def test_lista_brakow_pomija_raport_i_rozliczenie_a_pokazuje_adresatow(
    portal_restored,  # noqa: F811
    mailer,
) -> None:
    world = await _world()
    month = _previous_month()
    year, mon = (int(x) for x in month.split("-"))
    with_report, _ = await make_consultant(world.client_id)
    settled, _ = await make_consultant(world.client_id)
    draft, _ = await make_consultant(world.client_id, status=ContractStatus.draft)
    try:
        await set_portal("pilot")
        async with AsyncSessionLocal() as db:
            db.add(
                CpDocument(
                    contract_id=with_report,
                    kind="report",
                    period_year=year,
                    period_month=mon,
                    status="received",
                    file_path="x/raport.pdf",
                    file_name="raport.pdf",
                    mime="application/pdf",
                    sha256="a" * 64,
                    size_bytes=10,
                    channel="mailbox",
                )
            )
            db.add(
                ClientSettlement(
                    client_id=world.client_id,
                    contract_id=settled,
                    period_month=month,
                    kind="actual",
                    status="needs_fix",
                )
            )
            await db.commit()
            items = {
                i.contract_id: i
                for i in await reminders.missing_reports(
                    db, month, client_id=world.client_id
                )
            }
        assert set(items) == {world.with_panel, world.no_panel}
        panel = items[world.with_panel]
        assert panel.mail_allowed and panel.consultant_email == world.panel_email
        assert (panel.owner.user_id, panel.owner.source) == (
            world.owner_id,
            "contract_care",
        )
        other = items[world.no_panel]
        assert other.consultant_reason == reminders.REASON_NO_PANEL
        assert (other.owner.user_id, other.owner.source) == (world.lead_id, "client_dl")
    finally:
        await _cleanup(world.client_id)


async def test_tylko_zespol_nie_wysyla_nic_do_konsultanta(
    portal_restored,  # noqa: F811
    mailer,
    switches_on,
) -> None:
    world = await _world()
    try:
        await set_portal("internal")
        async with AsyncSessionLocal() as db:
            result = await reminders.run_step(db, _day("day3"))
        assert result["status"] == "done" and result["step"] == "day3"
        assert mailer.to(world.panel_email) == []
        assert await _journal(world.with_panel) == []
    finally:
        await _cleanup(world.client_id)


async def test_trzeci_dzien_mail_raz_dziennie_a_piaty_z_opiekunem_w_kopii(
    portal_restored,  # noqa: F811
    mailer,
    switches_on,
) -> None:
    world = await _world()
    try:
        await set_portal("pilot")
        async with AsyncSessionLocal() as db:
            await reminders.run_step(db, _day("day3"))
        async with AsyncSessionLocal() as db:
            again = await reminders.run_step(db, _day("day3"))
        sent = mailer.to(world.panel_email)
        assert len(sent) == 1, "drugi przebieg tego samego dnia nic nie wysyła"
        assert sent[0]["cc"] is None
        assert ADDRESS in sent[0]["text"]
        assert again["already_today"] >= 1
        journal = await _journal(world.with_panel)
        assert [(r.step, r.channel, r.outcome) for r in journal] == [
            ("day3", "consultant", "sent")
        ]
        # Kontrakt bez panelu nie dostaje maila w żadnym kroku.
        assert mailer.to(f"konsultant-bez-{world.client_id}@example.com") == []

        async with AsyncSessionLocal() as db:
            await reminders.run_step(db, _day("day5"))
        fifth = mailer.to(world.panel_email)[-1]
        assert fifth["cc"] == world.owner_email
        assert len(await _journal(world.with_panel)) == 2
    finally:
        await _cleanup(world.client_id)


async def test_automat_pomija_klienta_bez_regul_rozliczen(
    portal_restored,  # noqa: F811
    mailer,
    switches_on,
) -> None:
    world = await _world(with_rules=False)
    try:
        await set_portal("pilot")
        async with AsyncSessionLocal() as db:
            await reminders.run_step(db, _day("day3"))
            await reminders.run_step(db, _day("day7"))
            view = await reminders.overview(
                db, _previous_month(), client_id=world.client_id
            )
        assert mailer.to(world.panel_email) == []
        assert await _bells(world.lead_id, world.client_id) == []
        assert await _journal(world.with_panel) == []
        # Na liście Finansów klient jest, z informacją, że automat go pomija.
        (client,) = view["clients"]
        assert client["automatic"] is False and client["missing"] == 2
    finally:
        await _cleanup(world.client_id)


async def test_siodmy_dzien_dzwonek_opiekuna_raz_dziennie(
    portal_restored,  # noqa: F811
    mailer,
    switches_on,
) -> None:
    world = await _world()
    try:
        await set_portal("internal")
        async with AsyncSessionLocal() as db:
            await reminders.run_step(db, _day("day7"))
        async with AsyncSessionLocal() as db:
            await reminders.run_step(db, _day("day7"))
        owner_bells = await _bells(world.owner_id, world.client_id)
        lead_bells = await _bells(world.lead_id, world.client_id)
        assert len(owner_bells) == 1 and len(lead_bells) == 1
        assert "(1)" in owner_bells[0].title
        assert owner_bells[0].link == f"/contracts/{world.with_panel}"
        journal = await _journal(world.no_panel)
        assert [(r.step, r.channel, r.owner_user_id) for r in journal] == [
            ("day7", "owner", world.lead_id)
        ]
        assert mailer.sent == [] or mailer.to(world.panel_email) == []
    finally:
        await _cleanup(world.client_id)


async def test_dzien_bez_kroku_i_wylaczony_przelacznik_nic_nie_robia(
    portal_restored,  # noqa: F811
    mailer,
) -> None:
    world = await _world()
    previous = await _get_setting(reminders.SETTING_KEY)
    module = await _get_setting("client_settlements")
    try:
        await set_portal("pilot")
        await _set_setting("client_settlements", {"enabled": True})
        await _set_setting(reminders.SETTING_KEY, None)
        async with AsyncSessionLocal() as db:
            assert await reminders.run_step(db, _day("day3")) == {"status": "disabled"}
            with pytest.raises(SettlementError):
                await reminders.send_manual(
                    db,
                    world.client_id,
                    _previous_month(),
                    actor=await db.get(User, world.owner_id),
                    today=_day("day3"),
                )
        await _set_setting(reminders.SETTING_KEY, {"enabled": True})
        async with AsyncSessionLocal() as db:
            # 4. dzień roboczy nie jest krokiem.
            third = _day("day3")
            fourth = next(
                third.replace(day=third.day + k)
                for k in range(1, 5)
                if reminders.business_day_number(third.replace(day=third.day + k)) == 4
            )
            assert await reminders.run_step(db, fourth) == {"status": "not_today"}
        assert mailer.sent == []
    finally:
        await _set_setting(reminders.SETTING_KEY, previous)
        await _set_setting("client_settlements", module)
        await _cleanup(world.client_id)


async def test_bez_adresata_zostaje_na_liscie_i_w_liczbie(
    portal_restored,  # noqa: F811
    mailer,
    switches_on,
) -> None:
    world = await _world(with_lead=False)
    try:
        await set_portal("internal")
        async with AsyncSessionLocal() as db:
            view = await reminders.overview(
                db, _previous_month(), client_id=world.client_id
            )
            counts = await reminders.send_manual(
                db,
                world.client_id,
                _previous_month(),
                actor=await db.get(User, world.owner_id),
                today=business_today(),
            )
        (client,) = view["clients"]
        assert client["missing"] == 2
        assert client["without_recipient"] == 1
        nobody = next(r for r in client["rows"] if r["contract_id"] == world.no_panel)
        assert nobody["action"] == "none" and nobody["owner"] is None
        assert nobody["consultant"]["reason"] == reminders.REASON_PORTAL_CLOSED
        assert counts["without_recipient"] == 1
        assert counts["bells"] == 1 and counts["mails"] == 0
        assert await _journal(world.no_panel) == []
    finally:
        await _cleanup(world.client_id)


async def test_api_podglad_przycisk_i_przelacznik_tylko_admina(
    app_client,
    portal_restored,  # noqa: F811
    mailer,
    switches_on,
) -> None:
    world = await _world()
    admin = await make_user(UserRole.admin, name="Admin")
    finance = await make_user(UserRole.finance, name="Finanse")
    base = "/api/finance/settlements/reminders"
    month = _previous_month()
    try:
        await set_portal("pilot")
        view = await app_client.get(
            base,
            params={"month": month, "client_id": world.client_id},
            headers=headers(finance),
        )
        assert view.status_code == 200, view.text
        body = view.json()
        assert body["enabled"] is True
        (client,) = body["clients"]
        assert client["to_consultant"] == 1 and client["to_owner"] == 1
        assert client["last_reminder_on"] is None
        assert ADDRESS in client["mail"]["text"]

        sent = await app_client.post(
            f"{base}/send",
            json={"client_id": world.client_id, "month": month},
            headers=headers(finance),
        )
        assert sent.status_code == 200, sent.text
        assert sent.json()["mails"] == 1 and sent.json()["bells"] == 1
        assert mailer.to(world.panel_email)[-1]["cc"] == world.owner_email
        again = await app_client.post(
            f"{base}/send",
            json={"client_id": world.client_id, "month": month},
            headers=headers(finance),
        )
        assert again.json()["already_today"] == 2
        assert len(mailer.to(world.panel_email)) == 1

        after = await app_client.get(
            base,
            params={"month": month, "client_id": world.client_id},
            headers=headers(finance),
        )
        assert after.json()["clients"][0]["last_reminder_on"] == (
            business_today().isoformat()
        )

        refused = await app_client.put(
            f"{base}/settings", json={"enabled": False}, headers=headers(finance)
        )
        assert refused.status_code == 403
        off = await app_client.put(
            f"{base}/settings", json={"enabled": False}, headers=headers(admin)
        )
        assert off.status_code == 200 and off.json() == {"enabled": False}
        blocked = await app_client.post(
            f"{base}/send",
            json={"client_id": world.client_id, "month": month},
            headers=headers(finance),
        )
        assert blocked.status_code == 409
    finally:
        await _cleanup(world.client_id)
        async with AsyncSessionLocal() as db:
            assert (
                await db.scalar(
                    select(func.count())
                    .select_from(ClientSettlementReminder)
                    .where(ClientSettlementReminder.client_id == world.client_id)
                )
                == 0
            )
