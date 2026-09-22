"""Testy delegated system-mail (`app/services/m365/system_mail.py`).

- `send_system_email`: mock GraphClient (draft+send), bez DB/sieci.
- `get_system_sender_connection`: realny wybór po mailbox_upn (DB).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

import app.services.m365.system_mail as sysmail
from app.core.config import settings

pytestmark = pytest.mark.asyncio


def _fake_graph(behavior, deleted=None, delete_error=None):
    """Factory podmieniająca GraphClient na async-CM z zadanym `post`.

    `deleted` (opcjonalna lista) zbiera URL-e przekazane do `delete` — do
    weryfikacji sprzątania osieroconego draftu.
    """

    class _FGC:
        def __init__(self, conn, db):
            self.conn = conn

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json=None):
            return behavior(url, json)

        async def delete(self, url):
            if deleted is not None:
                deleted.append(url)
            if delete_error is not None:
                raise delete_error

    return _FGC


class _Conn:
    mailbox_upn = "nexus@example.com"


async def test_send_system_email_success(monkeypatch):
    calls = []

    def _behavior(url, json):
        calls.append(url)
        return {"id": "m-1"} if url == "/me/messages" else {}

    monkeypatch.setattr(sysmail, "GraphClient", _fake_graph(_behavior))
    ok = await sysmail.send_system_email(
        db=None,
        connection=_Conn(),
        to="rec@example.com",
        subject="Deadline",
        text_body="tresc",
    )
    assert ok is True
    assert calls == ["/me/messages", "/me/messages/m-1/send"]


async def test_send_system_email_html_body(monkeypatch):
    captured = {}

    def _behavior(url, json):
        if url == "/me/messages":
            captured["payload"] = json
            return {"id": "m-2"}
        return {}

    monkeypatch.setattr(sysmail, "GraphClient", _fake_graph(_behavior))
    ok = await sysmail.send_system_email(
        db=None,
        connection=_Conn(),
        to="rec@example.com",
        subject="s",
        text_body="plain",
        html_body="<p>rich</p>",
    )
    assert ok is True
    assert captured["payload"]["body"] == {
        "contentType": "HTML",
        "content": "<p>rich</p>",
    }
    assert captured["payload"]["toRecipients"] == [
        {"emailAddress": {"address": "rec@example.com"}}
    ]


async def test_send_system_email_draft_without_id(monkeypatch):
    monkeypatch.setattr(
        sysmail, "GraphClient", _fake_graph(lambda url, json: {})
    )  # draft bez id
    ok = await sysmail.send_system_email(
        db=None, connection=_Conn(), to="x@example.com", subject="s", text_body="t"
    )
    assert ok is False


async def test_send_system_email_graph_error(monkeypatch):
    def _boom(url, json):
        raise RuntimeError("graph down")

    monkeypatch.setattr(sysmail, "GraphClient", _fake_graph(_boom))
    ok = await sysmail.send_system_email(
        db=None, connection=_Conn(), to="x@example.com", subject="s", text_body="t"
    )
    assert ok is False


async def test_send_system_email_deletes_orphaned_draft_on_send_failure(monkeypatch):
    """Draft powstał, /send padł → sierota usuwana z Drafts, wynik False."""
    deleted = []

    def _behavior(url, json):
        if url == "/me/messages":
            return {"id": "m-9"}
        raise RuntimeError("send exploded")  # /send

    monkeypatch.setattr(sysmail, "GraphClient", _fake_graph(_behavior, deleted=deleted))
    ok = await sysmail.send_system_email(
        db=None, connection=_Conn(), to="x@example.com", subject="s", text_body="t"
    )
    assert ok is False
    assert deleted == ["/me/messages/m-9"]


@pytest.mark.parametrize("kind", ["job_deadline", "delivery_alert"])
@pytest.mark.parametrize("transition", ["unchanged", "off", "off_on"])
async def test_send_system_email_rechecks_policy_after_draft_creation(
    monkeypatch, kind, transition
):
    from app.services import notification_delivery as delivery

    now = datetime(2026, 9, 22, 12, tzinfo=timezone.utc)
    event_at = now + timedelta(seconds=1)
    policy = delivery.DeliveryPolicy.from_value(
        delivery.updated_value(
            delivery.DeliveryPolicy(), enabled=True, toggles={kind: True}, now=now
        )
    )
    assert policy.allows(kind, event_at)
    calls, deleted = [], []

    async def _policy(_db):
        return policy

    def _behavior(url, json):
        nonlocal policy
        calls.append(url)
        if url == "/me/messages":
            if transition != "unchanged":
                policy = delivery.DeliveryPolicy.from_value(
                    delivery.updated_value(
                        policy,
                        enabled=False,
                        toggles={},
                        now=now + timedelta(seconds=2),
                    )
                )
            if transition == "off_on":
                policy = delivery.DeliveryPolicy.from_value(
                    delivery.updated_value(
                        policy, enabled=True, toggles={}, now=now + timedelta(seconds=3)
                    )
                )
            return {"id": "policy-race"}
        return {}

    monkeypatch.setattr(delivery, "load_policy", _policy)
    monkeypatch.setattr(sysmail, "GraphClient", _fake_graph(_behavior, deleted=deleted))
    ok = await sysmail.send_system_email(
        db=None,
        connection=_Conn(),
        to="rec@example.invalid",
        subject="Routine notification",
        text_body="Test",
        delivery_kind=kind,
        event_at=event_at,
    )
    if transition == "unchanged":
        assert ok is True
        assert calls == ["/me/messages", "/me/messages/policy-race/send"]
        assert deleted == []
    else:
        assert ok is False
        assert calls == ["/me/messages"]
        assert deleted == ["/me/messages/policy-race"]


@pytest.mark.parametrize("policy_error", [False, True])
async def test_send_system_email_cannot_send_if_policy_or_cleanup_fails(
    monkeypatch, policy_error, caplog
):
    from app.services import notification_delivery as delivery

    calls, deleted = [], []

    async def _policy(_db):
        if policy_error:
            raise RuntimeError("Policy unavailable")
        return delivery.DeliveryPolicy()

    def _behavior(url, json):
        calls.append(url)
        return {"id": "retained-unsent-draft"}

    monkeypatch.setattr(delivery, "load_policy", _policy)
    monkeypatch.setattr(
        sysmail,
        "GraphClient",
        _fake_graph(
            _behavior, deleted=deleted, delete_error=RuntimeError("Cleanup unavailable")
        ),
    )
    ok = await sysmail.send_system_email(
        db=None,
        connection=_Conn(),
        to="rec@example.invalid",
        subject="Routine notification",
        text_body="Test",
        delivery_kind="job_deadline",
        event_at=datetime.now(timezone.utc),
    )
    assert ok is False
    assert calls == ["/me/messages"]
    assert deleted == ["/me/messages/retained-unsent-draft"]
    assert "retained-unsent-draft" in caplog.text


async def test_get_system_sender_connection_matches_active_upn(monkeypatch):
    from app.core.database import AsyncSessionLocal
    from app.core.security import hash_password
    from app.models.m365 import M365Connection
    from app.models.user import User, UserRole

    upn = f"nexus-{uuid.uuid4().hex[:6]}@example.com"
    monkeypatch.setattr(settings, "M365_MAIL_SENDER_UPN", upn)

    async with AsyncSessionLocal() as db:
        u = User(
            email=f"sysmail-{uuid.uuid4().hex[:6]}@example.com",
            password_hash=hash_password("x"),
            name="Sys Mail Owner",
            role=UserRole.admin,
            is_active=True,
        )
        db.add(u)
        await db.flush()
        conn = M365Connection(
            user_id=u.id,
            tenant_id="tenant-guid",
            mailbox_upn=upn.upper(),  # case-insensitive match
            access_token_ct="ct",
            refresh_token_ct="ct",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            is_active=True,
        )
        db.add(conn)
        await db.commit()
        conn_id, uid = conn.id, u.id

    try:
        async with AsyncSessionLocal() as db:
            found = await sysmail.get_system_sender_connection(db)
            assert found is not None
            assert found.id == conn_id

        # inactive → brak dopasowania
        async with AsyncSessionLocal() as db:
            c = await db.get(M365Connection, conn_id)
            c.is_active = False
            await db.commit()
        async with AsyncSessionLocal() as db:
            assert await sysmail.get_system_sender_connection(db) is None
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(
                M365Connection.__table__.delete().where(M365Connection.id == conn_id)
            )
            await db.execute(User.__table__.delete().where(User.id == uid))
            await db.commit()


async def test_get_system_sender_connection_none_when_upn_empty(monkeypatch):
    from app.core.database import AsyncSessionLocal

    monkeypatch.setattr(settings, "M365_MAIL_SENDER_UPN", "")
    async with AsyncSessionLocal() as db:
        assert await sysmail.get_system_sender_connection(db) is None
