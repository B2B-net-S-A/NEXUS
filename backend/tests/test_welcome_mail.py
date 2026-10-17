"""Mail powitalny konsultanta (etap 3, O6, karta z makiety M6).

Nic nie wychodzi do konsultantów: przełącznik jest domyślnie wyłączony,
a w testach nadawcą jest fałszywa skrzynka (podmieniona zależność trasy).
Dane fikcyjne (repo jest publiczne).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Optional

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.equipment import ConsultantWelcomeMail
from app.models.hr_ops import HrAuditEvent
from app.models.user import UserRole
from app.services.hr import client_pack, welcome_mail
from tests.client_onboarding_support import (
    PREFIX,
    ensure_router_mounted,
    get_setting,
    headers,
    make_client,
    make_contact,
    make_contract,
    make_user,
    modules_state,
    set_setting,
)

pytestmark = pytest.mark.asyncio

MAILBOX = "administracja-test@example.com"


@dataclass(frozen=True)
class Outcome:
    """Wynik nadawcy jak ``care.announcement_mail.MailOutcome``."""

    status: str
    code: Optional[str] = None
    simulated: bool = False


class FakeSender:
    def __init__(self) -> None:
        self.status = "accepted"
        self.sent: list[dict] = []

    async def send(self, *, to: str, subject: str, text: str) -> Outcome:
        self.sent.append({"to": to, "subject": subject, "text": text})
        return Outcome(self.status)


@pytest_asyncio.fixture
async def fake_sender():
    from app.main import app

    ensure_router_mounted()
    sender = FakeSender()
    app.dependency_overrides[welcome_mail.default_sender] = lambda: sender
    try:
        yield sender
    finally:
        app.dependency_overrides.pop(welcome_mail.default_sender, None)


@pytest_asyncio.fixture
async def modules_on():
    ensure_router_mounted()
    async with modules_state(True):
        yield


@pytest_asyncio.fixture
async def mail_switch():
    """Przełącznik na czas testu; po teście wraca stan sprzed (domyślnie brak)."""
    previous = await get_setting(welcome_mail.SETTING_KEY)

    async def _set(enabled: bool) -> None:
        await set_setting(welcome_mail.SETTING_KEY, {"enabled": enabled})

    try:
        yield _set
    finally:
        await set_setting(welcome_mail.SETTING_KEY, previous)


@pytest.fixture
def mailbox(monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_CASES_MAILBOX", MAILBOX)


def _url(contract_id: int) -> str:
    return f"{PREFIX}/contracts/{contract_id}/welcome-mail"


async def _pack(client_id: int) -> int:
    manager = await make_contact(client_id, "Piotr Menedżer")
    actor = await make_user(UserRole.admin)
    async with AsyncSessionLocal() as db:
        await client_pack.save_pack(
            db,
            client_id,
            {
                "first_day": {
                    "place": "ul. Przykładowa 20, recepcja B",
                    "time": "09:00",
                },
                "documents": [
                    {"name": "Zaświadczenie o niekaralności", "offset_days": -5},
                    {"name": "NDA klienta", "offset_days": 0},
                ],
            },
            actor=actor,
        )
        await db.commit()
    return manager


# ── Treść ─────────────────────────────────────────────────────────────────────


def test_compose_builds_the_mockup_mail() -> None:
    subject, body = welcome_mail.compose(
        first_name="Marek",
        client_name="Bank Przykładowy",
        start_date=date(2026, 11, 2),  # poniedziałek
        first_day=client_pack.FirstDay(
            contact_id=1,
            contact_name="Piotr Przykładowy",
            place="ul. Przykładowa 20, recepcja B",
            time="09:00",
            bring="dowód osobisty",
        ),
        documents=(
            client_pack.PackItem(name="Zaświadczenie o niekaralności", offset_days=-5),
            client_pack.PackItem(
                name="NDA klienta", note="podpis u klienta", offset_days=0
            ),
            client_pack.PackItem(name="Szkolenie bezpieczeństwa", offset_days=7),
        ),
        owner_name="Zofia Opiekuńska",
        owner_email="opiekun@example.com",
    )
    assert subject == "Twój start w Bank Przykładowy — 02.11.2026"
    lines = body.splitlines()
    assert lines[0] == "Cześć Marek,"
    assert (
        "w poniedziałek 02.11 o 9:00 zaczynasz w Bank Przykładowy "
        "(ul. Przykładowa 20, recepcja B)." in lines
    )
    assert "Odbierze Cię Piotr Przykładowy." in lines
    assert "Zabierz ze sobą: dowód osobisty." in lines
    assert "Przed startem prześlij: Zaświadczenie o niekaralności." in lines
    assert "W dniu startu: NDA klienta (podpis u klienta)." in lines
    assert "W pierwszych dniach po starcie: Szkolenie bezpieczeństwa." in lines
    assert lines[-2:] == ["Zofia Opiekuńska", "opiekun@example.com"]


def test_compose_without_pack_and_owner_stays_polite() -> None:
    subject, body = welcome_mail.compose(
        first_name=None,
        client_name="Bank Przykładowy",
        start_date=date(2026, 11, 4),
        first_day=None,
        documents=(),
        owner_name=None,
        owner_email=None,
    )
    assert body.startswith(
        "Dzień dobry,\n\nw środę 04.11 zaczynasz w Bank Przykładowy."
    )
    assert "Odbierze" not in body and "prześlij" not in body
    assert body.endswith("Pozdrawiamy")


# ── Podgląd i wysyłka ─────────────────────────────────────────────────────────


async def test_switch_is_off_by_default_and_sending_answers_409(
    app_client, modules_on, mail_switch, mailbox, fake_sender
) -> None:
    await set_setting(welcome_mail.SETTING_KEY, None)
    dl = await make_user(UserRole.delivery_lead)
    client_id = await make_client(dl=dl)
    contract_id = await make_contract(client_id)
    state = await app_client.get(_url(contract_id), headers=headers(dl))
    assert state.status_code == 200, state.text
    body = state.json()
    assert body["enabled"] is False and body["can_send"] is False
    assert body["draft"]["subject"].startswith("Twój start w ")
    refused = await app_client.post(
        _url(contract_id),
        json={"subject": "Temat", "body": "Treść"},
        headers=headers(dl),
    )
    assert refused.status_code == 409
    assert refused.json()["detail"] == welcome_mail.DISABLED_DETAIL
    assert fake_sender.sent == []


async def test_care_owner_sends_once_from_administration_mailbox(
    app_client, modules_on, mail_switch, mailbox, fake_sender
) -> None:
    await mail_switch(True)
    dl = await make_user(UserRole.delivery_lead)
    client_id = await make_client(dl=dl)
    manager = await _pack(client_id)
    contract_id = await make_contract(client_id, manager_contact_id=manager)
    state = (await app_client.get(_url(contract_id), headers=headers(dl))).json()
    assert state["can_send"] is True and state["issues"] == []
    draft = state["draft"]
    assert "Odbierze Cię Piotr Menedżer" in draft["body"]
    assert "Przed startem prześlij: Zaświadczenie o niekaralności." in draft["body"]

    edited = draft["body"] + "\n\nDo zobaczenia w biurze."
    sent = await app_client.post(
        _url(contract_id),
        json={"subject": draft["subject"], "body": edited},
        headers=headers(dl),
    )
    assert sent.status_code == 201, sent.text
    assert sent.json()["sent"]["body"] == edited
    assert sent.json()["sent"]["sent_by_name"] == dl.name
    (mail,) = fake_sender.sent
    assert mail["to"] == draft["recipient_email"]
    assert mail["text"] == edited
    assert sent.json()["sent"]["delivery"] == "sent"

    again = await app_client.post(
        _url(contract_id),
        json={"subject": draft["subject"], "body": edited},
        headers=headers(dl),
    )
    assert again.status_code == 409 and "wysłano już" in again.json()["detail"]
    assert len(fake_sender.sent) == 1
    async with AsyncSessionLocal() as db:
        rows = (
            await db.scalars(
                select(ConsultantWelcomeMail).where(
                    ConsultantWelcomeMail.contract_id == contract_id
                )
            )
        ).all()
        events = (
            await db.scalars(
                select(HrAuditEvent).where(
                    HrAuditEvent.entity_type == "contract",
                    HrAuditEvent.entity_id == str(contract_id),
                    HrAuditEvent.action == "welcome_mail_sent",
                )
            )
        ).all()
    assert len(rows) == 1 and len(events) == 1
    # Ślad bez adresu i treści maila.
    assert set(events[0].details) == {
        "welcome_mail_id",
        "delivery",
        "entry_task_checked",
    }


async def test_failed_send_saves_nothing_and_can_be_retried(
    app_client, modules_on, mail_switch, mailbox, fake_sender
) -> None:
    await mail_switch(True)
    fake_sender.status = "deferred"
    dl = await make_user(UserRole.delivery_lead)
    contract_id = await make_contract(await make_client(dl=dl))
    failed = await app_client.post(
        _url(contract_id),
        json={"subject": "Temat", "body": "Treść"},
        headers=headers(dl),
    )
    assert failed.status_code == 502
    async with AsyncSessionLocal() as db:
        assert await welcome_mail.sent_for(db, contract_id) is None
    fake_sender.status = "accepted"
    retried = await app_client.post(
        _url(contract_id),
        json={"subject": "Temat", "body": "Treść"},
        headers=headers(dl),
    )
    assert retried.status_code == 201


async def test_missing_mailbox_or_email_blocks_sending(
    app_client, modules_on, mail_switch, monkeypatch, fake_sender
) -> None:
    await mail_switch(True)
    dl = await make_user(UserRole.delivery_lead)
    client_id = await make_client(dl=dl)
    no_email = await make_contract(client_id, email=None)
    monkeypatch.setattr(settings, "ADMIN_CASES_MAILBOX", "")
    no_box = await app_client.post(
        _url(no_email), json={"subject": "T", "body": "B"}, headers=headers(dl)
    )
    assert no_box.status_code == 409 and "administracja@" in no_box.json()["detail"]
    monkeypatch.setattr(settings, "ADMIN_CASES_MAILBOX", MAILBOX)
    state = (await app_client.get(_url(no_email), headers=headers(dl))).json()
    assert state["can_send"] is False
    assert (
        {"no_email", "no_pack", "no_owner"}
        >= {i["code"] for i in state["issues"]}
        >= {
            "no_email",
            "no_pack",
        }
    )
    refused = await app_client.post(
        _url(no_email), json={"subject": "T", "body": "B"}, headers=headers(dl)
    )
    assert refused.status_code == 422 and "e-mail" in refused.json()["detail"]
    assert fake_sender.sent == []


async def test_who_reads_and_who_sends(
    app_client, modules_on, mail_switch, mailbox, fake_sender
) -> None:
    await mail_switch(True)
    dl = await make_user(UserRole.delivery_lead)
    other_dl = await make_user(UserRole.delivery_lead)
    viewer = await make_user(UserRole.recruiter, grants=("delivery_view",))
    recruiter = await make_user(UserRole.recruiter)
    tcm = await make_user(UserRole.talent_community_manager)
    contract_id = await make_contract(await make_client(dl=dl))

    assert (
        await app_client.get(_url(contract_id), headers=headers(other_dl))
    ).status_code == 403
    assert (
        await app_client.get(_url(contract_id), headers=headers(recruiter))
    ).status_code == 403
    read = await app_client.get(_url(contract_id), headers=headers(viewer))
    assert read.status_code == 200 and read.json()["can_send"] is False
    assert (
        await app_client.post(
            _url(contract_id),
            json={"subject": "T", "body": "B"},
            headers=headers(viewer),
        )
    ).status_code == 403
    assert (
        await app_client.post(
            _url(contract_id),
            json={"subject": "T", "body": "B"},
            headers=headers(other_dl),
        )
    ).status_code == 403
    by_tcm = await app_client.post(
        _url(contract_id), json={"subject": "T", "body": "B"}, headers=headers(tcm)
    )
    assert by_tcm.status_code == 201, by_tcm.text
    assert (await app_client.get(_url(10**9), headers=headers(dl))).status_code == 404


async def test_only_admin_flips_the_switch(app_client, modules_on, mail_switch) -> None:
    await set_setting(welcome_mail.SETTING_KEY, None)
    dl = await make_user(UserRole.delivery_lead)
    admin = await make_user(UserRole.admin)
    url = f"{PREFIX}/welcome-mail/switch"
    assert (await app_client.get(url, headers=headers(dl))).json() == {"enabled": False}
    refused = await app_client.put(url, json={"enabled": True}, headers=headers(dl))
    assert refused.status_code == 403
    flipped = await app_client.put(url, json={"enabled": True}, headers=headers(admin))
    assert flipped.status_code == 200 and flipped.json() == {"enabled": True}
    assert await get_setting(welcome_mail.SETTING_KEY) == {"enabled": True}


async def test_sending_checks_off_the_welcome_mail_entry_task(
    app_client, modules_on, mail_switch, mailbox, fake_sender
) -> None:
    """Wysłanie odhacza pozycję ``welcome_mail`` w wejściu konsultanta (G1)."""
    from app.models.contract import Contract
    from app.models.hr_lifecycle import LifecycleTask
    from app.services.hr import lifecycle_entry
    from app.services.hr_lifecycle_schema import KEY_WELCOME_MAIL

    await mail_switch(True)
    dl = await make_user(UserRole.delivery_lead)
    client_id = await make_client(dl=dl)
    manager = await _pack(client_id)
    contract_id = await make_contract(client_id, manager_contact_id=manager)
    async with AsyncSessionLocal() as db:
        case = await lifecycle_entry.ensure_contract_entry(
            db, await db.get(Contract, contract_id)
        )
        assert case is not None, "ścieżka „Konsultant u klienta” nie jest zasiana"
        await db.commit()
        case_id = case.id

    async def welcome_task() -> LifecycleTask:
        async with AsyncSessionLocal() as db:
            return await db.scalar(
                select(LifecycleTask).where(
                    LifecycleTask.case_id == case_id,
                    LifecycleTask.key == KEY_WELCOME_MAIL,
                )
            )

    assert (await welcome_task()).status == "open"
    state = (await app_client.get(_url(contract_id), headers=headers(dl))).json()
    sent = await app_client.post(
        _url(contract_id),
        json={"subject": state["draft"]["subject"], "body": state["draft"]["body"]},
        headers=headers(dl),
    )
    assert sent.status_code == 201, sent.text
    task = await welcome_task()
    assert task.status == "done" and task.done_by == dl.id


async def test_uncertain_send_is_kept_so_nobody_sends_twice(
    app_client, modules_on, mail_switch, mailbox, fake_sender
) -> None:
    await mail_switch(True)
    fake_sender.status = "uncertain"
    dl = await make_user(UserRole.delivery_lead)
    contract_id = await make_contract(await make_client(dl=dl))
    first = await app_client.post(
        _url(contract_id), json={"subject": "T", "body": "B"}, headers=headers(dl)
    )
    assert first.status_code == 201
    assert first.json()["sent"]["delivery"] == "uncertain"
    again = await app_client.post(
        _url(contract_id), json={"subject": "T", "body": "B"}, headers=headers(dl)
    )
    assert again.status_code == 409
    assert len(fake_sender.sent) == 1


async def test_simulation_mode_sends_nothing_and_says_so(
    app_client, modules_on, mail_switch, mailbox, monkeypatch
) -> None:
    """Lokalnie (``HR_M365_MODE=simulate``) nic nie wychodzi — ślad to mówi."""
    ensure_router_mounted()
    await mail_switch(True)
    monkeypatch.setattr(settings, "HR_M365_MODE", "simulate")
    dl = await make_user(UserRole.delivery_lead)
    contract_id = await make_contract(await make_client(dl=dl))
    sent = await app_client.post(
        _url(contract_id), json={"subject": "T", "body": "B"}, headers=headers(dl)
    )
    assert sent.status_code == 201, sent.text
    assert sent.json()["sent"]["delivery"] == "simulated"


async def test_microsoft_365_off_means_no_sender(
    app_client, modules_on, mail_switch, mailbox, monkeypatch
) -> None:
    ensure_router_mounted()
    await mail_switch(True)
    monkeypatch.setattr(settings, "HR_M365_MODE", "off")
    dl = await make_user(UserRole.delivery_lead)
    contract_id = await make_contract(await make_client(dl=dl))
    state = (await app_client.get(_url(contract_id), headers=headers(dl))).json()
    assert state["transport_ready"] is False and state["can_send"] is False
    refused = await app_client.post(
        _url(contract_id), json={"subject": "T", "body": "B"}, headers=headers(dl)
    )
    assert refused.status_code == 409
    assert refused.json()["detail"] == welcome_mail.NO_TRANSPORT_DETAIL
    async with AsyncSessionLocal() as db:
        assert await welcome_mail.sent_for(db, contract_id) is None


async def test_after_contract_merge_the_first_mail_counts() -> None:
    """Scalenie duplikatów kontraktu przenosi oba ślady — bez UNIQUE i bez kasowania."""
    from datetime import datetime, timezone

    contract_id = await make_contract(await make_client())
    async with AsyncSessionLocal() as db:
        for day, body in ((3, "drugi"), (1, "pierwszy")):
            db.add(
                ConsultantWelcomeMail(
                    contract_id=contract_id,
                    recipient_email="kons@example.com",
                    subject="Temat",
                    body=body,
                    sent_at=datetime(2026, 10, day, 9, tzinfo=timezone.utc),
                )
            )
        await db.commit()
        first = await welcome_mail.sent_for(db, contract_id)
    assert first is not None and first.body == "pierwszy"
