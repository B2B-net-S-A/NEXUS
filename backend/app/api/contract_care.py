"""Opieka nad konsultantami i mapa technologii klienta.

Prefiks ``/api/care`` (wpięty w ``app/main.py``). Każda trasa ma nazwaną bramkę
``require_hr_*`` z ``app/api/care_gates.py`` i sprawdza przełącznik modułu
w ``app_settings['hr_modules']``. Pod tym samym prefiksem: kolejka technologii
(``app/api/care_skills.py``) i sygnały dla ATLASA (``app/api/care_atlas.py``);
odczyt zakładki „Opieka” i listy konsultantów liczy ``services/care/overview.py``.

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
* **Struktura u klienta i opinie klienta** (etap 2, D8–D11, 17.10.2026) —
  czytają opiekun (DL, TCM, admin) i Head of Recruitment; Finanse i Kadry
  z samego uprawnienia nie (D11). Opinię zapisują piszący opiekę, a „Podlega
  pod” i dział kontaktu — ci, którzy edytują kontakty klienta
  (``ClientAccess.can_edit_contacts``, ta sama reguła co ``api/contacts.py``).
* **„Ten tydzień”, oś konsultanta i „Przekaż do front office”** (D15,
  17.10.2026) — czytają czytelnicy opieki (zakres jak lista opieki), prośby
  o opinię i opinie na osi tylko role z D11 (Finanse widzą resztę);
  przekazanie zapisują piszący opiekę.
* **„Konsultanci”, rytm kontaktu i „Przydział”** (etap 3, O7–O10,
  17.10.2026) — trasy w ``app/api/care_consultants.py``, dołączone na końcu
  tego modułu (ten sam prefiks). „Pomiń” punkt planu wymaga powodu z listy
  i zostawia ślad ``care.plan_item_skipped``; zmiana opiekuna niesie powód
  i poprzedniego opiekuna w śladzie ``care.owner_set``.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.care_gates import (
    PEOPLE_DENIED,
    CareReader,
    CareWriter,
    OrgEditor,
    PeopleReader,
    can_curate,
    reads_client_people,
)
from app.api.recruitment_access import job_read_scope_clause
from app.core.database import get_db
from app.core.scheduling import business_today, local_now
from app.models.client_knowledge import ClientKnowledge, KnowledgeCategory
from app.models.contract import Contract
from app.models.contract_care import (
    CLIENTS_CARE,
    CONTRACTS_CARE,
    ClientFeedbackScore,
    CarePlanItem,
    ClientArea,
    RedeployQueueItem,
    SkillReviewItem,
    TechCard,
    TechVendor,
)
from app.models.job import Job
from app.models.user import User, UserRole
from app.services.care import access as care_access
from app.services.care import plan as care_plan
from app.services.care import records
from app.services.care import skills as care_skills
from app.services.care import card_inbox, client_feedback, client_people, tech_map
from app.services.care import card as care_card
from app.services.care import conversation_save, demand, front_office
from app.services.care import overview as care_overview
from app.services.care import timeline as care_timeline
from app.services.care import week as care_week_queue
from app.services.care.overview import person
from app.services.client_access import resolve_client_access
from app.services.contract_care_schema import (
    FEEDBACK_NOTE_MAX,
    NAME_MAX,
    NOTE_MAX,
    SHORT_TEXT_MAX,
)
from app.services.care.assignment import OwnerReason
from app.services.hr import audit

router = APIRouter()


@router.get("/owners")
async def list_owners(
    current_user: User = Depends(CareReader), db: AsyncSession = Depends(get_db)
) -> dict:
    users = await care_access.owner_candidates(db)
    return {"items": [{"id": user.id, "name": user.name} for user in users]}


# ── Kontrakt → zakładka „Opieka” ────────────────────────────────────────────


@router.get("/contracts/{contract_id}")
async def contract_care(
    contract_id: int,
    current_user: User = Depends(CareReader),
    db: AsyncSession = Depends(get_db),
) -> dict:
    contract = await care_access.load_contract(db, contract_id, current_user)
    return await care_overview.contract_overview(db, contract, current_user)


class OwnerBody(BaseModel):
    user_id: Optional[int] = None
    #: Powód zmiany (etap 3) — na osi konsultanta; stare wywołania go nie mają.
    reason: Optional[OwnerReason] = None


class DefaultOwnerBody(BaseModel):
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
    previous = (await care_access.effective_owners(db, [contract]))[contract.id]
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
        details={
            "previous": contract.explicit_owner_id,
            "previous_effective": previous.user_id,
            "owner": body.user_id,
            "reason": body.reason,
        },
    )
    fresh = await care_access.load_contract(db, contract_id, current_user)
    return await care_overview.contract_overview(db, fresh, current_user)


class ClientStateChangesBody(BaseModel):
    """„Co u klienta” — tylko zmienione pola (brak pola = bez zmian)."""

    area_id: Optional[int] = None
    new_area_name: Optional[str] = Field(default=None, max_length=NAME_MAX)
    manager_contact_id: Optional[int] = None
    team_size: Optional[str] = Field(default=None, max_length=80)
    team_externals: Optional[int] = Field(default=None, ge=0, le=10000)
    skill_ids: Optional[list[int]] = Field(default=None, max_length=100)
    new_skill_names: Optional[list[str]] = Field(default=None, max_length=50)
    vendors: Optional[list[str]] = Field(default=None, max_length=20)
    project_end_month: Optional[str] = Field(
        default=None, pattern=r"^\d{4}-(0[1-9]|1[0-2])$"
    )
    hiring_roles: Optional[list[str]] = Field(default=None, max_length=20)
    hiring_source: Optional[Literal["widzial", "slyszal", "plotka"]] = None


class ClientStateBody(BaseModel):
    confirmed: bool = True
    changes: ClientStateChangesBody = Field(default_factory=ClientStateChangesBody)


class GapAnswerBody(BaseModel):
    key: str = Field(min_length=3, max_length=60)
    reports_to_contact_id: Optional[int] = None
    skill_ids: list[int] = Field(default_factory=list, max_length=50)
    new_skill_names: list[str] = Field(default_factory=list, max_length=20)
    note: Optional[str] = Field(default=None, max_length=SHORT_TEXT_MAX)


class ConversationCaseBody(BaseModel):
    title: str = Field(min_length=3, max_length=200)
    area: Literal[
        "onboarding",
        "offboarding",
        "negotiation",
        "administration",
        "marketing",
        "other",
    ] = "other"
    assignee_user_id: Optional[int] = None
    due_on: Optional[date] = None


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
    # Okno „Rozmowa” (22.10.2026) — wszystko opcjonalne, stare ciało działa.
    #: „Klient zatrudnia”: role i źródło przy rozmowie — także bez „Co u klienta”.
    hiring_roles: list[str] = Field(default_factory=list, max_length=20)
    hiring_source: Optional[Literal["widzial", "slyszal", "plotka"]] = None
    client_state: Optional[ClientStateBody] = None
    gap_answers: list[GapAnswerBody] = Field(default_factory=list, max_length=20)
    cases: list[ConversationCaseBody] = Field(
        default_factory=list, max_length=conversation_save.MAX_CASES
    )


_CONVERSATION_FIELDS = tuple(records.ConversationInput.__dataclass_fields__)


def _extras(body: ConversationBody) -> conversation_save.Extras:
    client_state = None
    if body.client_state is not None:
        client_state = {
            "confirmed": body.client_state.confirmed,
            "changes": body.client_state.changes.model_dump(exclude_unset=True),
        }
    return conversation_save.Extras(
        client_state=client_state,
        hiring_roles=tuple(body.hiring_roles) if body.client_hiring else (),
        hiring_source=body.hiring_source if body.client_hiring else None,
        gap_answers=tuple(
            conversation_save.GapAnswer(
                key=answer.key,
                reports_to_contact_id=answer.reports_to_contact_id,
                skill_ids=tuple(answer.skill_ids),
                new_skill_names=tuple(answer.new_skill_names),
                note=answer.note,
            )
            for answer in body.gap_answers
        ),
        cases=tuple(
            conversation_save.CaseRequest(**case.model_dump()) for case in body.cases
        ),
    )


@router.post(
    "/contracts/{contract_id}/conversations", status_code=status.HTTP_201_CREATED
)
async def add_conversation(
    contract_id: int,
    body: ConversationBody,
    current_user: User = Depends(CareWriter),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Rozmowa + „Co u klienta”, odpowiedzi z mapy, sprawy i popyt — jedna transakcja.

    Odpowiedź to zakładka „Opieka” kontraktu (jak dotąd) z dopisanymi
    ``conversation_id``, ``tech_card_id``, ``case_ids``, ``demand_notified``
    i ``manager_kept``.
    """

    contract = await care_access.load_contract(db, contract_id, current_user)
    extras = _extras(body)
    await conversation_save.precheck(db, contract, extras, user=current_user)
    today, now = business_today(), local_now()
    conversation = await records.add_conversation(
        db,
        contract,
        records.ConversationInput(**body.model_dump(include=set(_CONVERSATION_FIELDS))),
        actor_id=current_user.id,
        today=today,
        now=now,
    )
    saved = await conversation_save.save_extras(
        db, contract, conversation, extras, user=current_user, today=today, now=now
    )
    await db.flush()
    await tech_map.invalidate([contract.client_id])
    overview = await care_overview.contract_overview(db, contract, current_user)
    return {
        **overview,
        "conversation_id": conversation.id,
        "tech_card_id": saved.tech_card_id,
        "case_ids": saved.case_ids,
        "demand_notified": saved.demand_notified,
        "manager_kept": saved.manager_kept,
    }


SkipReason = Literal[
    "recent_contact", "unreachable", "absence", "person_request", "ending", "other"
]


class PlanItemBody(BaseModel):
    status: Literal["open", "skipped"]
    #: Powód „Pomiń” (wymagany przy ``skipped``) i notatka.
    reason: Optional[SkipReason] = None
    note: Optional[str] = Field(default=None, max_length=SHORT_TEXT_MAX)


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
    skipping = body.status == "skipped"
    if skipping and body.reason is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "Podaj powód pominięcia."
        )
    item.status = body.status
    item.resolved_at = local_now() if skipping else None
    item.resolved_by = current_user.id if skipping else None
    item.skip_reason = body.reason if skipping else None
    item.skip_note = (" ".join((body.note or "").split()) or None) if skipping else None
    details: dict[str, Any] = {
        "plan_item_id": item.id,
        "kind": item.kind,
        "due_on": item.due_on.isoformat(),
    }
    if skipping:
        details["reason"] = body.reason
    audit.record(
        db,
        actor_user_id=current_user.id,
        subject_user_id=None,
        entity_type="contract",
        entity_id=contract.id,
        action="care.plan_item_skipped" if skipping else "care.plan_item_restored",
        details=details,
    )
    await db.flush()
    return await care_overview.contract_overview(db, contract, current_user)


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
    return await care_overview.contract_overview(db, contract, current_user)


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
    return await care_overview.contract_overview(db, contract, current_user)


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
    return care_overview.redeploy_payload(item)


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
        "default_owner": person(default_owner, names),
        "can_edit": await care_access.is_care_writer(db, current_user),
    }


@router.get("/clients/{client_id}/tech-cards/unlinked")
async def client_unlinked_tech_cards(
    client_id: int,
    current_user: User = Depends(CareReader),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Karty z Compassa bez kontraktu z propozycjami (import 18.10.2026)."""

    client = await care_access.load_client(db, client_id, current_user)
    result = await card_inbox.unlinked_cards(db, client.id)
    can_link = await care_access.is_care_writer(db, current_user)
    return {**result, "can_link": can_link}


class LinkCardBody(BaseModel):
    contract_id: int


@router.post("/tech-cards/{card_id}/link")
async def link_tech_card(
    card_id: int,
    body: LinkCardBody,
    current_user: User = Depends(CareWriter),
    db: AsyncSession = Depends(get_db),
) -> dict:
    card = await card_inbox.link_card(
        db, card_id=card_id, contract_id=body.contract_id, user=current_user
    )
    return {"id": card.id, "contract_id": card.contract_id}


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
    body: DefaultOwnerBody,
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
    # Nowy opiekun widzi plan swoich konsultantów od razu, nie po nocnym przebiegu.
    await care_plan.ensure_plans(
        db,
        await care_access.live_contracts(db, client_id=client.id),
        today=business_today(),
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
    return {"default_owner": person(body.user_id, names)}


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


# ── Klient → zakładka „Struktura u klienta” i opinie klienta ────────────────


async def _org_payload(
    db: AsyncSession, client_id: int, client_name: str, user: User
) -> dict[str, Any]:
    """Drzewo dla odczytu i odpowiedzi zapisu — opinie i prośby tylko w kręgu D11.

    Zapis „Podlega pod” ma inną bramkę (edycja kontaktów), więc Finanse
    z prawem edycji klientów dostają drzewo bez opinii, tak jak odczyt by im
    ich nie pokazał.
    """

    access = await resolve_client_access(db, user, client_id)
    org = await client_people.client_org(
        db,
        client_id,
        today=business_today(),
        show_contact_details=access.can_view_contacts,
        include_feedback=reads_client_people(user),
    )
    return {
        **org,
        "client_name": client_name,
        "can_edit_org": access.can_edit_contacts,
        "can_write_feedback": care_access.is_care_worker(user),
    }


@router.get("/clients/{client_id}/org")
async def client_org(
    client_id: int,
    current_user: User = Depends(PeopleReader),
    db: AsyncSession = Depends(get_db),
) -> dict:
    client = await care_access.load_client(db, client_id, current_user)
    return await _org_payload(db, client.id, client.name, current_user)


class ContactOrgBody(BaseModel):
    reports_to_contact_id: Optional[int] = None
    client_area_id: Optional[int] = None
    new_area_name: Optional[str] = Field(default=None, max_length=NAME_MAX)


@router.patch("/clients/{client_id}/contacts/{contact_id}")
async def update_contact_org(
    client_id: int,
    contact_id: int,
    body: ContactOrgBody,
    current_user: User = Depends(OrgEditor),
    db: AsyncSession = Depends(get_db),
) -> dict:
    client = await care_access.load_client(db, client_id, current_user)
    access = await resolve_client_access(db, current_user, client.id)
    if not access.can_edit_contacts:
        raise access.edit_denial(
            "edycja struktury u klienta wymaga prawa edycji kontaktów klienta"
        )
    await client_people.update_contact_org(
        db,
        client_id=client.id,
        contact_id=contact_id,
        changes={key: getattr(body, key) for key in body.model_fields_set},
        actor_id=current_user.id,
    )
    await tech_map.invalidate([client.id])
    return await _org_payload(db, client.id, client.name, current_user)


@router.get("/feedback-requests")
async def feedback_requests(
    scope: Literal["mine", "all"] = "mine",
    current_user: User = Depends(PeopleReader),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Prośby o opinię (D9) w zakresie czytającego.

    ``mine`` — u opiekuna jego konsultantów, a u Delivery Leada wszystkie
    z jego portfela; ``all`` — cały zakres (DL i tak tylko swoich klientów).
    """

    allowed = await care_access.allowed_client_ids(current_user, db)
    items = await client_people.feedback_requests(
        db, client_ids=allowed, today=business_today()
    )
    if scope == "mine" and not (
        allowed is not None and current_user.has_role(UserRole.delivery_lead)
    ):
        items = [item for item in items if current_user.id in item["owner_ids"]]
    return {"items": items, "total": len(items), "scope": scope}


class FeedbackScoreBody(BaseModel):
    contract_id: int
    quality: Optional[int] = Field(default=None, ge=1, le=5)
    communication: Optional[int] = Field(default=None, ge=1, le=5)
    autonomy: Optional[int] = Field(default=None, ge=1, le=5)


class DemandBody(BaseModel):
    """Rozstrzygnięcie karty „Popyt do sprawdzenia” (Delivery Lead klienta)."""

    key: str = Field(min_length=8, max_length=120)
    outcome: Literal["confirmed", "not_now", "stale"]
    role: Optional[str] = Field(default=None, max_length=demand.ROLE_MAX)
    headcount: Optional[int] = Field(default=None, ge=1, le=100)
    start_month: Optional[str] = Field(default=None, pattern=r"^\d{4}-(0[1-9]|1[0-2])$")
    skill_ids: list[int] = Field(default_factory=list, max_length=30)


class FeedbackBody(BaseModel):
    #: Bez kontaktu tylko przy samym rozstrzygnięciu popytu („nieaktualne”).
    contact_id: Optional[int] = None
    held_on: date
    channel: Literal["phone", "meeting", "email"] = "phone"
    extension_outlook: Optional[Literal["yes", "likely", "unsure", "no"]] = None
    note: Optional[str] = Field(default=None, max_length=FEEDBACK_NOTE_MAX)
    scores: list[FeedbackScoreBody] = Field(default_factory=list, max_length=100)
    demand: Optional[DemandBody] = None


NO_FEEDBACK_CONTACT = "Wybierz osobę z firmy klienta, z którą była rozmowa."


@router.post("/clients/{client_id}/feedback", status_code=status.HTTP_201_CREATED)
async def add_client_feedback(
    client_id: int,
    body: FeedbackBody,
    current_user: User = Depends(CareWriter),
    db: AsyncSession = Depends(get_db),
) -> dict:
    # D11: opinie klienta zapisuje ten sam krąg, który je czyta — osoba z puli
    # opiekunów bez roli (np. Finanse) prowadzi opiekę, ale opinii nie widzi.
    if not reads_client_people(current_user):
        raise HTTPException(status.HTTP_403_FORBIDDEN, PEOPLE_DENIED)
    client = await care_access.load_client(db, client_id, current_user)
    if body.contact_id is None and body.demand is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, NO_FEEDBACK_CONTACT)
    if body.demand is not None and not await demand.can_resolve(
        db, current_user, client.id
    ):
        raise HTTPException(status.HTTP_403_FORBIDDEN, demand.RESOLVE_DENIED)
    today = business_today()
    session = None
    if body.contact_id is not None:
        session = await client_feedback.save_feedback(
            db,
            client_id=client.id,
            payload=client_feedback.FeedbackInput(
                contact_id=body.contact_id,
                held_on=body.held_on,
                channel=body.channel,
                extension_outlook=body.extension_outlook,
                note=body.note,
                scores=tuple(
                    client_feedback.ScoreInput(**score.model_dump())
                    for score in body.scores
                ),
            ),
            actor_id=current_user.id,
            today=today,
        )
    jobs_new_url = None
    demand_keys: list[str] = []
    if body.demand is not None:
        demand_keys = await demand.resolve(
            db,
            client_id=client.id,
            resolution=demand.Resolution(
                key=body.demand.key,
                outcome=body.demand.outcome,
                role=body.demand.role,
                headcount=body.demand.headcount,
                start_month=body.demand.start_month,
                skill_ids=tuple(body.demand.skill_ids),
            ),
            actor_id=current_user.id,
            today=today,
            now=local_now(),
        )
        if body.demand.outcome == "confirmed":
            jobs_new_url = demand.jobs_new_url(
                client_id=client.id,
                hm_contact_id=body.contact_id,
                skill_ids=body.demand.skill_ids,
                title=body.demand.role,
            )
    contract_ids = (
        sorted(
            await db.scalars(
                select(ClientFeedbackScore.contract_id).where(
                    ClientFeedbackScore.session_id == session.id
                )
            )
        )
        if session is not None
        else []
    )
    return {
        "id": session.id if session is not None else None,
        "held_on": session.held_on if session is not None else body.held_on,
        "contact_id": session.contact_id if session is not None else None,
        "contract_ids": contract_ids,
        "demand_keys": demand_keys,
        "jobs_new_url": jobs_new_url,
    }


@router.get("/contracts/{contract_id}/feedback")
async def contract_feedback(
    contract_id: int,
    current_user: User = Depends(PeopleReader),
    db: AsyncSession = Depends(get_db),
) -> dict:
    contract = await care_access.load_contract(db, contract_id, current_user)
    items = await client_feedback.contract_history(db, contract.id)
    names = await care_access.user_names(db, [item["created_by"] for item in items])
    return {
        "items": [
            {
                **{key: value for key, value in item.items() if key != "created_by"},
                "author": person(item["created_by"], names),
            }
            for item in items
        ],
        "client_id": contract.client_id,
        "can_write": await care_access.is_care_writer(db, current_user),
    }


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
    return await care_overview.my_consultants(db, current_user, scope)


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
                **care_overview.redeploy_payload(item),
                "candidate_id": contract.candidate_id,
                "candidate_name": contract.candidate_name,
                "client_id": contract.client_id,
                "client_name": contract.client_name,
                "job_title": contract.job_title,
                "end_date": contract.end_date,
                "owner": person(owners[contract.id].user_id, names),
            }
        )
    return {
        "items": rows,
        "total": len(rows),
        "can_edit": await care_access.is_care_writer(db, current_user),
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
    return care_overview.redeploy_payload(item)


# ── /care: „Ten tydzień”, oś konsultanta, „Przekaż do front office” (D15) ──


@router.get("/week")
async def care_week(
    scope: Literal["mine", "all"] = "mine",
    day: Optional[date] = Query(default=None, alias="from"),
    current_user: User = Depends(CareReader),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Jedna kolejka na tydzień (pon–pt): rozmowy z powodem i prośby o opinię."""

    today = business_today()
    allowed = await care_access.allowed_client_ids(current_user, db)
    result = await care_week_queue.week_queue(
        db,
        user=current_user,
        allowed=allowed,
        scope=scope,
        day=day or care_week_queue.default_day(today),
        today=today,
        include_feedback=reads_client_people(current_user),
    )
    return {
        **result,
        "can_edit": await care_access.is_care_writer(db, current_user),
        "can_write_feedback": care_access.is_care_worker(current_user),
    }


@router.get("/contracts/{contract_id}/timeline")
async def contract_timeline(
    contract_id: int,
    current_user: User = Depends(CareReader),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Oś konsultanta: rekrutacja → start → rozmowy → opinie → zamówienia."""

    contract = await care_access.load_contract(db, contract_id, current_user)
    result = await care_timeline.contract_timeline(
        db,
        contract,
        today=business_today(),
        include_feedback=reads_client_people(current_user),
        viewer=current_user,
    )
    return {**result, "can_edit": await care_access.is_care_writer(db, current_user)}


@router.get("/contracts/{contract_id}/card")
async def contract_card(
    contract_id: int,
    current_user: User = Depends(CareReader),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Karta konsultanta (panel ``/care`` i zakładka „Opieka” kontraktu)."""

    contract = await care_access.load_contract(db, contract_id, current_user)
    return await care_card.consultant_card(
        db,
        contract,
        current_user,
        today=business_today(),
        scope_clause=job_read_scope_clause(current_user, Job.id),
    )


@router.get("/contracts/{contract_id}/client-state")
async def contract_client_state(
    contract_id: int,
    current_user: User = Depends(CareReader),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """„Co u klienta” w oknie rozmowy: ostatni stan i pytania z mapy klienta."""

    contract = await care_access.load_contract(db, contract_id, current_user)
    return await care_card.client_state(db, contract, today=business_today())


@router.get("/contracts/{contract_id}/front-office")
async def contract_front_office(
    contract_id: int,
    current_user: User = Depends(CareReader),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Czy przekazać do front office i pasujące rekrutacje („Pasuje też do”)."""

    contract = await care_access.load_contract(db, contract_id, current_user)
    result = await front_office.overview(
        db,
        contract,
        today=business_today(),
        profile_user_id=current_user.id,
        scope_clause=job_read_scope_clause(current_user, Job.id),
    )
    return {**result, "can_edit": await care_access.is_care_writer(db, current_user)}


class FrontOfficeBody(BaseModel):
    job_ids: list[int] = Field(default_factory=list, max_length=20)


@router.post(
    "/contracts/{contract_id}/front-office", status_code=status.HTTP_201_CREATED
)
async def hand_off_to_front_office(
    contract_id: int,
    body: FrontOfficeBody,
    current_user: User = Depends(CareWriter),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Ślad, wpis „Do przepięcia” w toku i powiadomienia front office."""

    contract = await care_access.load_contract(db, contract_id, current_user)
    result = await front_office.hand_off(
        db,
        contract,
        job_ids=body.job_ids,
        actor=current_user,
        today=business_today(),
        scope_clause=job_read_scope_clause(current_user, Job.id),
    )
    await tech_map.invalidate([contract.client_id])
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
        "can_edit": await care_access.is_care_writer(db, current_user),
        "can_curate": can_curate(current_user),
    }


# „Konsultanci”, rytm kontaktu i „Przydział” (etap 3) — ten sam prefiks ``/api/care``.
from app.api import care_consultants  # noqa: E402

router.include_router(care_consultants.router)

# Propozycje struktury u klienta („Propozycja automatu + akcept DL”, 18.10.2026).
from app.api import care_structure  # noqa: E402

router.include_router(care_structure.router)

# „Do zrobienia” (kanban) i „Klienci” w Opiece (przebudowa, 22.10.2026).
from app.api import care_board  # noqa: E402

router.include_router(care_board.router)

# Sprawy konsultanta w karcie (``GET /contracts/{id}/cases``, moduł spraw).
from app.api import care_cases  # noqa: E402

router.include_router(care_cases.router)
