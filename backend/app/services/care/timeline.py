"""Oś konsultanta (panel boczny „Ten tydzień”, D15, 17.10.2026).

Od rekrutacji, z której przyszedł (``contracts.job_id``), przez start
kontraktu, rozmowy opieki i karty technologiczne, opinie klienta, zamówienia
i ich końce, po sygnały „Do przepięcia” i przekazania do front office.
Najbliższy otwarty punkt planu i przyszłe końce stoją na końcu jako
zdarzenia „przed nami” (``future``).

Bez stawek (zamówienie to tytuł, status i daty) i bez danych o zdrowiu —
rozmowy opieki ich nie zbierają. Opinie klienta tylko dla ról z D11
(trasa przekazuje ``include_feedback``): Finanse widzą oś bez nich.

Sprawy kontraktu (22.10.2026): założenie, podpięcie i zamknięcie z serwisu
spraw (``admin_cases.queries.contract_case_events``) — tytuł i obszar, bez
treści maili; bez ``may_read`` czytającego tytuł zastępczy „Sprawa: <obszar>”.

Etap 3 (O8, O10): zmiany rytmu kontaktu z powodem i autorem, powrót rytmu
po dacie „do kiedy” (przed nami, gdy w przyszłości) i zmiany opiekuna ze
śladu ``care.owner_set`` z powodem — zmianę widzi DL klienta na osi.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Optional
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scheduling import DEFAULT_TZ
from app.models.client_order import ClientOrder, ClientOrderStatus
from app.models.contact import Contact
from app.models.contract_care import (
    CareCadencePeriod,
    CareConversation,
    CarePlanItem,
    ClientArea,
    ClientFeedbackScore,
    ClientFeedbackSession,
    RedeployQueueItem,
    TechCard,
    TechCardSkill,
)
from app.models.hr_ops import HrAuditEvent
from app.models.job import Job
from app.models.user import User
from app.services.care import access as care_access
from app.services.care import client_feedback, front_office
from app.services.care import plan as care_plan
from app.services.care.access import CareContract
from app.services.care.assignment import OWNER_REASON_LABELS
from app.services.care.cadence import LEVEL_LABELS, REASON_LABELS
from app.services.care.cadence_rules import transitions
from app.services.care.week import client_managers, conversation_signals, excerpt
from app.services.job_working_title import display_title

REDEPLOY_REASON_LABELS = {
    "project_end": "koniec projektu",
    "wants_change": "chce zmiany projektu",
    "attrition_risk": "ryzyko odejścia",
}
REDEPLOY_STATUS_LABELS = {
    "open": "nowe",
    "in_progress": "w toku",
    "done": "przepięty",
    "dismissed": "nie dotyczy",
}
SIGNAL_LABELS = {
    "attrition_risk": "ryzyko odejścia",
    "wants_change": "chce zmiany projektu",
    "project_end": "zna koniec projektu",
    "client_hiring": "klient zatrudnia",
}
EXTENSION_LABELS = {
    "yes": "tak",
    "likely": "raczej tak",
    "unsure": "nie wiem",
    "no": "nie",
}
ORDER_STATUS_LABELS = {
    "draft": "szkic",
    "active": "aktywne",
    "paused": "wstrzymane",
    "completed": "zakończone",
}
# Kolejność zdarzeń z tego samego dnia: najpierw to, co było wcześniej w życiu kontraktu.
_KIND_ORDER = {
    "recruitment": 0,
    "start": 1,
    "order_start": 2,
    "conversation": 3,
    "tech_card": 4,
    "feedback": 5,
    "redeploy": 6,
    "owner": 6,
    "cadence": 6,
    "cadence_return": 6,
    "handoff": 7,
    "case_opened": 7,
    "case_linked": 7,
    "case_closed": 7,
    "plan": 8,
    "order_end": 9,
    "contract_end": 10,
}


def _local(moment: Optional[datetime]) -> Optional[date]:
    if moment is None:
        return None
    return moment.astimezone(ZoneInfo(DEFAULT_TZ)).date()


CHANNEL_LABELS = {"phone": "telefon", "meeting": "spotkanie", "chat": "czat"}


def conversation_title(
    *,
    plan_kind: Optional[str],
    channel: Optional[str],
    satisfaction: Optional[int],
    signals: list[str],
) -> str:
    """„Rozmowa · telefon · 4/5 · chce zmiany projektu” (makieta P2).

    Rozmowa, która zamknęła punkt planu, mówi który („dzień 7”) zamiast formy.
    Cytat z notatki idzie do ``detail``.
    """

    parts = ["Rozmowa"]
    if plan_kind is not None:
        parts.append(care_plan.KIND_LABELS.get(plan_kind, plan_kind).lower())
    elif channel:
        parts.append(CHANNEL_LABELS.get(channel, channel))
    if satisfaction:
        parts.append(f"{satisfaction}/5")
    parts.extend(SIGNAL_LABELS[s] for s in signals if s in SIGNAL_LABELS)
    return " · ".join(parts)


def _event(
    kind: str,
    on: Optional[date],
    title: str,
    *,
    today: date,
    detail: Optional[str] = None,
    link: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    if on is None:
        return None
    return {
        "kind": kind,
        "on": on,
        "title": title,
        "detail": detail,
        "link": link,
        "future": on > today,
    }


async def _recruitment(
    db: AsyncSession, contract: CareContract, today: date
) -> Optional[dict[str, Any]]:
    if contract.job_id is None:
        return None
    row = (
        await db.execute(
            select(Job, func.coalesce(Job.opened_at, Job.created_at)).where(
                Job.id == contract.job_id
            )
        )
    ).first()
    if row is None:
        return None
    job, opened = row
    names = await care_access.user_names(db, [job.delivery_lead_id])
    lead = names.get(job.delivery_lead_id) if job.delivery_lead_id else None
    return _event(
        "recruitment",
        _local(opened),
        f"Rekrutacja „{display_title(job)}”",
        today=today,
        detail="front office" + (f" · prowadzi {lead}" if lead else ""),
        link=f"/jobs/{job.id}",
    )


async def _conversations(
    db: AsyncSession, contract_id: int, today: date
) -> list[dict[str, Any]]:
    conversations = (
        await db.scalars(
            select(CareConversation)
            .where(CareConversation.contract_id == contract_id)
            .order_by(CareConversation.occurred_on, CareConversation.id)
        )
    ).all()
    closed = {
        conversation_id: kind
        for conversation_id, kind in (
            await db.execute(
                select(CarePlanItem.done_conversation_id, CarePlanItem.kind)
                .where(
                    CarePlanItem.contract_id == contract_id,
                    CarePlanItem.done_conversation_id.is_not(None),
                )
                .order_by(CarePlanItem.due_on.desc())
            )
        ).all()
    }
    out = []
    for conversation in conversations:
        note = excerpt(conversation.note)
        out.append(
            _event(
                "conversation",
                conversation.occurred_on,
                conversation_title(
                    plan_kind=closed.get(conversation.id),
                    channel=conversation.channel,
                    satisfaction=conversation.satisfaction,
                    signals=conversation_signals(conversation),
                ),
                today=today,
                detail=f"„{note}”" if note else None,
            )
        )
    return out


async def _tech_cards(
    db: AsyncSession, contract_id: int, today: date
) -> list[dict[str, Any]]:
    rows = (
        await db.execute(
            select(TechCard.id, TechCard.interview_on, ClientArea.name)
            .outerjoin(ClientArea, ClientArea.id == TechCard.client_area_id)
            .where(TechCard.contract_id == contract_id, TechCard.is_draft.is_(False))
            .order_by(TechCard.interview_on, TechCard.id)
        )
    ).all()
    counts = dict(
        (
            await db.execute(
                select(TechCardSkill.card_id, func.count())
                .where(TechCardSkill.card_id.in_([row[0] for row in rows] or [-1]))
                .group_by(TechCardSkill.card_id)
            )
        ).all()
    )
    out = []
    for card_id, interview_on, area in rows:
        parts = [area] if area else []
        if counts.get(card_id):
            parts.append(f"technologie: {counts[card_id]}")
        item = _event(
            "tech_card",
            interview_on,
            "Karta technologiczna",
            today=today,
            detail=" · ".join(parts) or None,
        )
        if item is not None:
            # „Edytuj” w historii szuka karty po id (dwie karty jednego dnia).
            item["tech_card_id"] = card_id
        out.append(item)
    return out


async def _feedback(
    db: AsyncSession, contract_id: int, today: date
) -> list[dict[str, Any]]:
    rows = (
        await db.execute(
            select(ClientFeedbackScore, ClientFeedbackSession, Contact.name)
            .join(
                ClientFeedbackSession,
                ClientFeedbackSession.id == ClientFeedbackScore.session_id,
            )
            .outerjoin(Contact, Contact.id == ClientFeedbackSession.contact_id)
            .where(ClientFeedbackScore.contract_id == contract_id)
            .order_by(ClientFeedbackSession.held_on, ClientFeedbackSession.id)
        )
    ).all()
    out = []
    for score, session, contact_name in rows:
        # „Opinia menedżera · 4,0 · przedłużenie: tak”, kto w ``detail`` (makieta P2).
        parts = ["Opinia menedżera"]
        average = client_feedback.average(
            [score.quality, score.communication, score.autonomy]
        )
        if average is not None:
            parts.append(f"{average:.1f}".replace(".", ","))
        if session.extension_outlook:
            parts.append(
                "przedłużenie: "
                + EXTENSION_LABELS.get(
                    session.extension_outlook, session.extension_outlook
                )
            )
        out.append(
            _event(
                "feedback",
                session.held_on,
                " · ".join(parts),
                today=today,
                detail=contact_name or None,
            )
        )
    return out


async def _orders(
    db: AsyncSession, contract_id: int, today: date
) -> list[dict[str, Any]]:
    # Tylko tytuł, status i daty — stawki zamówienia nie wychodzą na oś.
    rows = (
        await db.execute(
            select(
                ClientOrder.title,
                ClientOrder.status,
                ClientOrder.start_date,
                ClientOrder.end_date,
            )
            .where(
                ClientOrder.contract_id == contract_id,
                ClientOrder.status != ClientOrderStatus.cancelled,
            )
            .order_by(ClientOrder.start_date.asc().nulls_last(), ClientOrder.id)
        )
    ).all()
    out = []
    for title, order_status, start, end in rows:
        value = getattr(order_status, "value", order_status)
        label = ORDER_STATUS_LABELS.get(value, value)
        out.append(
            _event(
                "order_start",
                start,
                f"Zamówienie „{title}”",
                today=today,
                detail=label,
            )
        )
        out.append(
            _event(
                "order_end",
                end,
                f"Koniec zamówienia „{title}”",
                today=today,
            )
        )
    return out


async def _redeploy(
    db: AsyncSession, contract_id: int, today: date
) -> list[dict[str, Any]]:
    items = (
        await db.scalars(
            select(RedeployQueueItem)
            .where(RedeployQueueItem.contract_id == contract_id)
            .order_by(RedeployQueueItem.created_at, RedeployQueueItem.id)
        )
    ).all()
    return [
        _event(
            "redeploy",
            _local(item.created_at),
            "Do przepięcia: " + REDEPLOY_REASON_LABELS.get(item.reason, item.reason),
            today=today,
            detail=REDEPLOY_STATUS_LABELS.get(item.status, item.status),
        )
        for item in items
    ]


async def _handoffs(
    db: AsyncSession, contract_id: int, today: date
) -> list[dict[str, Any]]:
    events = (await front_office.handoffs(db, [contract_id]))[contract_id]
    names = await care_access.user_names(db, [e.actor_user_id for e in events])
    out = []
    for event in events:
        jobs = len((event.details or {}).get("job_ids") or [])
        parts = []
        if event.actor_user_id in names:
            parts.append(names[event.actor_user_id])
        if jobs:
            parts.append(f"pasujące rekrutacje: {jobs}")
        out.append(
            _event(
                "handoff",
                front_office.local_day(event),
                "Przekazano do front office",
                today=today,
                detail=" · ".join(parts) or None,
            )
        )
    return out


async def _cadence(
    db: AsyncSession, contract: CareContract, today: date
) -> list[dict[str, Any]]:
    periods: list[CareCadencePeriod] = (
        await care_plan.periods_by_contract(db, [contract.id])
    ).get(contract.id, [])
    if not periods:
        return []
    names = await care_access.user_names(db, [p.created_by for p in periods])
    out = []
    for step in transitions(contract.start_date or date.min, periods):
        label = LEVEL_LABELS.get(step.level, step.level)
        if step.kind == "change":
            period = step.period
            parts = [REASON_LABELS.get(period.reason, period.reason)]
            note = excerpt(period.note, 120)
            if note:
                parts.append(f"„{note}”")
            if period.created_by in names:
                parts.append(names[period.created_by])
            if period.until_on is not None:
                parts.append(f"do {period.until_on.strftime('%d.%m.%Y')}")
            out.append(
                _event(
                    "cadence",
                    step.on,
                    f"Rytm: {label}",
                    today=today,
                    detail=" · ".join(parts),
                )
            )
        elif step.kind == "return":
            out.append(
                _event("cadence_return", step.on, f"Rytm wraca: {label}", today=today)
            )
    return out


async def _owners(
    db: AsyncSession, contract_id: int, today: date
) -> list[dict[str, Any]]:
    events = (
        await db.scalars(
            select(HrAuditEvent)
            .where(
                HrAuditEvent.entity_type == "contract",
                HrAuditEvent.entity_id == str(contract_id),
                HrAuditEvent.action == "care.owner_set",
            )
            .order_by(HrAuditEvent.created_at, HrAuditEvent.id)
        )
    ).all()
    if not events:
        return []
    names = await care_access.user_names(
        db,
        [
            *(event.actor_user_id for event in events),
            *((event.details or {}).get("owner") for event in events),
        ],
    )
    out = []
    for event in events:
        details = event.details or {}
        owner = details.get("owner")
        title = (
            f"Opiekun: {names.get(owner, '')}"
            if owner is not None
            else "Opiekun: domyślny (klient albo DL)"
        )
        parts = []
        if details.get("reason"):
            parts.append(OWNER_REASON_LABELS.get(details["reason"], details["reason"]))
        if event.actor_user_id in names:
            parts.append(names[event.actor_user_id])
        out.append(
            _event(
                "owner",
                front_office.local_day(event),
                title,
                today=today,
                detail=" · ".join(parts) or None,
            )
        )
    return out


MAIL_LINKED_DETAIL = "powiązana po e-mailu z kontraktu"


def case_event_text(
    kind: str,
    title: str,
    *,
    from_mail: bool,
    mail_linked: bool,
    person: Optional[str],
    checklist: tuple[int, int],
) -> tuple[str, Optional[str]]:
    """Tytuł i dopisek zdarzenia sprawy na osi (makieta S3, czysta reguła).

    * założenie: „Sprawa otwarta: X · Natalia O.”, z maila — „Sprawa z maila:
      X”, a gdy czytnik sam ją powiązał po e-mailu konsultanta — dopisek
      „powiązana po e-mailu z kontraktu”;
    * zamknięcie: „Sprawa zamknięta: X 4/4” (checklista, gdy jest);
    * podpięcie ręczne: „Sprawa podpięta: X”.

    ``person`` jest ``None``, gdy czytający nie widzi osoby (tytuł zastępczy).
    """

    if kind == "case_opened":
        if from_mail:
            return (
                f"Sprawa z maila: {title}",
                MAIL_LINKED_DETAIL if mail_linked else person,
            )
        return f"Sprawa otwarta: {title}", person
    if kind == "case_closed":
        done, total = checklist
        return (
            f"Sprawa zamknięta: {title}" + (f" {done}/{total}" if total else ""),
            None,
        )
    return f"Sprawa podpięta: {title}", person


async def _cases(
    db: AsyncSession, contract_id: int, today: date, viewer: User
) -> list[dict[str, Any]]:
    """Sprawy kontraktu z serwisu spraw (``contract_case_events``) — bez treści."""

    # Import w funkcji: moduł spraw ciągnie serwisy HR, a oś jest w opiece.
    from app.models.admin_case import AdminCase  # noqa: PLC0415
    from app.services.admin_cases.queries import (  # noqa: PLC0415
        contract_case_events,
        redact_case_title,
    )
    from app.services.care.card import checklist_progress  # noqa: PLC0415

    events = await contract_case_events(db, contract_id, viewer)
    case_ids = sorted({event["case_id"] for event in events})
    cases = (
        {
            case.id: case
            for case in (
                await db.scalars(select(AdminCase).where(AdminCase.id.in_(case_ids)))
            ).all()
        }
        if case_ids
        else {}
    )
    # Powiązanie przez czytnik poczty (nadawca = e-mail konsultanta z kontraktu).
    mail_linked = (
        {
            int(entity_id)
            for (entity_id,) in (
                await db.execute(
                    select(HrAuditEvent.entity_id).where(
                        HrAuditEvent.entity_type == "admin_case",
                        HrAuditEvent.action == "case_linked",
                        HrAuditEvent.entity_id.in_([str(cid) for cid in case_ids]),
                        HrAuditEvent.details["source"].astext == "mail_sender",
                    )
                )
            ).all()
        }
        if case_ids
        else set()
    )
    people = {
        case.id: case.created_by or case.assignee_user_id
        for case in cases.values()
        if redact_case_title(case, viewer) is None
    }
    names = await care_access.user_names(db, [uid for uid in people.values() if uid])

    out = []
    for event in events:
        case = cases.get(event["case_id"])
        from_mail = case is not None and case.source == "mail"
        if event["kind"] == "case_linked" and from_mail and case.id in mail_linked:
            # Jedno zdarzenie „Sprawa z maila … powiązana po e-mailu”.
            continue
        person_id = people.get(event["case_id"])
        title, detail = case_event_text(
            event["kind"],
            event["title"],
            from_mail=from_mail,
            mail_linked=case is not None and case.id in mail_linked,
            person=names.get(person_id) if person_id else None,
            checklist=checklist_progress(case.checklist) if case else (0, 0),
        )
        at = event["at"]
        on = _local(at) if isinstance(at, datetime) else at
        item = _event(
            event["kind"],
            on,
            title,
            today=today,
            detail=detail,
            link=f"/people/cases/{event['case_id']}",
        )
        if item is not None:
            item["case_id"] = event["case_id"]
        out.append(item)
    return out


#: Punkt planu na osi słowami opiekuna („Plan: kontakt przed końcem zamówienia”).
PLAN_TITLES = {
    "day_7": "rozmowa „dzień 7”",
    "cadence": "rozmowa według rytmu",
    "pre_end": "kontakt przed końcem zamówienia",
}


def _days_text(count: int) -> str:
    return "1 dzień" if count == 1 else f"{count} dni"


def plan_event_text(kind: str, due_on: date, today: date) -> tuple[str, str]:
    """„Plan: kontakt przed końcem zamówienia” + „za 2 dni” / „dziś” / „zaległy 3 dni”."""

    label = PLAN_TITLES.get(kind) or care_plan.KIND_LABELS.get(kind, kind).lower()
    days = (due_on - today).days
    if days < 0:
        detail = f"zaległy {_days_text(-days)}"
    elif days == 0:
        detail = "dziś"
    elif days == 1:
        detail = "jutro"
    else:
        detail = f"za {days} dni"
    return f"Plan: {label}", detail


async def _next_plan(
    db: AsyncSession, contract_id: int, today: date
) -> Optional[dict[str, Any]]:
    item = await db.scalar(
        select(CarePlanItem)
        .where(
            CarePlanItem.contract_id == contract_id,
            CarePlanItem.status == "open",
        )
        .order_by(CarePlanItem.due_on, CarePlanItem.id)
        .limit(1)
    )
    if item is None:
        return None
    title, detail = plan_event_text(item.kind, item.due_on, today)
    event = _event("plan", item.due_on, title, today=today, detail=detail)
    if event is not None:
        # Zaległy punkt nie jest historią — stoi na końcu osi jak przyszły.
        event["future"] = True
    return event


async def contract_timeline(
    db: AsyncSession,
    contract: CareContract,
    *,
    today: date,
    include_feedback: bool,
    viewer: User,
) -> dict[str, Any]:
    events: list[Optional[dict[str, Any]]] = [
        await _recruitment(db, contract, today),
        _event(
            "start",
            contract.start_date,
            "Start kontraktu",
            today=today,
            detail=contract.job_title,
        ),
        *(await _conversations(db, contract.id, today)),
        *(await _tech_cards(db, contract.id, today)),
        *(await _orders(db, contract.id, today)),
        *(await _redeploy(db, contract.id, today)),
        *(await _handoffs(db, contract.id, today)),
        *(await _cadence(db, contract, today)),
        *(await _owners(db, contract.id, today)),
        *(await _cases(db, contract.id, today, viewer)),
        _event(
            "contract_end",
            contract.contract_end_date,
            "Koniec umowy",
            today=today,
        ),
    ]
    if include_feedback:
        events.extend(await _feedback(db, contract.id, today))
    if contract.is_live:
        events.append(await _next_plan(db, contract.id, today))
    ordered = sorted(
        (event for event in events if event is not None),
        key=lambda e: (e["future"], e["on"], _KIND_ORDER.get(e["kind"], 99)),
    )
    manager = (await client_managers(db, [contract])).get(contract.id)
    owner = (await care_access.effective_owners(db, [contract]))[contract.id]
    names = await care_access.user_names(db, [owner.user_id])
    active = (await front_office.active_redeploy(db, [contract.id]))[contract.id]
    return {
        "contract": {
            "id": contract.id,
            "candidate_id": contract.candidate_id,
            "candidate_name": contract.candidate_name,
            "client_id": contract.client_id,
            "client_name": contract.client_name,
            "job_id": contract.job_id,
            "job_title": contract.job_title,
            "status": contract.status,
            "is_live": contract.is_live,
            "start_date": contract.start_date,
            "end_date": contract.end_date,
        },
        "owner": (
            {"id": owner.user_id, "name": names.get(owner.user_id, "")}
            if owner.user_id is not None
            else None
        ),
        "manager": manager,
        "signals": sorted({item.reason for item in active}),
        "front_office_reasons": front_office.eligibility(contract, active, today),
        "events": ordered,
        "feedback_visible": include_feedback,
    }
