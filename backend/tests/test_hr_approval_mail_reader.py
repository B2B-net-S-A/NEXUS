# ruff: noqa: F811 — fixture'y ``client`` i ``team`` z testów API zgód
"""Zgody, etap 2 — czytnik skrzynki zgód (``services/hr/approvals/mail_reader.py``).

Odpowiedź „approved” od osoby, która może teraz zdecydować, zatwierdza zgodę
kanałem ``mail_reply``; inna treść wraca do autora jako pytanie; obcy adres,
zgoda już rozpatrzona i odpowiedź na wersję sprzed poprawki — nic. Ten sam
mail drugi raz nic nie robi. Skrzynka jest fałszywa, dane fikcyjne.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from sqlalchemy import delete

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.app_setting import AppSetting
from app.models.hr_approval import ApprovalRequest
from app.models.notification import NotificationType
from app.models.user import User
from app.services.hr.approvals import mail as approval_mail
from app.services.hr.approvals import mail_reader, mail_reply
from tests.test_hr_approvals_api import (  # noqa: F401  (fixture'y zgód)
    BASE,
    _headers,
    _notifications,
    _trip,
    client,
    team,
)

MAILBOX = "zgody@example.com"


class FakeMailbox:
    def __init__(self, messages: list[dict]) -> None:
        self.messages = messages

    async def list_messages(self, mailbox: str, since: datetime) -> list[dict]:
        assert mailbox == MAILBOX
        return list(self.messages)


@pytest_asyncio.fixture
async def reply_on(monkeypatch):
    monkeypatch.setattr(settings, "HR_APPROVALS_MAIL_REPLY_ENABLED", True)
    monkeypatch.setattr(settings, "HR_APPROVALS_REPLY_MAILBOX", MAILBOX)
    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(AppSetting).where(AppSetting.key == mail_reader.STATE_KEY)
        )
        await db.commit()
    yield
    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(AppSetting).where(AppSetting.key == mail_reader.STATE_KEY)
        )
        await db.commit()


async def _request(request_id: int) -> ApprovalRequest:
    async with AsyncSessionLocal() as db:
        return await db.get(ApprovalRequest, request_id)


async def _reply(request_id: int, sender: User | str, body: str) -> dict:
    request = await _request(request_id)
    address = sender if isinstance(sender, str) else sender.email
    marker = mail_reply.marker(request.id, request.submitted_at)
    return {
        "id": f"graph-{uuid.uuid4().hex}",
        "subject": f"RE: [Nexus] Zgoda: Delegacja — 980 zł brutto {marker}",
        "from": {"emailAddress": {"address": address.upper()}},
        "sender": {"emailAddress": {"address": address}},
        "receivedDateTime": datetime.now(timezone.utc).isoformat(),
        "body": {
            "contentType": "html",
            "content": f'<div>{body}</div><div id="appendonsend"></div><hr>'
            '<div id="divRplyFwdMsg">Od: Nexus</div><div>approved</div>',
        },
        "internetMessageHeaders": [
            {"name": "X-MS-Exchange-Organization-AuthAs", "value": "Internal"}
        ],
    }


async def _notices(user: User) -> list:
    return [
        notif
        for notif in await _notifications(user, NotificationType.hr_approval_requested)
        if notif.related_entity_type == mail_reply.NOTICE_ENTITY
    ]


async def _run(*messages: dict) -> dict:
    async with AsyncSessionLocal() as db:
        return await mail_reader.run_once(db, FakeMailbox(list(messages)))


async def _submit(client, team, amount: str = "980") -> int:
    created = await client.post(
        BASE, json=_trip(amount), headers=_headers(team["worker"])
    )
    assert created.status_code == 201, created.text
    return created.json()["id"]


@pytest.mark.asyncio
async def test_approved_reply_approves_once(client, team, reply_on) -> None:
    request_id = await _submit(client, team)
    message = await _reply(request_id, team["boss"], "Approved")

    result = await _run(message)
    assert result["status"] == "ok" and result["approved"] == 1
    request = await _request(request_id)
    assert request.status == "approved"
    assert request.decision_channel == "mail_reply"
    assert request.decided_by == team["boss"].id
    assert request.decision_note is None
    (decided,) = await _notifications(
        team["worker"], NotificationType.hr_approval_decided
    )

    # Ten sam mail drugi raz — nic (i bez drugiego dzwonka do autora).
    again = await _run(message)
    assert again.get("duplicate") == 1 and "approved" not in again
    assert (
        len(await _notifications(team["worker"], NotificationType.hr_approval_decided))
        == 1
    )
    assert decided.link == f"/my-time?tab=consents&request={request_id}"


@pytest.mark.asyncio
async def test_other_words_go_back_to_the_author_as_a_question(
    client,
    team,
    reply_on,
) -> None:
    request_id = await _submit(client, team)
    result = await _run(await _reply(request_id, team["boss"], "ok?"))
    assert result["returned"] == 1
    request = await _request(request_id)
    assert request.status == "returned"
    assert request.decision_note == "ok?"
    assert request.decision_channel == "mail_reply"


@pytest.mark.asyncio
async def test_not_approved_is_never_an_approval(client, team, reply_on) -> None:
    request_id = await _submit(client, team)
    await _run(await _reply(request_id, team["boss"], "not approved"))
    request = await _request(request_id)
    assert request.status == "returned"
    assert request.decision_note == "not approved"


@pytest.mark.asyncio
async def test_reply_from_another_address_decides_nothing(
    client,
    team,
    reply_on,
) -> None:
    request_id = await _submit(client, team)
    result = await _run(
        # Konto, które na tym etapie nie decyduje (sama zgoda jest u przełożonego).
        await _reply(request_id, team["colleague"], "approved"),
        # Autor zgody — we własnej sprawie nie decyduje.
        await _reply(request_id, team["worker"], "approved"),
        # Adres spoza NEXUSA.
        await _reply(request_id, "obcy@example.org", "approved"),
    )
    assert result["not_decider"] == 2 and result["foreign_sender"] == 1
    assert (await _request(request_id)).status == "pending_supervisor"

    # Przełożony, ale w czyimś imieniu (sender ≠ from) — też nic.
    on_behalf = await _reply(request_id, team["boss"], "approved")
    on_behalf["sender"] = {"emailAddress": {"address": team["colleague"].email}}
    assert (await _run(on_behalf))["foreign_sender"] == 1
    assert (await _request(request_id)).status == "pending_supervisor"


@pytest.mark.asyncio
async def test_reply_to_an_already_decided_request_does_nothing(
    client,
    team,
    reply_on,
) -> None:
    request_id = await _submit(client, team)
    rejected = await client.post(
        f"{BASE}/{request_id}/decide",
        json={"action": "reject", "note": "Nie w tym kwartale."},
        headers=_headers(team["boss"]),
    )
    assert rejected.status_code == 200, rejected.text
    result = await _run(await _reply(request_id, team["boss"], "approved"))
    assert result["already_decided"] == 1
    request = await _request(request_id)
    assert request.status == "rejected" and request.decision_channel == "app"
    # Decydujący dowiaduje się, że odpowiedź niczego nie zmieniła.
    assert len(await _notices(team["boss"])) == 1


@pytest.mark.asyncio
async def test_old_reply_does_not_approve_the_corrected_request(
    client,
    team,
    reply_on,
) -> None:
    request_id = await _submit(client, team, "900")
    old_reply = await _reply(request_id, team["boss"], "approved")
    returned = await client.post(
        f"{BASE}/{request_id}/decide",
        json={"action": "return", "note": "Dopisz, ile nocy w hotelu."},
        headers=_headers(team["boss"]),
    )
    assert returned.status_code == 200
    fixed = await client.put(
        f"{BASE}/{request_id}", json=_trip("1400"), headers=_headers(team["worker"])
    )
    assert fixed.status_code == 200, fixed.text

    result = await _run(old_reply)
    assert result["stale"] == 1
    assert (await _request(request_id)).status == "pending_supervisor"
    (notice,) = await _notices(team["boss"])
    assert "poprawił" in notice.message
    # Odpowiedź na mail o poprawionej wersji już zatwierdza.
    assert (await _run(await _reply(request_id, team["boss"], "ok")))["approved"] == 1


@pytest.mark.asyncio
async def test_supervisor_reply_over_limit_endorses_then_approver_approves(
    client,
    team,
    reply_on,
) -> None:
    request_id = await _submit(client, team, "3000")
    endorsed = await _run(await _reply(request_id, team["boss"], "zgoda"))
    assert endorsed["endorsed"] == 1
    request = await _request(request_id)
    assert request.status == "pending_final" and request.endorsed_by == team["boss"].id

    # Spóźnione „ok” przełożonego po poparciu — już nie jego etap.
    late = await _run(await _reply(request_id, team["boss"], "ok"))
    assert late["not_decider"] == 1
    approved = await _run(await _reply(request_id, team["ceo"], "Tak."))
    assert approved["approved"] == 1
    assert (await _request(request_id)).decided_by == team["ceo"].id


@pytest.mark.asyncio
async def test_auto_reply_and_unmarked_mail_are_skipped(client, team, reply_on) -> None:
    request_id = await _submit(client, team)
    auto = await _reply(request_id, team["boss"], "Jestem na urlopie")
    auto["subject"] = "Automatic reply: " + auto["subject"]
    unmarked = await _reply(request_id, team["boss"], "approved")
    unmarked["subject"] = "RE: coś innego"
    unmarked["body"]["content"] = "<div>approved</div>"
    result = await _run(auto, unmarked)
    assert result["auto_reply"] == 1 and result["no_marker"] == 1
    assert (await _request(request_id)).status == "pending_supervisor"


@pytest.mark.asyncio
async def test_reader_is_off_without_the_flag(client, team, monkeypatch) -> None:
    monkeypatch.setattr(settings, "HR_APPROVALS_MAIL_REPLY_ENABLED", False)
    monkeypatch.setattr(settings, "HR_APPROVALS_REPLY_MAILBOX", MAILBOX)
    request_id = await _submit(client, team)
    assert (await _run(await _reply(request_id, team["boss"], "ok"))) == {
        "status": "disabled"
    }
    assert (await _request(request_id)).status == "pending_supervisor"


@pytest.mark.asyncio
async def test_mail_to_the_decider_carries_the_marker_and_the_hint(
    client,
    team,
    reply_on,
) -> None:
    request_id = await _submit(client, team)
    (notif,) = await _notifications(
        team["boss"], NotificationType.hr_approval_requested
    )
    async with AsyncSessionLocal() as db:
        subject, text_body, html_body = await approval_mail.render(
            db, notif, await db.get(User, team["boss"].id)
        )
    request = await _request(request_id)
    assert subject.endswith(mail_reply.marker(request.id, request.submitted_at))
    assert "jednym słowem „approved”" in text_body
    assert "wróci do autora jako pytanie" in html_body


@pytest.mark.asyncio
async def test_unauthenticated_reply_decides_nothing_and_tells_the_decider(
    client,
    team,
    reply_on,
) -> None:
    request_id = await _submit(client, team)
    spoofed = await _reply(request_id, team["boss"], "approved")
    spoofed["internetMessageHeaders"] = []
    result = await _run(spoofed)
    assert result["unauthenticated"] == 1
    assert (await _request(request_id)).status == "pending_supervisor"
    (notice,) = await _notices(team["boss"])
    assert notice.link == f"/people/approvals?tab=consents&request={request_id}"
    async with AsyncSessionLocal() as db:
        subject, text_body, _html = await approval_mail.render(
            db, notice, await db.get(User, team["boss"].id)
        )
    assert "nie została zapisana" in subject
    # Bez kwoty i bez treści odpowiedzi.
    assert "980" not in text_body and "approved" not in text_body


@pytest.mark.asyncio
async def test_refused_decision_leaves_the_request_and_tells_the_decider(
    client,
    team,
    reply_on,
    monkeypatch,
) -> None:
    from app.services.hr.approvals import service

    async def _closed(*args, **kwargs):
        raise service.ApprovalConflict("Miesiąc wypłaty jest zamknięty.")

    request_id = await _submit(client, team)
    monkeypatch.setattr(service, "decide", _closed)
    result = await _run(await _reply(request_id, team["boss"], "approved"))
    assert result["refused"] == 1
    assert (await _request(request_id)).status == "pending_supervisor"
    (notice,) = await _notices(team["boss"])
    assert notice.message.startswith("Miesiąc wypłaty jest zamknięty.")
