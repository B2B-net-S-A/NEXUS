"""Poranne powiadomienia automatu przydziału (raz dziennie, o ``review_time``).

* ``request_assignment_changed`` — JEDEN wpis na osobę: „Od dziś: X, Y.
  Zwolnione: Z (Mamy championa)”. Tylko w trybie ``auto``: propozycje trybu
  podglądu nikogo do niczego nie zobowiązują, więc nikogo o nich nie budzimy.
* ``request_review_needed`` — JEDEN wpis na Delivery Leada: nowe requesty
  z Traffita „Do przejrzenia”, „Klient milczy” od 14+ dni, „Szukamy” bez
  pracy od 30+ dni. Link prowadzi do „Porządku w requestach”.

Oba idą przez ``notification_triggers.emit`` (dedup dobowy, sprawdzenie
odbiorcy). Treść bez nazwisk kandydatów — same tytuły requestów.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.job import Job, JobStatus
from app.models.job_work_assignment import JobWorkAssignment
from app.models.notification import NotificationType
from app.services.job_working_title import job_display_title_expr
from app.services.request_allocation_plan import RELEASE_REASONS

REVIEW_LINK = "/jobs/review-states"
BOARD_LINK = "/dashboard"
MAX_TITLES = 4


def _titles(titles: list[str]) -> str:
    shown = ", ".join(titles[:MAX_TITLES])
    rest = len(titles) - MAX_TITLES
    return shown + (f" i {rest} więcej" if rest > 0 else "")


async def _assignment_notices(db: AsyncSession, *, now: datetime) -> int:
    from app.services.notification_triggers import emit  # noqa: PLC0415

    since = now - timedelta(hours=24)
    rows = (
        await db.execute(
            select(
                JobWorkAssignment.user_id,
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
    per_user: dict[int, dict[str, list[str]]] = {}
    for user_id, state, _assigned, _released, reason, title in rows:
        bucket = per_user.setdefault(user_id, {"new": [], "gone": []})
        if state == "active":
            bucket["new"].append(title)
        else:
            label = RELEASE_REASONS.get(reason or "", "")
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
