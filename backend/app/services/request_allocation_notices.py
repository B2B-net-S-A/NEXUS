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

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.job import Job, JobStatus
from app.models.job_work_assignment import JobWorkAssignment
from app.models.notification import NotificationType
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
                Job.title,
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


def _every_two_weeks(now: datetime, since: Optional[datetime]) -> bool:
    """„Klient milczy” przypomina się co 14 dni, nie codziennie."""
    if since is None:
        return False
    days = (now - since).days
    return days >= 14 and days % 14 == 0


async def _review_notices(db: AsyncSession, *, now: datetime) -> int:
    from app.models.recruitment_pipeline import CandidateStage  # noqa: PLC0415
    from app.services.notification_triggers import emit  # noqa: PLC0415

    day = now - timedelta(hours=24)
    rows = (
        await db.execute(
            select(
                Job.delivery_lead_id,
                Job.work_state,
                Job.created_at,
                Job.work_state_changed_at,
            ).where(
                Job.status == JobStatus.published,
                Job.delivery_lead_id.is_not(None),
                or_(
                    and_(Job.work_state == "to_review", Job.created_at >= day),
                    Job.work_state == "client_silent",
                ),
            )
        )
    ).all()
    per_lead: dict[int, dict[str, int]] = {}
    for lead_id, state, created, changed in rows:
        if state == "client_silent" and not _every_two_weeks(now, changed or created):
            continue
        bucket = per_lead.setdefault(lead_id, {"new": 0, "silent": 0, "stale": 0})
        bucket["new" if state == "to_review" else "silent"] += 1

    # W poniedziałek: „Szukamy” bez żadnego ruchu rekrutera od 30 dni.
    if now.weekday() == 0:
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
                    Job.delivery_lead_id.is_not(None),
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
        for (lead_id,) in stale:
            bucket = per_lead.setdefault(lead_id, {"new": 0, "silent": 0, "stale": 0})
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
    return sent


async def send_morning_notices(
    db: AsyncSession, *, now: datetime, mode: str
) -> dict[str, int]:
    assignments = await _assignment_notices(db, now=now) if mode == "auto" else 0
    reviews = await _review_notices(db, now=now)
    return {"assignment_notices": assignments, "review_notices": reviews}
