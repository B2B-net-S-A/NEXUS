"""Opieka nad konsultantami i mapa technologii klienta.

Prefiks ``/api/care`` (wpięty w ``app/main.py``). Każda trasa ma nazwaną bramkę
``require_hr_*`` (``app/api/hr_gates.py`` albo własną w tym module) i sprawdza
przełącznik modułu w ``app_settings['hr_modules']``.

Dostęp (decyzja D7 i zadanie E5, 16.10.2026):

* **odczyt** — sekcja Delivery i „Klienci, kontrakty i zamówienia: podgląd”
  (``DeliveryViewUser``); Delivery Lead tylko u swoich klientów (cudzy → 403),
* **zapis** (opiekun, rozmowy, karty, przepięcia, notatki o stacku) — dodatkowo
  rola Delivery Lead, Talent Community Manager albo admin: opieka to praca
  z ludźmi, a nie uprawnienie z ekranu kontraktów,
* **kolejka technologii** — czytają ją też osoby od słownika umiejętności
  (Head of Recruitment); decyzje: admin, Head of Recruitment, TCM,
* **ATLAS** — klucz konta serwisowego (``X-API-Key``) z ``clients:read``
  i ``contracts:read`` (najbliższe istniejące zakresy; własnego zakresu
  sygnałów nie ma), zwrot statusów — na razie tylko admin.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    Caller,
    require_permission_or_roles,
    require_roles,
    require_service_scope,
)
from app.api.hr_gates import MODULE_DISABLED_DETAIL
from app.api.permission_access import DeliveryViewUser
from app.api.section_access import (
    require_section_access,
    require_section_access_any,
    require_section_access_any_read,
)
from app.core.database import get_db
from app.core.scheduling import business_today, local_now
from app.models.client_knowledge import ClientKnowledge, KnowledgeCategory
from app.models.contract import Contract
from app.models.contract_care import (
    CLIENTS_CARE,
    CONTRACTS_CARE,
    CareConversation,
    CarePlanItem,
    ClientArea,
    RedeployQueueItem,
    SkillReviewItem,
    TechCard,
    TechVendor,
)
from app.models.service_account import ServiceScope
from app.models.skill import Skill
from app.models.user import User, UserRole
from app.services.action_permissions import ProductAction
from app.services.care import access as care_access
from app.services.care import plan as care_plan
from app.services.care import records, signals
from app.services.care import skills as care_skills
from app.services.care import tech_map
from app.services.contract_care_schema import NAME_MAX, NOTE_MAX, SHORT_TEXT_MAX
from app.services.hr import audit
from app.services.hr import modules as hr_modules
from app.services.section_permissions import ProductSection

router = APIRouter()

CARE_MODULE = "care"
WRITER_DENIED = (
    "Opiekę nad konsultantami prowadzą Delivery Lead, Talent Community Manager "
    "i administrator."
)

_DELIVERY_SECTION = require_section_access(ProductSection.delivery)
_CARE_ROLES = require_roles(
    UserRole.admin, UserRole.delivery_lead, UserRole.talent_community_manager
)
_REVIEW_SECTION_READ = require_section_access_any_read(
    ProductSection.delivery, ProductSection.sourcing
)
_REVIEW_SECTION = require_section_access_any(
    ProductSection.delivery, ProductSection.sourcing
)
_REVIEW_READER = require_permission_or_roles(
    ProductAction.delivery_view, UserRole.head_of_recruitment
)
_CURATOR_ROLES = require_roles(
    UserRole.admin, UserRole.head_of_recruitment, UserRole.talent_community_manager
)
_ATLAS_SCOPE = require_service_scope(ServiceScope.sales_signals_read)
_ATLAS_WRITE_SCOPE = require_service_scope(ServiceScope.sales_signals_write)


async def _ensure_module(db: AsyncSession, user: User) -> None:
    loaded = await hr_modules.load_modules(db)
    if not hr_modules.module_open_for(user, loaded, CARE_MODULE):
        raise HTTPException(status.HTTP_404_NOT_FOUND, MODULE_DISABLED_DETAIL)


def require_hr_care_reader():
    """Odczyt opieki i mapy: sekcja Delivery + podgląd Delivery + moduł włączony."""

    async def _check(
        viewer: DeliveryViewUser,
        current_user: User = Depends(_DELIVERY_SECTION),
        db: AsyncSession = Depends(get_db),
    ) -> User:
        await _ensure_module(db, current_user)
        return current_user

    return _check


def require_hr_care_writer():
    """Zapis opieki: jak odczyt + rola DL, TCM albo admin."""

    async def _check(
        viewer: DeliveryViewUser,
        current_user: User = Depends(_DELIVERY_SECTION),
        db: AsyncSession = Depends(get_db),
    ) -> User:
        if not care_access.is_care_worker(current_user):
            raise HTTPException(status.HTTP_403_FORBIDDEN, WRITER_DENIED)
        await _ensure_module(db, current_user)
        return current_user

    return _check


def require_hr_care_review_reader():
    """Kolejka technologii: czytelnicy opieki i osoby od słownika umiejętności."""

    async def _check(
        reader: User = Depends(_REVIEW_READER),
        current_user: User = Depends(_REVIEW_SECTION_READ),
        db: AsyncSession = Depends(get_db),
    ) -> User:
        await _ensure_module(db, current_user)
        return current_user

    return _check


def require_hr_care_skill_curator():
    """Decyzje w kolejce technologii (zmieniają słownik całej aplikacji)."""

    async def _check(
        curator: User = Depends(_CURATOR_ROLES),
        current_user: User = Depends(_REVIEW_SECTION),
        db: AsyncSession = Depends(get_db),
    ) -> User:
        await _ensure_module(db, current_user)
        return current_user

    return _check


def require_hr_care_atlas_reader():
    """ATLAS: klucz z ``sales_signals:read`` albo admin z JWT."""

    async def _check(
        caller: Caller = Depends(_ATLAS_SCOPE),
        db: AsyncSession = Depends(get_db),
    ) -> Caller:
        if caller.user is not None:
            return caller
        loaded = await hr_modules.load_modules(db)
        if not loaded.get(CARE_MODULE):
            raise HTTPException(status.HTTP_404_NOT_FOUND, MODULE_DISABLED_DETAIL)
        return caller

    return _check


def require_hr_care_atlas_admin():
    """Zwrot statusów sygnałów: klucz z ``sales_signals:write`` albo admin z JWT."""

    async def _check(caller: Caller = Depends(_ATLAS_WRITE_SCOPE)) -> Caller:
        return caller

    return _check


CareReader = require_hr_care_reader()
CareWriter = require_hr_care_writer()
ReviewReader = require_hr_care_review_reader()
SkillCurator = require_hr_care_skill_curator()
AtlasReader = require_hr_care_atlas_reader()
AtlasAdmin = require_hr_care_atlas_admin()


# ── Wspólne ─────────────────────────────────────────────────────────────────


def _person(user_id: Optional[int], names: dict[int, str]) -> Optional[dict[str, Any]]:
    if user_id is None:
        return None
    return {"id": user_id, "name": names.get(user_id, "")}


@router.get("/owners")
async def list_owners(
    current_user: User = Depends(CareReader), db: AsyncSession = Depends(get_db)
) -> dict:
    users = await care_access.owner_candidates(db)
    return {"items": [{"id": user.id, "name": user.name} for user in users]}


# ── Kontrakt → zakładka „Opieka” ────────────────────────────────────────────


def _plan_payload(item: CarePlanItem, today: date) -> dict[str, Any]:
    return {
        "id": item.id,
        "kind": item.kind,
        "label": care_plan.KIND_LABELS.get(item.kind, item.kind),
        "due_on": item.due_on,
        "status": item.status,
        "overdue": item.status == "open" and item.due_on < today,
        "done_conversation_id": item.done_conversation_id,
        "resolved_at": item.resolved_at,
    }


def _conversation_payload(
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
        "author": _person(conv.author_user_id, names),
    }


async def _cards_payload(
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
                "author": _person(card.author_user_id, names),
            }
        )
    return out


def _redeploy_payload(item: RedeployQueueItem) -> dict[str, Any]:
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


async def _contract_overview(
    db: AsyncSession, contract: care_access.CareContract, user: User
) -> dict[str, Any]:
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
    next_item = care_plan.next_open(plan_items)
    latest = conversations[0] if conversations else None
    follow_up = latest.follow_up_on if latest is not None else None
    next_contact = None
    if next_item is not None:
        next_contact = {
            "due_on": next_item.due_on,
            "label": care_plan.KIND_LABELS.get(next_item.kind, next_item.kind),
            "plan_item_id": next_item.id,
        }
    if follow_up is not None and (
        next_contact is None or follow_up < next_contact["due_on"]
    ):
        next_contact = {
            "due_on": follow_up,
            "label": "Umówiony kontakt",
            "plan_item_id": None,
        }
    if next_contact is not None:
        next_contact["overdue"] = next_contact["due_on"] < today
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
            "user": _person(owner.user_id, names),
            "source": owner.source,
            "explicit": contract.explicit_owner_id is not None,
        },
        "client_default_owner": _person(contract.client_default_owner_id, names),
        "plan": [_plan_payload(item, today) for item in plan_items],
        "next_contact": next_contact,
        "last_satisfaction": satisfaction,
        "conversations": [_conversation_payload(c, names) for c in conversations],
        "tech_cards": await _cards_payload(db, list(cards), names),
        "redeploy": [_redeploy_payload(item) for item in redeploy],
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


@router.get("/contracts/{contract_id}")
async def contract_care(
    contract_id: int,
    current_user: User = Depends(CareReader),
    db: AsyncSession = Depends(get_db),
) -> dict:
    contract = await care_access.load_contract(db, contract_id, current_user)
    return await _contract_overview(db, contract, current_user)


class OwnerBody(BaseModel):
    user_id: Optional[int] = None


@router.put("/contracts/{contract_id}/owner")
async def set_contract_owner(
    contract_id: int,
    body: OwnerBody,
    current_user: User = Depends(CareWriter),
    db: AsyncSession = Depends(get_db),
) -> dict:
    contract = await care_access.load_contract(db, contract_id, current_user)
    if body.user_id is not None:
        await care_access.validate_owner(db, body.user_id, client_id=contract.client_id)
    await db.execute(
        update(CONTRACTS_CARE)
        .where(CONTRACTS_CARE.c.id == contract.id)
        .values(care_owner_user_id=body.user_id)
    )
    audit.record(
        db,
        actor_user_id=current_user.id,
        subject_user_id=body.user_id,
        entity_type="contract",
        entity_id=contract.id,
        action="care.owner_set",
        details={"previous": contract.explicit_owner_id, "owner": body.user_id},
    )
    fresh = await care_access.load_contract(db, contract_id, current_user)
    return await _contract_overview(db, fresh, current_user)


class ConversationBody(BaseModel):
    occurred_on: date
    channel: Literal["phone", "meeting", "chat"] = "phone"
    satisfaction: Optional[int] = Field(default=None, ge=1, le=5)
    note: Optional[str] = Field(default=None, max_length=NOTE_MAX)
    attrition_risk: bool = False
    wants_change: bool = False
    project_end_on: Optional[date] = None
    client_hiring: bool = False
    client_hiring_note: Optional[str] = Field(default=None, max_length=SHORT_TEXT_MAX)
    follow_up_on: Optional[date] = None
    plan_item_id: Optional[int] = None


@router.post(
    "/contracts/{contract_id}/conversations", status_code=status.HTTP_201_CREATED
)
async def add_conversation(
    contract_id: int,
    body: ConversationBody,
    current_user: User = Depends(CareWriter),
    db: AsyncSession = Depends(get_db),
) -> dict:
    contract = await care_access.load_contract(db, contract_id, current_user)
    await records.add_conversation(
        db,
        contract,
        records.ConversationInput(**body.model_dump()),
        actor_id=current_user.id,
        today=business_today(),
        now=local_now(),
    )
    await tech_map.invalidate([contract.client_id])
    return await _contract_overview(db, contract, current_user)


class PlanItemBody(BaseModel):
    status: Literal["open", "skipped"]


@router.patch("/plan-items/{item_id}")
async def update_plan_item(
    item_id: int,
    body: PlanItemBody,
    current_user: User = Depends(CareWriter),
    db: AsyncSession = Depends(get_db),
) -> dict:
    item = await db.get(CarePlanItem, item_id, with_for_update=True)
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Nie ma takiego punktu planu.")
    contract = await care_access.load_contract(db, item.contract_id, current_user)
    if item.status == "done":
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Ten kontakt jest już zapisany rozmową."
        )
    item.status = body.status
    item.resolved_at = local_now() if body.status == "skipped" else None
    item.resolved_by = current_user.id if body.status == "skipped" else None
    await db.flush()
    return await _contract_overview(db, contract, current_user)


class InitiativeBody(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    kind: Literal["migracja", "nowy_system", "ai", "regulacje", "inne"] = "inne"
    priority: Literal["wysoki", "normalny"] = "normalny"


class TechCardBody(BaseModel):
    interview_on: date
    finalize: bool = False
    status: Optional[Literal["ok", "odmowa", "brak_czasu", "niechetny"]] = None
    satisfaction: Optional[int] = Field(default=None, ge=1, le=5)
    client_area_id: Optional[int] = None
    new_area_name: Optional[str] = Field(default=None, max_length=NAME_MAX)
    skill_ids: list[int] = Field(default_factory=list, max_length=100)
    skill_names: list[str] = Field(default_factory=list, max_length=50)
    vendor_ids: list[int] = Field(default_factory=list, max_length=50)
    new_vendor_names: list[str] = Field(default_factory=list, max_length=20)
    hiring: Optional[bool] = None
    hiring_source: Optional[Literal["widzial", "slyszal", "plotka"]] = None
    hiring_roles: list[str] = Field(default_factory=list, max_length=20)
    project_end_on: Optional[date] = None
    project_end_unknown: bool = False
    team_size: Optional[str] = Field(default=None, max_length=80)
    team_externals: Optional[int] = Field(default=None, ge=0, le=10000)
    initiatives: list[InitiativeBody] = Field(default_factory=list, max_length=20)
    memorable_quote: Optional[str] = Field(default=None, max_length=SHORT_TEXT_MAX)
    note: Optional[str] = Field(default=None, max_length=NOTE_MAX)


def _card_input(body: TechCardBody) -> records.TechCardInput:
    data = body.model_dump()
    data["skill_names"] = [name[:NAME_MAX] for name in data["skill_names"]]
    data["new_vendor_names"] = [name[:NAME_MAX] for name in data["new_vendor_names"]]
    return records.TechCardInput(**data)


@router.post("/contracts/{contract_id}/tech-cards", status_code=status.HTTP_201_CREATED)
async def add_tech_card(
    contract_id: int,
    body: TechCardBody,
    current_user: User = Depends(CareWriter),
    db: AsyncSession = Depends(get_db),
) -> dict:
    contract = await care_access.load_contract(db, contract_id, current_user)
    await records.save_tech_card(
        db,
        contract,
        _card_input(body),
        actor_id=current_user.id,
        today=business_today(),
        now=local_now(),
    )
    await tech_map.invalidate([contract.client_id])
    return await _contract_overview(db, contract, current_user)


@router.put("/tech-cards/{card_id}")
async def update_tech_card(
    card_id: int,
    body: TechCardBody,
    current_user: User = Depends(CareWriter),
    db: AsyncSession = Depends(get_db),
) -> dict:
    card = await db.get(TechCard, card_id, with_for_update=True)
    if card is None or card.contract_id is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Nie ma takiej karty.")
    contract = await care_access.load_contract(db, card.contract_id, current_user)
    await records.save_tech_card(
        db,
        contract,
        _card_input(body),
        actor_id=current_user.id,
        today=business_today(),
        now=local_now(),
        card=card,
    )
    await tech_map.invalidate([contract.client_id])
    return await _contract_overview(db, contract, current_user)


class RedeployCreateBody(BaseModel):
    reason: Literal["project_end", "wants_change", "attrition_risk"]
    due_on: Optional[date] = None
    note: Optional[str] = Field(default=None, max_length=NOTE_MAX)


@router.post("/contracts/{contract_id}/redeploy", status_code=status.HTTP_201_CREATED)
async def add_redeploy(
    contract_id: int,
    body: RedeployCreateBody,
    current_user: User = Depends(CareWriter),
    db: AsyncSession = Depends(get_db),
) -> dict:
    contract = await care_access.load_contract(db, contract_id, current_user)
    active = await db.scalar(
        select(RedeployQueueItem.id).where(
            RedeployQueueItem.contract_id == contract.id,
            RedeployQueueItem.reason == body.reason,
            RedeployQueueItem.status.in_(("open", "in_progress")),
        )
    )
    if active is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Ten konsultant ma już aktywny wpis z tym powodem.",
        )
    item = RedeployQueueItem(
        contract_id=contract.id,
        reason=body.reason,
        status="open",
        due_on=body.due_on,
        source="manual",
        note=(body.note or "").strip() or None,
        created_by=current_user.id,
        updated_by=current_user.id,
    )
    db.add(item)
    await db.flush()
    await tech_map.invalidate([contract.client_id])
    return _redeploy_payload(item)


# ── Klient → zakładka „Technologie” ─────────────────────────────────────────


@router.get("/clients/{client_id}/tech-map")
async def client_tech_map(
    client_id: int,
    current_user: User = Depends(CareReader),
    db: AsyncSession = Depends(get_db),
) -> dict:
    client = await care_access.load_client(db, client_id, current_user)
    default_owner = await db.scalar(
        select(CLIENTS_CARE.c.default_care_owner_user_id).where(
            CLIENTS_CARE.c.id == client.id
        )
    )
    names = await care_access.user_names(db, [default_owner])
    result = await tech_map.client_tech_map(db, client.id, today=business_today())
    return {
        **result,
        "client_name": client.name,
        "default_owner": _person(default_owner, names),
        "can_edit": care_access.is_care_worker(current_user),
    }


@router.get("/clients/{client_id}/areas")
async def client_areas(
    client_id: int,
    current_user: User = Depends(CareReader),
    db: AsyncSession = Depends(get_db),
) -> dict:
    client = await care_access.load_client(db, client_id, current_user)
    ids = await tech_map.related_client_ids(db, client.id)
    areas = (
        await db.scalars(
            select(ClientArea)
            .where(ClientArea.client_id.in_(ids))
            .order_by(ClientArea.name)
        )
    ).all()
    return {
        "items": [
            {"id": a.id, "name": a.name} for a in areas if a.client_id == client.id
        ]
    }


class NameBody(BaseModel):
    name: str = Field(min_length=1, max_length=NAME_MAX)


@router.post("/clients/{client_id}/areas", status_code=status.HTTP_201_CREATED)
async def add_client_area(
    client_id: int,
    body: NameBody,
    current_user: User = Depends(CareWriter),
    db: AsyncSession = Depends(get_db),
) -> dict:
    client = await care_access.load_client(db, client_id, current_user)
    area = await records.add_area(db, client.id, body.name, actor_id=current_user.id)
    await tech_map.invalidate([client.id])
    return {"id": area.id, "name": area.name}


@router.put("/clients/{client_id}/default-owner")
async def set_client_default_owner(
    client_id: int,
    body: OwnerBody,
    current_user: User = Depends(CareWriter),
    db: AsyncSession = Depends(get_db),
) -> dict:
    client = await care_access.load_client(db, client_id, current_user)
    if body.user_id is not None:
        await care_access.validate_owner(db, body.user_id, client_id=client.id)
    await db.execute(
        update(CLIENTS_CARE)
        .where(CLIENTS_CARE.c.id == client.id)
        .values(default_care_owner_user_id=body.user_id)
    )
    audit.record(
        db,
        actor_user_id=current_user.id,
        subject_user_id=body.user_id,
        entity_type="client",
        entity_id=client.id,
        action="care.default_owner_set",
        details={"owner": body.user_id},
    )
    names = await care_access.user_names(db, [body.user_id])
    return {"default_owner": _person(body.user_id, names)}


class StackNoteBody(BaseModel):
    content: str = Field(min_length=1, max_length=NOTE_MAX)


@router.post("/clients/{client_id}/stack-notes", status_code=status.HTTP_201_CREATED)
async def add_stack_note(
    client_id: int,
    body: StackNoteBody,
    current_user: User = Depends(CareWriter),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """„Dodaj notatkę o stacku” = wpis wiedzy o kliencie w kategorii stacku."""

    client = await care_access.load_client(db, client_id, current_user)
    content = body.content.strip()
    if not content:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Notatka jest pusta.")
    note = ClientKnowledge(
        client_id=client.id,
        category=KnowledgeCategory.tech_stack,
        content=content,
        added_by=current_user.id,
        source="care",
    )
    db.add(note)
    await db.flush()
    await tech_map.invalidate([client.id])
    return {"id": note.id, "content": note.content}


# ── Słowniki ────────────────────────────────────────────────────────────────


@router.get("/vendors")
async def list_vendors(
    q: str = Query("", max_length=NAME_MAX),
    current_user: User = Depends(CareReader),
    db: AsyncSession = Depends(get_db),
) -> dict:
    query = select(TechVendor).order_by(TechVendor.name).limit(50)
    if q.strip():
        query = query.where(
            TechVendor.name_key.contains(care_skills.name_key(q), autoescape=True)
        )
    vendors = (await db.scalars(query)).all()
    return {"items": [{"id": v.id, "name": v.name} for v in vendors]}


@router.post("/vendors", status_code=status.HTTP_201_CREATED)
async def add_vendor(
    body: NameBody,
    current_user: User = Depends(CareWriter),
    db: AsyncSession = Depends(get_db),
) -> dict:
    vendor_id = await records.upsert_vendor(db, body.name, actor_id=current_user.id)
    vendor = await db.get(TechVendor, vendor_id)
    return {"id": vendor.id, "name": vendor.name}


# ── /care: „Moi konsultanci” i „Do przepięcia” ──────────────────────────────


@router.get("/my-consultants")
async def my_consultants(
    scope: Literal["mine", "all"] = "mine",
    current_user: User = Depends(CareReader),
    db: AsyncSession = Depends(get_db),
) -> dict:
    today = business_today()
    allowed = await care_access.allowed_client_ids(current_user, db)
    contracts = await care_access.live_contracts(db, allowed=allowed)
    owners = await care_access.effective_owners(db, contracts)
    if scope == "mine":
        contracts = [c for c in contracts if owners[c.id].user_id == current_user.id]
        for contract in contracts:
            await care_access_plan(db, contract, today)
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
    last_conv: dict[int, CareConversation] = {}
    if ids:
        for conv in (
            await db.scalars(
                select(CareConversation)
                .where(CareConversation.contract_id.in_(ids))
                .order_by(
                    CareConversation.contract_id,
                    CareConversation.occurred_on.desc(),
                    CareConversation.id.desc(),
                )
            )
        ).all():
            last_conv.setdefault(conv.contract_id, conv)
    reasons: dict[int, list[str]] = {cid: [] for cid in ids}
    if ids:
        for contract_id, reason in (
            await db.execute(
                select(RedeployQueueItem.contract_id, RedeployQueueItem.reason).where(
                    RedeployQueueItem.contract_id.in_(ids),
                    RedeployQueueItem.status.in_(("open", "in_progress")),
                )
            )
        ).all():
            reasons[contract_id].append(reason)
    names = await care_access.user_names(db, [owners[c.id].user_id for c in contracts])
    rows = []
    for contract in contracts:
        items = open_items[contract.id]
        conv = last_conv.get(contract.id)
        next_item = items[0] if items else None
        next_contact = (
            {
                "due_on": next_item.due_on,
                "label": care_plan.KIND_LABELS.get(next_item.kind, next_item.kind),
            }
            if next_item
            else None
        )
        if (
            conv is not None
            and conv.follow_up_on is not None
            and (next_contact is None or conv.follow_up_on < next_contact["due_on"])
        ):
            next_contact = {"due_on": conv.follow_up_on, "label": "Umówiony kontakt"}
        if next_contact is not None:
            next_contact["overdue"] = next_contact["due_on"] < today
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
                "owner": _person(owners[contract.id].user_id, names),
                "next_contact": next_contact,
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


async def care_access_plan(
    db: AsyncSession, contract: care_access.CareContract, today: date
) -> None:
    await care_plan.ensure_plan(
        db, contract.id, start=contract.start_date, end=contract.end_date, today=today
    )


@router.get("/redeploy")
async def redeploy_queue(
    state: Literal["active", "closed"] = "active",
    current_user: User = Depends(CareReader),
    db: AsyncSession = Depends(get_db),
) -> dict:
    allowed = await care_access.allowed_client_ids(current_user, db)
    statuses = ("open", "in_progress") if state == "active" else ("done", "dismissed")
    query = (
        select(RedeployQueueItem)
        .join(Contract, Contract.id == RedeployQueueItem.contract_id)
        .where(RedeployQueueItem.status.in_(statuses))
        .order_by(
            RedeployQueueItem.due_on.asc().nulls_last(),
            RedeployQueueItem.created_at.desc(),
        )
        .limit(300)
    )
    if allowed is not None:
        query = query.where(Contract.client_id.in_(sorted(allowed) or [-1]))
    items = (await db.scalars(query)).all()
    contracts = await care_access.contracts_by_id(
        db, [item.contract_id for item in items]
    )
    owners = await care_access.effective_owners(db, list(contracts.values()))
    names = await care_access.user_names(db, [o.user_id for o in owners.values()])
    rows = []
    for item in items:
        contract = contracts.get(item.contract_id)
        if contract is None:
            continue
        rows.append(
            {
                **_redeploy_payload(item),
                "candidate_id": contract.candidate_id,
                "candidate_name": contract.candidate_name,
                "client_id": contract.client_id,
                "client_name": contract.client_name,
                "job_title": contract.job_title,
                "end_date": contract.end_date,
                "owner": _person(owners[contract.id].user_id, names),
            }
        )
    return {
        "items": rows,
        "total": len(rows),
        "can_edit": care_access.is_care_worker(current_user),
    }


class RedeployPatchBody(BaseModel):
    status: Optional[Literal["open", "in_progress", "done", "dismissed"]] = None
    note: Optional[str] = Field(default=None, max_length=NOTE_MAX)


@router.patch("/redeploy/{item_id}")
async def update_redeploy(
    item_id: int,
    body: RedeployPatchBody,
    current_user: User = Depends(CareWriter),
    db: AsyncSession = Depends(get_db),
) -> dict:
    item = await db.get(RedeployQueueItem, item_id, with_for_update=True)
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Nie ma takiego wpisu.")
    contract = await care_access.load_contract(db, item.contract_id, current_user)
    await records.update_redeploy(
        db,
        item,
        new_status=body.status,
        note=body.note,
        note_set="note" in body.model_fields_set,
        actor_id=current_user.id,
        now=local_now(),
    )
    await db.flush()
    await tech_map.invalidate([contract.client_id])
    return _redeploy_payload(item)


# ── Technologie do przejrzenia ──────────────────────────────────────────────


def _can_curate(user: User) -> bool:
    return user.has_any_role(
        UserRole.admin, UserRole.head_of_recruitment, UserRole.talent_community_manager
    )


@router.get("/skill-review")
async def skill_review(
    state: Literal["open", "closed"] = "open",
    current_user: User = Depends(ReviewReader),
    db: AsyncSession = Depends(get_db),
) -> dict:
    statuses = ("open",) if state == "open" else ("mapped", "created", "dismissed")
    items = (
        await db.scalars(
            select(SkillReviewItem)
            .where(SkillReviewItem.status.in_(statuses))
            .order_by(SkillReviewItem.occurrences.desc(), SkillReviewItem.name_key)
            .limit(300)
        )
    ).all()
    skill_ids = sorted({i.skill_id for i in items if i.skill_id})
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
    names = await care_access.user_names(db, [i.reported_by for i in items])
    return {
        "items": [
            {
                "id": item.id,
                "name": item.name,
                "status": item.status,
                "occurrences": item.occurrences,
                "skill": (
                    {"id": item.skill_id, "name": skill_names.get(item.skill_id, "")}
                    if item.skill_id
                    else None
                ),
                "reported_by": _person(item.reported_by, names),
                "created_at": item.created_at,
                "resolved_at": item.resolved_at,
            }
            for item in items
        ],
        "can_curate": _can_curate(current_user),
    }


class MapSkillBody(BaseModel):
    skill_id: int


class CreateSkillBody(BaseModel):
    canonical_name: str = Field(min_length=1, max_length=NAME_MAX)
    category: Optional[str] = Field(default=None, max_length=64)


def _review_error(exc: care_skills.ReviewError) -> HTTPException:
    code = (
        status.HTTP_409_CONFLICT
        if exc.conflict
        else status.HTTP_422_UNPROCESSABLE_ENTITY
    )
    return HTTPException(code, str(exc))


@router.post("/skill-review/{item_id}/map")
async def map_review_item(
    item_id: int,
    body: MapSkillBody,
    current_user: User = Depends(SkillCurator),
    db: AsyncSession = Depends(get_db),
) -> dict:
    try:
        clients = await care_skills.map_to_skill(
            db, item_id, body.skill_id, actor_id=current_user.id, now=local_now()
        )
    except care_skills.ReviewError as exc:
        await db.rollback()
        raise _review_error(exc) from exc
    await tech_map.invalidate(clients)
    return {"id": item_id, "status": "mapped", "skill_id": body.skill_id}


@router.post("/skill-review/{item_id}/create")
async def create_review_skill(
    item_id: int,
    body: CreateSkillBody,
    current_user: User = Depends(SkillCurator),
    db: AsyncSession = Depends(get_db),
) -> dict:
    try:
        clients = await care_skills.create_skill(
            db,
            item_id,
            canonical_name=body.canonical_name,
            category=(body.category or "").strip() or None,
            actor_id=current_user.id,
            now=local_now(),
        )
    except care_skills.ReviewError as exc:
        await db.rollback()
        raise _review_error(exc) from exc
    await tech_map.invalidate(clients)
    item = await db.get(SkillReviewItem, item_id)
    return {
        "id": item_id,
        "status": "created",
        "skill_id": item.skill_id if item else None,
    }


@router.post("/skill-review/{item_id}/dismiss")
async def dismiss_review_item(
    item_id: int,
    current_user: User = Depends(SkillCurator),
    db: AsyncSession = Depends(get_db),
) -> dict:
    try:
        await care_skills.dismiss(
            db, item_id, actor_id=current_user.id, now=local_now()
        )
    except care_skills.ReviewError as exc:
        raise _review_error(exc) from exc
    return {"id": item_id, "status": "dismissed"}


# ── ATLAS: sygnały sprzedażowe ──────────────────────────────────────────────


@router.get("/atlas/sales-signals")
async def atlas_sales_signals(
    since: Optional[str] = Query(default=None, max_length=64),
    caller: Caller = Depends(AtlasReader),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Karty „klient zatrudnia” z wynikiem obsługi po stronie ATLASA.

    Pusta lista to poprawna odpowiedź (``count`` = 0) — ATLAS rozróżnia ją od
    awarii po kodzie HTTP. ``since`` (ISO-8601 ze strefą) zawęża do kart
    zmienionych od tej chwili; zła data = 422, nie cichy pełny eksport.
    """

    parsed: Optional[datetime] = None
    if since:
        try:
            parsed = datetime.fromisoformat(since.replace("Z", "+00:00"))
        except ValueError as exc:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "since musi być datą ISO-8601 ze strefą (np. 2026-09-01T10:00:00Z).",
            ) from exc
        if parsed.tzinfo is None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "since musi mieć strefę czasową (np. 2026-09-01T10:00:00Z).",
            )
    rows = await signals.export(db, since=parsed)
    return {"count": len(rows), "signals": rows}


class SignalStatusItem(BaseModel):
    signal_id: str = Field(min_length=1, max_length=100)
    status: Literal["converted", "archived"]
    handled_at: datetime
    deal_title: Optional[str] = Field(default=None, max_length=SHORT_TEXT_MAX)
    handled_by_name: Optional[str] = Field(default=None, max_length=200)
    reason: Optional[str] = Field(default=None, max_length=2000)


class SignalStatusBody(BaseModel):
    updates: list[SignalStatusItem] = Field(max_length=200)


@router.post("/atlas/sales-signals/status")
async def atlas_sales_signal_status(
    body: SignalStatusBody,
    _caller: Caller = Depends(AtlasAdmin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    for item in body.updates:
        if item.handled_at.tzinfo is None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "handled_at musi mieć strefę czasową.",
            )
    result = await signals.apply_statuses(
        db,
        [signals.StatusUpdate(**item.model_dump()) for item in body.updates],
    )
    return result


# Liczba wierszy kolejki do przejrzenia na pasku /care (lekki odczyt).
@router.get("/summary")
async def care_summary(
    current_user: User = Depends(CareReader),
    db: AsyncSession = Depends(get_db),
) -> dict:
    allowed = await care_access.allowed_client_ids(current_user, db)
    redeploy = (
        select(func.count())
        .select_from(RedeployQueueItem)
        .join(Contract, Contract.id == RedeployQueueItem.contract_id)
        .where(RedeployQueueItem.status.in_(("open", "in_progress")))
    )
    if allowed is not None:
        redeploy = redeploy.where(Contract.client_id.in_(sorted(allowed) or [-1]))
    review = (
        select(func.count())
        .select_from(SkillReviewItem)
        .where(SkillReviewItem.status == "open")
    )
    return {
        "redeploy_active": int(await db.scalar(redeploy) or 0),
        "skill_review_open": int(await db.scalar(review) or 0),
        "can_edit": care_access.is_care_worker(current_user),
        "can_curate": _can_curate(current_user),
    }
