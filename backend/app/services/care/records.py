"""Rozmowy, karty technologiczne i kolejka „Do przepięcia”.

Reguły z Compassa, które przenosimy, i błędy, których nie przenosimy:

* rozmowa zamyka punkt planu i może zgłosić przepięcie („chce zmiany”,
  „ryzyko odejścia”) — wpis aktywny jest jeden na kontrakt i powód;
* koniec projektu bierzemy z NAJNOWSZEJ informacji (karta sfinalizowana albo
  rozmowa); starsza data nie wygrywa z nowszym „nie wiem” (Compass: tylko
  najnowsza karta);
* koniec projektu < 60 dni → wpis „Do przepięcia” od razu przy zapisie i w
  dziennym przebiegu. Wpis odrzucony albo zamknięty dla tej samej daty nie
  wraca (Compass alarmował do skutku albo gubił alert, gdy stempel szedł przed
  wysyłką);
* karta sfinalizowana zostaje kompletna (status obowiązkowy).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Optional

from fastapi import HTTPException, status
from sqlalchemy import delete, func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.contract_care import (
    CareConversation,
    ClientArea,
    RedeployQueueItem,
    TechCard,
    TechCardSkill,
    TechCardVendor,
    TechVendor,
)
from app.services.care import plan as care_plan
from app.services.care import skills as care_skills
from app.services.care.access import CareContract
from app.services.contract_care_schema import REDEPLOY_ACTIVE_WHERE
from app.services.hr import audit

PROJECT_END_ALERT_DAYS = 60

_UNPROCESSABLE = status.HTTP_422_UNPROCESSABLE_ENTITY


def _clean(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


# ── Rozmowy ─────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ConversationInput:
    occurred_on: date
    channel: str
    satisfaction: Optional[int] = None
    note: Optional[str] = None
    attrition_risk: bool = False
    wants_change: bool = False
    project_end_on: Optional[date] = None
    client_hiring: bool = False
    client_hiring_note: Optional[str] = None
    follow_up_on: Optional[date] = None
    plan_item_id: Optional[int] = None


async def add_conversation(
    db: AsyncSession,
    contract: CareContract,
    payload: ConversationInput,
    *,
    actor_id: int,
    today: date,
    now: datetime,
) -> CareConversation:
    if payload.occurred_on > today:
        raise HTTPException(_UNPROCESSABLE, "Rozmowa nie może mieć daty z przyszłości.")
    if payload.follow_up_on is not None and payload.follow_up_on < payload.occurred_on:
        raise HTTPException(
            _UNPROCESSABLE, "Następny kontakt musi być po dacie rozmowy."
        )
    conversation = CareConversation(
        contract_id=contract.id,
        author_user_id=actor_id,
        occurred_on=payload.occurred_on,
        channel=payload.channel,
        satisfaction=payload.satisfaction,
        note=_clean(payload.note),
        attrition_risk=payload.attrition_risk,
        wants_change=payload.wants_change,
        project_end_on=payload.project_end_on,
        client_hiring=payload.client_hiring,
        client_hiring_note=_clean(payload.client_hiring_note)
        if payload.client_hiring
        else None,
        follow_up_on=payload.follow_up_on,
    )
    db.add(conversation)
    await db.flush()
    closed = await care_plan.close_with_conversation(
        db,
        conversation,
        actor_id=actor_id,
        now=now,
        plan_item_id=payload.plan_item_id,
    )
    if payload.plan_item_id is not None and closed is None:
        raise HTTPException(_UNPROCESSABLE, "Ten punkt planu jest już zamknięty.")
    for reason, flagged in (
        ("wants_change", payload.wants_change),
        ("attrition_risk", payload.attrition_risk),
    ):
        if flagged:
            await ensure_redeploy(
                db,
                contract.id,
                reason,
                due_on=None,
                source="conversation",
                source_id=conversation.id,
                actor_id=actor_id,
            )
    await sync_project_end(db, contract.id, today=today, actor_id=actor_id)
    audit.record(
        db,
        actor_user_id=actor_id,
        subject_user_id=None,
        entity_type="care_conversation",
        entity_id=conversation.id,
        action="care.conversation_added",
        details={
            "contract_id": contract.id,
            "channel": payload.channel,
            "plan_item_id": closed.id if closed else None,
            "signals": [
                name
                for name, on in (
                    ("attrition_risk", payload.attrition_risk),
                    ("wants_change", payload.wants_change),
                    ("project_end", payload.project_end_on is not None),
                    ("client_hiring", payload.client_hiring),
                )
                if on
            ],
        },
    )
    return conversation


# ── Karty technologiczne ────────────────────────────────────────────────────


@dataclass(frozen=True)
class TechCardInput:
    interview_on: date
    finalize: bool = False
    status: Optional[str] = None
    satisfaction: Optional[int] = None
    client_area_id: Optional[int] = None
    new_area_name: Optional[str] = None
    skill_ids: Sequence[int] = ()
    skill_names: Sequence[str] = ()
    vendor_ids: Sequence[int] = ()
    new_vendor_names: Sequence[str] = ()
    hiring: Optional[bool] = None
    hiring_source: Optional[str] = None
    hiring_roles: Sequence[str] = ()
    project_end_on: Optional[date] = None
    project_end_unknown: bool = False
    team_size: Optional[str] = None
    team_externals: Optional[int] = None
    initiatives: Sequence[dict[str, Any]] = field(default_factory=tuple)
    memorable_quote: Optional[str] = None
    note: Optional[str] = None


async def _upsert_area(
    db: AsyncSession, client_id: int, name: str, *, actor_id: int
) -> int:
    key = care_skills.name_key(name)
    statement = (
        insert(ClientArea)
        .values(
            client_id=client_id, name=name.strip(), name_key=key, created_by=actor_id
        )
        .on_conflict_do_nothing(index_elements=["client_id", "name_key"])
        .returning(ClientArea.id)
    )
    created = (await db.execute(statement)).scalar_one_or_none()
    if created is not None:
        return created
    return (
        await db.scalars(
            select(ClientArea.id).where(
                ClientArea.client_id == client_id, ClientArea.name_key == key
            )
        )
    ).one()


async def add_area(
    db: AsyncSession, client_id: int, name: str, *, actor_id: int
) -> ClientArea:
    if not _clean(name):
        raise HTTPException(_UNPROCESSABLE, "Podaj nazwę obszaru.")
    area_id = await _upsert_area(db, client_id, name, actor_id=actor_id)
    return await db.get(ClientArea, area_id)


async def upsert_vendor(db: AsyncSession, name: str, *, actor_id: int) -> int:
    cleaned = _clean(name)
    if not cleaned:
        raise HTTPException(_UNPROCESSABLE, "Podaj nazwę dostawcy.")
    key = care_skills.name_key(cleaned)
    statement = (
        insert(TechVendor)
        .values(name=cleaned, name_key=key, created_by=actor_id)
        .on_conflict_do_nothing(index_elements=["name_key"])
        .returning(TechVendor.id)
    )
    created = (await db.execute(statement)).scalar_one_or_none()
    if created is not None:
        return created
    return (
        await db.scalars(select(TechVendor.id).where(TechVendor.name_key == key))
    ).one()


def _normalized_initiatives(raw: Iterable[dict[str, Any]]) -> list[dict[str, str]]:
    out = []
    for item in raw:
        name = _clean(str(item.get("name") or ""))
        if not name:
            continue
        out.append(
            {
                "name": name[:200],
                "kind": str(item.get("kind") or "inne"),
                "priority": str(item.get("priority") or "normalny"),
            }
        )
    return out


async def save_tech_card(
    db: AsyncSession,
    contract: CareContract,
    payload: TechCardInput,
    *,
    actor_id: int,
    today: date,
    now: datetime,
    card: Optional[TechCard] = None,
) -> TechCard:
    """Zakłada albo zmienia kartę kontraktu (z technologiami, dostawcami, obszarem)."""

    if payload.interview_on > today:
        raise HTTPException(_UNPROCESSABLE, "Rozmowa nie może mieć daty z przyszłości.")
    final = payload.finalize or (card is not None and not card.is_draft)
    has_technology = bool(payload.skill_ids) or any(
        _clean(name) for name in payload.skill_names
    )
    if final and payload.status is None:
        raise HTTPException(_UNPROCESSABLE, "Karta gotowa potrzebuje statusu rozmowy.")
    if final and payload.status == "ok" and not has_technology:
        raise HTTPException(
            _UNPROCESSABLE,
            "Karta ze statusem „OK” potrzebuje co najmniej jednej technologii.",
        )
    if payload.hiring is not True and payload.hiring_source is not None:
        raise HTTPException(
            _UNPROCESSABLE,
            "Źródło informacji o rekrutacjach podaje się tylko przy „klient zatrudnia”.",
        )
    missing = set(payload.skill_ids) - await care_skills.existing_skill_ids(
        db, payload.skill_ids
    )
    if missing:
        raise HTTPException(
            _UNPROCESSABLE, "Część technologii nie istnieje w słowniku."
        )

    area_id = payload.client_area_id
    if area_id is not None:
        area = await db.get(ClientArea, area_id)
        if area is None or area.client_id != contract.client_id:
            raise HTTPException(
                _UNPROCESSABLE, "Ten obszar nie należy do klienta kontraktu."
            )
    elif _clean(payload.new_area_name):
        area_id = await _upsert_area(
            db, contract.client_id, payload.new_area_name or "", actor_id=actor_id
        )

    vendor_ids = set(payload.vendor_ids)
    if vendor_ids:
        known = set(
            (
                await db.scalars(
                    select(TechVendor.id).where(TechVendor.id.in_(sorted(vendor_ids)))
                )
            ).all()
        )
        if vendor_ids - known:
            raise HTTPException(
                _UNPROCESSABLE, "Część dostawców nie istnieje w słowniku."
            )
    for name in payload.new_vendor_names:
        if _clean(name):
            vendor_ids.add(await upsert_vendor(db, name, actor_id=actor_id))

    resolved = await care_skills.resolve_card_names(
        db,
        payload.skill_names,
        previous_unrecognized=(card.unrecognized_skills if card is not None else []),
        actor_id=actor_id,
    )
    skill_ids = set(payload.skill_ids) | resolved.skill_ids

    created = card is None
    if card is None:
        card = TechCard(
            contract_id=contract.id,
            client_id=contract.client_id,
            author_user_id=actor_id,
            is_draft=True,
        )
        db.add(card)
    card.interview_on = payload.interview_on
    card.status = payload.status
    card.satisfaction = payload.satisfaction
    card.client_area_id = area_id
    card.hiring = payload.hiring
    card.hiring_source = payload.hiring_source if payload.hiring is True else None
    card.hiring_roles = (
        [role.strip()[:120] for role in payload.hiring_roles if role and role.strip()]
        if payload.hiring is True
        else []
    )
    card.project_end_unknown = payload.project_end_unknown
    card.project_end_on = (
        None if payload.project_end_unknown else payload.project_end_on
    )
    card.team_size = _clean(payload.team_size)
    card.team_externals = payload.team_externals
    card.initiatives = _normalized_initiatives(payload.initiatives)
    card.memorable_quote = _clean(payload.memorable_quote)
    card.note = _clean(payload.note)
    card.unrecognized_skills = resolved.unrecognized
    if final and card.is_draft:
        card.is_draft = False
        card.finalized_at = now
    await db.flush()

    await db.execute(delete(TechCardSkill).where(TechCardSkill.card_id == card.id))
    if skill_ids:
        await db.execute(
            insert(TechCardSkill).values(
                [{"card_id": card.id, "skill_id": sid} for sid in sorted(skill_ids)]
            )
        )
    await db.execute(delete(TechCardVendor).where(TechCardVendor.card_id == card.id))
    if vendor_ids:
        await db.execute(
            insert(TechCardVendor).values(
                [{"card_id": card.id, "vendor_id": vid} for vid in sorted(vendor_ids)]
            )
        )
    await sync_project_end(db, contract.id, today=today, actor_id=actor_id)
    audit.record(
        db,
        actor_user_id=actor_id,
        subject_user_id=None,
        entity_type="tech_card",
        entity_id=card.id,
        action="care.tech_card_created" if created else "care.tech_card_updated",
        details={
            "contract_id": contract.id,
            "finalized": not card.is_draft,
            "skills": len(skill_ids),
            "unrecognized": len(resolved.unrecognized),
        },
    )
    return card


async def card_relations(
    db: AsyncSession, card_ids: Sequence[int]
) -> tuple[dict[int, list[int]], dict[int, list[int]]]:
    ids = sorted(set(card_ids))
    skills: dict[int, list[int]] = {cid: [] for cid in ids}
    vendors: dict[int, list[int]] = {cid: [] for cid in ids}
    if not ids:
        return skills, vendors
    for card_id, skill_id in (
        await db.execute(
            select(TechCardSkill.card_id, TechCardSkill.skill_id).where(
                TechCardSkill.card_id.in_(ids)
            )
        )
    ).all():
        skills[card_id].append(skill_id)
    for card_id, vendor_id in (
        await db.execute(
            select(TechCardVendor.card_id, TechCardVendor.vendor_id).where(
                TechCardVendor.card_id.in_(ids)
            )
        )
    ).all():
        vendors[card_id].append(vendor_id)
    return skills, vendors


# ── „Do przepięcia” ─────────────────────────────────────────────────────────


async def ensure_redeploy(
    db: AsyncSession,
    contract_id: int,
    reason: str,
    *,
    due_on: Optional[date],
    source: str,
    source_id: Optional[int],
    actor_id: Optional[int],
) -> Optional[RedeployQueueItem]:
    """Aktywny wpis dla kontraktu i powodu (idempotentnie).

    Koniec projektu: wpis zamknięty albo odrzucony dla TEJ SAMEJ daty nie
    wraca; aktywny wpis z inną datą dostaje nową datę.
    """

    active = await db.scalar(
        select(RedeployQueueItem)
        .where(
            RedeployQueueItem.contract_id == contract_id,
            RedeployQueueItem.reason == reason,
            RedeployQueueItem.status.in_(("open", "in_progress")),
        )
        .with_for_update()
    )
    if active is not None:
        if reason == "project_end" and due_on is not None and active.due_on != due_on:
            active.due_on = due_on
            active.source = source
            active.source_id = source_id
            active.updated_by = actor_id
        return active
    if reason == "project_end":
        handled = await db.scalar(
            select(func.count())
            .select_from(RedeployQueueItem)
            .where(
                RedeployQueueItem.contract_id == contract_id,
                RedeployQueueItem.reason == reason,
                RedeployQueueItem.due_on == due_on,
            )
        )
        if handled:
            return None
    statement = (
        insert(RedeployQueueItem)
        .values(
            contract_id=contract_id,
            reason=reason,
            status="open",
            due_on=due_on,
            source=source,
            source_id=source_id,
            created_by=actor_id,
            updated_by=actor_id,
        )
        .on_conflict_do_nothing(
            index_elements=["contract_id", "reason"],
            index_where=text(REDEPLOY_ACTIVE_WHERE),
        )
        .returning(RedeployQueueItem.id)
    )
    created = (await db.execute(statement)).scalar_one_or_none()
    return await db.get(RedeployQueueItem, created) if created is not None else None


@dataclass(frozen=True)
class ProjectEnd:
    end_on: Optional[date]
    source: str  # tech_card | conversation
    source_id: int
    known_on: date


async def latest_project_end(
    db: AsyncSession, contract_id: int
) -> Optional[ProjectEnd]:
    """Najnowsza informacja o końcu projektu (karta sfinalizowana albo rozmowa)."""

    card = (
        await db.execute(
            select(TechCard.id, TechCard.interview_on, TechCard.project_end_on)
            .where(
                TechCard.contract_id == contract_id,
                TechCard.is_draft.is_(False),
                (TechCard.project_end_on.is_not(None)) | TechCard.project_end_unknown,
            )
            .order_by(TechCard.interview_on.desc(), TechCard.id.desc())
            .limit(1)
        )
    ).first()
    conversation = (
        await db.execute(
            select(
                CareConversation.id,
                CareConversation.occurred_on,
                CareConversation.project_end_on,
            )
            .where(
                CareConversation.contract_id == contract_id,
                CareConversation.project_end_on.is_not(None),
            )
            .order_by(CareConversation.occurred_on.desc(), CareConversation.id.desc())
            .limit(1)
        )
    ).first()
    options = []
    if card is not None:
        options.append(ProjectEnd(card[2], "tech_card", card[0], card[1]))
    if conversation is not None:
        options.append(
            ProjectEnd(
                conversation[2], "conversation", conversation[0], conversation[1]
            )
        )
    if not options:
        return None
    # Ta sama data informacji: rozmowa jest późniejszym zapisem niż karta.
    return max(options, key=lambda end: (end.known_on, end.source == "conversation"))


async def sync_project_end(
    db: AsyncSession, contract_id: int, *, today: date, actor_id: Optional[int]
) -> Optional[RedeployQueueItem]:
    end = await latest_project_end(db, contract_id)
    if end is None or end.end_on is None:
        return None
    if not today <= end.end_on <= today + timedelta(days=PROJECT_END_ALERT_DAYS):
        return None
    return await ensure_redeploy(
        db,
        contract_id,
        "project_end",
        due_on=end.end_on,
        source=end.source,
        source_id=end.source_id,
        actor_id=actor_id,
    )


async def update_redeploy(
    db: AsyncSession,
    item: RedeployQueueItem,
    *,
    new_status: Optional[str],
    note: Optional[str],
    note_set: bool,
    actor_id: int,
    now: datetime,
) -> RedeployQueueItem:
    if new_status is not None and new_status != item.status:
        if new_status in {"open", "in_progress"} and item.status not in {
            "open",
            "in_progress",
        }:
            clash = await db.scalar(
                select(func.count())
                .select_from(RedeployQueueItem)
                .where(
                    RedeployQueueItem.contract_id == item.contract_id,
                    RedeployQueueItem.reason == item.reason,
                    RedeployQueueItem.status.in_(("open", "in_progress")),
                    RedeployQueueItem.id != item.id,
                )
            )
            if clash:
                raise HTTPException(
                    status.HTTP_409_CONFLICT,
                    "Ten konsultant ma już aktywny wpis z tym powodem.",
                )
        item.status = new_status
        item.resolved_at = None if new_status in {"open", "in_progress"} else now
    if note_set:
        item.note = _clean(note)
    item.updated_by = actor_id
    return item
