"""Powiadomienia automatu przydziału.

Od razu, gdy osoba dostaje request (``notify_assigned``): akceptacja
propozycji, ręczny wybór z pulpitu i — w trybie ``auto`` — przydział przez
automat. ``request_assignment_changed``, jeden wpis na (osoba, request) na
dzień: „Nowy request do pracy”.

Rano, raz dziennie o ``review_time``:

* ``request_assignment_changed`` — JEDEN wpis na osobę: „Zwolnione: Z (Mamy
  championa)”, a „Od dziś: …” tylko dla requestów, o których osoba nie
  dostała dzwonka od razu (nieudane powiadomienie). Tylko w trybie ``auto``:
  propozycje trybu podglądu nikogo do niczego nie zobowiązują.
* ``request_review_needed`` — JEDEN wpis na Delivery Leada: nowe requesty
  z Traffita „Do przejrzenia”, „Klient milczy” od 14+ dni, „Szukamy” bez
  pracy od 30+ dni. Link prowadzi do „Porządku w requestach”.

Po każdej nowej propozycji i rano (02.10.2026):

* ``request_allocation_proposals`` — JEDEN wpis dziennie na Head of
  Recruitment: ile propozycji automatu czeka na akceptację. Poranne
  przypomnienie z niezmienioną liczbą nie dzwoni drugi raz
  (``send_proposal_notices``).

Wszystkie idą przez ``notification_triggers.emit`` (dedup dobowy, sprawdzenie
odbiorcy). Treść bez nazwisk kandydatów — same tytuły requestów.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Iterable, Optional
from zoneinfo import ZoneInfo

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.client import Client
from app.models.job import Job, JobStatus
from app.models.job_work_assignment import JobWorkAssignment
from app.models.notification import Notification, NotificationType
from app.services.job_working_title import job_display_title_expr
from app.services.notification_ws_after_commit import queue_ws_notification
from app.services.request_allocation_plan import (
    is_silent_release,
    release_reason_label,
)

logger = logging.getLogger(__name__)

REVIEW_LINK = "/jobs/review-states"
BOARD_LINK = "/dashboard"
# Panel „Czeka na Ciebie” na pulpicie — tam są przyciski akceptacji.
PROPOSALS_LINK = "/dashboard#czeka-na-ciebie"
PROPOSALS_MESSAGE = (
    "Automat zaproponował osoby do requestów. "
    "Zaakceptuj, zmień albo odrzuć na pulpicie."
)
MAX_TITLES = 4


def _titles(titles: list[str]) -> str:
    shown = ", ".join(titles[:MAX_TITLES])
    rest = len(titles) - MAX_TITLES
    return shown + (f" i {rest} więcej" if rest > 0 else "")


async def notify_assigned(
    db: AsyncSession,
    *,
    job_id: int,
    title: str,
    client_name: Optional[str],
    user_id: int,
) -> None:
    """Dzwonek dla osoby, która właśnie dostała request.

    Propozycja nikogo nie budzi; od przydziału osoba pracuje, więc musi się
    dowiedzieć od razu. Savepoint: nieudane powiadomienie nie cofa przydziału
    ani nie zatrzymuje przebiegu automatu.
    """
    from app.services.notification_triggers import emit  # noqa: PLC0415

    try:
        async with db.begin_nested():
            await emit(
                db,
                user_id=user_id,
                title="Nowy request do pracy",
                message=f"{title} · {client_name}" if client_name else title,
                ntype=NotificationType.request_assignment_changed,
                related_entity_type="job",
                related_entity_id=job_id,
                link=f"/jobs/{job_id}",
            )
    except Exception:  # noqa: BLE001 — dzwonek nie może cofnąć przydziału
        logger.exception(
            "[request_allocation] powiadomienie o przydziale nie wyszło job=%s",
            job_id,
        )


async def notify_assigned_pairs(
    db: AsyncSession, pairs: Iterable[tuple[int, int]]
) -> None:
    """``notify_assigned`` dla par (request, osoba) przydzielonych przez
    automat — tytuły i klienci jednym zapytaniem."""
    wanted = list(dict.fromkeys(pairs))
    if not wanted:
        return
    jobs = {
        job_id: (title, client_name)
        for job_id, title, client_name in (
            await db.execute(
                select(Job.id, job_display_title_expr(), Client.name)
                .outerjoin(Client, Client.id == Job.client_id)
                .where(Job.id.in_(sorted({job_id for job_id, _ in wanted})))
            )
        ).all()
    }
    for job_id, user_id in wanted:
        title, client_name = jobs.get(job_id, (None, None))
        if title is None:
            continue
        await notify_assigned(
            db, job_id=job_id, title=title, client_name=client_name, user_id=user_id
        )


async def _assignment_notices(db: AsyncSession, *, now: datetime) -> int:
    from app.services.notification_triggers import emit  # noqa: PLC0415

    since = now - timedelta(hours=24)
    rows = (
        await db.execute(
            select(
                JobWorkAssignment.user_id,
                JobWorkAssignment.job_id,
                JobWorkAssignment.state,
                JobWorkAssignment.assigned_at,
                JobWorkAssignment.released_at,
                JobWorkAssignment.release_reason,
                job_display_title_expr(),
            )
            .join(Job, Job.id == JobWorkAssignment.job_id)
            .where(
                JobWorkAssignment.source != "owner",
                or_(
                    and_(
                        JobWorkAssignment.state == "active",
                        JobWorkAssignment.assigned_at >= since,
                    ),
                    and_(
                        JobWorkAssignment.state == "released",
                        JobWorkAssignment.released_at >= since,
                    ),
                ),
            )
        )
    ).all()
    # Zaakceptowana propozycja i osoba wybrana przez człowieka dostają dzwonek
    # od razu („Nowy request do pracy”) — rano nie wspominamy o tym samym
    # requeście drugi raz.
    announced: set[tuple[int, int]] = set()
    if any(state == "active" for _u, _j, state, *_rest in rows):
        announced = {
            (user_id, job_id)
            for user_id, job_id in (
                await db.execute(
                    select(Notification.user_id, Notification.related_entity_id).where(
                        Notification.notification_type
                        == NotificationType.request_assignment_changed,
                        Notification.related_entity_type == "job",
                        Notification.created_at >= since,
                    )
                )
            ).all()
        }
    per_user: dict[int, dict[str, list[str]]] = {}
    for user_id, job_id, state, _assigned, _released, reason, title in rows:
        if state != "active" and is_silent_release(reason):
            # Wycofana propozycja albo zdjęcie, po którym przypisano tę osobę
            # ponownie — patrz `is_silent_release`.
            continue
        if state == "active" and (user_id, job_id) in announced:
            continue
        bucket = per_user.setdefault(user_id, {"new": [], "gone": []})
        if state == "active":
            bucket["new"].append(title)
        else:
            label = release_reason_label(reason, "")
            bucket["gone"].append(f"{title} ({label})" if label else title)
    sent = 0
    for user_id, bucket in sorted(per_user.items()):
        parts = []
        if bucket["new"]:
            parts.append("Od dziś: " + _titles(bucket["new"]) + ".")
        if bucket["gone"]:
            parts.append("Zwolnione: " + _titles(bucket["gone"]) + ".")
        created = await emit(
            db,
            user_id=user_id,
            title="Twoje requesty na dziś",
            message=" ".join(parts),
            ntype=NotificationType.request_assignment_changed,
            related_entity_type="user",
            related_entity_id=user_id,
            link=BOARD_LINK,
        )
        sent += int(created is not None)
    return sent


SILENT_EVERY_DAYS = 14


def is_stale_check_day(now: datetime) -> bool:
    """Poniedziałek w kalendarzu firmy (``BUSINESS_TZ``), nie w UTC.

    Przegląd o ``review_time`` przed 02:00 wypada w UTC jeszcze w niedzielę —
    ``now.weekday()`` na czasie UTC gubił wtedy poniedziałkowy przegląd
    „Szukamy” bez ruchu, a dawał go we wtorek.
    """
    return now.astimezone(ZoneInfo(settings.BUSINESS_TZ)).weekday() == 0


def silent_reminder_due(
    now: datetime, since: Optional[datetime], last_reminded: Optional[str]
) -> bool:
    """„Klient milczy” przypomina się co 14 dni, nie codziennie.

    Liczone od OSTATNIEGO wysłanego przypomnienia (``last_reminded``, data ISO
    z ``stats`` automatu), nie z ``dni % 14 == 0`` — tamto gubiło przypomnienie
    na kolejne 14 dni, gdy poranny przebieg nie wypadł dokładnie w 14. dniu
    (pętla stała, deploy w oknie). Przypomnienie z poprzedniego epizodu
    „Klient milczy” (sprzed ``since``) się nie liczy.
    """
    if since is None:
        return False
    if (now - since).days < SILENT_EVERY_DAYS:
        return False
    if not last_reminded:
        return True
    try:
        last = datetime.fromisoformat(last_reminded)
    except ValueError:
        return True
    if last.tzinfo is None and now.tzinfo is not None:
        last = last.replace(tzinfo=now.tzinfo)
    if last < since:
        return True
    return (now - last).days >= SILENT_EVERY_DAYS


def route_to_recipients(
    lead_id: Optional[int], active_leads: set[int], hor_ids: list[int]
) -> list[int]:
    """Adresaci sprawy rekrutacji: aktywny DL, a bez niego Head of Recruitment.

    Ta sama reguła co ``notification_triggers._delivery_lead_targets``
    (runda 6 audytu): „Requesty do decyzji” szły na ``Job.delivery_lead_id``
    bez sprawdzenia ``is_active``, więc `emit` odrzucał odbiorcę, dzwonek
    przepadał, a przypomnienie „Klient milczy” nie zapisywało się w mapie
    i próbowało od nowa każdego ranka — donikąd.
    """
    if lead_id is not None and lead_id in active_leads:
        return [lead_id]
    return list(hor_ids)


async def _recipient_router(db: AsyncSession, lead_ids: set[int]):
    from app.models.user import User, UserRole  # noqa: PLC0415

    ids = {i for i in lead_ids if i is not None}
    active = (
        set(
            (
                await db.scalars(
                    select(User.id).where(User.id.in_(ids), User.is_active.is_(True))
                )
            ).all()
        )
        if ids
        else set()
    )
    hor: Optional[list[int]] = None

    async def route(lead_id: Optional[int]) -> list[int]:
        nonlocal hor
        if lead_id is not None and lead_id in active:
            return [lead_id]
        if hor is None:
            hor = sorted(
                (
                    await db.scalars(
                        select(User.id).where(
                            User.roles.contains([UserRole.head_of_recruitment.value]),
                            User.is_active.is_(True),
                        )
                    )
                ).all()
            )
        return route_to_recipients(lead_id, active, hor)

    return route


async def _review_notices(
    db: AsyncSession,
    *,
    now: datetime,
    reminded: Optional[dict[str, str]] = None,
) -> tuple[int, dict[str, str]]:
    """Zwraca (liczba wysłanych, nowa mapa ``job_id → ostatnie przypomnienie``).

    Adresat wpisu to aktywny Delivery Lead rekrutacji, a bez niego (brak DL-a
    albo konto nieaktywne) Head of Recruitment — ``route_to_recipients``.
    """
    from app.models.recruitment_pipeline import CandidateStage  # noqa: PLC0415
    from app.services.notification_triggers import emit  # noqa: PLC0415

    day = now - timedelta(hours=24)
    rows = (
        await db.execute(
            select(
                Job.id,
                Job.delivery_lead_id,
                Job.work_state,
                Job.created_at,
                Job.work_state_changed_at,
            ).where(
                Job.status == JobStatus.published,
                or_(
                    and_(Job.work_state == "to_review", Job.created_at >= day),
                    Job.work_state == "client_silent",
                ),
            )
        )
    ).all()
    reminded = dict(reminded or {})
    silent_ids = {
        job_id for job_id, _lead, state, _c, _ch in rows if state == "client_silent"
    }
    # Mapa trzyma tylko requesty, które nadal milczą — nie rośnie bez końca.
    reminded = {
        k: v for k, v in reminded.items() if k.isdigit() and int(k) in silent_ids
    }
    per_lead: dict[int, dict[str, int]] = {}
    silent_by_lead: dict[int, list[int]] = {}
    route = await _recipient_router(db, {lead for _j, lead, *_ in rows})
    for job_id, lead_id, state, created, changed in rows:
        if state == "client_silent":
            if not silent_reminder_due(
                now, changed or created, reminded.get(str(job_id))
            ):
                continue
        for recipient in await route(lead_id):
            if state == "client_silent":
                silent_by_lead.setdefault(recipient, []).append(job_id)
            bucket = per_lead.setdefault(recipient, {"new": 0, "silent": 0, "stale": 0})
            bucket["new" if state == "to_review" else "silent"] += 1

    # W poniedziałek: „Szukamy” bez żadnego ruchu rekrutera od 30 dni.
    if is_stale_check_day(now):
        month = now - timedelta(days=30)
        last_move = (
            select(CandidateStage.job_id)
            .where(
                CandidateStage.moved_at >= month, CandidateStage.moved_by.is_not(None)
            )
            .distinct()
        )
        stale = (
            await db.execute(
                select(Job.delivery_lead_id).where(
                    Job.status == JobStatus.published,
                    Job.work_state == "searching",
                    Job.champion_found_at.is_(None),
                    or_(
                        Job.work_state_changed_at.is_(None),
                        Job.work_state_changed_at <= month,
                    ),
                    Job.id.not_in(last_move),
                )
            )
        ).all()
        stale_route = await _recipient_router(db, {lead for (lead,) in stale})
        for (lead_id,) in stale:
            for recipient in await stale_route(lead_id):
                bucket = per_lead.setdefault(
                    recipient, {"new": 0, "silent": 0, "stale": 0}
                )
                bucket["stale"] += 1

    sent = 0
    for lead_id, bucket in sorted(per_lead.items()):
        parts: list[Optional[str]] = [
            f"Nowe do przejrzenia: {bucket['new']}." if bucket["new"] else None,
            (
                f"Klient milczy od 2 tygodni lub dłużej: {bucket['silent']} — "
                "sprawdź, czy się odezwał."
            )
            if bucket["silent"]
            else None,
            (f"„Szukamy” bez pracy od miesiąca: {bucket['stale']} — czy nadal szukamy?")
            if bucket["stale"]
            else None,
        ]
        created = await emit(
            db,
            user_id=lead_id,
            title="Requesty do decyzji",
            message=" ".join(p for p in parts if p),
            ntype=NotificationType.request_review_needed,
            related_entity_type="user",
            related_entity_id=lead_id,
            link=REVIEW_LINK,
        )
        sent += int(created is not None)
        if created is not None:
            for job_id in silent_by_lead.get(lead_id, []):
                reminded[str(job_id)] = now.isoformat()
    return sent, reminded


async def send_morning_notices(
    db: AsyncSession,
    *,
    now: datetime,
    mode: str,
    silent_reminded: Optional[dict[str, str]] = None,
) -> dict:
    """Liczniki + ``silent_reminded`` (do zapisania w ``stats`` automatu)."""
    assignments = await _assignment_notices(db, now=now) if mode == "auto" else 0
    reviews, reminded = await _review_notices(db, now=now, reminded=silent_reminded)
    return {
        "assignment_notices": assignments,
        "review_notices": reviews,
        "silent_reminded": reminded,
    }


async def _head_of_recruitment_ids(db: AsyncSession) -> list[int]:
    from app.models.user import User, UserRole  # noqa: PLC0415

    role = UserRole.head_of_recruitment
    return sorted(
        (
            await db.scalars(
                select(User.id).where(
                    User.is_active.is_(True),
                    or_(User.role == role, User.roles.contains([role.value])),
                )
            )
        ).all()
    )


async def send_proposal_notices(
    db: AsyncSession, *, new_proposals: bool = False
) -> int:
    """Dzwonek „propozycje czekają” — JEDEN wpis dziennie na Head of Recruitment.

    Liczba pochodzi z tego samego źródła co panel na pulpicie
    (``request_allocation_proposals.load_pending``), więc dzwonek nie obiecuje
    wierszy, których na pulpicie nie ma. Pierwsza propozycja dnia tworzy wpis
    (``emit``: bramka odbiorcy + dobowy dedup); potem ten sam wpis dostaje nową
    liczbę i wraca jako nieprzeczytany — gdy liczba się zmieniła albo gdy
    przebieg właśnie dołożył propozycję (``new_proposals``; jedna zaakceptowana
    i jedna nowa dają tę samą liczbę, a to nadal nowa sprawa). Poranne
    przypomnienie z niezmienioną liczbą nie dzwoni drugi raz.
    Zwraca liczbę nowych albo podbitych wpisów.
    """
    from app.core.scheduling import business_today  # noqa: PLC0415
    from app.services.notification_triggers import emit  # noqa: PLC0415
    from app.services.request_allocation_proposals import (  # noqa: PLC0415
        load_pending,
    )

    pending = len(await load_pending(db))
    if not pending:
        return 0
    ntype = NotificationType.request_allocation_proposals
    title = f"Propozycje przydziału do akceptacji: {pending}"
    today = business_today(settings.BUSINESS_TZ)
    sent = 0
    for user_id in await _head_of_recruitment_ids(db):
        created = await emit(
            db,
            user_id=user_id,
            title=title,
            message=PROPOSALS_MESSAGE,
            ntype=ntype,
            related_entity_type="user",
            related_entity_id=user_id,
            link=PROPOSALS_LINK,
        )
        if created is not None:
            sent += 1
            continue
        # Dzisiejszy wpis już jest (albo odbiorca nie ma dostępu — wtedy nie
        # ma czego podbić).
        existing = await db.scalar(
            select(Notification)
            .where(
                Notification.user_id == user_id,
                Notification.notification_type == ntype,
                Notification.related_entity_type == "user",
                Notification.related_entity_id == user_id,
                func.date(func.timezone(settings.BUSINESS_TZ, Notification.created_at))
                == today,
            )
            .order_by(Notification.created_at.desc())
            .limit(1)
        )
        if existing is not None and (new_proposals or existing.title != title):
            existing.title = title
            existing.is_read = False
            # ``emit`` wysyła zdarzenie tylko przy NOWYM wpisie. Po odrzuceniu
            # propozycji automat proponuje następną osobę jeszcze tego samego
            # dnia, czyli podbija ten wpis — otwarty pulpit ma ją pokazać od
            # razu, nie po kilku minutach odpytywania.
            queue_ws_notification(
                db,
                user_id=user_id,
                event_payload={
                    "type": "notification",
                    "data": {
                        "id": existing.id,
                        "title": title,
                        "message": existing.message,
                        "link": existing.link,
                        "notification_type": ntype.value,
                        "created_at": datetime.now(timezone.utc).isoformat(),
                    },
                },
                row=existing,
            )
            sent += 1
    return sent
