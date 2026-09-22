"""Tożsamość maila M365 = ``internetMessageId`` w obrębie skrzynki (INT-14).

Szkic wysłany z NEXUSA dostaje nowe ID Graph po przeniesieniu do Wysłanych;
do 09.2026 delta Wysłanych zakładała wtedy drugi wiersz tej samej wiadomości.
Sync przepisuje teraz ID na istniejącym wierszu, a jednorazowe sprzątanie
scala duplikaty, które już są w bazie.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
import pytest_asyncio
from sqlalchemy import delete, select

from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.app_setting import AppSetting
from app.models.candidate import Candidate, CandidateStatus
from app.models.m365 import Email, EmailAttachment, EmailDirection
from app.models.user import User, UserRole
from app.services import m365_email_dedupe_repair as repair
from app.services.m365 import sync as sync_mod


@pytest_asyncio.fixture
async def owner():
    suffix = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        user = User(
            email=f"identity-{suffix}@example.com",
            password_hash=hash_password("P@ss"),
            name="Identity",
            role=UserRole.recruiter,
            is_active=True,
        )
        candidate = Candidate(
            name="Ewa",
            lastname=f"Tozsamosc{suffix}",
            email=f"cand-{suffix}@example.com",
            status=CandidateStatus.active,
        )
        db.add_all([user, candidate])
        await db.commit()
        ids = SimpleNamespace(user_id=user.id, candidate_id=candidate.id, suffix=suffix)
    yield ids
    async with AsyncSessionLocal() as db:
        await db.execute(delete(Email).where(Email.user_id == ids.user_id))
        await db.execute(delete(Candidate).where(Candidate.id == ids.candidate_id))
        await db.execute(delete(User).where(User.id == ids.user_id))
        await db.commit()


def _email(user_id: int, **kw) -> Email:
    now = datetime.now(timezone.utc)
    defaults = dict(
        user_id=user_id,
        m365_conversation_id="conv",
        from_address="me@example.com",
        received_at=now,
        sent_at=now,
        direction=EmailDirection.sent,
    )
    defaults.update(kw)
    return Email(**defaults)


@pytest.mark.asyncio
async def test_sync_reidentifies_sent_draft_instead_of_duplicating(owner):
    imid = f"<{owner.suffix}@nexus.test>"
    async with AsyncSessionLocal() as db:
        db.add(
            _email(
                owner.user_id,
                candidate_id=owner.candidate_id,
                m365_message_id=f"draft-{owner.suffix}",
                m365_internet_message_id=imid,
                idempotency_key=f"key-{owner.suffix}",
                send_state="uncertain",
                subject="Oferta",
            )
        )
        await db.commit()

    msg = {
        "id": f"sent-{owner.suffix}",
        "conversationId": "conv",
        "internetMessageId": imid,
        "subject": "Oferta",
        "from": {"emailAddress": {"address": "me@example.com"}},
        "sentDateTime": "2026-09-22T10:00:00Z",
        "receivedDateTime": "2026-09-22T10:00:00Z",
        "body": {"contentType": "html", "content": "<p>x</p>"},
        "hasAttachments": False,
        "isRead": True,
    }
    conn = SimpleNamespace(id=1, user_id=owner.user_id, mailbox_upn="me@example.com")
    async with AsyncSessionLocal() as db:
        row = await sync_mod._upsert_message(db, None, conn, msg, "SentItems")
        await db.commit()
        assert row is not None

    async with AsyncSessionLocal() as db:
        rows = (
            await db.scalars(select(Email).where(Email.user_id == owner.user_id))
        ).all()
    assert len(rows) == 1, "delta Wysłanych założyła drugi wiersz tej samej wysyłki"
    assert rows[0].m365_message_id == f"sent-{owner.suffix}"
    assert rows[0].send_state == "sent"
    assert rows[0].idempotency_key == f"key-{owner.suffix}"


@pytest.mark.asyncio
async def test_dedupe_repair_keeps_send_row_and_moves_children(owner):
    imid = f"<dup-{owner.suffix}@nexus.test>"
    other = f"<solo-{owner.suffix}@nexus.test>"
    async with AsyncSessionLocal() as db:
        sent = _email(
            owner.user_id,
            m365_message_id=f"draft-{owner.suffix}",
            m365_internet_message_id=imid,
            idempotency_key=f"key-{owner.suffix}",
        )
        synced = _email(
            owner.user_id,
            candidate_id=owner.candidate_id,
            m365_message_id=f"sent-{owner.suffix}",
            m365_internet_message_id=imid,
            has_attachments=True,
        )
        solo = _email(
            owner.user_id,
            m365_message_id=f"solo-{owner.suffix}",
            m365_internet_message_id=other,
        )
        db.add_all([sent, synced, solo])
        await db.flush()
        db.add(
            EmailAttachment(
                email_id=synced.id,
                m365_attachment_id="a1",
                filename="CV.pdf",
                content_type="application/pdf",
                size_bytes=10,
            )
        )
        await db.commit()
        sent_id, synced_id, solo_id = sent.id, synced.id, solo.id

    marker = f"test_m365_dedupe_{owner.suffix}"
    try:
        async with AsyncSessionLocal() as db:
            summary = await repair.run_m365_email_dedupe_repair(db, marker=marker)
            await db.commit()
        assert summary is not None
        assert any(item["kept_id"] == sent_id for item in summary["merged"])

        async with AsyncSessionLocal() as db:
            rows = {
                r.id: r
                for r in (
                    await db.scalars(
                        select(Email).where(Email.user_id == owner.user_id)
                    )
                ).all()
            }
            attachments = (
                await db.scalars(
                    select(EmailAttachment).where(EmailAttachment.email_id == sent_id)
                )
            ).all()
        assert set(rows) == {sent_id, solo_id}
        assert synced_id not in rows
        kept = rows[sent_id]
        assert kept.m365_message_id == f"sent-{owner.suffix}"
        assert kept.candidate_id == owner.candidate_id
        assert [a.filename for a in attachments] == ["CV.pdf"]

        # Jednorazowe: drugi bieg nic nie robi.
        async with AsyncSessionLocal() as db:
            assert await repair.run_m365_email_dedupe_repair(db, marker=marker) is None
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(delete(AppSetting).where(AppSetting.key == marker))
            await db.commit()


@pytest.mark.asyncio
async def test_dedupe_repair_refuses_unknown_foreign_key(owner, monkeypatch):
    monkeypatch.setattr(repair, "KNOWN_EMAIL_FKS", frozenset())
    marker = f"test_m365_dedupe_fk_{owner.suffix}"
    async with AsyncSessionLocal() as db:
        with pytest.raises(RuntimeError, match="unknown FK"):
            await repair.run_m365_email_dedupe_repair(db, marker=marker)
        await db.rollback()
        assert await db.get(AppSetting, marker) is None
