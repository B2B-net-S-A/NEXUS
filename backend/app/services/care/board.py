"""Opieka · „Do zrobienia” = kanban (decyzja Artura 22.10.2026).

Karty opieki liczone przy odczycie (``GET /api/care/board``); miejsce na
tablicy pamięta ``care_board_states`` (``board_state``). Kolumny: Nowa ·
W toku · Czeka na kogoś (karty opieki) i wąska „Zrobione” (liczba z tygodnia
i ostatnie pozycje). Ta sama tablica co Ludzie → Sprawy — front skleja karty
spraw i opieki.

* **contact** — jedna karta na kontrakt: otwarty punkt planu z terminem do
  piątku tygodnia albo po terminie i umówiony kontakt z ostatniej rozmowy
  (``week.contact_reasons`` — ta sama reguła co „Ten tydzień”). Klucz od
  pierwszego powodu: ``contact:plan:<punkt>`` albo
  ``contact:followup:<rozmowa>``. „W toku” = umówiona (``scheduled_at``),
  „Czeka” = nie odbiera (``retry_on``; w dniu ponowienia wraca do „Nowa”).
* **feedback** — prośby o opinię menedżera (D9), tylko krąg D11; zakres jak
  „Ten tydzień” (opiekun swoje, DL cały portfel). Klucz ``feedback:<kontakt>``.
* **decision** — aktywne „Do przepięcia”: ``open`` → Nowa, ``in_progress`` →
  W toku, stan tablicy „Czeka” → Czeka. Zamknięte nie wchodzą.
* **demand** — „Popyt do sprawdzenia” (``care/demand``) tylko dla DL klienta
  (portfel) i admina.

``mine`` = kontrakty, których czytający jest opiekunem (popyt — zawsze
klienci DL, prośby — jak „Ten tydzień”); ``all`` = cały zakres czytającego.
Odczyt niczego nie zapisuje. Bez stawek.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime, time
from typing import Any, Optional
from zoneinfo import ZoneInfo

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scheduling import DEFAULT_TZ
from app.models.contact import Contact
from app.models.contract_care import (
    CareConversation,
    CarePlanItem,
    ClientFeedbackSession,
    RedeployQueueItem,
)
from app.models.user import User, UserRole
from app.services.care import access as care_access
from app.services.care import board_state, client_people, demand, health, records
from app.services.care import plan as care_plan
from app.services.care.access import CareContract
from app.services.care.timeline import REDEPLOY_REASON_LABELS
from app.services.care.week import (
    client_managers,
    contact_reasons,
    default_day,
    excerpt,
    week_bounds,
)

RECENT_DONE = 10
FEEDBACK_REASON_LABELS = {
    "pre_end": "Przed końcem współpracy",
    "quarterly": "Kwartał bez opinii",
}


def _local_day(moment: Optional[datetime]) -> Optional[date]:
    if moment is None:
        return None
    return moment.astimezone(ZoneInfo(DEFAULT_TZ)).date()


def _bounds(monday: date, friday: date) -> tuple[datetime, datetime]:
    zone = ZoneInfo(DEFAULT_TZ)
    return (
        datetime.combine(monday, time.min, tzinfo=zone),
        datetime.combine(friday, time.max, tzinfo=zone),
    )


def contact_key(reason: Any, latest: Optional[CareConversation]) -> str:
    if reason.plan_item_id is not None:
        return f"contact:plan:{reason.plan_item_id}"
    return f"contact:followup:{latest.id if latest is not None else 0}"


def _state_fields(
    state: Optional[board_state.BoardState], today: date
) -> dict[str, Any]:
    return {
        "column": board_state.column_for(state, today),
        "scheduled_at": state.scheduled_at if state else None,
        "retry_on": state.retry_on if state else None,
        "state_note": state.note if state else None,
    }


def _subtitle(contract: CareContract, manager: Optional[dict[str, Any]]) -> str:
    """Klient · dział menedżera u klienta (bez niego — rola), jak „Ten tydzień”."""

    area = (manager or {}).get("area") or {}
    second = area.get("name") or contract.job_title
    return " · ".join(part for part in (contract.client_name, second) if part)


async def _contact_cards(
    db: AsyncSession,
    contracts: Sequence[CareContract],
    *,
    owners: dict[int, care_access.OwnerChoice],
    names: dict[int, str],
    today: date,
    friday: date,
    healths: dict[int, Optional[dict[str, Any]]],
) -> list[dict[str, Any]]:
    ids = [c.id for c in contracts]
    open_items: dict[int, list[CarePlanItem]] = {cid: [] for cid in ids}
    if ids:
        for item in (
            await db.scalars(
                select(CarePlanItem)
                .where(
                    CarePlanItem.contract_id.in_(ids),
                    CarePlanItem.status == "open",
                    CarePlanItem.due_on <= friday,
                )
                .order_by(CarePlanItem.due_on, CarePlanItem.id)
            )
        ).all():
            open_items[item.contract_id].append(item)
    latest = await care_plan.latest_conversations(db, ids)
    due: list[tuple[CareContract, Any, str]] = []
    for contract in contracts:
        reasons = contact_reasons(
            open_items[contract.id], latest.get(contract.id), today=today, friday=friday
        )
        if reasons:
            due.append(
                (contract, reasons[0], contact_key(reasons[0], latest.get(contract.id)))
            )
    managers = await client_managers(db, [c for c, _, _ in due])
    states = await board_state.states_for(db, (key for _, _, key in due))
    cards = []
    for contract, reason, key in due:
        last = latest.get(contract.id)
        manager = managers.get(contract.id)
        owner_id = owners[contract.id].user_id
        cards.append(
            {
                "key": key,
                "kind": "contact",
                **_state_fields(states.get(key), today),
                "title": contract.candidate_name or "Konsultant",
                "subtitle": _subtitle(contract, manager),
                "reason_label": care_plan.contact_label(reason.kind),
                "due_on": reason.due_on,
                "overdue_days": max((today - reason.due_on).days, 0),
                "note_excerpt": excerpt(last.note) if last is not None else None,
                "contract_id": contract.id,
                "candidate_id": contract.candidate_id,
                "client_id": contract.client_id,
                "client_name": contract.client_name,
                "manager": (
                    {"contact_id": manager["id"], "name": manager["name"]}
                    if manager
                    else None
                ),
                "owner_user_id": owner_id,
                "owner_name": names.get(owner_id) if owner_id else None,
                "health": healths.get(contract.id),
                "last_satisfaction": last.satisfaction if last is not None else None,
            }
        )
    return cards


async def _feedback_cards(
    db: AsyncSession,
    *,
    user: User,
    allowed: Optional[frozenset[int]],
    live: Sequence[CareContract],
    owners: dict[int, care_access.OwnerChoice],
    names: dict[int, str],
    scope: str,
    today: date,
) -> list[dict[str, Any]]:
    items = await client_people.feedback_requests_for(
        db, live, owners=owners, today=today
    )
    if scope == "mine" and not (
        allowed is not None and user.has_role(UserRole.delivery_lead)
    ):
        items = [item for item in items if user.id in item["owner_ids"]]
    keys = [f"feedback:{item['contact_id']}" for item in items]
    states = await board_state.states_for(db, keys)
    missing = {oid for item in items for oid in item["owner_ids"]} - set(names)
    names = {**names, **await care_access.user_names(db, missing)}
    cards = []
    for key, item in zip(keys, items):
        owner_id = item["owner_ids"][0] if item["owner_ids"] else None
        cards.append(
            {
                "key": key,
                "kind": "feedback",
                **_state_fields(states.get(key), today),
                "title": item["contact_name"],
                "subtitle": " · ".join(
                    part for part in (item["client_name"], item["position"]) if part
                ),
                "reason_label": " · ".join(
                    FEEDBACK_REASON_LABELS.get(r, r) for r in item["reasons"]
                ),
                "due_on": item["due_on"],
                "overdue_days": max((today - item["due_on"]).days, 0),
                "note_excerpt": None,
                "client_id": item["client_id"],
                "client_name": item["client_name"],
                "manager": {
                    "contact_id": item["contact_id"],
                    "name": item["contact_name"],
                },
                "owner_user_id": owner_id,
                "owner_name": names.get(owner_id) if owner_id else None,
                "health": None,
                "consultants": [
                    {"contract_id": c["contract_id"], "name": c["candidate_name"]}
                    for c in item["consultants"]
                ],
            }
        )
    return cards


async def _decision_cards(
    db: AsyncSession,
    contracts: Sequence[CareContract],
    *,
    owners: dict[int, care_access.OwnerChoice],
    names: dict[int, str],
    today: date,
    healths: dict[int, Optional[dict[str, Any]]],
) -> list[dict[str, Any]]:
    by_id = {c.id: c for c in contracts}
    if not by_id:
        return []
    items = (
        await db.scalars(
            select(RedeployQueueItem)
            .where(
                RedeployQueueItem.contract_id.in_(sorted(by_id)),
                RedeployQueueItem.status.in_(("open", "in_progress")),
            )
            .order_by(RedeployQueueItem.due_on.asc().nulls_last(), RedeployQueueItem.id)
        )
    ).all()
    states = await board_state.states_for(db, (f"decision:{i.id}" for i in items))
    cards = []
    for item in items:
        contract = by_id[item.contract_id]
        key = f"decision:{item.id}"
        state = states.get(key)
        column = "in_progress" if item.status == "in_progress" else "new"
        if state is not None and board_state.column_for(state, today) == "waiting":
            column = "waiting"
        owner_id = owners[contract.id].user_id
        cards.append(
            {
                "key": key,
                "kind": "decision",
                "column": column,
                "scheduled_at": state.scheduled_at if state else None,
                "retry_on": state.retry_on if state else None,
                "state_note": state.note if state else None,
                "title": contract.candidate_name or "Konsultant",
                "subtitle": " · ".join(
                    p for p in (contract.client_name, contract.job_title) if p
                ),
                "reason_label": "Decyzja: "
                + REDEPLOY_REASON_LABELS.get(item.reason, item.reason),
                "due_on": item.due_on,
                "overdue_days": (
                    max((today - item.due_on).days, 0) if item.due_on else 0
                ),
                "note_excerpt": excerpt(item.note),
                "contract_id": contract.id,
                "candidate_id": contract.candidate_id,
                "client_id": contract.client_id,
                "client_name": contract.client_name,
                "owner_user_id": owner_id,
                "owner_name": names.get(owner_id) if owner_id else None,
                "health": healths.get(contract.id),
            }
        )
    return cards


async def _demand_cards(
    db: AsyncSession, *, user: User, today: date
) -> list[dict[str, Any]]:
    clients = await demand.demand_clients(db, user)
    if clients is not None and not clients:
        return []
    groups = await demand.open_groups(db, clients, today=today)
    leads = {}
    if groups:
        from app.services.care.structure_proposals import client_leads  # noqa: PLC0415

        leads = await client_leads(db, sorted({g.head.client_id for g, _ in groups}))
    names = await care_access.user_names(db, [ids[0] for ids in leads.values() if ids])
    cards = []
    for group, state in groups:
        head = group.head
        lead_ids = leads.get(head.client_id) or []
        owner_id = lead_ids[0] if lead_ids else None
        cards.append(
            {
                "key": head.key,
                "kind": "demand",
                **_state_fields(state, today),
                "title": demand.card_title(head.roles),
                "subtitle": " · ".join(
                    p for p in (head.client_name, head.area_name) if p
                ),
                "reason_label": "Klient zatrudnia",
                "due_on": head.on,
                "overdue_days": 0,
                "note_excerpt": head.note,
                "contract_id": head.contract_id,
                "client_id": head.client_id,
                "client_name": head.client_name,
                "owner_user_id": owner_id,
                "owner_name": names.get(owner_id) if owner_id else None,
                "health": None,
                "consultants": [
                    {"contract_id": s.contract_id, "name": s.candidate_name}
                    for s in group.signals
                ],
                "demand": {
                    "roles": list(head.roles),
                    "source": head.source,
                    "area": (
                        {"id": head.area_id, "name": head.area_name}
                        if head.area_id is not None
                        else None
                    ),
                    "conversation_id": head.conversation_id,
                },
                "sources": [
                    {
                        "conversation_id": s.conversation_id,
                        "on": s.on,
                        "contract_id": s.contract_id,
                        "name": s.candidate_name,
                    }
                    for s in group.signals
                ],
            }
        )
    return cards


async def _done(
    db: AsyncSession,
    *,
    contract_ids: Sequence[int],
    client_ids: Optional[frozenset[int]],
    include_feedback: bool,
    include_demand: bool,
    monday: date,
    friday: date,
    names_by_contract: dict[int, str],
) -> dict[str, Any]:
    first, last = _bounds(monday, friday)
    done: list[dict[str, Any]] = []
    if contract_ids:
        for conv in (
            await db.scalars(
                select(CareConversation).where(
                    CareConversation.contract_id.in_(list(contract_ids)),
                    CareConversation.occurred_on >= monday,
                    CareConversation.occurred_on <= friday,
                )
            )
        ).all():
            done.append(
                {
                    "key": f"contact:conversation:{conv.id}",
                    "kind": "contact",
                    "title": "Rozmowa: "
                    + names_by_contract.get(conv.contract_id, "konsultant"),
                    "done_on": conv.occurred_on,
                }
            )
        for item in (
            await db.scalars(
                select(RedeployQueueItem).where(
                    RedeployQueueItem.contract_id.in_(list(contract_ids)),
                    RedeployQueueItem.status.in_(("done", "dismissed")),
                    RedeployQueueItem.resolved_at >= first,
                    RedeployQueueItem.resolved_at <= last,
                )
            )
        ).all():
            done.append(
                {
                    "key": f"decision:{item.id}",
                    "kind": "decision",
                    "title": "Decyzja: "
                    + names_by_contract.get(item.contract_id, "konsultant"),
                    "done_on": _local_day(item.resolved_at),
                }
            )
    if include_feedback:
        query = select(ClientFeedbackSession).where(
            ClientFeedbackSession.held_on >= monday,
            ClientFeedbackSession.held_on <= friday,
        )
        if client_ids is not None:
            query = query.where(
                ClientFeedbackSession.client_id.in_(sorted(client_ids) or [-1])
            )
        for session in (await db.scalars(query)).all():
            done.append(
                {
                    "key": f"feedback:session:{session.id}",
                    "kind": "feedback",
                    "title": "Opinia menedżera",
                    "done_on": session.held_on,
                }
            )
    if include_demand:
        for state in await board_state.updated_between(db, first, last, kind="demand"):
            if state.outcome in ("confirmed", "stale"):
                parsed = board_state.parse_key(state.key)
                if parsed is None or (
                    client_ids is not None and parsed.ids[0] not in client_ids
                ):
                    continue
                done.append(
                    {
                        "key": state.key,
                        "kind": "demand",
                        "title": "Popyt: "
                        + (
                            "potwierdzony"
                            if state.outcome == "confirmed"
                            else "nieaktualny"
                        ),
                        "done_on": _local_day(state.updated_at),
                    }
                )
    done.sort(key=lambda row: (row["done_on"] or date.min, row["key"]), reverse=True)
    return {"this_week": len(done), "recent": done[:RECENT_DONE]}


async def board(
    db: AsyncSession, *, user: User, scope: str, today: date
) -> dict[str, Any]:
    monday, friday = week_bounds(default_day(today))
    allowed = await care_access.allowed_client_ids(user, db)
    include_feedback = care_access.reads_client_people(user)
    live = await care_access.live_contracts(db, allowed=allowed)
    owners = await care_access.effective_owners(db, live)
    mine = (
        [c for c in live if owners[c.id].user_id == user.id]
        if scope == "mine"
        else live
    )
    names = await care_access.user_names(db, [owners[c.id].user_id for c in mine])
    healths: dict[int, Optional[dict[str, Any]]] = (
        await health.health_for(db, mine, today=today) if include_feedback else {}
    )
    cards = await _contact_cards(
        db,
        mine,
        owners=owners,
        names=names,
        today=today,
        friday=friday,
        healths=healths,
    )
    if include_feedback:
        cards += await _feedback_cards(
            db,
            user=user,
            allowed=allowed,
            live=live,
            owners=owners,
            names=names,
            scope=scope,
            today=today,
        )
    cards += await _decision_cards(
        db, mine, owners=owners, names=names, today=today, healths=healths
    )
    demand_scope = await demand.demand_clients(db, user)
    include_demand = demand_scope is None or bool(demand_scope)
    if include_demand:
        cards += await _demand_cards(db, user=user, today=today)
    order = {"contact": 0, "decision": 1, "feedback": 2, "demand": 3}
    cards.sort(
        key=lambda card: (
            card["due_on"] or date.max,
            order[card["kind"]],
            (card["title"] or "").casefold(),
        )
    )
    return {
        "today": today,
        "week_end": friday,
        "scope": scope,
        "cards": cards,
        "done": await _done(
            db,
            contract_ids=[c.id for c in mine],
            client_ids=allowed,
            include_feedback=include_feedback,
            include_demand=include_demand,
            monday=monday,
            friday=friday,
            names_by_contract={c.id: c.candidate_name or "konsultant" for c in mine},
        ),
        "can_edit": await care_access.is_care_writer(db, user),
    }


# ── Zapis stanu karty (``PUT /api/care/board/state``) ───────────────────────

UNKNOWN_CARD = "Nie ma takiej karty na tablicy."
NEEDS_SCHEDULE = "„W toku” wymaga terminu umówionej rozmowy."
NEEDS_RETRY = "„Czeka na kogoś” wymaga daty ponowienia późniejszej niż dziś."
DEMAND_DENIED = "Popyt prowadzi Delivery Lead klienta albo administrator."
FEEDBACK_DENIED = (
    "Opinie menedżerów prowadzą opiekun kontraktu, Delivery Lead klienta "
    "i administrator."
)


def _not_found() -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, UNKNOWN_CARD)


async def _authorize(
    db: AsyncSession, key: board_state.CardKey, user: User
) -> Optional[RedeployQueueItem]:
    """Prawo do karty (zakres klienta i rola); zwraca wpis „Do przepięcia”."""

    if key.variant == "contact_plan":
        contract_id = await db.scalar(
            select(CarePlanItem.contract_id).where(CarePlanItem.id == key.ids[0])
        )
        if contract_id is None:
            raise _not_found()
        await care_access.load_contract(db, contract_id, user)
        return None
    if key.variant == "contact_followup":
        contract_id = await db.scalar(
            select(CareConversation.contract_id).where(
                CareConversation.id == key.ids[0]
            )
        )
        if contract_id is None:
            raise _not_found()
        await care_access.load_contract(db, contract_id, user)
        return None
    if key.variant == "decision":
        item = await db.get(RedeployQueueItem, key.ids[0], with_for_update=True)
        if item is None or item.status not in ("open", "in_progress"):
            raise _not_found()
        await care_access.load_contract(db, item.contract_id, user)
        return item
    if key.variant == "feedback":
        client_id = await db.scalar(
            select(Contact.client_id).where(Contact.id == key.ids[0])
        )
        if client_id is None:
            raise _not_found()
        await care_access.load_client(db, client_id, user)
        if not care_access.reads_client_people(user):
            raise HTTPException(status.HTTP_403_FORBIDDEN, FEEDBACK_DENIED)
        return None
    # demand
    await care_access.load_client(db, key.ids[0], user)
    if not await demand.can_resolve(db, user, key.ids[0]):
        raise HTTPException(status.HTTP_403_FORBIDDEN, DEMAND_DENIED)
    return None


async def set_state(
    db: AsyncSession,
    *,
    user: User,
    raw_key: str,
    column: str,
    scheduled_at: Optional[datetime],
    retry_on: Optional[date],
    note: Optional[str],
    today: date,
    now: datetime,
) -> dict[str, Any]:
    key = board_state.parse_key(raw_key)
    if key is None:
        raise _not_found()
    item = await _authorize(db, key, user)
    if column == "in_progress" and key.kind in ("contact", "feedback"):
        if scheduled_at is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, NEEDS_SCHEDULE)
    if column == "waiting" and (retry_on is None or retry_on <= today):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, NEEDS_RETRY)
    if item is not None:
        # Decyzja w „W toku” = wpis „Do przepięcia” w toku (istniejący serwis).
        target = {"in_progress": "in_progress", "new": "open"}.get(column)
        if target is not None and target != item.status:
            await records.update_redeploy(
                db,
                item,
                new_status=target,
                note=None,
                note_set=False,
                actor_id=user.id,
                now=now,
            )
    if column == "new":
        await board_state.clear(db, [key.raw])
    else:
        await board_state.save(
            db,
            key=key.raw,
            kind=key.kind,
            column_value=column,
            scheduled_at=scheduled_at if column == "in_progress" else None,
            retry_on=retry_on if column == "waiting" else None,
            note=note,
            actor_id=user.id,
            now=now,
        )
    await db.flush()
    return {
        "key": key.raw,
        "kind": key.kind,
        "column": column,
        "scheduled_at": scheduled_at if column == "in_progress" else None,
        "retry_on": retry_on if column == "waiting" else None,
        "note": board_state.clean_note(note) if column != "new" else None,
    }
