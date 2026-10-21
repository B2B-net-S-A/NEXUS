"""Zamknięte rekrutacje w podziale na grupy hit ratio — lista kontrolna (21.10.2026).

Decyzja Artura 21.10.2026: wyłączenie rekrutacji z hit ratio („Nie liczy się”)
wymaga uzasadnienia, a kontrola jest po fakcie — Insights pokazuje każde
wyłączenie z uzasadnieniem i osobą, oraz zamknięcia bez powodu („Inny”, PATCH
statusu), które czekają na przegląd i do tego czasu liczą się jak przegrane.

Grupy wiersza są tą samą regułą co wzory hit ratio (`hit_ratio_scope`):
wygrana = zatrudnienie od nas, nie liczy się = powód z grupy neutralnej,
do przejrzenia = `other` / brak powodu, przegrana = reszta.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.activity import Activity
from app.models.client import Client
from app.models.job import Job, JobStatus
from app.models.user import User
from app.services.client_identity import client_display_name_expression
from app.services.hit_ratio_scope import close_reason_group
from app.services.job_fill import placements_by_job

_CLOSE_ACTIONS = ("closed", "close_reason_changed")


def _row_group(reason, hired: bool) -> str:
    group = close_reason_group(reason)
    if group == "neutral":
        return "neutral"
    if hired:
        return "won"
    if group == "unreviewed":
        return "unreviewed"
    return "lost"


async def hit_ratio_closures(
    db: AsyncSession, *, start: datetime, end: Optional[datetime]
) -> dict:
    """Liczby grup i wiersze „nie liczy się” oraz „do przejrzenia” w oknie."""
    effective_name = client_display_name_expression()
    q = (
        select(
            Job.id,
            Job.title,
            Job.close_reason,
            Job.close_notes,
            Job.closed_at,
            Job.duplicate_of_job_id,
            Job.delivery_lead_id,
            effective_name.label("client_name"),
        )
        .join(Client, Job.client_id == Client.id)
        .where(Job.status == JobStatus.closed, Job.closed_at >= start)
        .order_by(Job.closed_at.desc())
    )
    if end is not None:
        q = q.where(Job.closed_at < end)
    rows = (await db.execute(q)).all()
    job_ids = [r.id for r in rows]
    hired = await placements_by_job(db, job_ids)

    # Kto zamknął albo ostatni zmienił powód — z historii rekrutacji.
    closed_by: dict[int, tuple[Optional[int], datetime]] = {}
    if job_ids:
        acts = (
            await db.execute(
                select(Activity.entity_id, Activity.user_id, Activity.created_at)
                .where(
                    Activity.entity_type == "job",
                    Activity.entity_id.in_(job_ids),
                    Activity.action.in_(_CLOSE_ACTIONS),
                )
                .order_by(Activity.created_at)
            )
        ).all()
        for a in acts:
            closed_by[int(a.entity_id)] = (a.user_id, a.created_at)
    user_ids = {uid for uid, _ in closed_by.values() if uid is not None}
    user_ids |= {r.delivery_lead_id for r in rows if r.delivery_lead_id}
    names: dict[int, str] = {}
    if user_ids:
        names = {
            u.id: u.name
            for u in (
                await db.execute(
                    select(User.id, User.name).where(User.id.in_(user_ids))
                )
            ).all()
        }

    counts = {"won": 0, "lost": 0, "neutral": 0, "unreviewed": 0}
    listed: dict[str, list[dict]] = {"neutral": [], "unreviewed": []}
    for r in rows:
        group = _row_group(r.close_reason, bool(hired.get(r.id)))
        counts[group] += 1
        if group not in listed:
            continue
        actor_id, _ = closed_by.get(r.id, (None, None))
        listed[group].append(
            {
                "job_id": r.id,
                "title": r.title,
                "client_name": r.client_name,
                "close_reason": r.close_reason.value if r.close_reason else None,
                "close_notes": r.close_notes,
                "duplicate_of_job_id": r.duplicate_of_job_id,
                "closed_at": r.closed_at.isoformat() if r.closed_at else None,
                "closed_by_name": names.get(actor_id) if actor_id else None,
                "delivery_lead_name": names.get(r.delivery_lead_id)
                if r.delivery_lead_id
                else None,
            }
        )
    counted = counts["won"] + counts["lost"] + counts["unreviewed"]
    return {
        "since": start.isoformat(),
        "counts": counts,
        "hit_ratio": round(counts["won"] / counted * 100, 1) if counted else None,
        "neutral": listed["neutral"],
        "unreviewed": listed["unreviewed"],
    }
