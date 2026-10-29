"""Zastępca do Cpro we wniosku urlopowym osoby od Cpro (decyzja Artura 29.10.2026).

Zgłoszenie: osoba od Cpro poszła na urlop bez wskazania, kto wrzuca — kolejka
Cpro i dzwonki czekały na nieobecną, bo ustawienie firmy jej nie zmieniło.
Teraz osoba od Cpro wskazuje zastępcę we własnym wniosku (wymagane na pełne
dni), a zatwierdzony urlop obejmujący dziś podmienia osobę przy odczycie
(``cpro_sender.effective_sender``) — po urlopie wraca sama. Dane fikcyjne.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, time, timedelta, timezone

import pytest

from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today
from app.models.hr_leave import LeaveRequest
from app.models.user import User
from app.services import cpro_sender
from app.services.hr.leave_service import (
    CPRO_SUBSTITUTE_NOT_SENDER,
    CPRO_SUBSTITUTE_REQUIRED,
)
from tests.test_board_tasks import restore_cpro_sender
from tests.test_hr_time_support import (  # noqa: F401 — fikstury
    headers,
    make_user,
    notifications_of,
    time_on,
)

BASE = "/api/hr/leave"
MON = date(2091, 11, 12)
FRI = date(2091, 11, 16)


def _body(**extra) -> dict:
    return {
        "leave_type": "vacation",
        "start_date": MON.isoformat(),
        "end_date": FRI.isoformat(),
        **extra,
    }


def _noon(day: date) -> datetime:
    """Południe dnia w UTC — ten sam dzień kalendarza firmy (Europe/Warsaw)."""

    return datetime.combine(day, time(12, 0), tzinfo=timezone.utc)


async def _people(employment_type: str = "uop") -> tuple[User, User, User]:
    """Osoba od Cpro (z Finansów), rekruter na zastępstwo i osoba spoza rekrutacji."""

    async with AsyncSessionLocal() as db:
        sender = await make_user(db, "finance", employment_type=employment_type)
        recruiter = await make_user(db, "recruiter")
        outsider = await make_user(db, "employee")
        admin = await make_user(db, "admin", profile=False)
        await cpro_sender.set_sender(db, user_id=sender.id, until=None, actor=admin)
        await db.commit()
    return sender, recruiter, outsider


async def _leave(
    sender: User,
    substitute: User | None,
    *,
    start: date,
    end: date,
    status: str = "approved",
    half_day: str | None = None,
) -> None:
    async with AsyncSessionLocal() as db:
        db.add(
            LeaveRequest(
                id=uuid.uuid4(),
                user_id=sender.id,
                leave_type="vacation",
                status=status,
                start_date=start,
                end_date=end,
                half_day=half_day,
                cpro_substitute_user_id=substitute.id if substitute else None,
                source="self",
                created_by=sender.id,
            )
        )
        await db.commit()


async def _effective(now: datetime | None = None) -> cpro_sender.CproSenderState:
    async with AsyncSessionLocal() as db:
        return await cpro_sender.effective_sender(db, now)


# ── Wniosek ──────────────────────────────────────────────────────────────────


@pytest.mark.usefixtures("time_on")
@pytest.mark.asyncio
async def test_cpro_sender_must_name_who_sends_during_leave(app_client) -> None:
    async with restore_cpro_sender():
        sender, recruiter, outsider = await _people()

        preview = await app_client.post(
            BASE + "/preview", json=_body(), headers=headers(sender)
        )
        assert preview.status_code == 200, preview.text
        assert preview.json()["cpro_sender"] is True

        missing = await app_client.post(
            BASE + "/requests", json=_body(), headers=headers(sender)
        )
        assert missing.status_code == 422, missing.text
        assert missing.json()["detail"] == CPRO_SUBSTITUTE_REQUIRED

        yourself = await app_client.post(
            BASE + "/requests",
            json=_body(cpro_substitute_user_id=sender.id),
            headers=headers(sender),
        )
        assert yourself.status_code == 422, yourself.text

        # Jak w „Zmień” przy kolejce: tylko osoba z zespołu rekrutacji.
        not_recruitment = await app_client.post(
            BASE + "/requests",
            json=_body(cpro_substitute_user_id=outsider.id),
            headers=headers(sender),
        )
        assert not_recruitment.status_code == 422, not_recruitment.text
        assert "Cpro" in not_recruitment.json()["detail"]

        created = await app_client.post(
            BASE + "/requests",
            json=_body(cpro_substitute_user_id=recruiter.id),
            headers=headers(sender),
        )
        assert created.status_code == 201, created.text
        listed = await app_client.get(BASE + "/my-requests", headers=headers(sender))
        assert listed.status_code == 200, listed.text
        body = listed.json()
        rows = body["items"] if isinstance(body, dict) else body
        row = next(r for r in rows if r["id"] == created.json()["id"])
        assert row["cpro_substitute_name"] == recruiter.name


@pytest.mark.usefixtures("time_on")
@pytest.mark.asyncio
async def test_half_day_does_not_ask_and_others_cannot_name_one(app_client) -> None:
    async with restore_cpro_sender():
        sender, recruiter, _ = await _people()
        half = await app_client.post(
            BASE + "/requests",
            json=_body(end_date=MON.isoformat(), half_day="morning"),
            headers=headers(sender),
        )
        assert half.status_code == 201, half.text

        preview = await app_client.post(
            BASE + "/preview", json=_body(), headers=headers(recruiter)
        )
        assert preview.json()["cpro_sender"] is False
        refused = await app_client.post(
            BASE + "/requests",
            json=_body(cpro_substitute_user_id=sender.id),
            headers=headers(recruiter),
        )
        assert refused.status_code == 422, refused.text
        assert refused.json()["detail"] == CPRO_SUBSTITUTE_NOT_SENDER

        plain = await app_client.post(
            BASE + "/requests", json=_body(), headers=headers(recruiter)
        )
        assert plain.status_code == 201, plain.text


@pytest.mark.usefixtures("time_on")
@pytest.mark.asyncio
async def test_approved_report_rings_the_cpro_substitute_without_leave_type(
    app_client,
) -> None:
    async with restore_cpro_sender():
        # B2B: zgłoszenie jest od razu zatwierdzone (D5), więc dzwonek od razu.
        sender, recruiter, _ = await _people(employment_type="b2b")
        created = await app_client.post(
            BASE + "/requests",
            json=_body(cpro_substitute_user_id=recruiter.id),
            headers=headers(sender),
        )
        assert created.status_code == 201, created.text
        bells = await notifications_of(recruiter.id, "cpro_send_assigned")
        assert len(bells) == 1
        title, message = bells[0]
        assert title == "Wysyłasz kandydatów do Cpro"
        assert f"w zastępstwie za {sender.name}" in message
        assert "urlop" not in message.lower()


# ── Kto wysyła dziś ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_approved_full_day_leave_hands_the_queue_over_and_back() -> None:
    async with restore_cpro_sender():
        sender, recruiter, _ = await _people()
        today = business_today()
        await _leave(sender, recruiter, start=today, end=today + timedelta(days=1))

        during = await _effective()
        assert during.user_id == recruiter.id
        assert during.until == today + timedelta(days=1)
        assert during.fallback_user_id == sender.id
        assert during.set_by_user_id == sender.id
        async with AsyncSessionLocal() as db:
            assert await cpro_sender.can_send_to_cpro(db, recruiter)
            assert (await cpro_sender.firm_sender(db)).user_id == sender.id

        after = await _effective(_noon(today + timedelta(days=2)))
        assert after.user_id == sender.id
        assert after.until is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "half_day"),
    [("pending", None), ("cancelled", None), ("approved", "morning")],
)
async def test_pending_cancelled_or_half_day_leave_keeps_the_sender(
    status: str, half_day: str | None
) -> None:
    async with restore_cpro_sender():
        sender, recruiter, _ = await _people()
        today = business_today()
        await _leave(
            sender, recruiter, start=today, end=today, status=status, half_day=half_day
        )
        assert (await _effective()).user_id == sender.id


@pytest.mark.asyncio
async def test_inactive_substitute_or_manual_change_wins_over_the_leave() -> None:
    async with restore_cpro_sender():
        sender, recruiter, _ = await _people()
        today = business_today()
        await _leave(sender, recruiter, start=today, end=today)
        async with AsyncSessionLocal() as db:
            gone = await db.get(User, recruiter.id)
            gone.is_active = False
            await db.commit()
        assert (await _effective()).user_id == sender.id

        # „Zmień” w trakcie urlopu dotyczy innej osoby niż urlopowicz — wygrywa.
        async with AsyncSessionLocal() as db:
            other = await make_user(db, "delivery_lead")
            admin = await make_user(db, "admin", profile=False)
            await cpro_sender.set_sender(db, user_id=other.id, until=today, actor=admin)
            await db.commit()
        manual = await _effective()
        assert manual.user_id == other.id
        assert manual.fallback_user_id == sender.id
