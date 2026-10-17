"""Odpowiedzi na komunikat stają się sprawami administracja@ (O12, M8).

Czytnik skrzynki rozpoznaje znacznik ``[Komunikat <id>/<kod>]`` w temacie
nowej sprawy: przypina ją do komunikatu, a gdy nadawca jest odbiorcą —
także do jego kontraktu (opiekun widzi odpowiedź przy konsultancie). Sam
numer bez właściwego kodu niczego nie przypina. Odbity mail (zwrotka serwera
z adresem odbiorcy) oznacza osobę jako „odbity” i daje opiekunowi
powiadomienie „popraw e-mail”. Fałszywa skrzynka, dane fikcyjne.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.admin_case import AdminCase, AdminCaseMessage
from app.models.care_announcement import (
    CareAnnouncement,
    CareAnnouncementRecipient,
    CareAnnouncementReply,
)
from app.models.notification import Notification, NotificationType
from app.models.user import UserRole
from tests.care_announcements_seed import make_client, make_consultant, make_user
from tests.test_admin_cases_mail_ingest import (  # noqa: F401  (fixture'y)
    FakeMailbox,
    _run,
    cases_on,
    mailbox_on,
)

pytestmark = pytest.mark.asyncio


async def _sent_announcement() -> dict:
    author = await make_user(UserRole.talent_community_manager)
    owner = await make_user(UserRole.talent_community_manager, name="Natalia")
    client_id = await make_client()
    contract_id, candidate_id = await make_consultant(client_id, owner_id=owner.id)
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        announcement = CareAnnouncement(
            code="QW34",
            kind="mandatory",
            status="sent",
            subject="Od listopada faktury do 5. dnia miesiąca",
            body="Cześć {imię}",
            audience={"group": "client", "client_ids": [client_id]},
            created_by=author.id,
            queued_at=now,
        )
        db.add(announcement)
        await db.flush()
        recipient = CareAnnouncementRecipient(
            announcement_id=announcement.id,
            candidate_id=candidate_id,
            contract_id=contract_id,
            client_id=client_id,
            owner_user_id=owner.id,
            email=f"odbiorca-{announcement.id}@example.com",
            first_name="Anna",
            status="sent",
            sent_at=now,
        )
        db.add(recipient)
        await db.commit()
        return {
            "id": announcement.id,
            "marker": f"[Komunikat {announcement.id}/QW34]",
            "recipient_id": recipient.id,
            "email": recipient.email,
            "contract_id": contract_id,
            "owner_id": owner.id,
        }


async def _case_of(message_id: str) -> AdminCase:
    async with AsyncSessionLocal() as db:
        case_id = await db.scalar(
            select(AdminCaseMessage.case_id).where(
                AdminCaseMessage.graph_message_id == message_id
            )
        )
        return await db.get(AdminCase, case_id)


async def _link_of(case_id: int):
    async with AsyncSessionLocal() as db:
        return await db.scalar(
            select(CareAnnouncementReply).where(
                CareAnnouncementReply.case_id == case_id
            )
        )


@pytest.mark.usefixtures("mailbox_on")
async def test_reply_with_marker_becomes_case_linked_to_consultant() -> None:
    sent = await _sent_announcement()
    fake = FakeMailbox()
    reply = fake.add(
        subject=f"RE: Od listopada faktury {sent['marker']}",
        hours_ago=1,
        sender=sent["email"],
    )
    result = await _run(fake)
    assert result["created"] == 1

    case = await _case_of(reply["id"])
    link = await _link_of(case.id)
    assert link is not None
    assert link.announcement_id == sent["id"]
    assert link.kind == "reply"
    assert link.recipient_id == sent["recipient_id"]
    assert case.contract_id == sent["contract_id"]


@pytest.mark.usefixtures("mailbox_on")
async def test_number_without_the_right_code_links_nothing() -> None:
    sent = await _sent_announcement()
    fake = FakeMailbox()
    forged = fake.add(
        subject=f"RE: coś [Komunikat {sent['id']}/ZZZZ]",
        hours_ago=1,
        sender=sent["email"],
    )
    await _run(fake)
    case = await _case_of(forged["id"])
    assert await _link_of(case.id) is None
    assert case.contract_id is None


@pytest.mark.usefixtures("mailbox_on")
async def test_reply_from_unknown_sender_links_announcement_only() -> None:
    sent = await _sent_announcement()
    fake = FakeMailbox()
    reply = fake.add(subject=f"Odp: {sent['marker']}", hours_ago=1)
    await _run(fake)
    case = await _case_of(reply["id"])
    link = await _link_of(case.id)
    assert link.announcement_id == sent["id"] and link.recipient_id is None
    assert case.contract_id is None


@pytest.mark.usefixtures("mailbox_on")
async def test_bounce_marks_recipient_and_asks_owner_to_fix_email() -> None:
    sent = await _sent_announcement()
    fake = FakeMailbox()
    bounce = fake.add(
        subject=f"Undeliverable: Od listopada faktury {sent['marker']}",
        hours_ago=1,
        sender="postmaster@example.com",
    )
    bounce["body"] = {
        "contentType": "text",
        "content": f"Delivery has failed to these recipients: {sent['email']}",
    }
    await _run(fake)

    case = await _case_of(bounce["id"])
    link = await _link_of(case.id)
    assert link.kind == "bounce" and link.recipient_id == sent["recipient_id"]
    async with AsyncSessionLocal() as db:
        recipient = await db.get(CareAnnouncementRecipient, sent["recipient_id"])
        assert recipient.status == "bounced" and recipient.bounced_at is not None
        notified = await db.scalar(
            select(Notification).where(
                Notification.user_id == sent["owner_id"],
                Notification.notification_type == NotificationType.care_announcement,
            )
        )
    assert notified is not None
    assert notified.link == f"/contracts/{sent['contract_id']}"
    # Adres konsultanta nie trafia do tytułu ani treści powiadomienia.
    assert sent["email"] not in f"{notified.title} {notified.message}"


@pytest.mark.usefixtures("mailbox_on")
async def test_undeliverable_subject_from_a_person_is_a_reply_not_a_bounce() -> None:
    """Zwrotkę wysyła serwer — temat „Undeliverable” od człowieka niczego nie odbija."""

    sent = await _sent_announcement()
    fake = FakeMailbox()
    forged = fake.add(
        subject=f"Undeliverable: {sent['marker']}",
        hours_ago=1,
        sender="ktos@example.com",
    )
    forged["body"] = {
        "contentType": "text",
        "content": f"nie doszło do {sent['email']}",
    }
    await _run(fake)
    case = await _case_of(forged["id"])
    link = await _link_of(case.id)
    assert link.kind == "reply"
    async with AsyncSessionLocal() as db:
        recipient = await db.get(CareAnnouncementRecipient, sent["recipient_id"])
    assert recipient.status == "sent"
