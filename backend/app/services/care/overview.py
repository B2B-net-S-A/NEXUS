"""Zakładka „Opieka” kontraktu i lista „Moi konsultanci” (odczyt dla tras ``/api/care``).

Następny kontakt liczy ``plan.next_contact`` — ta sama reguła co dzienny
przebieg (``reminders``) i „Ten tydzień” (``week``).
"""

from __future__ import annotations

from datetime import date
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scheduling import business_today
from app.models.contract_care import (
    CareConversation,
    CarePlanItem,
    ClientArea,
    RedeployQueueItem,
    TechCard,
    TechVendor,
)
from app.models.skill import Skill
from app.models.user import User
from app.services.care import access as care_access
from app.services.care import cadence as care_cadence
from app.services.care import plan as care_plan
from app.services.care import records
from app.services.care import skills as care_skills
from app.services.contract_care_schema import REDEPLOY_ACTIVE_STATUSES


def person(user_id: Optional[int], names: dict[int, str]) -> Optional[dict[str, Any]]:
    if user_id is None:
        return None
    return {"id": user_id, "name": names.get(user_id, "")}


def plan_payload(item: CarePlanItem, today: date) -> dict[str, Any]:
    return {
        "id": item.id,
        "kind": item.kind,
        "label": care_plan.KIND_LABELS.get(item.kind, item.kind),
        "due_on": item.due_on,
        "status": item.status,
        "overdue": item.status == "open" and item.due_on < today,
        "done_conversation_id": item.done_conversation_id,
        "resolved_at": item.resolved_at,
        "skip_reason": item.skip_reason,
        "skip_note": item.skip_note,
    }


def conversation_payload(
    conv: CareConversation, names: dict[int, str]
) -> dict[str, Any]:
    return {
        "id": conv.id,
        "occurred_on": conv.occurred_on,
        "channel": conv.channel,
        "satisfaction": conv.satisfaction,
        "note": conv.note,
        "attrition_risk": conv.attrition_risk,
        "wants_change": conv.wants_change,
        "project_end_on": conv.project_end_on,
        "client_hiring": conv.client_hiring,
        "client_hiring_note": conv.client_hiring_note,
        "follow_up_on": conv.follow_up_on,
        "author": person(conv.author_user_id, names),
    }


async def cards_payload(
    db: AsyncSession, cards: list[TechCard], names: dict[int, str]
) -> list[dict[str, Any]]:
    card_skills, card_vendors = await records.card_relations(db, [c.id for c in cards])
    skill_ids = sorted({sid for ids in card_skills.values() for sid in ids})
    vendor_ids = sorted({vid for ids in card_vendors.values() for vid in ids})
    area_ids = sorted({c.client_area_id for c in cards if c.client_area_id})
    skill_names = (
        dict(
            (
                await db.execute(
                    select(Skill.id, Skill.canonical_name).where(
                        Skill.id.in_(skill_ids)
                    )
                )
            ).all()
        )
        if skill_ids
        else {}
    )
    vendor_names = (
        dict(
            (
                await db.execute(
                    select(TechVendor.id, TechVendor.name).where(
                        TechVendor.id.in_(vendor_ids)
                    )
                )
            ).all()
        )
        if vendor_ids
        else {}
    )
    area_names = (
        dict(
            (
                await db.execute(
                    select(ClientArea.id, ClientArea.name).where(
                        ClientArea.id.in_(area_ids)
                    )
                )
            ).all()
        )
        if area_ids
        else {}
    )
    out = []
    for card in cards:
        out.append(
            {
                "id": card.id,
                "contract_id": card.contract_id,
                "client_id": card.client_id,
                "interview_on": card.interview_on,
                "status": card.status,
                "is_draft": card.is_draft,
                "finalized_at": card.finalized_at,
                "satisfaction": card.satisfaction,
                "area": (
                    {
                        "id": card.client_area_id,
                        "name": area_names.get(card.client_area_id, ""),
                    }
                    if card.client_area_id
                    else None
                ),
                "skills": sorted(
                    (
                        {"id": sid, "name": care_skills.display_name(skill_names[sid])}
                        for sid in card_skills.get(card.id, [])
                        if sid in skill_names
                    ),
                    key=lambda item: item["name"].lower(),
                ),
                "unrecognized_skills": list(card.unrecognized_skills or []),
                "vendors": sorted(
                    (
                        {"id": vid, "name": vendor_names.get(vid, "")}
                        for vid in card_vendors.get(card.id, [])
                    ),
                    key=lambda item: item["name"].lower(),
                ),
                "hiring": card.hiring,
                "hiring_source": card.hiring_source,
                "hiring_roles": list(card.hiring_roles or []),
                "project_end_on": card.project_end_on,
                "project_end_unknown": card.project_end_unknown,
                "team_size": card.team_size,
                "team_externals": card.team_externals,
                "initiatives": list(card.initiatives or []),
                "memorable_quote": card.memorable_quote,
                "note": card.note,
                "sales_status": card.sales_status,
                "author": person(card.author_user_id, names),
            }
        )
    return out


def redeploy_payload(item: RedeployQueueItem) -> dict[str, Any]:
    return {
        "id": item.id,
        "contract_id": item.contract_id,
        "reason": item.reason,
        "status": item.status,
        "due_on": item.due_on,
        "source": item.source,
        "note": item.note,
        "created_at": item.created_at,
        "resolved_at": item.resolved_at,
    }


async def contract_overview(
    db: AsyncSession, contract: care_access.CareContract, user: User
) -> dict[str, Any]:
    """Zakładka „Opieka” kontraktu; dopisuje plan żywego kontraktu (dwie instrukcje)."""

    today = business_today()
    if contract.is_live:
        await care_plan.ensure_plan(
            db,
            contract.id,
            start=contract.start_date,
            end=contract.end_date,
            today=today,
        )
    plan_items = (
        await db.scalars(
            select(CarePlanItem)
            .where(CarePlanItem.contract_id == contract.id)
            .order_by(CarePlanItem.due_on, CarePlanItem.id)
        )
    ).all()
    conversations = (
        await db.scalars(
            select(CareConversation)
            .where(CareConversation.contract_id == contract.id)
            .order_by(CareConversation.occurred_on.desc(), CareConversation.id.desc())
        )
    ).all()
    cards = (
        await db.scalars(
            select(TechCard)
            .where(TechCard.contract_id == contract.id)
            .order_by(TechCard.interview_on.desc(), TechCard.id.desc())
        )
    ).all()
    redeploy = (
        await db.scalars(
            select(RedeployQueueItem)
            .where(RedeployQueueItem.contract_id == contract.id)
            .order_by(RedeployQueueItem.created_at.desc())
        )
    ).all()
    owner = (await care_access.effective_owners(db, [contract]))[contract.id]
    names = await care_access.user_names(
        db,
        [
            owner.user_id,
            contract.client_default_owner_id,
            *(c.author_user_id for c in conversations),
            *(c.author_user_id for c in cards),
        ],
    )
    upcoming = care_plan.next_contact(
        plan_items, conversations[0] if conversations else None, today
    )
    satisfaction = next(
        (
            {"value": item.satisfaction, "on": when}
            for item, when in sorted(
                [
                    *((c, c.occurred_on) for c in conversations if c.satisfaction),
                    *(
                        (c, c.interview_on)
                        for c in cards
                        if c.satisfaction and not c.is_draft
                    ),
                ],
                key=lambda pair: pair[1],
                reverse=True,
            )
        ),
        None,
    )
    project_end = await records.latest_project_end(db, contract.id)
    return {
        "contract": {
            "id": contract.id,
            "label": contract.label,
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
            "day_of_cooperation": (
                (today - contract.start_date).days + 1
                if contract.start_date and contract.start_date <= today
                else None
            ),
        },
        "owner": {
            "user": person(owner.user_id, names),
            "source": owner.source,
            "explicit": contract.explicit_owner_id is not None,
        },
        "client_default_owner": person(contract.client_default_owner_id, names),
        "cadence": await care_cadence.contract_cadence(
            db, contract, user=user, today=today
        ),
        "plan": [plan_payload(item, today) for item in plan_items],
        "next_contact": upcoming.payload(today) if upcoming else None,
        "last_satisfaction": satisfaction,
        "conversations": [conversation_payload(c, names) for c in conversations],
        "tech_cards": await cards_payload(db, list(cards), names),
        "redeploy": [redeploy_payload(item) for item in redeploy],
        "project_end": (
            {
                "end_on": project_end.end_on,
                "source": project_end.source,
                "known_on": project_end.known_on,
            }
            if project_end is not None
            else None
        ),
        "can_edit": care_access.is_care_worker(user),
    }


async def my_consultants(db: AsyncSession, user: User, scope: str) -> dict[str, Any]:
    """„Moi konsultanci” (``mine``) albo wszystkie kontrakty w zakresie (``all``).

    Odczyt niczego nie zapisuje — plan dopisuje dzienny przebieg i zmiana
    opiekuna (``care_plan.ensure_plans``).
    """

    today = business_today()
    allowed = await care_access.allowed_client_ids(user, db)
    contracts = await care_access.live_contracts(db, allowed=allowed)
    owners = await care_access.effective_owners(db, contracts)
    if scope == "mine":
        contracts = [c for c in contracts if owners[c.id].user_id == user.id]
    ids = [c.id for c in contracts]
    open_items: dict[int, list[CarePlanItem]] = {cid: [] for cid in ids}
    if ids:
        for item in (
            await db.scalars(
                select(CarePlanItem)
                .where(CarePlanItem.contract_id.in_(ids), CarePlanItem.status == "open")
                .order_by(CarePlanItem.due_on, CarePlanItem.id)
            )
        ).all():
            open_items[item.contract_id].append(item)
    last_conv = await care_plan.latest_conversations(db, ids)
    reasons: dict[int, list[str]] = {cid: [] for cid in ids}
    if ids:
        for contract_id, reason in (
            await db.execute(
                select(RedeployQueueItem.contract_id, RedeployQueueItem.reason).where(
                    RedeployQueueItem.contract_id.in_(ids),
                    RedeployQueueItem.status.in_(REDEPLOY_ACTIVE_STATUSES),
                )
            )
        ).all():
            reasons[contract_id].append(reason)
    names = await care_access.user_names(db, [owners[c.id].user_id for c in contracts])
    rows = []
    for contract in contracts:
        items = open_items[contract.id]
        conv = last_conv.get(contract.id)
        upcoming = care_plan.next_contact(items, conv, today)
        rows.append(
            {
                "contract_id": contract.id,
                "candidate_id": contract.candidate_id,
                "candidate_name": contract.candidate_name,
                "client_id": contract.client_id,
                "client_name": contract.client_name,
                "job_title": contract.job_title,
                "start_date": contract.start_date,
                "end_date": contract.end_date,
                "owner": person(owners[contract.id].user_id, names),
                "next_contact": upcoming.payload(today) if upcoming else None,
                "overdue_count": sum(1 for item in items if item.due_on < today),
                "last_conversation_on": conv.occurred_on if conv else None,
                "last_satisfaction": conv.satisfaction if conv else None,
                "redeploy_reasons": sorted(reasons[contract.id]),
            }
        )
    rows.sort(
        key=lambda row: (
            -row["overdue_count"],
            row["next_contact"]["due_on"] if row["next_contact"] else date.max,
            (row["candidate_name"] or "").lower(),
        )
    )
    return {"items": rows, "total": len(rows), "scope": scope}
