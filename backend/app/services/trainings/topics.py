"""„Szukamy trenerów” (0698): tematy, na które TCM szuka prowadzącego.

Do S4 konsultant zgłaszał się na trenera w ciemno, nie wiedząc, na jakie tematy jest
zapotrzebowanie. TCM publikuje temat w NEXUSIE, panel konsultanta pokazuje otwarte
tematy, a „Zgłoś się na temat” dopisuje temat do zgłoszenia trenera
(``cp_trainer_applications.topic_request_ids``) i do opisu jego sprawy. Zgłoszenie
jest jedno na konsultanta, więc temat to dopisek, nie osobne zgłoszenie.

Funkcje nie robią commita; transakcję kończy trasa.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.consultant_panel import CpTrainerApplication
from app.models.training import TrainingTopicRequest
from app.services.trainings.errors import TrainingError
from app.services.trainings_schema import (
    TITLE_MAX,
    TOPIC_DESCRIPTION_MAX,
    TRAINER_SHORT_MAX,
)

NOT_FOUND = "Nie ma takiego tematu."
CLOSED = "Ten temat jest już zamknięty."


def _clean(value: Optional[str], limit: int) -> str:
    return (value or "").replace("\x00", "").strip()[:limit]


def public_row(topic: TrainingTopicRequest, *, applied: bool) -> dict[str, Any]:
    return {
        "id": topic.id,
        "title": topic.title,
        "description": topic.description,
        "audience": topic.audience,
        "applied": applied,
    }


async def _applicants(db: AsyncSession) -> dict[int, int]:
    counts: dict[int, int] = {}
    for ids in (
        await db.scalars(
            select(CpTrainerApplication.topic_request_ids).where(
                func.jsonb_array_length(CpTrainerApplication.topic_request_ids) > 0
            )
        )
    ).all():
        for topic_id in ids or []:
            if isinstance(topic_id, int):
                counts[topic_id] = counts.get(topic_id, 0) + 1
    return counts


async def staff_list(db: AsyncSession) -> list[dict[str, Any]]:
    rows = (
        await db.scalars(
            select(TrainingTopicRequest).order_by(
                TrainingTopicRequest.status.desc(),  # open przed closed
                TrainingTopicRequest.created_at.desc(),
            )
        )
    ).all()
    counts = await _applicants(db)
    return [
        {
            "id": topic.id,
            "title": topic.title,
            "description": topic.description,
            "audience": topic.audience,
            "status": topic.status,
            "created_at": topic.created_at.isoformat() if topic.created_at else None,
            "closed_at": topic.closed_at.isoformat() if topic.closed_at else None,
            "applicants": counts.get(topic.id, 0),
        }
        for topic in rows
    ]


def _apply(
    topic: TrainingTopicRequest, *, title: str, description: str, audience: str
) -> None:
    clean_title = _clean(title, TITLE_MAX)
    if not clean_title:
        raise TrainingError(422, "Podaj temat szkolenia.", "title_required")
    topic.title = clean_title
    topic.description = _clean(description, TOPIC_DESCRIPTION_MAX)
    topic.audience = _clean(audience, TRAINER_SHORT_MAX)


async def create(
    db: AsyncSession, *, title: str, description: str, audience: str, actor_id: int
) -> TrainingTopicRequest:
    topic = TrainingTopicRequest(status="open", created_by=actor_id)
    _apply(topic, title=title, description=description, audience=audience)
    db.add(topic)
    await db.flush()
    return topic


async def update(
    db: AsyncSession,
    topic_id: int,
    *,
    title: str,
    description: str,
    audience: str,
    is_open: bool,
    now: datetime,
) -> TrainingTopicRequest:
    topic = await db.get(TrainingTopicRequest, topic_id, with_for_update=True)
    if topic is None:
        raise TrainingError(404, NOT_FOUND, "topic_not_found")
    _apply(topic, title=title, description=description, audience=audience)
    if is_open and topic.status != "open":
        topic.status, topic.closed_at = "open", None
    elif not is_open and topic.status == "open":
        topic.status, topic.closed_at = "closed", now
    await db.flush()
    return topic


async def open_topics(db: AsyncSession, applied_ids: list[Any]) -> list[dict[str, Any]]:
    rows = (
        await db.scalars(
            select(TrainingTopicRequest)
            .where(TrainingTopicRequest.status == "open")
            .order_by(TrainingTopicRequest.created_at.desc())
            .limit(30)
        )
    ).all()
    mine = set(applied_ids or [])
    return [public_row(topic, applied=topic.id in mine) for topic in rows]


async def titles(db: AsyncSession, ids: list[Any]) -> list[str]:
    clean = [i for i in ids or [] if isinstance(i, int)]
    if not clean:
        return []
    rows = (
        await db.scalars(
            select(TrainingTopicRequest).where(TrainingTopicRequest.id.in_(clean))
        )
    ).all()
    by_id = {topic.id: topic.title for topic in rows}
    return [by_id[i] for i in clean if i in by_id]


async def toggle(
    db: AsyncSession, application: CpTrainerApplication, topic_id: int, *, join: bool
) -> None:
    """Dopisuje temat do zgłoszenia albo go z niego zdejmuje."""

    current = [i for i in application.topic_request_ids or [] if isinstance(i, int)]
    if join:
        topic = await db.get(TrainingTopicRequest, topic_id)
        if topic is None:
            raise TrainingError(404, NOT_FOUND, "topic_not_found")
        if topic.status != "open":
            raise TrainingError(409, CLOSED, "topic_closed")
        if topic_id not in current:
            current.append(topic_id)
    else:
        current = [i for i in current if i != topic_id]
    # Nowa lista, nie mutacja: JSONB bez MutableList nie zauważy zmiany w miejscu.
    application.topic_request_ids = current
    await db.flush()
