"""Spotkanie szkolenia w Teams zakłada NEXUS (0697, decyzje Artura 13.11.2026).

Do tej daty TCM wklejał link ze spotkania założonego we własnym Teams: nagranie
lądowało w OneDrive tej osoby i wygasało po 120 dniach, trener w panelu linku nie
dostawał, a zapis na szkolenie nie wysyłał zaproszenia.

Jak to działa:

* **Spotkanie główne** powstaje w kalendarzu skrzynki ``TRAININGS_TEAMS_MAILBOX``
  (szkolenia@), gdy szkolenie jest ``signed`` i ma termin. Zaproszony jest tylko
  prowadzący (prezenter). Nagrywanie i transkrypcja od startu, bez poczekalni.
* **Zaproszenie dla zapisanego** to osobne wydarzenie z tym samym linkiem, bez
  własnego spotkania Teams. Dzięki temu zapis i wypis jednej osoby nie wysyłają
  aktualizacji do wszystkich (PATCH listy uczestników w Graphie powiadamia każdego).
* Webinaru Teams z rejestracją aplikacja założyć nie może (Graph pozwala na to tylko
  zalogowanemu człowiekowi), więc rejestrację, limit miejsc i przypomnienia robi NEXUS.
* Konsultant dostaje zaproszenie tylko przy otwartym panelu (``open_for``), tak jak
  każdy mail z panelu — to wysyłka do osoby spoza firmy.

Awaria Graph nie cofa kroku w NEXUSIE: stan ląduje w ``teams_status``/``teams_error``
albo ``invite_status`` i TCM widzi „Spróbuj ponownie”. Funkcje nie robią commita.
"""

from __future__ import annotations

import html
import logging
from datetime import datetime, time, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.scheduling import DEFAULT_TZ, is_business_day
from app.models.contract import Contract
from app.models.training import Training, TrainingRegistration
from app.models.user import User
from app.services.trainings_schema import REHEARSAL_MINUTES

logger = logging.getLogger(__name__)

#: Próba techniczna (0698): tyle dni roboczych przed szkoleniem, o tej samej godzinie.
REHEARSAL_BUSINESS_DAYS = 2
REHEARSAL_NOTICE = (
    "Próba techniczna przed szkoleniem: sprawdzamy dźwięk, kamerę i udostępnianie "
    "ekranu. Próba nie jest nagrywana."
)

NOTICE = (
    "Szkolenie jest nagrywane i transkrybowane. Nagranie z transkryptem trafi do "
    "Szkoleń w NEXUSIE i w panelu konsultanta."
)


def ready() -> bool:
    from app.services.prep_meetings import app_only_ready  # noqa: PLC0415

    return bool(
        settings.TRAININGS_TEAMS_ENABLED
        and settings.TRAININGS_TEAMS_MAILBOX
        and app_only_ready()
    )


def organizer() -> str:
    return settings.TRAININGS_TEAMS_MAILBOX.strip()


def window(training: Training) -> Optional[tuple[datetime, datetime]]:
    """Początek i koniec w strefie firmy; bez daty albo godzin = brak spotkania."""

    if training.session_date is None or not training.time_from:
        return None
    zone = ZoneInfo(DEFAULT_TZ)
    hh, mm = (int(p) for p in training.time_from.split(":"))
    start = datetime.combine(training.session_date, time(hh, mm), tzinfo=zone)
    if training.time_to:
        eh, em = (int(p) for p in training.time_to.split(":"))
        end = datetime.combine(training.session_date, time(eh, em), tzinfo=zone)
    else:
        end = start + timedelta(minutes=training.duration_minutes or 60)
    if end <= start:
        end = start + timedelta(minutes=training.duration_minutes or 60)
    return start, end


def rehearsal_window(training: Training) -> Optional[tuple[datetime, datetime]]:
    """15 minut z prowadzącym dwa dni robocze przed szkoleniem, o godzinie startu."""

    slot = window(training)
    if slot is None:
        return None
    start = slot[0]
    remaining = REHEARSAL_BUSINESS_DAYS
    while remaining:
        start -= timedelta(days=1)
        if is_business_day(start):
            remaining -= 1
    return start, start + timedelta(minutes=REHEARSAL_MINUTES)


def _description(training: Training, *, join_url: str = "") -> str:
    parts = []
    if training.description:
        parts.append(f"<p>{html.escape(training.description)}</p>")
    if join_url:
        safe = html.escape(join_url, quote=True)
        parts.append(
            f'<p><a href="{safe}">Dołącz do szkolenia w Microsoft Teams</a></p>'
        )
    parts.append(f"<p><small>{html.escape(NOTICE)}</small></p>")
    return "".join(parts)


async def trainer_email(db: AsyncSession, training: Training) -> Optional[str]:
    """Adres prowadzącego: konto pracownika albo adres z umowy przy otwartym panelu."""

    if training.trainer_user_id:
        email = await db.scalar(
            select(User.email).where(User.id == training.trainer_user_id)
        )
        return (email or "").strip() or None
    if training.trainer_contract_id:
        return await consultant_email(db, training.trainer_contract_id)
    return None


async def consultant_email(db: AsyncSession, contract_id: int) -> Optional[str]:
    from app.services.consultant_portal import portal_settings  # noqa: PLC0415

    state = await portal_settings.load(db)
    if not state.open_for(contract_id):
        return None
    email = await db.scalar(
        select(Contract.candidate_email).where(Contract.id == contract_id)
    )
    return (email or "").strip() or None


def _fail(training: Training, exc: BaseException, now: datetime) -> None:
    training.teams_status = "failed"
    training.teams_error = f"{type(exc).__name__}: {str(exc)[:300]}"
    training.teams_synced_at = now
    logger.warning(
        "trainings_teams: sync failed training=%s err=%s",
        training.id,
        type(exc).__name__,
    )


async def sync_meeting(db: AsyncSession, training: Training, *, now: datetime) -> None:
    """Załóż, przesuń albo odwołaj spotkanie tak, żeby zgadzało się ze szkoleniem."""

    if not ready():
        return
    from app.services.m365 import teams_prep_graph as graph  # noqa: PLC0415
    from app.services.m365.calendar import (  # noqa: PLC0415
        _build_event_payload,
        build_update_payload,
    )

    if training.status == "cancelled":
        await cancel_meeting(db, training, now=now)
        return
    slot = window(training)
    if training.status != "signed" or slot is None:
        return
    start, end = slot
    try:
        email = await trainer_email(db, training)
        if not training.teams_event_id:
            payload = _build_event_payload(
                title=training.title,
                description=_description(training),
                start=start,
                end=end,
                attendee_emails=[email] if email else [],
                want_teams=True,
                transaction_id=f"nexus-training-{training.id}",
            )
            payload["allowNewTimeProposals"] = False
            created = await graph.create_event(organizer(), payload)
            training.teams_event_id = created.graph_event_id
            training.join_url = created.join_url or training.join_url
            # Zapis przed konfiguracją: jej awaria nie może założyć drugiego wydarzenia.
            await db.flush()
        else:
            await graph.update_event(
                organizer(),
                training.teams_event_id,
                build_update_payload(
                    title=training.title,
                    description=_description(training),
                    start=start,
                    end=end,
                ),
            )
            await reschedule_invites(db, training, start=start, end=end)
        # Pusty stan nagrania = nagrywanie jeszcze nieskonfigurowane (pierwsza próba
        # padła po założeniu wydarzenia). Ponowienie kończy konfigurację, bez tego
        # pętla nagrań nigdy nie weźmie szkolenia (przegląd kodu 13.11.2026).
        if not training.recording_status:
            await _configure_meeting(training, [email] if email else [])
            training.recording_status = "waiting"
        training.recording_next_at = end + timedelta(
            minutes=settings.TRAININGS_RECORDING_DELAY_MINUTES
        )
        training.teams_status = "created"
        training.teams_error = ""
        training.teams_synced_at = now
    except Exception as exc:  # noqa: BLE001 — awaria Graph nie cofa kroku
        _fail(training, exc, now)
    if training.teams_status == "created":
        await sync_rehearsal(db, training, now=now)
    await db.flush()


def _clear_rehearsal(training: Training, status: str) -> None:
    training.rehearsal_event_id = None
    training.rehearsal_join_url = ""
    training.rehearsal_status = status


async def sync_rehearsal(
    db: AsyncSession, training: Training, *, now: datetime
) -> None:
    """Próba techniczna (0698): osobne 15-minutowe spotkanie z prowadzącym.

    Ta sama skrzynka szkolenia@, bez nagrywania i bez zapisanych. Zaznaczona
    w zamówieniu, przesuwa się z terminem, a odznaczona albo przy odwołaniu
    szkolenia jest odwoływana. Termin, który już minął (zamówienie na ostatnią
    chwilę), daje stan ``skipped`` zamiast spotkania w przeszłości. Awaria
    Graph nie rusza spotkania głównego: zostaje ``rehearsal_status=failed``
    i „Spróbuj ponownie” zakłada próbę razem z resztą."""

    from app.services.m365 import teams_prep_graph as graph  # noqa: PLC0415
    from app.services.m365.calendar import (  # noqa: PLC0415
        _build_event_payload,
        build_update_payload,
    )

    slot = rehearsal_window(training)
    wanted = training.rehearsal and training.status == "signed" and slot is not None
    try:
        if not wanted:
            if training.rehearsal_event_id:
                await graph.cancel_event(
                    organizer(),
                    training.rehearsal_event_id,
                    "Próba techniczna została odwołana.",
                )
                _clear_rehearsal(training, "cancelled")
            elif not training.rehearsal:
                _clear_rehearsal(training, "")
            return
        assert slot is not None
        start, end = slot
        title = f"Próba techniczna: {training.title}"[:255]
        if not training.rehearsal_event_id:
            if start <= now:
                training.rehearsal_start = start
                _clear_rehearsal(training, "skipped")
                return
            email = await trainer_email(db, training)
            payload = _build_event_payload(
                title=title,
                description=f"<p>{html.escape(REHEARSAL_NOTICE)}</p>",
                start=start,
                end=end,
                attendee_emails=[email] if email else [],
                want_teams=True,
                transaction_id=(
                    f"nexus-training-{training.id}-rehearsal-{int(start.timestamp())}"
                ),
            )
            payload["allowNewTimeProposals"] = False
            created = await graph.create_event(organizer(), payload)
            training.rehearsal_event_id = created.graph_event_id
            training.rehearsal_join_url = created.join_url or ""
            await db.flush()
            await _configure_rehearsal(training)
        elif training.rehearsal_start != start:
            await graph.update_event(
                organizer(),
                training.rehearsal_event_id,
                build_update_payload(
                    title=title,
                    description=f"<p>{html.escape(REHEARSAL_NOTICE)}</p>",
                    start=start,
                    end=end,
                ),
            )
        training.rehearsal_start = start
        training.rehearsal_status = "created"
    except Exception as exc:  # noqa: BLE001 — próba nie rusza spotkania głównego
        training.rehearsal_status = "failed"
        logger.warning(
            "trainings_teams: rehearsal failed training=%s err=%s",
            training.id,
            type(exc).__name__,
        )


async def _configure_rehearsal(training: Training) -> None:
    """Bez nagrywania i bez poczekalni. Porażka zostaje w logu: próba i tak się odbędzie."""

    from app.services.m365 import teams_prep_graph as graph  # noqa: PLC0415
    from app.services.m365 import teams_training_graph as tgraph  # noqa: PLC0415

    try:
        user_id = await graph.resolve_user_id(organizer())
        meeting_id = (
            await graph.find_online_meeting(user_id, training.rehearsal_join_url)
            if user_id and training.rehearsal_join_url
            else None
        )
        if user_id and meeting_id:
            await tgraph.rehearsal_settings(user_id, meeting_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "trainings_teams: rehearsal settings failed training=%s err=%s",
            training.id,
            type(exc).__name__,
        )


async def _configure_meeting(training: Training, presenters: list[str]) -> None:
    """Nagrywanie od startu i prowadzący jako prezenter. Porażka = komunikat, nie błąd."""

    from app.services.m365 import teams_prep_graph as graph  # noqa: PLC0415
    from app.services.m365 import teams_training_graph as tgraph  # noqa: PLC0415

    user_id = await graph.resolve_user_id(organizer())
    if not user_id or not training.join_url:
        raise RuntimeError("organizer or join url missing")
    meeting_id = await graph.find_online_meeting(user_id, training.join_url)
    if not meeting_id:
        raise RuntimeError("online meeting not found")
    training.teams_meeting_id = meeting_id
    await graph.enable_auto_transcription(user_id, meeting_id)
    await tgraph.set_presenters(user_id, meeting_id, presenters)


async def cancel_meeting(
    db: AsyncSession, training: Training, *, now: datetime
) -> None:
    if not ready() or not training.teams_event_id:
        return
    from app.services.m365 import teams_prep_graph as graph  # noqa: PLC0415

    comment = "Szkolenie zostało odwołane."
    try:
        await graph.cancel_event(organizer(), training.teams_event_id, comment)
        if training.rehearsal_event_id:
            await graph.cancel_event(organizer(), training.rehearsal_event_id, comment)
            _clear_rehearsal(training, "cancelled")
        for registration in await _invited(db, training.id):
            await graph.cancel_event(organizer(), registration.invite_event_id, comment)
            registration.invite_status = "cancelled"
        training.teams_status = "cancelled"
        training.teams_error = ""
        training.teams_synced_at = now
        training.recording_status = ""
    except Exception as exc:  # noqa: BLE001
        _fail(training, exc, now)
    await db.flush()


async def _invited(db: AsyncSession, training_id: int) -> list[TrainingRegistration]:
    return list(
        (
            await db.scalars(
                select(TrainingRegistration).where(
                    TrainingRegistration.training_id == training_id,
                    TrainingRegistration.invite_event_id.is_not(None),
                    TrainingRegistration.invite_status == "sent",
                )
            )
        ).all()
    )


async def reschedule_invites(
    db: AsyncSession, training: Training, *, start: datetime, end: datetime
) -> None:
    from app.services.m365 import teams_prep_graph as graph  # noqa: PLC0415
    from app.services.m365.calendar import build_update_payload  # noqa: PLC0415

    for registration in await _invited(db, training.id):
        await graph.update_event(
            organizer(),
            registration.invite_event_id,
            build_update_payload(
                title=training.title,
                description=_description(training, join_url=training.join_url),
                start=start,
                end=end,
            ),
        )


async def _registrant_email(
    db: AsyncSession, registration: TrainingRegistration
) -> Optional[str]:
    if registration.user_id:
        email = await db.scalar(
            select(User.email).where(User.id == registration.user_id)
        )
        return (email or "").strip() or None
    if registration.contract_id:
        return await consultant_email(db, registration.contract_id)
    return None


async def invite(
    db: AsyncSession, training: Training, registration: TrainingRegistration
) -> None:
    """Zaproszenie do kalendarza zapisanego z linkiem do spotkania głównego."""

    if not ready() or not training.teams_event_id or not training.join_url:
        return
    slot = window(training)
    if slot is None:
        return
    from app.services.m365 import teams_prep_graph as graph  # noqa: PLC0415
    from app.services.m365.calendar import _build_event_payload  # noqa: PLC0415

    email = await _registrant_email(db, registration)
    if not email:
        registration.invite_status = "skipped"
        await db.flush()
        return
    start, end = slot
    payload = _build_event_payload(
        title=training.title,
        description=_description(training, join_url=training.join_url),
        start=start,
        end=end,
        attendee_emails=[email],
        want_teams=False,
        transaction_id=f"nexus-training-{training.id}-reg-{registration.id}",
    )
    payload["location"] = {"displayName": "Microsoft Teams"}
    payload["responseRequested"] = False
    payload["allowNewTimeProposals"] = False
    payload["reminderMinutesBeforeStart"] = 15
    try:
        created = await graph.create_event(organizer(), payload)
        registration.invite_event_id = created.graph_event_id
        registration.invite_status = "sent"
    except Exception:  # noqa: BLE001 — zapis zostaje, zaproszenie można ponowić
        logger.warning(
            "trainings_teams: invite failed training=%s registration=%s",
            training.id,
            registration.id,
        )
        registration.invite_status = "failed"
    await db.flush()


async def invite_pending(db: AsyncSession, training: Training) -> int:
    """Zaproszenia dla zapisanych przed założeniem spotkania albo po awarii."""

    rows = (
        await db.scalars(
            select(TrainingRegistration).where(
                TrainingRegistration.training_id == training.id,
                TrainingRegistration.invite_status.in_(("", "failed")),
            )
        )
    ).all()
    for registration in rows:
        await invite(db, training, registration)
    return len(rows)


async def uninvite_event(invite_event_id: Optional[str]) -> None:
    """Odwołanie zaproszenia po wypisie (wiersz zapisu już nie istnieje)."""

    if not ready() or not invite_event_id:
        return
    from app.services.m365 import teams_prep_graph as graph  # noqa: PLC0415

    try:
        await graph.cancel_event(organizer(), invite_event_id, "Wypisano ze szkolenia.")
    except Exception:  # noqa: BLE001
        logger.warning("trainings_teams: uninvite failed")


async def registration_changed(
    db: AsyncSession,
    training_id: int,
    *,
    join: bool,
    user_id: Optional[int] = None,
    contract_id: Optional[int] = None,
    removed_invite: Optional[str] = None,
) -> None:
    """Po zapisie (już zatwierdzonym w bazie): zaproszenie albo jego odwołanie."""

    if not ready():
        return
    if not join:
        await uninvite_event(removed_invite)
        return
    training = await db.get(Training, training_id)
    query = select(TrainingRegistration).where(
        TrainingRegistration.training_id == training_id
    )
    query = (
        query.where(TrainingRegistration.user_id == user_id)
        if user_id is not None
        else query.where(TrainingRegistration.contract_id == contract_id)
    )
    registration = await db.scalar(query)
    if training is None or registration is None or registration.invite_status == "sent":
        return
    await invite(db, training, registration)
