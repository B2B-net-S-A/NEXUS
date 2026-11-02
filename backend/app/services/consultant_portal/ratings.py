"""Oceny rozmów: prośba po rozmowie, zadanie po 1–2, przegląd miesięczny.

Reguła, której macierz uprawnień nie zobaczy, bo widzi tylko zależności tras: **osoba
oceniana nie widzi pojedynczych ocen**. Dotyczy to także kierownika, który sam prowadził
rozmowę. Dostaje raz w miesiącu zbiorczy przegląd, a przy mniej niż ``MIN_FOR_REVIEW``
ocenach tylko informację, że jest ich za mało: przy jednej ocenie średnia to ta ocena.
Zadanie po ocenie 1–2 jest wierszem oceny, a nie sprawą, bo sprawy widzi cały zespół
z uprawnieniem „Sprawy”, w tym często oceniana osoba.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scheduling import business_today, local_now
from app.models.back_office import BoCard
from app.models.candidate import Candidate
from app.models.consultant_portal import CpMeeting, CpRating
from app.models.contract import Contract
from app.models.notification import NotificationType
from app.models.user import User
from app.services.admin_cases import rules
from app.services.back_office import access
from app.services.care.access import full_name
from app.services.consultant_portal import (
    auth,
    content,
    identity,
    portal_mail,
    portal_settings,
)
from app.services.consultant_portal.auth import PortalError
from app.services.consultant_portal.portal_settings import PortalSettings
from app.services.consultant_portal_schema import COMMENT_MAX
from app.services.hr import job_runs
from app.services.hr.notify import notify_each

logger = logging.getLogger(__name__)

REQUEST_DELAY = timedelta(minutes=15)
REQUEST_WINDOW = timedelta(days=3)
MIN_FOR_REVIEW = 3
QUALITY_LINK = "/care?tab=quality"
ALREADY_RATED = "Ta rozmowa ma już ocenę. Dziękujemy."
NOT_RATEABLE = "Tej rozmowy nie można jeszcze ocenić."
MONTHS = (
    "styczeń",
    "luty",
    "marzec",
    "kwiecień",
    "maj",
    "czerwiec",
    "lipiec",
    "sierpień",
    "wrzesień",
    "październik",
    "listopad",
    "grudzień",
)


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def rateable(meeting: CpMeeting, now: datetime) -> bool:
    return meeting.status == "booked" and _aware(meeting.end_at) <= now


async def _create(
    db: AsyncSession,
    meeting: CpMeeting,
    *,
    score: int,
    resolved: Optional[bool],
    comment: Optional[str],
    now: datetime,
) -> CpRating:
    low = score <= 2
    rating = CpRating(
        meeting_id=meeting.id,
        contract_id=meeting.contract_id,
        host_user_id=meeting.host_user_id,
        score=score,
        resolved=resolved,
        comment=(comment or "").replace("\x00", "").strip()[:COMMENT_MAX] or None,
        followup_status="open" if low else "none",
        followup_due_on=rules.add_business_days(local_now(), 1) if low else None,
        created_at=now,
    )
    try:
        async with db.begin_nested():
            db.add(rating)
            await db.flush()
    except IntegrityError as exc:
        raise PortalError(ALREADY_RATED, status=409, code="already_rated") from exc
    if low:
        await notify_each(
            db,
            await access.lead_user_ids(db),
            title="Niska ocena rozmowy z portalu",
            message="Konsultant źle ocenił rozmowę: oddzwoń w ciągu 24 godzin.",
            ntype=NotificationType.portal_low_rating,
            link=QUALITY_LINK,
            related_entity_type="cp_rating",
            related_entity_id=rating.id,
            # Oceniana osoba nie dostaje dzwonka o własnej ocenie.
            exclude=(meeting.host_user_id,),
            log_tag="consultant_portal",
        )
    return rating


async def rate_as_consultant(
    db: AsyncSession,
    context: auth.PortalContext,
    meeting_id: int,
    *,
    score: int,
    resolved: Optional[bool],
    comment: Optional[str],
    now: datetime,
) -> CpRating:
    meeting = await db.get(CpMeeting, meeting_id)
    if meeting is None or meeting.contract_id not in context.consultant.contract_ids:
        raise PortalError("Nie ma takiej rozmowy.", status=404, code="not_found")
    if not rateable(meeting, now):
        raise PortalError(NOT_RATEABLE, status=409, code="not_rateable")
    return await _create(
        db, meeting, score=score, resolved=resolved, comment=comment, now=now
    )


async def link_summary(
    db: AsyncSession, raw: str, *, state: PortalSettings, now: datetime
) -> Optional[dict[str, Any]]:
    link = await auth.peek_link(db, raw, purpose="rating", now=now)
    if link is None or link.meeting_id is None or not state.open_for(link.contract_id):
        return None
    meeting = await db.get(CpMeeting, link.meeting_id)
    if meeting is None:
        return None
    host = await db.get(User, meeting.host_user_id) if meeting.host_user_id else None
    return {
        "host": host.name if host else None,
        "start_at": meeting.start_at.isoformat(),
        "topic_label": content.TOPIC_LABELS[meeting.topic],
    }


async def rate_by_link(
    db: AsyncSession,
    raw: str,
    *,
    state: PortalSettings,
    score: int,
    resolved: Optional[bool],
    comment: Optional[str],
    now: datetime,
) -> Optional[CpRating]:
    """``None`` = link nieprawidłowy, zużyty, wygasły albo portal zamknięty."""

    link = await auth.consume_link(db, raw, purpose="rating", now=now)
    if link is None or link.meeting_id is None or not state.open_for(link.contract_id):
        return None
    meeting = await db.get(CpMeeting, link.meeting_id)
    if meeting is None or not rateable(meeting, now):
        return None
    return await _create(
        db, meeting, score=score, resolved=resolved, comment=comment, now=now
    )


# ── Prośba o ocenę ───────────────────────────────────────────────────────────


async def send_requests(db: AsyncSession, *, now: datetime) -> dict[str, int]:
    state = await portal_settings.load(db)
    if not state.is_on:
        return {"sent": 0}
    meeting_ids = (
        await db.scalars(
            select(CpMeeting.id)
            .outerjoin(CpRating, CpRating.meeting_id == CpMeeting.id)
            .where(
                CpMeeting.status == "booked",
                CpMeeting.rating_requested_at.is_(None),
                CpMeeting.end_at <= now - REQUEST_DELAY,
                CpMeeting.end_at >= now - REQUEST_WINDOW,
                CpRating.id.is_(None),
            )
            .limit(50)
        )
    ).all()
    sent = 0
    for meeting_id in meeting_ids:
        meeting = await db.get(CpMeeting, meeting_id)
        if meeting is None:
            continue
        contract = await db.get(Contract, meeting.contract_id)
        email = identity.normalize_email(contract.candidate_email if contract else None)
        if not email or not state.open_for(meeting.contract_id):
            continue
        host = (
            await db.get(User, meeting.host_user_id) if meeting.host_user_id else None
        )
        raw = await auth.rating_link(
            db,
            contract_id=meeting.contract_id,
            meeting_id=meeting.id,
            email=email,
            now=now,
        )
        outcome = await portal_mail.send(
            db,
            contract_id=meeting.contract_id,
            to=email,
            subject="Jak oceniasz rozmowę z B2B.net?",
            text=(
                f"Dziękujemy za rozmowę{f' z {host.name}' if host else ''}.\n\n"
                "Oceń ją jednym kliknięciem (link ważny 7 dni):\n"
                f"{portal_mail.portal_url(f'/ocena#{raw}')}\n\n"
                "Ocena trafia do kierownika back office."
            ),
        )
        if outcome is None or outcome.status not in ("accepted", "uncertain"):
            # Odłożone: link bez maila nigdzie nie wyjdzie, a pętla spróbuje ponownie.
            await db.rollback()
            continue
        meeting.rating_requested_at = now
        await db.commit()
        sent += 1
    return {"sent": sent}


# ── Jakość (kierownik) ───────────────────────────────────────────────────────


def _average(total: Optional[float]) -> Optional[float]:
    return round(float(total), 2) if total is not None else None


async def quality(
    db: AsyncSession, *, viewer_id: int, days: int = 30, now: datetime
) -> dict[str, Any]:
    since = now - timedelta(days=days)
    meetings_held = (
        select(
            CpMeeting.host_user_id.label("host"),
            func.count().label("meetings"),
        )
        .where(
            CpMeeting.status == "booked",
            CpMeeting.end_at >= since,
            CpMeeting.end_at <= now,
            CpMeeting.host_user_id.is_not(None),
        )
        .group_by(CpMeeting.host_user_id)
        .subquery()
    )
    ratings = (
        select(
            CpRating.host_user_id.label("host"),
            func.count().label("rated"),
            func.avg(CpRating.score).label("average"),
            func.count().filter(CpRating.score <= 2).label("low"),
            func.count().filter(CpRating.resolved.is_(True)).label("resolved"),
        )
        .where(CpRating.created_at >= since, CpRating.host_user_id.is_not(None))
        .group_by(CpRating.host_user_id)
        .subquery()
    )
    takes = (
        select(
            BoCard.assignee_user_id.label("host"),
            func.percentile_cont(0.5)
            .within_group(
                func.extract("epoch", BoCard.taken_at - BoCard.created_at) / 60
            )
            .label("median"),
        )
        .where(
            BoCard.taken_at.is_not(None),
            BoCard.created_at >= since,
            BoCard.assignee_user_id.is_not(None),
        )
        .group_by(BoCard.assignee_user_id)
        .subquery()
    )
    rows = (
        await db.execute(
            select(
                User.id,
                User.name,
                meetings_held.c.meetings,
                ratings.c.rated,
                ratings.c.average,
                ratings.c.low,
                ratings.c.resolved,
                takes.c.median,
            )
            .join(meetings_held, meetings_held.c.host == User.id, isouter=True)
            .join(ratings, ratings.c.host == User.id, isouter=True)
            .join(takes, takes.c.host == User.id, isouter=True)
            .where((meetings_held.c.meetings > 0) | (ratings.c.rated > 0))
            .order_by(User.name)
        )
    ).all()
    people = [
        {
            "user_id": row.id,
            "name": row.name,
            "meetings": row.meetings or 0,
            "rated": row.rated or 0,
            "average": _average(row.average),
            "low": row.low or 0,
            "median_take_minutes": round(row.median)
            if row.median is not None
            else None,
        }
        for row in rows
        # Kierownik, który sam prowadzi rozmowy, ma własny przegląd miesięczny.
        if row.id != viewer_id
    ]
    total_meetings = sum(person["meetings"] for person in people)
    total_rated = sum(person["rated"] for person in people)
    total_score = sum(
        (row.average or 0) * (row.rated or 0) for row in rows if row.rated
    )
    total_resolved = sum(row.resolved or 0 for row in rows)
    return {
        "days": days,
        "meetings": total_meetings,
        "rated": total_rated,
        "average": _average(float(total_score) / total_rated) if total_rated else None,
        "resolved_share": round(100 * total_resolved / total_rated)
        if total_rated
        else None,
        "people": people,
        "tasks": await _open_tasks(db, viewer_id=viewer_id),
    }


async def _open_tasks(db: AsyncSession, *, viewer_id: int) -> list[dict[str, Any]]:
    rows = (
        await db.execute(
            select(CpRating, CpMeeting, Candidate.name, Candidate.lastname, User.name)
            .join(CpMeeting, CpMeeting.id == CpRating.meeting_id)
            .join(Contract, Contract.id == CpRating.contract_id)
            .outerjoin(Candidate, Candidate.id == Contract.candidate_id)
            .outerjoin(User, User.id == CpRating.host_user_id)
            .where(CpRating.followup_status == "open")
            .order_by(CpRating.followup_due_on, CpRating.id)
        )
    ).all()
    return [
        {
            "id": rating.id,
            "meeting_id": meeting.id,
            "score": rating.score,
            "comment": rating.comment,
            "resolved": rating.resolved,
            "due_on": rating.followup_due_on.isoformat()
            if rating.followup_due_on
            else None,
            "consultant": full_name(first, last),
            "host": host_name,
            "start_at": meeting.start_at.isoformat(),
        }
        for rating, meeting, first, last, host_name in rows
        if rating.host_user_id != viewer_id
    ]


async def close_task(
    db: AsyncSession, rating_id: int, *, viewer_id: int, note: str, now: datetime
) -> CpRating:
    rating = await db.get(CpRating, rating_id)
    if (
        rating is None
        or rating.followup_status == "none"
        or rating.host_user_id == viewer_id
    ):
        raise PortalError("Nie ma takiego zadania.", status=404, code="not_found")
    if rating.followup_status == "done":
        raise PortalError("To zadanie jest już zamknięte.", status=409, code="done")
    rating.followup_status = "done"
    rating.followup_note = note.replace("\x00", "").strip()[:COMMENT_MAX] or None
    rating.followup_done_by = viewer_id
    rating.followup_done_at = now
    return rating


# ── Przegląd miesięczny osoby ────────────────────────────────────────────────


def previous_month(today: date) -> tuple[int, int]:
    total = today.year * 12 + today.month - 2
    return total // 12, total % 12 + 1


def _month_bounds(year: int, month: int) -> tuple[datetime, datetime]:
    start = local_now().replace(
        year=year, month=month, day=1, hour=0, minute=0, second=0, microsecond=0
    )
    total = year * 12 + month
    end = start.replace(year=total // 12, month=total % 12 + 1)
    return start, end


async def my_review(db: AsyncSession, *, user_id: int, today: date) -> dict[str, Any]:
    """Zamknięty miesiąc w zbiorczych liczbach; bez komentarzy i bez pojedynczych ocen."""

    year, month = previous_month(today)
    start, end = _month_bounds(year, month)
    row = (
        await db.execute(
            select(
                func.count().label("rated"),
                func.avg(CpRating.score).label("average"),
                func.count().filter(CpRating.resolved.is_(True)).label("resolved"),
            ).where(
                CpRating.host_user_id == user_id,
                CpRating.created_at >= start,
                CpRating.created_at < end,
            )
        )
    ).one()
    rated = row.rated or 0
    enough = rated >= MIN_FOR_REVIEW
    return {
        "year": year,
        "month": month,
        "month_label": f"{MONTHS[month - 1]} {year}",
        "enough": enough,
        "min_for_review": MIN_FOR_REVIEW,
        "rated": rated if enough else None,
        "average": _average(row.average) if enough else None,
        "resolved_share": round(100 * (row.resolved or 0) / rated) if enough else None,
    }


async def notify_monthly_reviews(db: AsyncSession, *, now: datetime) -> dict[str, int]:
    """Dzwonek raz w miesiącu, pierwszego dnia, dla osób z ocenami z minionego."""

    today = business_today()
    if today.day != 1:
        return {"notified": 0}
    year, month = previous_month(today)
    run_id = await job_runs.claim(
        db, "consultant_portal_review", f"{year}-{month:02d}", now
    )
    if run_id is None:
        return {"notified": 0}
    start, end = _month_bounds(year, month)
    hosts = (
        await db.scalars(
            select(CpRating.host_user_id)
            .where(
                CpRating.host_user_id.is_not(None),
                CpRating.created_at >= start,
                CpRating.created_at < end,
            )
            .group_by(CpRating.host_user_id)
            .having(func.count() >= MIN_FOR_REVIEW)
        )
    ).all()
    notified = await notify_each(
        db,
        hosts,
        title="Przegląd rozmów za miesiąc",
        message="Twój przegląd rozmów z portalu za miniony miesiąc jest gotowy.",
        ntype=NotificationType.portal_monthly_review,
        link=QUALITY_LINK,
        log_tag="consultant_portal",
    )
    await job_runs.finish(db, run_id, status="done", counts={"notified": notified})
    return {"notified": notified}


async def run_once(
    db: AsyncSession, *, now: Optional[datetime] = None
) -> dict[str, Any]:
    moment = now or datetime.now(timezone.utc)
    state = await portal_settings.load(db)
    if not state.is_on:
        return {"status": "disabled"}
    return {
        "status": "ok",
        **await send_requests(db, now=moment),
        **await notify_monthly_reviews(db, now=moment),
    }
