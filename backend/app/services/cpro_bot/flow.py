"""Kiedy bot Cpro dostaje karty: pętla, „Ponów botem” i próba skryptem.

* Jeden bieg naraz: bot wypełnia formularze po kolei, a dwa biegi mogłyby
  wrzucić tę samą osobę dwa razy.
* Karty bez braków, których stan na to pozwala (``runs.due_for_bot``),
  najstarsze w kolejce pierwsze, najwyżej ``MAX_ITEMS_PER_RUN``.
* „Ponów botem” i skrypt próby biorą wskazane karty niezależnie od stanu,
  ale nigdy karty z brakami ani karty już wysłanej przez bota.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Iterable, Optional

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.cpro_bot import CproBotRun
from app.services.cpro_bot import items as bot_items
from app.services.cpro_bot import runs


def _cards(chosen: list[bot_items.BotItem]) -> dict[str, dict]:
    return {
        str(item.stage_id): {
            "candidate_id": item.candidate_id,
            "job_id": item.job_id,
            "target_stage_def_id": item.target_stage_def_id,
            "process_state_version": item.process_state_version,
            "cv_stage_id": item.cv.candidate_stage_id if item.cv else None,
        }
        for item in chosen
    }


async def start_for(
    db: AsyncSession,
    chosen: list[bot_items.BotItem],
    *,
    now: datetime,
    submit: bool = True,
    requested_by_user_id: Optional[int] = None,
    client: Optional[httpx.AsyncClient] = None,
) -> Optional[CproBotRun]:
    ready = [item for item in chosen if item.payload is not None]
    if not ready:
        return None
    return await runs.start_run(
        db,
        [item.payload for item in ready if item.payload is not None],
        submit=submit,
        cards=_cards(ready),
        now=now,
        requested_by_user_id=requested_by_user_id,
        client=client,
    )


async def due_items(
    db: AsyncSession, *, now: datetime, today: date
) -> list[bot_items.BotItem]:
    queue = await bot_items.load_items(db, now=now, today=today)
    ready = [item for item in queue if item.payload is not None]
    states = await runs.item_states(db, [item.stage_id for item in ready], now=now)
    return [
        item for item in ready if runs.due_for_bot(states.get(item.stage_id), now=now)
    ][: runs.MAX_ITEMS_PER_RUN]


async def start_due(
    db: AsyncSession, *, now: datetime, today: date
) -> Optional[CproBotRun]:
    """Krok pętli: bieg dla kart czekających, gdy żaden bieg nie trwa."""

    if await runs.has_open_run(db):
        return None
    chosen = await due_items(db, now=now, today=today)
    return await start_for(db, chosen, now=now)


class NotReady(Exception):
    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


async def start_chosen(
    db: AsyncSession,
    stage_ids: Iterable[int],
    *,
    now: datetime,
    today: date,
    submit: bool = True,
    requested_by_user_id: Optional[int] = None,
) -> CproBotRun:
    """„Ponów botem” albo próba: wskazane karty, z polskim powodem odmowy."""

    wanted = [int(s) for s in stage_ids]
    if await runs.has_open_run(db):
        raise NotReady("Bot właśnie wypełnia Cpro — spróbuj za kilka minut.")
    found = await bot_items.load_items(db, now=now, today=today, stage_ids=wanted)
    if not found:
        raise NotReady("Tej osoby nie ma już w kolejce Cpro.")
    blocked = [item for item in found if item.payload is None]
    if blocked:
        raise NotReady("Bot nie może wrzucić: " + "; ".join(blocked[0].blockers) + ".")
    states = await runs.item_states(db, wanted, now=now)
    if any(state.state == "submitted" and state.submit for state in states.values()):
        raise NotReady("Bot już wysłał tę osobę do Cpro — przesuń kartę ręcznie.")
    if not runs.configured():
        raise NotReady("Bot Cpro nie jest skonfigurowany (brak webhooka rutyny).")
    run = await start_for(
        db,
        found,
        now=now,
        submit=submit,
        requested_by_user_id=requested_by_user_id,
    )
    if run is None:
        raise NotReady("Nie udało się zlecić biegu bota.")
    return run
