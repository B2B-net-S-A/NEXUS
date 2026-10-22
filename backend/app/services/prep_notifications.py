"""Powiadomienia o prepach dla ludzi pary (0453, 17.10.2026, decyzje D5–D8).

Zgłoszenie Delivery Leada: DL-e nie dowiadywali się, że kandydat przyjął prep
albo poprosił o inny termin, ani że rekruter założył prep w ich kalendarzu.
Mail „Zaakceptowano” z Outlooka dostaje tylko organizator, a samo spotkanie
pojawia się w kalendarzu organizatora bez żadnego maila.

Adresaci: ludzie pary — prowadzący, osoba, która prep zaplanowała, Delivery
Lead rekrutacji i rekruter kandydata (``prep_meetings.prep_editor_ids``), bez
autora zmiany. Wszystko w ikonie „Kalendarz” (kategoria „Rozmowy”). Dymek
(front, ``QUIET_INTERVIEW_TYPES``) tylko tam, gdzie ktoś ma ruch: kandydat
odmówił albo proponuje inny termin, ktoś zmienił prep w Twoim kalendarzu.

Encja powiadomienia: (``prep_<rodzaj>``, id wydarzenia). Dzienny dedup
``emit`` (``ix_notif_dedup_daily``: adresat, typ, ID encji, dzień — BEZ rodzaju
encji) zjadałby „przełożony” tego samego dnia co „zaplanowany”, bo oba to
``prep_changed`` tego samego wydarzenia. Dlatego zmiany prepu (``prep_changed``,
``prep_changed_yours``) idą bez ID encji — każda zmiana i tak wysyła je raz
(akcja w NEXUSIE albo wykryta różnica w Outlooku), a para jest w linku.
Odpowiedzi kandydata zostają przy dedupie: ten sam stan nie dzwoni dwa razy.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable, Literal, Optional
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.calendar_event import CalendarEvent
from app.models.candidate import Candidate
from app.models.job import Job
from app.models.notification import Notification, NotificationType
from app.models.prep_meeting import PrepMeeting, PrepReview
from app.models.user import User
from app.services import prep_invitation
from app.services.job_working_title import job_display_title_expr

ChangeKind = Literal["scheduled", "moved", "cancelled", "attendees", "organizer"]


async def _labels(db: AsyncSession, prep: PrepMeeting) -> tuple[str, str]:
    """Nazwisko kandydata i tytuł rekrutacji (tytuł dla rekrutera, jak na ekranie)."""
    row = (
        await db.execute(
            select(Candidate.name, Candidate.lastname).where(
                Candidate.id == prep.candidate_id
            )
        )
    ).first()
    who = (
        " ".join(p for p in (row[0], row[1]) if p) if row else ""
    ) or f"Kandydat #{prep.candidate_id}"
    title = await db.scalar(
        select(job_display_title_expr()).where(Job.id == prep.job_id)
    )
    return who, title or f"Rekrutacja #{prep.job_id}"


async def _name(db: AsyncSession, user_id: Optional[int]) -> str:
    if not user_id:
        return "ktoś z zespołu"
    return (await db.scalar(select(User.name).where(User.id == user_id))) or (
        "ktoś z zespołu"
    )


def _when(value: Optional[datetime]) -> str:
    return prep_invitation.when_label(value) if value is not None else "—"


def _short(value: Optional[datetime]) -> str:
    """„20.10, 16:00” w strefie firmy — do tytułu, który w okienku się ucina."""
    if value is None:
        return "—"
    aware = value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    return f"{aware.astimezone(ZoneInfo(settings.BUSINESS_TZ)):%d.%m, %H:%M}"


def _link(prep: PrepMeeting) -> str:
    return f"/calendar?cycle={prep.candidate_id}-{prep.job_id}"


async def _emit(
    db: AsyncSession,
    *,
    user_ids: Iterable[int],
    ntype: NotificationType,
    title: str,
    message: str,
    entity_type: str,
    event_id: int,
    prep: PrepMeeting,
) -> int:
    from app.services.notification_triggers import emit  # noqa: PLC0415 — cykl

    # Zmiany prepu bez ID encji — patrz docstring modułu (dedup dzienny).
    entity_id = (
        None
        if ntype in (NotificationType.prep_changed, NotificationType.prep_changed_yours)
        else event_id
    )

    sent = 0
    for uid in sorted(set(user_ids)):
        created = await emit(
            db,
            user_id=uid,
            title=title,
            message=message,
            ntype=ntype,
            related_entity_type=entity_type,
            related_entity_id=entity_id,
            link=_link(prep),
        )
        sent += int(created is not None)
    return sent


async def _pair_people(db: AsyncSession, prep: PrepMeeting) -> set[int]:
    from app.services import prep_meetings  # noqa: PLC0415 — cykl

    job = await db.get(Job, prep.job_id)
    return await prep_meetings.prep_editor_ids(db, prep, job)


async def notify_prep_change(
    db: AsyncSession,
    *,
    actor: User,
    prep: PrepMeeting,
    event: CalendarEvent,
    kind: ChangeKind,
    previous_start: Optional[datetime] = None,
    previous_organizer_id: Optional[int] = None,
) -> int:
    """Ktoś z pary założył, przełożył, odwołał albo przekazał prep (D6).

    Prowadzący (w jego kalendarzu stoi spotkanie) dostaje ``prep_changed_yours``
    — z dymkiem; reszta pary ``prep_changed`` — sam licznik. Autor nic.
    Przy zmianie prowadzącego poprzedni też dostaje „Twój” wpis — stracił
    spotkanie ze swojego kalendarza.
    """
    people = await _pair_people(db, prep)
    if previous_organizer_id:
        people.add(previous_organizer_id)
    people.discard(actor.id)
    if not people:
        return 0
    who, what = await _labels(db, prep)
    n = prep.prep_no
    author = actor.name or "ktoś z zespołu"
    organizer = await _name(db, prep.organizer_user_id)
    when = _when(event.start_time)
    short = _short(event.start_time)
    yours: dict[ChangeKind, tuple[str, str]] = {
        "scheduled": (
            f"Nowy Prep {n} w Twoim kalendarzu · {short}",
            f"{who} — {what}: prep zaplanowany przez: {author}.",
        ),
        "moved": (
            f"Twój Prep {n} przełożony na {short}",
            f"{who} — {what}: zmiana od: {author}, było {_when(previous_start)}.",
        ),
        "cancelled": (
            f"Twój Prep {n} odwołany",
            f"{who} — {what}: prep odwołany przez: {author}.",
        ),
        "attendees": (
            f"Zmienieni zaproszeni na Twój Prep {n}",
            f"{who} — {what}: zmiana od: {author}. Termin bez zmian ({when}).",
        ),
        "organizer": (
            f"Prep {n} przekazany Tobie · {short}",
            f"{who} — {what}: prowadzisz ten prep; zmiana od: {author}.",
        ),
    }
    others: dict[ChangeKind, tuple[str, str]] = {
        "scheduled": (
            f"Prep {n} zaplanowany · {short}",
            f"{who} — {what}: prowadzi {organizer}, zaplanowany przez: {author}.",
        ),
        "moved": (
            f"Prep {n} przełożony na {short}",
            f"{who} — {what}: zmiana od: {author}, było {_when(previous_start)}.",
        ),
        "cancelled": (
            f"Prep {n} odwołany",
            f"{who} — {what}: prep odwołany przez: {author}.",
        ),
        "attendees": (
            f"Zmienieni zaproszeni na Prep {n}",
            f"{who} — {what}: zmiana od: {author}.",
        ),
        "organizer": (
            f"Prep {n}: prowadzi teraz {organizer}",
            f"{who} — {what}: zmiana od: {author}. Termin {when}.",
        ),
    }
    sent = 0
    entity = f"prep_{kind}"
    owner = prep.organizer_user_id
    if owner in people:
        title, message = yours[kind]
        sent += await _emit(
            db,
            user_ids=[owner],
            ntype=NotificationType.prep_changed_yours,
            title=title,
            message=message,
            entity_type=entity,
            event_id=event.id,
            prep=prep,
        )
    if previous_organizer_id and previous_organizer_id in people:
        sent += await _emit(
            db,
            user_ids=[previous_organizer_id],
            ntype=NotificationType.prep_changed_yours,
            title=f"Twój Prep {n} przekazany: prowadzi {organizer}",
            message=f"{who} — {what}: spotkanie zniknęło z Twojego kalendarza; zmiana od: {author}.",
            entity_type=entity,
            event_id=event.id,
            prep=prep,
        )
    rest = people - {owner, previous_organizer_id}
    if rest:
        title, message = others[kind]
        sent += await _emit(
            db,
            user_ids=rest,
            ntype=NotificationType.prep_changed,
            title=title,
            message=message,
            entity_type=entity,
            event_id=event.id,
            prep=prep,
        )
    return sent


async def notify_outlook_change(
    db: AsyncSession,
    *,
    prep: PrepMeeting,
    event: CalendarEvent,
    kind: Literal["moved", "cancelled"],
    previous_start: Optional[datetime] = None,
) -> int:
    """Prowadzący przełożył albo odwołał prep u siebie w Outlooku (D6).

    Reszta pary dowiaduje się w ≤10 min (pętla ``prep_responses``); do
    17.10.2026 NEXUS widział taką zmianę dopiero po starej godzinie prepu.
    """
    people = await _pair_people(db, prep)
    people.discard(prep.organizer_user_id)
    if not people:
        return 0
    who, what = await _labels(db, prep)
    organizer = await _name(db, prep.organizer_user_id)
    n = prep.prep_no
    if kind == "moved":
        title = f"Prep {n} przełożony na {_short(event.start_time)}"
        message = (
            f"{who} — {what}: nowy termin ustawiono w kalendarzu prowadzącego "
            f"({organizer}), było {_when(previous_start)}."
        )
    else:
        title = f"Prep {n} odwołany"
        message = f"{who} — {what}: spotkanie odwołano w kalendarzu prowadzącego ({organizer})."
    return await _emit(
        db,
        user_ids=people,
        ntype=NotificationType.prep_changed,
        title=title,
        message=message,
        entity_type=f"prep_outlook_{kind}",
        event_id=event.id,
        prep=prep,
    )


async def notify_candidate_response(
    db: AsyncSession, *, prep: PrepMeeting, event: CalendarEvent
) -> int:
    """Nowa odpowiedź kandydata — do całej pary (D5, D6).

    Odmowa albo inny termin = ``prep_candidate_declined`` (dymek: ktoś musi
    przełożyć prep); przyjął / „może” = ``prep_candidate_response`` (licznik).
    """
    people = await _pair_people(db, prep)
    if not people:
        return 0
    who, what = await _labels(db, prep)
    n = prep.prep_no
    when = _when(event.start_time)
    if prep.proposed_start is not None:
        ntype = NotificationType.prep_candidate_declined
        entity = "prep_proposed"
        title = f"Prep {n}: kandydat proponuje {_short(prep.proposed_start)}"
        message = (
            f"{who} — {what}: zamiast {when}. Przyjmij termin w panelu osoby "
            "(„Zmień” przy prepie) albo ustal inny."
        )
    elif prep.candidate_response == "declined":
        ntype = NotificationType.prep_candidate_declined
        entity = "prep_declined"
        title = f"Prep {n}: kandydat odrzucił zaproszenie"
        message = (
            f"{who} — {what}: termin {when} nie pasuje. Ustal nowy i przełóż prep."
        )
    elif prep.candidate_response in ("accepted", "tentative"):
        ntype = NotificationType.prep_candidate_response
        entity = f"prep_{prep.candidate_response}"
        title = (
            f"Prep {n} przyjęty · {_short(event.start_time)}"
            if prep.candidate_response == "accepted"
            else f"Prep {n}: kandydat „może” · {_short(event.start_time)}"
        )
        message = f"{who} — {what}: odpowiedź na zaproszenie z Outlooka."
    else:
        return 0
    return await _emit(
        db,
        user_ids=people,
        ntype=ntype,
        title=title,
        message=message,
        entity_type=entity,
        event_id=event.id,
        prep=prep,
    )


async def notify_no_response(
    db: AsyncSession, *, prep: PrepMeeting, event: CalendarEvent
) -> int:
    """Doba przed prepem kandydat nie odpowiedział (D8) — raz na prep.

    Do prowadzącego i osoby, która prep zaplanowała. „Brak odpowiedzi” nie
    znaczy „nie przyjdzie” — część kandydatów przyjmuje w Gmailu bez wysłania
    odpowiedzi, dlatego to przypomnienie, a nie alarm.
    """
    already = await db.scalar(
        select(Notification.id)
        .where(
            Notification.notification_type == NotificationType.prep_no_response,
            Notification.related_entity_type == "prep_no_response",
            Notification.related_entity_id == event.id,
        )
        .limit(1)
    )
    if already is not None:
        return 0
    people = {i for i in (prep.organizer_user_id, prep.scheduled_by_user_id) if i}
    if not people:
        return 0
    who, what = await _labels(db, prep)
    return await _emit(
        db,
        user_ids=people,
        ntype=NotificationType.prep_no_response,
        title=f"Brak odpowiedzi na Prep {prep.prep_no} · {_short(event.start_time)}",
        message=f"{who} — {what}: potwierdź z kandydatem termin prepu.",
        entity_type="prep_no_response",
        event_id=event.id,
        prep=prep,
    )


def _points(n: int) -> str:
    """„1 punkt”, „3 punkty”, „5 punktów” (12–14 też „punktów”)."""
    if n == 1:
        return "1 punkt"
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return f"{n} punkty"
    return f"{n} punktów"


async def notify_review_ready(
    db: AsyncSession, *, prep: PrepMeeting, review: PrepReview
) -> int:
    """Ocena prepu gotowa — do całej pary, licznik (22.10.2026).

    Rekruter ma wiedzieć przed Prepem 2, co powtórzyć; DL — jak poszedł jego
    Prep 1. Ocena niedostępna (awaria AI) nie dzwoni: tu nie ma czego czytać,
    a brak oceny i tak widać w kroku prepu. Autora nie ma — ocenę robi AI.
    """
    if review.status != "ok" or not review.level:
        return 0
    people = await _pair_people(db, prep)
    if not people:
        return 0
    who, what = await _labels(db, prep)
    criteria = review.criteria or {}
    total = criteria.get("total")
    level = {"weak": "słaby", "ok": "OK", "good": "dobry"}[review.level]
    title = f"Prep {prep.prep_no} oceniony · {level}" + (
        f" ({total}%)" if total is not None else ""
    )
    if prep.prep_no == 1:
        n = len(criteria.get("followup") or review.remaining or [])
        tail = (
            f"{_points(n)} do powtórzenia na Prepie 2."
            if n
            else "Nic do powtórzenia na Prepie 2."
        )
    else:
        rows = criteria.get("comparison") or []
        improved = sum(1 for r in rows if r.get("after") == "strong")
        tail = (
            f"Z Prepu 1 poprawione {improved} z {len(rows)}."
            if rows
            else "Wnioski i transkrypt w karcie osoby."
        )
    return await _emit(
        db,
        user_ids=people,
        ntype=NotificationType.prep_review_ready,
        title=title,
        message=f"{who} — {what}: {tail}",
        entity_type="prep_review",
        event_id=prep.calendar_event_id,
        prep=prep,
    )
