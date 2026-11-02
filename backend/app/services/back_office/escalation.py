"""Eskalacja: karta bez osoby po jednym dniu roboczym idzie do kierownika.

Karty z akceptem na miejscu (raporty, premie, zmiany) nie mają „Biorę”, więc się
nie eskalują. Dzień roboczy liczy kalendarz firmy (święta i dni wolne).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scheduling import DEFAULT_TZ
from app.models.back_office import BoCard, BoCardEvent
from app.models.notification import NotificationType
from app.services.back_office import access
from app.services.hr.calendar import WorkCalendar, load_calendar
from app.services.hr.notify import notify_each

#: Karty, które zamyka akcept, a nie osoba prowadząca.
NO_ESCALATION_KINDS = frozenset({"timesheet", "bonus", "changes"})
_LOOKBACK_DAYS = 45


def escalation_moment(created_at: datetime, calendar: WorkCalendar) -> datetime:
    """Ta sama godzina następnego dnia roboczego po założeniu karty."""

    local = created_at.astimezone(ZoneInfo(DEFAULT_TZ))
    next_day = calendar.next_working_day_after(local.date())
    return local.replace(year=next_day.year, month=next_day.month, day=next_day.day)


def should_escalate(card: BoCard, *, now: datetime, calendar: WorkCalendar) -> bool:
    if card.state != "new" or card.assignee_user_id is not None:
        return False
    if card.escalated_at is not None or card.source_kind in NO_ESCALATION_KINDS:
        return False
    if card.lane == "triage":
        return False
    return now >= escalation_moment(card.created_at, calendar)


async def run(
    db: AsyncSession, *, today: date, now: Optional[datetime] = None
) -> dict[str, int]:
    moment = now or datetime.now(ZoneInfo(DEFAULT_TZ))
    calendar = await load_calendar(
        db, today - timedelta(days=_LOOKBACK_DAYS), today + timedelta(days=14)
    )
    candidates = (
        await db.scalars(
            select(BoCard).where(
                BoCard.state == "new",
                BoCard.assignee_user_id.is_(None),
                BoCard.escalated_at.is_(None),
            )
        )
    ).all()
    escalated = [
        card
        for card in candidates
        if should_escalate(card, now=moment, calendar=calendar)
    ]
    for card in escalated:
        card.escalated_at = moment
        db.add(
            BoCardEvent(
                card_id=card.id, action="escalated", details={}, created_at=moment
            )
        )
    if escalated:
        await db.flush()
        # Jeden dzwonek zbiorczy na przebieg; dobowy dedup ``emit`` chroni przed
        # zalewem, gdy kilka przebiegów tego samego dnia coś dołoży.
        await notify_each(
            db,
            await access.lead_user_ids(db),
            title="Sprawy do przydzielenia",
            message=f"Bez osoby po dniu roboczym: {len(escalated)}.",
            ntype=NotificationType.back_office_escalated,
            related_entity_type="back_office",
            related_entity_id=today.toordinal(),
            link="/back-office?zespol=all&filtr=escalated",
            log_tag="back_office",
        )
    return {"escalated": len(escalated)}
