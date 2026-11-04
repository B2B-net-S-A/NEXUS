"""Odpowiedź ze sprawy: wątek, kierunek, odmowy. Dane fikcyjne."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import delete, select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.admin_case import AdminCase, AdminCaseMessage
from app.models.user import User, UserRole
from app.services.admin_cases import reply
from app.services.admin_cases.service import CaseError


class _Transport:
    def __init__(self, fail: bool = False) -> None:
        self.calls: list[tuple[str, str, str]] = []
        self.fail = fail

    async def reply(self, mailbox_upn: str, message_id: str, text: str) -> None:
        if self.fail:
            raise RuntimeError("graph down")
        self.calls.append((mailbox_upn, message_id, text))


async def _seed(db, *, with_message: bool = True):
    marker = uuid.uuid4().hex[:10]
    user = User(
        email=f"reply-{marker}@example.com",
        name="Osoba Przykładowa",
        role=UserRole("admin"),
        roles=["admin"],
        is_active=True,
        profile_completed=True,
    )
    case = AdminCase(
        title="Pytanie o fakturę",
        area="administration",
        status="new",
        source="manual",
        checklist=[],
    )
    db.add_all([user, case])
    await db.flush()
    if with_message:
        db.add(
            AdminCaseMessage(
                case_id=case.id,
                graph_message_id=f"graph-{marker}",
                conversation_id="conv",
                subject="Pytanie",
                body_text="Treść",
                attachments=[],
            )
        )
        await db.flush()
    return user, case


@pytest.mark.asyncio
async def test_reply_goes_to_the_latest_inbound_and_is_stored_as_out(
    monkeypatch,
) -> None:
    monkeypatch.setattr(settings, "ADMIN_CASES_MAILBOX", "wsparcie@example.com")
    transport = _Transport()
    async with AsyncSessionLocal() as db:
        user, case = await _seed(db)
        message = await reply.send_reply(
            db, case, actor=user, body=" Dzień dobry ", transport=transport
        )
        assert message.direction == "out"
        assert message.body_text == "Dzień dobry"
        assert transport.calls[0][0] == "wsparcie@example.com"
        assert transport.calls[0][1].startswith("graph-")
        rows = (
            await db.scalars(
                select(AdminCaseMessage).where(AdminCaseMessage.case_id == case.id)
            )
        ).all()
        assert sorted(row.direction for row in rows) == ["in", "out"]
        await db.rollback()


@pytest.mark.asyncio
async def test_reply_refuses_without_mailbox_message_or_text(monkeypatch) -> None:
    async with AsyncSessionLocal() as db:
        user, case = await _seed(db, with_message=False)
        monkeypatch.setattr(settings, "ADMIN_CASES_MAILBOX", "")
        monkeypatch.setattr(settings, "ADMIN_CASES_M365_MAILBOX", "")
        with pytest.raises(CaseError, match="nie jest jeszcze ustawiona"):
            await reply.send_reply(
                db, case, actor=user, body="x", transport=_Transport()
            )
        monkeypatch.setattr(settings, "ADMIN_CASES_MAILBOX", "wsparcie@example.com")
        with pytest.raises(CaseError, match="nie ma maila"):
            await reply.send_reply(
                db, case, actor=user, body="x", transport=_Transport()
            )
        with pytest.raises(CaseError, match="pusta"):
            await reply.send_reply(
                db, case, actor=user, body="  ", transport=_Transport()
            )
        await db.rollback()


@pytest.mark.asyncio
async def test_failed_send_stores_nothing(monkeypatch) -> None:
    monkeypatch.setattr(settings, "ADMIN_CASES_MAILBOX", "wsparcie@example.com")
    async with AsyncSessionLocal() as db:
        user, case = await _seed(db)
        with pytest.raises(CaseError, match="Nie udało się wysłać"):
            await reply.send_reply(
                db, case, actor=user, body="x", transport=_Transport(fail=True)
            )
        rows = (
            await db.scalars(
                select(AdminCaseMessage).where(
                    AdminCaseMessage.case_id == case.id,
                    AdminCaseMessage.direction == "out",
                )
            )
        ).all()
        assert rows == []
        await db.execute(
            delete(AdminCaseMessage).where(AdminCaseMessage.case_id == case.id)
        )
        await db.rollback()
