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
* **decision** także bez wpisu: kontrakt z końcem zamówienia w 60 dni, bez
  aktywnego wpisu i bez rozstrzygniętego „koniec projektu” na tę datę —
  klucz ``decision:end:<kontrakt>``; pierwszy ruch zakłada wpis (K3).
* **demand** — „Popyt do sprawdzenia” (``care/demand``) tylko dla DL klienta
  (portfel) i admina; z menedżerem działu (menedżer konsultanta ze źródła)
  i otwartą rekrutacją klienta.
* **data** — „Dane do uzupełnienia” (krąg D11): pewne i niepewne propozycje
  menedżera (``structure_proposals``) i luki mapy technologii (tylko cache),
  u klientów „moich” jak w „Klientach” (DL, domyślny opiekun, opiekun
  konsultanta). Klucz ``data:<klient>``; nie przesuwa się — „Przejrzyj”.

``week_progress`` — punkty planu z terminem w tym tygodniu (pon–pt): ile
zapisanych z ilu (bez pominiętych), dla kontraktów z zakresu tablicy.

``mine`` = kontrakty, których czytający jest opiekunem (popyt — zawsze
klienci DL, prośby — jak „Ten tydzień”); ``all`` = cały zakres czytającego.
Odczyt niczego nie zapisuje. Bez stawek.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime, time, timedelta
from typing import Any, Optional
from zoneinfo import ZoneInfo

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import cache_get
from app.core.scheduling import DEFAULT_TZ, business_today
from app.models.contact import Contact
from app.models.contract_care import (
    CareConversation,
    CarePlanItem,
    ClientFeedbackSession,
    RedeployQueueItem,
)
from app.models.job import Job, JobStatus
from app.models.user import User, UserRole
from app.services.care import access as care_access
from app.services.care import (
    board_state,
    client_people,
    demand,
    health,
    records,
    structure_proposals,
    tech_map,
)
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
#: Koniec zamówienia w tylu dniach = karta „Decyzja” (K3, jak front office).
ORDER_END_DAYS = 60
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

    second = _role_label(contract, manager)
    return " · ".join(part for part in (contract.client_name, second) if part)


def _role_label(
    contract: CareContract, manager: Optional[dict[str, Any]]
) -> Optional[str]:
    """Dział menedżera u klienta, bez niego — rola z kontraktu („QA”)."""

    area = (manager or {}).get("area") or {}
    return area.get("name") or contract.job_title


def feedback_due_by_manager(requests: Sequence[dict[str, Any]]) -> dict[int, date]:
    """Prośba o opinię czeka od … — termin prośby per menedżer (kontakt)."""

    return {item["contact_id"]: item["due_on"] for item in requests}


def order_end_contracts(
    contracts: Sequence[CareContract],
    *,
    today: date,
    active_ids: set[int],
    handled: set[tuple[int, date]],
    resolved_ids: frozenset[int] = frozenset(),
) -> list[CareContract]:
    """Kontrakty na kartę „Decyzja” z samego końca zamówienia (K3).

    Koniec w ``ORDER_END_DAYS`` dni, bez aktywnego wpisu „Do przepięcia”
    (karta wpisu już stoi), bez rozstrzygniętego „koniec projektu” na tę
    samą datę (``records.ensure_redeploy`` też by go nie założył) i bez
    decyzji rozstrzygniętej niedawno z innego powodu albo na inną datę
    (``resolved_ids``: „chce zmiany”, koniec projektu z rozmowy) — inaczej
    zamknięta „Decyzja” wracałaby od razu jako nowa karta.
    """

    horizon = today + timedelta(days=ORDER_END_DAYS)
    return sorted(
        (
            c
            for c in contracts
            if c.end_date is not None
            and today <= c.end_date <= horizon
            and c.id not in active_ids
            and c.id not in resolved_ids
            and (c.id, c.end_date) not in handled
        ),
        key=lambda c: (c.end_date, (c.candidate_name or "").casefold()),
    )


def pick_open_job(
    jobs: Sequence[tuple[int, str]], roles: Sequence[str]
) -> Optional[dict[str, Any]]:
    """Otwarta rekrutacja klienta do karty popytu: najpierw pasująca do roli.

    ``jobs`` od najnowszej. Rola pasuje, gdy jej tekst zawiera się w tytule
    albo odwrotnie (bez wielkości liter); bez dopasowania — najnowsza.
    """

    if not jobs:
        return None
    wanted = [role.casefold() for role in roles if role.strip()]
    for job_id, title in jobs:
        folded = (title or "").casefold()
        if any(role in folded or (folded and folded in role) for role in wanted):
            return {"id": job_id, "title": title}
    job_id, title = jobs[0]
    return {"id": job_id, "title": title}


def data_card_counts(
    summary: Optional[dict[str, int]], gaps: Optional[int]
) -> Optional[dict[str, Any]]:
    """Liczniki karty „Dane do uzupełnienia”; ``None`` = nic do zrobienia."""

    certain = (summary or {}).get("certain", 0)
    uncertain = (summary or {}).get("uncertain", 0)
    if not (certain or uncertain or gaps):
        return None
    return {"certain": certain, "uncertain": uncertain, "gaps": gaps}


async def _contact_cards(
    db: AsyncSession,
    contracts: Sequence[CareContract],
    *,
    owners: dict[int, care_access.OwnerChoice],
    names: dict[int, str],
    today: date,
    friday: date,
    healths: dict[int, Optional[dict[str, Any]]],
    feedback_due: dict[int, date],
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
                "role_label": _role_label(contract, manager),
                "reason_kind": reason.kind,
                "reason_label": care_plan.contact_label(reason.kind),
                "due_on": reason.due_on,
                "overdue_days": max((today - reason.due_on).days, 0),
                "note_excerpt": excerpt(last.note) if last is not None else None,
                "note_on": last.occurred_on if last is not None else None,
                "contract_id": contract.id,
                "candidate_id": contract.candidate_id,
                "client_id": contract.client_id,
                "client_name": contract.client_name,
                "end_on": contract.end_date,
                "manager": (
                    {
                        "contact_id": manager["id"],
                        "name": manager["name"],
                        # Prośba o opinię — tylko krąg D11 (pusta mapa poza nim).
                        "feedback_due_on": feedback_due.get(manager["id"]),
                    }
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
    names: dict[int, str],
    scope: str,
    today: date,
    requests: Sequence[dict[str, Any]],
) -> list[dict[str, Any]]:
    items = list(requests)
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
                "role_label": item["position"],
                "reason_label": " · ".join(
                    FEEDBACK_REASON_LABELS.get(r, r) for r in item["reasons"]
                ),
                "last_feedback": (
                    {
                        "held_on": item["last_feedback"]["held_on"],
                        "average": item["last_feedback"]["average"],
                    }
                    if item.get("last_feedback")
                    else None
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


def decision_column(
    item_status: str, state: Optional[board_state.BoardState], today: date
) -> str:
    """Kolumna karty decyzji: „Czeka” do daty ponowienia, potem „Nowa”.

    Po ``retry_on`` karta wraca do „Nowa” także przy wpisie „W toku”
    (przegląd 22.10.2026) — inaczej opiekun nie widzi, że czas wrócić.
    Bez „Czeka” kolumnę wyznacza status wpisu „Do przepięcia”.
    """

    if state is not None and state.column == "waiting":
        return board_state.column_for(state, today)
    return "in_progress" if item_status == "in_progress" else "new"


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
    handled = {
        (contract_id, due_on)
        for contract_id, due_on in (
            await db.execute(
                select(RedeployQueueItem.contract_id, RedeployQueueItem.due_on).where(
                    RedeployQueueItem.contract_id.in_(sorted(by_id)),
                    RedeployQueueItem.reason == "project_end",
                    RedeployQueueItem.status.in_(("done", "dismissed")),
                    RedeployQueueItem.due_on.is_not(None),
                )
            )
        ).all()
    }
    resolved_since = datetime.now(ZoneInfo(DEFAULT_TZ)) - timedelta(
        days=health.DECISION_LOOKBACK_DAYS
    )
    resolved_ids = frozenset(
        (
            await db.scalars(
                select(RedeployQueueItem.contract_id).where(
                    RedeployQueueItem.contract_id.in_(sorted(by_id)),
                    RedeployQueueItem.status.in_(("done", "dismissed")),
                    RedeployQueueItem.resolved_at >= resolved_since,
                )
            )
        ).all()
    )
    ending = order_end_contracts(
        contracts,
        today=today,
        active_ids={item.contract_id for item in items},
        handled=handled,
        resolved_ids=resolved_ids,
    )
    # Notatka i data z rozmowy, z której wpis powstał („chce zmiany”).
    source_ids = sorted(
        {i.source_id for i in items if i.source == "conversation" and i.source_id}
    )
    talks = (
        {
            conv.id: conv
            for conv in (
                await db.scalars(
                    select(CareConversation).where(CareConversation.id.in_(source_ids))
                )
            ).all()
        }
        if source_ids
        else {}
    )
    keys = [f"decision:{i.id}" for i in items] + [
        f"decision:end:{c.id}" for c in ending
    ]
    states = await board_state.states_for(db, keys)

    def card(
        contract: CareContract,
        *,
        key: str,
        status_value: str,
        reason: str,
        due_on: Optional[date],
        note: Optional[str],
        note_on: Optional[date],
    ) -> dict[str, Any]:
        state = states.get(key)
        owner_id = owners[contract.id].user_id
        return {
            "key": key,
            "kind": "decision",
            "column": decision_column(status_value, state, today),
            "scheduled_at": state.scheduled_at if state else None,
            "retry_on": state.retry_on if state else None,
            "state_note": state.note if state else None,
            "title": contract.candidate_name or "Konsultant",
            "subtitle": " · ".join(
                p for p in (contract.client_name, contract.job_title) if p
            ),
            "role_label": contract.job_title,
            "reason_kind": reason,
            "reason_label": "Decyzja: " + REDEPLOY_REASON_LABELS.get(reason, reason),
            "due_on": due_on,
            "overdue_days": max((today - due_on).days, 0) if due_on else 0,
            "note_excerpt": excerpt(note),
            "note_on": note_on,
            "contract_id": contract.id,
            "candidate_id": contract.candidate_id,
            "client_id": contract.client_id,
            "client_name": contract.client_name,
            "end_on": contract.end_date,
            "owner_user_id": owner_id,
            "owner_name": names.get(owner_id) if owner_id else None,
            "health": healths.get(contract.id),
        }

    cards = []
    for item in items:
        talk = talks.get(item.source_id or 0) if item.source == "conversation" else None
        cards.append(
            card(
                by_id[item.contract_id],
                key=f"decision:{item.id}",
                status_value=item.status,
                reason=item.reason,
                due_on=item.due_on,
                note=item.note or (talk.note if talk else None),
                note_on=talk.occurred_on if talk else None,
            )
        )
    cards += [
        card(
            contract,
            key=f"decision:end:{contract.id}",
            status_value="open",
            reason="project_end",
            due_on=contract.end_date,
            note=None,
            note_on=None,
        )
        for contract in ending
    ]
    return cards


async def _open_jobs(
    db: AsyncSession, client_ids: Sequence[int]
) -> dict[int, list[tuple[int, str]]]:
    """Otwarte rekrutacje klientów (opublikowane, w pracy), od najnowszej."""

    out: dict[int, list[tuple[int, str]]] = {}
    if not client_ids:
        return out
    from app.services.job_working_title import display_title  # noqa: PLC0415
    from app.services.request_work_state import IN_WORK_STATES  # noqa: PLC0415

    for job in (
        await db.scalars(
            select(Job)
            .where(
                Job.client_id.in_(list(client_ids)),
                Job.status == JobStatus.published,
                Job.work_state.in_(IN_WORK_STATES),
            )
            .order_by(Job.id.desc())
        )
    ).all():
        out.setdefault(job.client_id, []).append((job.id, display_title(job)))
    return out


async def _demand_cards(
    db: AsyncSession,
    *,
    user: User,
    today: date,
    contracts_by_id: dict[int, CareContract],
) -> list[dict[str, Any]]:
    clients = await demand.demand_clients(db, user)
    if clients is not None and not clients:
        return []
    groups = await demand.open_groups(db, clients, today=today)
    leads = {}
    if groups:
        leads = await structure_proposals.client_leads(
            db, sorted({g.head.client_id for g, _ in groups})
        )
    names = await care_access.user_names(db, [ids[0] for ids in leads.values() if ids])
    # Menedżer działu = menedżer u klienta konsultanta, od którego jest sygnał
    # (dział karty popytu bierze się z niego, gdy karta nie ma działu).
    sources = [
        contracts_by_id[g.head.contract_id]
        for g, _ in groups
        if g.head.contract_id in contracts_by_id
    ]
    managers = await client_managers(db, sources)
    jobs = await _open_jobs(db, sorted({g.head.client_id for g, _ in groups}))
    cards = []
    for group, state in groups:
        head = group.head
        lead_ids = leads.get(head.client_id) or []
        owner_id = lead_ids[0] if lead_ids else None
        manager = managers.get(head.contract_id)
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
                "manager": (
                    {"contact_id": manager["id"], "name": manager["name"]}
                    if manager
                    else None
                ),
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
                    "manager": (
                        {"contact_id": manager["id"], "name": manager["name"]}
                        if manager
                        else None
                    ),
                    "open_job": pick_open_job(jobs.get(head.client_id, []), head.roles),
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


async def _my_clients(
    db: AsyncSession,
    *,
    user: User,
    live: Sequence[CareContract],
    owners: dict[int, care_access.OwnerChoice],
) -> list[int]:
    """Klienci „moi” jak w „Klientach”: DL klienta, domyślny opiekun, opiekun."""

    ids = sorted({c.client_id for c in live})
    if not ids:
        return []
    leads = await structure_proposals.client_leads(db, ids)
    return sorted(
        {
            c.client_id
            for c in live
            if owners[c.id].user_id == user.id or c.client_default_owner_id == user.id
        }
        | {cid for cid, lead_ids in leads.items() if user.id in lead_ids}
    )


async def _data_cards(
    db: AsyncSession,
    *,
    client_ids: Sequence[int],
    live: Sequence[CareContract],
) -> list[dict[str, Any]]:
    if not client_ids:
        return []
    datas = await structure_proposals.load(db, client_ids=client_ids)
    summary = {
        row["client_id"]: row
        for row in structure_proposals.summary_rows(datas.values())
    }
    consultants: dict[int, int] = {}
    names: dict[int, str] = {}
    for contract in live:
        consultants[contract.client_id] = consultants.get(contract.client_id, 0) + 1
        names[contract.client_id] = contract.client_name
    cards = []
    for client_id in client_ids:
        # Mapa technologii tylko z cache — pełnej mapy nie liczymy hurtem.
        cached = await cache_get(tech_map.cache_key(client_id))
        gaps = len(cached.get("gaps") or []) if cached else None
        counts = data_card_counts(summary.get(client_id), gaps)
        if counts is None:
            continue
        cards.append(
            {
                "key": f"data:{client_id}",
                "kind": "data",
                "column": "new",
                "scheduled_at": None,
                "retry_on": None,
                "state_note": None,
                "title": names.get(client_id) or "Klient",
                "subtitle": "klient · "
                + _consultants_text(consultants.get(client_id, 0)),
                "reason_label": "Dane do uzupełnienia",
                "due_on": None,
                "overdue_days": 0,
                "note_excerpt": None,
                "client_id": client_id,
                "client_name": names.get(client_id),
                "owner_user_id": None,
                "owner_name": None,
                "health": None,
                "data": {**counts, "consultants": consultants.get(client_id, 0)},
            }
        )
    return cards


def _consultants_text(count: int) -> str:
    # Rodzaj męskoosobowy: „2 konsultantów”, „6 konsultantów”.
    return "1 konsultant" if count == 1 else f"{count} konsultantów"


async def week_progress(
    db: AsyncSession, contract_ids: Sequence[int], *, monday: date, friday: date
) -> dict[str, int]:
    """„Ten tydzień: X z Y zapisane” — punkty planu z terminem pon–pt."""

    if not contract_ids:
        return {"done": 0, "total": 0}
    rows = (
        await db.execute(
            select(CarePlanItem.status, func.count())
            .where(
                CarePlanItem.contract_id.in_(list(contract_ids)),
                CarePlanItem.due_on >= monday,
                CarePlanItem.due_on <= friday,
                CarePlanItem.status != "skipped",
            )
            .group_by(CarePlanItem.status)
        )
    ).all()
    by_status = {status_value: int(count) for status_value, count in rows}
    return {"done": by_status.get("done", 0), "total": sum(by_status.values())}


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
        # Jedno rozstrzygnięcie karty zapisuje wszystkie jej źródła z tym samym
        # czasem — w „Zrobione” karta liczy się raz (audyt 22.10, F3).
        resolved: dict[tuple[Any, ...], tuple[int, board_state.BoardState]] = {}
        for state in await board_state.updated_between(db, first, last, kind="demand"):
            if state.outcome in ("confirmed", "stale"):
                parsed = board_state.parse_key(state.key)
                if parsed is None or (
                    client_ids is not None and parsed.ids[0] not in client_ids
                ):
                    continue
                group = (parsed.ids[0], state.outcome, state.updated_at)
                if group not in resolved or parsed.ids[1] > resolved[group][0]:
                    resolved[group] = (parsed.ids[1], state)
        for _conversation_id, state in resolved.values():
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
    # Prośby o opinię (D11) — karty opinii i „prośba czeka od …” przy rozmowie.
    requests = (
        await client_people.feedback_requests_for(db, live, owners=owners, today=today)
        if include_feedback
        else []
    )
    cards = await _contact_cards(
        db,
        mine,
        owners=owners,
        names=names,
        today=today,
        friday=friday,
        healths=healths,
        feedback_due=feedback_due_by_manager(requests),
    )
    if include_feedback:
        cards += await _feedback_cards(
            db,
            user=user,
            allowed=allowed,
            names=names,
            scope=scope,
            today=today,
            requests=requests,
        )
    cards += await _decision_cards(
        db, mine, owners=owners, names=names, today=today, healths=healths
    )
    demand_scope = await demand.demand_clients(db, user)
    include_demand = demand_scope is None or bool(demand_scope)
    if include_demand:
        cards += await _demand_cards(
            db,
            user=user,
            today=today,
            contracts_by_id={c.id: c for c in live},
        )
    if include_feedback:
        cards += await _data_cards(
            db,
            client_ids=await _my_clients(db, user=user, live=live, owners=owners),
            live=live,
        )
    order = {"contact": 0, "decision": 1, "feedback": 2, "demand": 3, "data": 4}
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
        "week_progress": await week_progress(
            db, [c.id for c in mine], monday=monday, friday=friday
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
    if key.variant == "decision_end":
        contract = await care_access.load_contract(db, key.ids[0], user)
        # Ta sama reguła co karta (``order_end_contracts``): ręczny PUT nie
        # założy wpisu „koniec projektu” dla dawno zakończonego zamówienia.
        today = business_today()
        if contract.end_date is None or not (
            today <= contract.end_date <= today + timedelta(days=ORDER_END_DAYS)
        ):
            raise _not_found()
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
    retry_on = waiting_retry_on(key.kind, column, retry_on, today)
    if column == "waiting" and (
        (retry_on is None and key.kind != "decision")
        or (retry_on is not None and retry_on <= today)
    ):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, NEEDS_RETRY)
    if key.variant == "decision_end":
        if column == "new":
            await board_state.clear(db, [key.raw])
            await db.flush()
            return _state_result(key.raw, key.kind, column, None, None, None)
        # Pierwszy ruch karty z samego końca zamówienia zakłada wpis
        # „Do przepięcia” (koniec projektu na datę końca) — dalej jak decyzja.
        contract = await care_access.load_contract(db, key.ids[0], user)
        item = await records.ensure_redeploy(
            db,
            contract.id,
            "project_end",
            due_on=contract.end_date,
            source="manual",
            source_id=None,
            actor_id=user.id,
        )
        if item is None:
            raise _not_found()
        await db.flush()
        key = board_state.CardKey(f"decision:{item.id}", "decision", (item.id,))
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
    return _state_result(key.raw, key.kind, column, scheduled_at, retry_on, note)


def waiting_retry_on(
    kind: str, column: str, retry_on: Optional[date], today: date
) -> Optional[date]:
    """Dzień ponowienia „Czeka”: popyt bez daty = „nie teraz” na 30 dni (R4);
    decyzja „czeka na front office” daty nie potrzebuje (K3)."""

    if column != "waiting":
        return retry_on
    if kind == "demand" and retry_on is None:
        return today + timedelta(days=demand.NOT_NOW_DAYS)
    return retry_on


def _state_result(
    raw: str,
    kind: str,
    column: str,
    scheduled_at: Optional[datetime],
    retry_on: Optional[date],
    note: Optional[str],
) -> dict[str, Any]:
    return {
        "key": raw,
        "kind": kind,
        "column": column,
        "scheduled_at": scheduled_at if column == "in_progress" else None,
        "retry_on": retry_on if column == "waiting" else None,
        "note": board_state.clean_note(note) if column != "new" else None,
    }
