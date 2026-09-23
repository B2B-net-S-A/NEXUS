"""Prepy wymagające uwagi przed rozmową u klienta (0362, miękka bramka).

Trzy powody, każdy na TEJ SAMEJ migawce pary co kroki ekranu „Rozmowy
u klienta” (``interview_cycle.load_snapshots``), więc kolejka, dzwonek
i stepper mówią to samo:

* ``missing`` — brak Prepu 1 albo Prepu 2 przed rozmową w ciągu
  ``WINDOW_DAYS`` (dzwonek dopiero na dobę przed — ``urgent``),
* ``weak`` — odbyty prep z oceną „słaby”,
* ``unrecorded`` — odbyty prep bez transkryptu.

Adresat: organizator prepu (dla brakującego — podpowiadany: Prep 1 → DL
rekrutacji, Prep 2 → rekruter) oraz Head of Recruitment (decyzja Artura
23.09.2026). Nic tu niczego nie blokuje.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.calendar_event import CalendarEvent, EventStatus, EventType
from app.models.candidate import Candidate
from app.models.job import Job
from app.models.user import User, UserRole
from app.services.interview_cycle import (
    PREP_URGENT_HOURS,
    load_snapshots,
    prep_quality,
)

Reason = Literal["missing", "weak", "unrecorded"]
WINDOW_DAYS = 7
MAX_INTERVIEWS = 300
_OVERSIGHT = (UserRole.admin, UserRole.head_of_recruitment)

REASON_LABELS = {
    "missing": "brak prepu",
    "weak": "prep słaby",
    "unrecorded": "prep bez nagrania",
}


@dataclass(frozen=True)
class PrepAttention:
    reason: Reason
    prep_no: int
    candidate_id: int
    job_id: int
    interview_event_id: int
    interview_start: datetime
    prep_event_id: Optional[int]
    owner_id: Optional[int]
    urgent: bool

    @property
    def entity_event_id(self) -> int:
        """Encja powiadomienia: prep (słaby/bez nagrania) albo rozmowa (brak)."""
        return self.prep_event_id or self.interview_event_id


async def load_prep_attention(
    db: AsyncSession, now: datetime, *, days_ahead: int = WINDOW_DAYS
) -> list[PrepAttention]:
    pairs = (
        await db.execute(
            select(CalendarEvent.candidate_id, CalendarEvent.job_id)
            .where(
                CalendarEvent.event_type == EventType.client_interview,
                CalendarEvent.status != EventStatus.cancelled,
                CalendarEvent.candidate_id.isnot(None),
                CalendarEvent.job_id.isnot(None),
                CalendarEvent.start_time > now,
                CalendarEvent.start_time <= now + timedelta(days=days_ahead),
            )
            .distinct()
            .limit(MAX_INTERVIEWS)
        )
    ).all()
    if not pairs:
        return []
    snaps = await load_snapshots(
        db,
        [(c, j) for c, j in pairs],
        window_start=now - timedelta(days=14),
        window_end=now + timedelta(days=days_ahead),
    )
    owners = {
        jid: (dl, rec)
        for jid, dl, rec in (
            await db.execute(
                select(Job.id, Job.delivery_lead_id, Job.recruiter_id).where(
                    Job.id.in_({j for _c, j in pairs})
                )
            )
        ).all()
    }
    out: list[PrepAttention] = []
    for (cid, jid), snap in snaps.items():
        iv = snap.interview
        if iv is None or iv.start <= now:
            continue
        urgent = iv.start - now <= timedelta(hours=PREP_URGENT_HOURS)
        dl, rec = owners.get(jid, (None, None))
        for n in (1, 2):
            ev = snap.prep_slot(n)
            if ev is None:
                reason: Optional[Reason] = "missing"
                owner = (dl or rec) if n == 1 else (rec or dl)
            elif ev.start <= now:
                quality = prep_quality(ev)[1]
                reason = (
                    "weak"
                    if quality == "weak"
                    else "unrecorded"
                    if quality == "unrecorded"
                    else None
                )
                owner = ev.owner_id
            else:
                reason = None
                owner = None
            if reason is None:
                continue
            out.append(
                PrepAttention(
                    reason=reason,
                    prep_no=n,
                    candidate_id=cid,
                    job_id=jid,
                    interview_event_id=iv.id,
                    interview_start=iv.start,
                    prep_event_id=ev.id if ev is not None else None,
                    owner_id=owner,
                    urgent=urgent,
                )
            )
    return sorted(out, key=lambda a: (not a.urgent, a.interview_start, a.prep_no))


def for_user(items: list[PrepAttention], user: User) -> list[PrepAttention]:
    """Organizator widzi swoje, HoR i admin — wszystkie."""
    if user.has_any_role(*_OVERSIGHT):
        return items
    return [a for a in items if a.owner_id == user.id]


async def labels(
    db: AsyncSession, items: list[PrepAttention]
) -> tuple[dict[int, str], dict[int, str]]:
    """Nazwiska kandydatów i tytuły rekrutacji dla wierszy kolejki."""
    cand_ids = {a.candidate_id for a in items}
    job_ids = {a.job_id for a in items}
    names: dict[int, str] = {}
    if cand_ids:
        for cid, first, last in (
            await db.execute(
                select(Candidate.id, Candidate.name, Candidate.lastname).where(
                    Candidate.id.in_(cand_ids)
                )
            )
        ).all():
            names[cid] = " ".join(p for p in (first, last) if p) or f"Kandydat #{cid}"
    titles: dict[int, str] = {}
    if job_ids:
        for jid, title in (
            await db.execute(select(Job.id, Job.title).where(Job.id.in_(job_ids)))
        ).all():
            titles[jid] = title or f"Rekrutacja #{jid}"
    return names, titles
