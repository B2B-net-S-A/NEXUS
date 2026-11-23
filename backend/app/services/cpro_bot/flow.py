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
from typing import Awaitable, Callable, Iterable, Optional
from urllib.parse import urlsplit

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.cpro_bot import CproBotRun
from app.services.cpro_bot import items as bot_items
from app.services.cpro_bot import ingest, runs


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
        submit=runs.effective_submit(submit),
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
    reserved = await runs.operator_reserved_stage_ids(
        db, [item.stage_id for item in ready]
    )
    limit = 1 if runs.auto_draft_enabled() else runs.MAX_ITEMS_PER_RUN
    return [
        item
        for item in ready
        if item.stage_id not in reserved
        and runs.due_for_bot(states.get(item.stage_id), now=now)
    ][:limit]


async def start_due(
    db: AsyncSession, *, now: datetime, today: date
) -> Optional[CproBotRun]:
    """Krok pętli: bieg dla kart czekających, gdy żaden bieg nie trwa."""

    await runs.lock_new_run(db)
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
    if runs.auto_draft_enabled() and len(wanted) != 1:
        raise NotReady("Tryb szkiców wymaga dokładnie jednej karty Cpro.")
    await runs.lock_new_run(db)
    if await runs.operator_reserved_stage_ids(db, wanted):
        raise NotReady("Karta ma już zlecenie operatora — otwórz istniejący bieg.")
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
    if runs.auto_draft_enabled() and await runs.recorded_offer_stage_ids(db, wanted):
        raise NotReady("Ta karta ma już szkic albo wysłaną ofertę w Cpro.")
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


async def create_interactive_draft(
    db: AsyncSession,
    stage_id: int,
    *,
    delivery_lead_id: int,
    request_number: str,
    now: datetime,
    today: date,
    repair_draft_run_id: Optional[int] = None,
    operator_user_id: Optional[int] = None,
    operator_check: Optional[Callable[[bot_items.BotItem], Awaitable[None]]] = None,
) -> tuple[CproBotRun, str]:
    """Nowe zlecenie jednej karty dla operatora, bez webhooka i wysyłki.

    Token istnieje jawnie tylko w wyniku tej funkcji; baza przechowuje hash.
    Nie odzyskuje ani nie odnawia dostępu do wcześniejszego biegu.
    """

    if runs.enabled():
        raise NotReady("Próba interaktywna wymaga CPRO_BOT_ENABLED=false.")
    if type(stage_id) is not int or stage_id <= 0:
        raise NotReady("Wskaż dokładnie jedną kartę Cpro.")
    if type(delivery_lead_id) is not int:
        raise NotReady("Wskaż obsługiwanego Delivery Leada rekrutacji.")
    if repair_draft_run_id is not None and (
        type(repair_draft_run_id) is not int or repair_draft_run_id <= 0
    ):
        raise NotReady("Wskaż bieg z potwierdzonym szkicem tej karty.")
    account = bot_items.CPRO_ACCOUNTS.get(delivery_lead_id)
    if account is None:
        raise NotReady("Delivery Lead rekrutacji nie ma konta Cpro bota.")
    if (
        not isinstance(request_number, str)
        or bot_items.request_number(request_number) != request_number
    ):
        raise NotReady("Podaj dokładny numer requestu Cpro.")

    await runs.lock_new_run(db)
    if await runs.operator_reserved_stage_ids(db, [stage_id]):
        raise NotReady("Karta ma już zlecenie operatora — otwórz istniejący bieg.")
    if await runs.has_open_run(db):
        raise NotReady("Bot właśnie wypełnia Cpro — spróbuj za kilka minut.")
    found = await bot_items.load_items(db, now=now, today=today, stage_ids=[stage_id])
    if len(found) != 1 or found[0].stage_id != stage_id:
        raise NotReady("Tej osoby nie ma już w kolejce Cpro.")
    item = found[0]
    if item.blockers or item.payload is None:
        raise NotReady("Karta nie jest gotowa do próby Cpro.")
    payload = item.payload
    if (
        payload.get("ref") != stage_id
        or payload.get("request_number") != request_number
    ):
        raise NotReady("Karta nie odpowiada wskazanemu requestowi Cpro.")
    if payload.get("cpro_account") != {
        "delivery_lead_id": delivery_lead_id,
        "delivery_lead_name": account[0],
        "vault_entry": account[1],
    }:
        raise NotReady("Delivery Lead karty nie odpowiada wskazanemu kontu Cpro.")

    # Nie tylko najnowszy bieg i nie tylko okno 30 dni: późniejsze failed
    # nie może zasłonić szkicu lub wysyłki, która już powstała dla tej karty.
    recorded = await db.scalar(
        select(CproBotRun.id)
        .where(
            CproBotRun.stage_ids.contains([stage_id]),
            CproBotRun.report["items"][str(stage_id)]["outcome"].astext.in_(
                ("draft", "submitted")
            ),
        )
        .limit(1)
    )
    if repair_draft_run_id is None and (
        recorded is not None or await runs.recorded_offer_stage_ids(db, [stage_id])
    ):
        raise NotReady("Ta karta ma już szkic albo wysłaną ofertę w Cpro.")
    if repair_draft_run_id is not None:
        submitted = await db.scalar(
            select(CproBotRun.id)
            .where(
                CproBotRun.stage_ids.contains([stage_id]),
                (
                    CproBotRun.report["items"][str(stage_id)]["outcome"].astext
                    == "submitted"
                )
                | (
                    CproBotRun.report["items"][str(stage_id)]["reported_outcome"].astext
                    == "submitted"
                )
                | (
                    CproBotRun.report["items"][str(stage_id)]["reason"].astext
                    == "submit_disallowed"
                ),
            )
            .limit(1)
        )
        if submitted is not None:
            raise NotReady("Ta karta ma już wysłaną ofertę w Cpro.")
        source = await db.get(CproBotRun, repair_draft_run_id)
        source_items = ((source.request or {}).get("items") or []) if source else []
        matching = [
            entry
            for entry in source_items
            if isinstance(entry, dict) and entry.get("ref") == stage_id
        ]
        outcome = (
            ((source.report or {}).get("items") or {}).get(str(stage_id))
            if source
            else None
        )
        if (
            source is None
            or source.status != "received"
            or source.submit is not False
            or stage_id not in (source.stage_ids or [])
            or len(matching) != 1
            or matching[0].get("request_number") != request_number
            or matching[0].get("cpro_account") != payload["cpro_account"]
            or not isinstance(outcome, dict)
            or outcome.get("outcome") != "draft"
            or outcome.get("cpro_status") != "DRAFT"
        ):
            raise NotReady(
                "Bieg nie potwierdza szkicu tej karty na tym koncie i requeście."
            )
        payload = {
            **payload,
            "edit_existing_draft_only": True,
            "repair_draft_run_id": source.id,
        }
        try:
            link = ingest.offer_link(outcome.get("offer_url"))
            if link:
                parsed = urlsplit(link)
                if (
                    parsed.hostname == "nordea.onevms.se"
                    and parsed.username is None
                    and parsed.password is None
                    and parsed.port in (None, 443)
                ):
                    payload["existing_offer_url"] = link
        except ValueError:
            # Wtedy bot potwierdza szkic na liście ofert właściwego requestu.
            pass

    if operator_user_id is not None:
        if (
            type(operator_user_id) is not int
            or operator_user_id <= 0
            or operator_check is None
        ):
            raise NotReady("Brak uprawnień operatora do tej karty.")
        await operator_check(item)
    run, token = runs.new_run([payload], now=now, submit=False, cards=_cards([item]))
    if operator_user_id is not None:
        run.request = {**run.request, "operator_browser": True}
        run.requested_by_user_id = operator_user_id
        run.token_hash = None
    db.add(run)
    await db.commit()
    return run, token
