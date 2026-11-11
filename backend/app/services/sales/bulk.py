"""Akcje na wielu szansach naraz z listy Szans (decyzja Artura 11.11.2026, „mniej kliknięć”).

Każda szansa przechodzi te same reguły co pojedyncza zmiana z karty:

* krok to zadanie u opiekuna szansy (albo u klikającego, gdy opiekuna nie ma lub jest nieaktywny),
  bez dotyku szansy, bo sam zaplanowany krok dotykiem nie jest;
* opiekuna zmienia obecny opiekun albo admin (``ensure_owner_or_admin``), a otwarte zadania
  poprzednika idą za szansą (``owner_tasks.hand_over``);
* zamknięcie to etap przegranej z lejka tej szansy przez ``apply_stage``, z opcjonalnym powodem.

Szansa, której reguła nie przepuszcza, nie wywraca całej akcji: trafia do ``skipped``
z powodem, a reszta się zapisuje. Commit robi wywołujący.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.sales import SalesActivity, SalesOpportunity, SalesPipelineStage
from app.models.user import User
from app.services.sales import history, offer_steps, owner_tasks
from app.services.sales.lifecycle import apply_stage

#: Ile szans naraz: tyle mieści lista na jednej stronie z zapasem.
MAX_IDS = 200

NOT_FOUND = "nie ma takiej szansy"
ARCHIVED = "szansa jest w archiwum"
CLOSED = "szansa jest już zamknięta"
NOT_OWNER = "zmienia ją tylko opiekun albo admin"
OTHER_PIPELINE = "szansa jest w innym lejku"


@dataclass(frozen=True)
class Skip:
    id: int
    title: Optional[str]
    reason: str


@dataclass(frozen=True)
class BulkResult:
    done: list[int]
    skipped: list[Skip]


async def load(
    db: AsyncSession, ids: list[int]
) -> tuple[list[SalesOpportunity], list[Skip]]:
    """Szanse w kolejności z żądania; brakujące od razu jako pominięte."""

    unique = list(dict.fromkeys(ids))
    rows = (
        await db.execute(
            select(SalesOpportunity).where(SalesOpportunity.id.in_(unique))
        )
    ).scalars()
    by_id = {opp.id: opp for opp in rows}
    found = [by_id[i] for i in unique if i in by_id]
    missing = [
        Skip(id=i, title=None, reason=NOT_FOUND) for i in unique if i not in by_id
    ]
    return found, missing


def _blocked(opp: SalesOpportunity, *, needs_open: bool) -> Optional[str]:
    if opp.archived_at is not None:
        return ARCHIVED
    if needs_open and opp.status != "open":
        return CLOSED
    return None


async def _active_owner(db: AsyncSession, owner_id: Optional[int]) -> Optional[int]:
    if owner_id is None:
        return None
    return await db.scalar(
        select(User.id).where(User.id == owner_id, User.is_active.is_(True))
    )


async def plan_step(
    db: AsyncSession,
    opportunities: list[SalesOpportunity],
    *,
    subject: str,
    due_at: datetime,
    user_id: int,
) -> BulkResult:
    done: list[int] = []
    skipped: list[Skip] = []
    for opp in opportunities:
        reason = _blocked(opp, needs_open=True)
        if reason:
            skipped.append(Skip(opp.id, opp.title, reason))
            continue
        db.add(
            SalesActivity(
                kind="task",
                subject=subject,
                due_at=due_at,
                company_id=opp.company_id,
                opportunity_id=opp.id,
                created_by_user_id=user_id,
                assignee_user_id=await _active_owner(db, opp.owner_user_id) or user_id,
            )
        )
        done.append(opp.id)
    return BulkResult(done, skipped)


async def change_owner(
    db: AsyncSession,
    opportunities: list[SalesOpportunity],
    *,
    new_owner_id: int,
    user: User,
    is_admin: bool,
) -> BulkResult:
    done: list[int] = []
    skipped: list[Skip] = []
    for opp in opportunities:
        reason = _blocked(opp, needs_open=False)
        if reason is None and not (opp.owner_user_id in (None, user.id) or is_admin):
            reason = NOT_OWNER
        if reason:
            skipped.append(Skip(opp.id, opp.title, reason))
            continue
        if opp.owner_user_id == new_owner_id:
            done.append(opp.id)
            continue
        previous = opp.owner_user_id
        before = history.snapshot(opp)
        opp.owner_user_id = new_owner_id
        history.record_changes(db, opp, before, user_id=user.id)
        await owner_tasks.hand_over(
            db, opp.id, previous_owner_id=previous, new_owner_id=new_owner_id
        )
        done.append(opp.id)
    return BulkResult(done, skipped)


async def close_lost(
    db: AsyncSession,
    opportunities: list[SalesOpportunity],
    *,
    stage_key: str,
    lost_reason: Optional[str],
    user_id: int,
    now: datetime,
) -> BulkResult:
    """Etap przegranej szukamy po kluczu w lejku każdej szansy, bo lejki mają własne id etapów."""

    done: list[int] = []
    skipped: list[Skip] = []
    stages_by_pipeline: dict[int, list[SalesPipelineStage]] = {}
    reason_text = (lost_reason or "").strip() or None
    for opp in opportunities:
        reason = _blocked(opp, needs_open=True)
        if reason:
            skipped.append(Skip(opp.id, opp.title, reason))
            continue
        if opp.pipeline_id not in stages_by_pipeline:
            stages_by_pipeline[opp.pipeline_id] = list(
                (
                    await db.execute(
                        select(SalesPipelineStage)
                        .where(SalesPipelineStage.pipeline_id == opp.pipeline_id)
                        .order_by(SalesPipelineStage.position, SalesPipelineStage.id)
                    )
                ).scalars()
            )
        stages = stages_by_pipeline[opp.pipeline_id]
        stage = next(
            (s for s in stages if s.key == stage_key and s.outcome == "lost"), None
        )
        if stage is None:
            skipped.append(Skip(opp.id, opp.title, OTHER_PIPELINE))
            continue
        before = history.snapshot(opp)
        apply_stage(opp, stage, stages, now=now)
        await offer_steps.schedule_on_entry(
            db, opp, stage.key, user_id=user_id, now=now
        )
        if reason_text:
            opp.lost_reason = reason_text
        history.record_changes(db, opp, before, user_id=user_id)
        done.append(opp.id)
    return BulkResult(done, skipped)
