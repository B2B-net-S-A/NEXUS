"""Akcje zbiorcze w Tabeli Dzwonienia (decyzja Artura 27.11.2026, wariant A).

Zaznaczone rekordy kampanii: „Przypisz osobie”, „Przenieś do kampanii”, „Usuń z listy”
i „Cofnij” po usunięciu. Jedna transakcja na całą paczkę, pod tą samą blokadą co import
listy, bo przeniesienie i import pytają o to samo: czy firma jest już w kampanii.

Czego akcja nie rusza (liczone w ``skipped`` i pokazane przed zapisem):

- ``not_on_list``: rekord szansy (bez kampanii), sprzeciw albo rekord już usunięty.
  Tabela takich nie daje do zaznaczenia, ale API przyjmuje dowolne id;
- ``meeting_booked``: „Umówione spotkanie” ma szansę w lejku, więc nie znika
  z listy ani nie przechodzi do innej kampanii (przypisać można);
- ``already_in_campaign``: przy przeniesieniu firma ma już rekord w kampanii docelowej
  (także usunięty, jak w bramce importu), albo to ta sama kampania.

Usunięcie jest miękkie (``removed_at``): historia telefonów i karta firmy zostają.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Optional

from fastapi import HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.sales import SalesCallCampaign, SalesCallRecord
from app.services.sales.calling import BULK_LIMIT, MEETING_BOOKED, TABLE_STATES
from app.services.sales.calling_import import LOCK_KEY

NOT_ON_LIST = "not_on_list"
ALREADY_IN_CAMPAIGN = "already_in_campaign"

CAMPAIGN_DETAIL = "Wybierz kampanię, do której przenieść rekordy."
CAMPAIGN_NOT_FOUND = "Nie ma takiej kampanii albo jest zarchiwizowana."
ASSIGNEE_REQUIRED = "Wybierz osobę, której przypisać rekordy."

BulkKind = Literal["assign", "move", "remove", "restore"]


class BulkRequest(BaseModel):
    action: BulkKind
    record_ids: list[int] = Field(min_length=1, max_length=BULK_LIMIT)
    #: „Przypisz osobie”: osoba z „Sprzedaż: edycja” (sprawdza trasa).
    assignee_user_id: Optional[int] = Field(default=None, ge=1)
    #: „Przenieś do kampanii”.
    campaign_id: Optional[int] = Field(default=None, ge=1)
    #: Tylko policz, co się stanie (okno przed zapisem).
    dry_run: bool = False


@dataclass(frozen=True)
class BulkResult:
    #: Id rekordów, które akcja zmieniła (albo zmieni przy ``dry_run``); „Cofnij” ich używa.
    done: list[int]
    skipped: dict[str, int] = field(default_factory=dict)


async def _target_campaign(db: AsyncSession, campaign_id: Optional[int]) -> int:
    if campaign_id is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, detail=CAMPAIGN_DETAIL
        )
    found = await db.scalar(
        select(SalesCallCampaign.id).where(
            SalesCallCampaign.id == campaign_id, SalesCallCampaign.archived_at.is_(None)
        )
    )
    if found is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, detail=CAMPAIGN_NOT_FOUND
        )
    return int(found)


async def apply_bulk(
    db: AsyncSession,
    request: BulkRequest,
    *,
    assignee_id: Optional[int],
    user_id: int,
    now: datetime,
) -> BulkResult:
    """Wykonuje (albo przy ``dry_run`` tylko liczy) akcję na rekordach; bez commita.

    ``assignee_id`` to osoba sprawdzona przez trasę (wymagana przy ``assign``).
    """

    if request.action == "assign" and assignee_id is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, detail=ASSIGNEE_REQUIRED
        )
    target = (
        await _target_campaign(db, request.campaign_id)
        if request.action == "move"
        else None
    )
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": LOCK_KEY}
    )
    ids = sorted(set(request.record_ids))
    records = list(
        (
            await db.execute(
                select(SalesCallRecord)
                .where(SalesCallRecord.id.in_(ids))
                .order_by(SalesCallRecord.id)
                .with_for_update()
            )
        ).scalars()
    )
    skipped: Counter[str] = Counter()
    skipped[NOT_ON_LIST] += len(ids) - len(records)

    taken: set[int] = set()
    if target is not None:
        taken = set(
            (
                await db.execute(
                    select(SalesCallRecord.company_id).where(
                        SalesCallRecord.campaign_id == target
                    )
                )
            ).scalars()
        )

    done: list[int] = []
    for record in records:
        removed = record.removed_at is not None
        listed = (
            record.campaign_id is not None
            and record.state in TABLE_STATES
            and (removed if request.action == "restore" else not removed)
        )
        if not listed:
            skipped[NOT_ON_LIST] += 1
            continue
        if request.action in ("move", "remove") and record.state == MEETING_BOOKED:
            skipped[MEETING_BOOKED] += 1
            continue
        if request.action == "move":
            if record.campaign_id == target or record.company_id in taken:
                skipped[ALREADY_IN_CAMPAIGN] += 1
                continue
            # Dwa zaznaczone rekordy tej samej firmy: do kampanii przechodzi pierwszy.
            taken.add(record.company_id)
        done.append(record.id)
        if request.dry_run:
            continue
        if request.action == "assign":
            record.assigned_user_id = assignee_id
        elif request.action == "move":
            record.campaign_id = target
        elif request.action == "remove":
            record.removed_at = now
            record.removed_by_user_id = user_id
        else:
            record.removed_at = None
            record.removed_by_user_id = None
    if not request.dry_run:
        await db.flush()
    return BulkResult(
        done=done, skipped={reason: n for reason, n in skipped.items() if n}
    )
