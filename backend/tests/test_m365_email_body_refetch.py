"""Ponowny odczyt treści maili skasowanych przez aktualizacje delty (02.11.2026)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from sqlalchemy import delete

from app.cli import m365_email_body_refetch as refetch
from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.m365 import Email, EmailDirection, M365Connection, M365SyncStatus
from app.models.user import User, UserRole
from app.services.m365.graph_client import GraphRequestError


def _row(**kw) -> SimpleNamespace:
    base = dict(
        id=5,
        m365_message_id="graph-1",
        m365_internet_message_id="<a@example.com>",
        body_html=None,
        body_text="",
        body_preview="",
        has_attachments=False,
        raw_categories=[],
        is_private_filtered=False,
    )
    base.update(kw)
    return SimpleNamespace(**base)


async def test_fill_row_restores_body_and_attachment_flag() -> None:
    row = _row()
    message = {
        "body": {"contentType": "html", "content": "<p>treść</p>"},
        "bodyPreview": "treść",
        "hasAttachments": True,
        "categories": [],
    }

    assert await refetch.fill_row(row, message) == "filled"

    assert "treść" in row.body_html
    assert "treść" in row.body_text
    assert row.body_preview == "treść"
    assert row.has_attachments is True


async def test_fill_row_does_not_store_private_mail() -> None:
    row = _row()
    message = {
        "body": {"contentType": "html", "content": "<p>prywatne</p>"},
        "bodyPreview": "prywatne",
        "categories": [settings.M365_IGNORE_CATEGORY],
    }

    assert await refetch.fill_row(row, message) == "private"

    assert row.is_private_filtered is True
    assert row.body_html is None
    assert row.body_text == ""


async def test_fill_row_reports_mail_empty_in_mailbox() -> None:
    row = _row()
    message = {"body": {"contentType": "html", "content": ""}, "hasAttachments": True}

    assert await refetch.fill_row(row, message) == "empty_in_mailbox"

    # Pusta wiadomość (zwykle odpowiedź na zaproszenie) zostaje nietknięta.
    assert row.body_html is None
    assert row.has_attachments is False
    assert row.raw_categories == []


def _ghost(**kw) -> SimpleNamespace:
    # Wiersz z aktualizacji delty nieznanej wiadomości: samo id i data zapisu.
    return _row(
        from_address="",
        from_name=None,
        subject=None,
        to_addresses=[],
        cc_addresses=[],
        sent_at=None,
        received_at=datetime(2026, 10, 20, tzinfo=timezone.utc),
        m365_internet_message_id=None,
        m365_conversation_id="graph-1",
        web_link=None,
        direction=EmailDirection.received,
        **kw,
    )


GHOST_MESSAGE = {
    "id": "graph-1",
    "from": {"emailAddress": {"address": "Nadawca@Example.com", "name": "Nadawca"}},
    "toRecipients": [{"emailAddress": {"address": "me@example.com", "name": "Ja"}}],
    "ccRecipients": [],
    "subject": "Temat",
    "sentDateTime": "2026-09-01T10:00:00Z",
    "receivedDateTime": "2026-09-01T10:00:05Z",
    "conversationId": "conv-1",
    "internetMessageId": "<a@example.com>",
    "webLink": "https://outlook.example/1",
}


def test_restore_sender_fills_identity_from_mailbox() -> None:
    row = _ghost()

    assert refetch.restore_sender(row, GHOST_MESSAGE, "me@example.com") is True

    assert row.from_address == "nadawca@example.com"
    assert row.from_name == "Nadawca"
    assert row.subject == "Temat"
    assert row.to_addresses[0]["address"] == "me@example.com"
    assert row.m365_internet_message_id == "<a@example.com>"
    assert row.m365_conversation_id == "conv-1"
    assert row.received_at == datetime(2026, 9, 1, 10, 0, 5, tzinfo=timezone.utc)
    assert row.web_link == "https://outlook.example/1"
    assert row.direction == EmailDirection.received


def test_restore_sender_marks_own_mail_as_sent() -> None:
    row = _ghost()

    refetch.restore_sender(row, GHOST_MESSAGE, "NADAWCA@example.com")

    assert row.direction == EmailDirection.sent


def test_restore_sender_without_sender_in_mailbox_changes_nothing() -> None:
    row = _ghost()

    assert refetch.restore_sender(row, {"id": "graph-1"}, "me@example.com") is False

    assert row.from_address == ""
    assert row.subject is None


async def test_fetch_message_finds_moved_mail_by_internet_message_id() -> None:
    gc = SimpleNamespace(
        get=AsyncMock(
            side_effect=[GraphRequestError(404, "gone"), {"value": [{"id": "new"}]}]
        )
    )

    message = await refetch.fetch_message(gc, _row(), "id")

    assert message == {"id": "new"}
    params = gc.get.await_args_list[1].kwargs["params"]
    assert params["$filter"] == "internetMessageId eq '<a@example.com>'"


async def test_fetch_message_returns_none_when_gone_and_no_internet_id() -> None:
    gc = SimpleNamespace(get=AsyncMock(side_effect=GraphRequestError(404, "gone")))

    message = await refetch.fetch_message(gc, _row(m365_internet_message_id=None), "id")

    assert message is None


async def test_fetch_message_raises_other_graph_errors() -> None:
    gc = SimpleNamespace(get=AsyncMock(side_effect=GraphRequestError(403, "denied")))

    with pytest.raises(GraphRequestError):
        await refetch.fetch_message(gc, _row(), "id")


def test_fingerprint_ignores_order() -> None:
    assert refetch.fingerprint([2, 1]) == refetch.fingerprint([1, 2])
    assert refetch.fingerprint([1, 2]) != refetch.fingerprint([1, 3])


@pytest_asyncio.fixture
async def mailbox():
    suffix = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        user = User(
            email=f"refetch-{suffix}@example.com",
            password_hash=hash_password("P@ss"),
            name="Refetch",
            role=UserRole.recruiter,
            is_active=True,
        )
        db.add(user)
        await db.flush()
        conn = M365Connection(
            user_id=user.id,
            mailbox_upn=f"refetch-{suffix}@example.com",
            tenant_id="tenant",
            access_token_ct="x",
            refresh_token_ct="x",
            expires_at=datetime.now(timezone.utc),
            last_sync_status=M365SyncStatus.idle,
        )
        db.add(conn)
        await db.commit()
        ids = SimpleNamespace(user_id=user.id, conn_id=conn.id, suffix=suffix)
    yield ids
    async with AsyncSessionLocal() as db:
        await db.execute(delete(Email).where(Email.user_id == ids.user_id))
        await db.execute(delete(M365Connection).where(M365Connection.id == ids.conn_id))
        await db.execute(delete(User).where(User.id == ids.user_id))
        await db.commit()


def _email(mailbox, name: str, **kw) -> Email:
    now = datetime.now(timezone.utc)
    defaults = dict(
        user_id=mailbox.user_id,
        m365_message_id=f"{name}-{mailbox.suffix}",
        m365_conversation_id="conv",
        from_address="nadawca@example.com",
        received_at=now,
        direction=EmailDirection.received,
        body_html=None,
        body_text="",
        body_preview="",
    )
    defaults.update(kw)
    return Email(**defaults)


@pytest.mark.asyncio
async def test_plan_takes_only_wiped_received_mail(mailbox) -> None:
    async with AsyncSessionLocal() as db:
        wiped = _email(mailbox, "wiped")
        rows = [
            wiped,
            _email(mailbox, "full", body_html="<p>x</p>", body_text="x"),
            _email(mailbox, "blank-html", body_html=""),
            _email(mailbox, "private", is_private_filtered=True),
            _email(mailbox, "sent-full", direction=EmailDirection.sent, body_text="x"),
        ]
        sent = _email(mailbox, "sent", direction=EmailDirection.sent)
        no_sender = _email(mailbox, "no-sender", from_address="")
        db.add_all([*rows, sent, no_sender])
        await db.commit()

        items = await refetch.plan(db)

    assert items["by_connection"][mailbox.conn_id] == [wiped.id, sent.id, no_sender.id]


@pytest.mark.asyncio
async def test_has_twin_finds_other_row_of_same_message(mailbox) -> None:
    async with AsyncSessionLocal() as db:
        twin = _email(
            mailbox,
            "twin",
            body_text="x",
            m365_internet_message_id="<bliźniak@example.com>",
        )
        ghost = _email(mailbox, "ghost", from_address="")
        db.add_all([twin, ghost])
        await db.commit()

        message = {"internetMessageId": "<bliźniak@example.com>"}
        other = {"internetMessageId": "<inny@example.com>"}

        assert await refetch.has_twin(db, ghost, message) is True
        assert await refetch.has_twin(db, ghost, other) is False
        assert await refetch.has_twin(db, twin, message) is False
