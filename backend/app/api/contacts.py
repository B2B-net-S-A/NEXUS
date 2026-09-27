"""Kontakty klienta + relacje (Moduł 1, PR 1/7 — containment RBAC).

Do 2026-07 cały CRUD (łącznie z przepisaniem właściciela relacji) działał na
samym ``CurrentUser`` — każdy aktywny użytkownik, także rola ``user``/viewer,
mógł zmieniać kontakty i prywatne notatki relacyjne. Teraz decyzje podejmuje
``app.services.client_access.ClientAccess`` i bramka sekcji:

- odczyt listy jest współdzielony z Pipeline i zawężany grafem klient/Job;
- ``relationship_notes`` (dane prywatne) tylko admin lub uprawniony owner —
  pozostali dostają projekcję BEZ tego pola (nie ``null``);
- create/update/delete: admin lub Delivery Lead u klientów z portfela;
- owner relacji może edytować pola relacyjne swojego kontaktu;
- zmiana ``key_relationship_owner_id``: admin (wyjątek: claim None → self);
- każda mutacja zostawia audit event w ``activities`` (bez wartości pól
  prywatnych — tylko nazwy pól).
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Optional, Union

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel, Field

from app.core.database import get_db
from app.models.contact import Contact, RelationshipStrength
from app.models.client import Client
from app.models.user import User
from app.api.deps import get_current_user
from app.api.section_access import (
    DeliverySectionUser,
    ProductSection,
    SectionAccess,
    section_access_for_user,
)
from app.services.client_access import (
    contact_private_notes_checker,
    ClientAccess,
    assert_client_assignable,
    assert_client_exists,
    deny,
    record_client_audit,
    resolve_client_access,
    resolve_client_visible_client_ids,
)

router = APIRouter()


# ── Schemas ──────────────────────────────────────────────────────────────────


class ContactCreate(BaseModel):
    client_id: int
    # Runda 9 (R9-N4-5): lustro długości kolumn `contacts` (422 zamiast 500).
    name: str = Field(max_length=255)
    email: Optional[str] = Field(None, max_length=255)
    phone: Optional[str] = Field(None, max_length=50)
    position: Optional[str] = Field(None, max_length=255)
    department: Optional[str] = Field(None, max_length=255)
    is_decision_maker: bool = False
    notes: Optional[str] = None
    last_contacted_at: Optional[datetime] = None
    # Key relationship fields (2026-05-11)
    is_key_relationship: bool = False
    relationship_strength: Optional[RelationshipStrength] = None
    relationship_notes: Optional[str] = None
    key_relationship_owner_id: Optional[int] = None
    last_personal_touchpoint_at: Optional[datetime] = None


class ContactUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=255)
    email: Optional[str] = Field(None, max_length=255)
    phone: Optional[str] = Field(None, max_length=50)
    position: Optional[str] = Field(None, max_length=255)
    department: Optional[str] = Field(None, max_length=255)
    is_decision_maker: Optional[bool] = None
    notes: Optional[str] = None
    last_contacted_at: Optional[datetime] = None
    # Key relationship fields
    is_key_relationship: Optional[bool] = None
    relationship_strength: Optional[RelationshipStrength] = None
    relationship_notes: Optional[str] = None
    key_relationship_owner_id: Optional[int] = None
    last_personal_touchpoint_at: Optional[datetime] = None


class ContactSafeResponse(BaseModel):
    """Projekcja bez prywatnych notatek relacyjnych.

    ``relationship_notes`` celowo NIE istnieje w tym modelu — użytkownik bez
    prawa nie dostaje pola nawet jako ``null`` (kryterium M1-SEC-02).
    """

    id: int
    client_id: int
    name: str
    email: Optional[str]
    phone: Optional[str]
    position: Optional[str]
    department: Optional[str]
    is_decision_maker: bool
    notes: Optional[str]
    last_contacted_at: Optional[datetime]
    created_at: datetime
    is_key_relationship: bool
    relationship_strength: Optional[RelationshipStrength]
    key_relationship_owner_id: Optional[int]
    last_personal_touchpoint_at: Optional[datetime]

    model_config = {"from_attributes": True}


class ContactResponse(ContactSafeResponse):
    """Pełna projekcja — admin i uprawniony właściciel danej relacji."""

    relationship_notes: Optional[str]


class ContactWithClientResponse(ContactResponse):
    client_name: Optional[str] = None


class ContactWithClientSafeResponse(ContactSafeResponse):
    client_name: Optional[str] = None


# Kolejność w Union nie decyduje — zwracamy gotowe instancje modeli, a brak
# atrybutu `relationship_notes` w wariancie safe wyklucza pełny model.
AnyContactResponse = Union[ContactResponse, ContactSafeResponse]
AnyContactWithClientResponse = Union[
    ContactWithClientResponse, ContactWithClientSafeResponse
]

# Pola, które może edytować właściciel relacji na SWOIM kontakcie
# (bez prawa do pól tożsamościowych i bez przepisania ownera).
_OWNER_EDITABLE_FIELDS = {
    "is_key_relationship",
    "relationship_strength",
    "relationship_notes",
    "last_personal_touchpoint_at",
    "last_contacted_at",
}


def _contact_projection(contact: Contact, access: ClientAccess) -> AnyContactResponse:
    if access.can_view_contact_private_notes(contact):
        return ContactResponse.model_validate(contact)
    return ContactSafeResponse.model_validate(contact)


async def _assert_relationship_owner_exists(
    db: AsyncSession, user_id: Optional[int]
) -> None:
    """422 dla właściciela relacji, którego nie ma albo jest nieaktywny.

    Runda 9 (R9-N4-5): nieistniejące id szło prosto do FK
    ``contacts.key_relationship_owner_id`` i kończyło się 500 bez CORS.
    """
    if user_id is None:
        return
    is_active = await db.scalar(select(User.is_active).where(User.id == user_id))
    if not is_active:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Wskazany właściciel relacji nie istnieje albo jest nieaktywny.",
        )


async def _load_contact(db: AsyncSession, contact_id: int) -> Contact:
    result = await db.execute(select(Contact).where(Contact.id == contact_id))
    contact = result.scalar_one_or_none()
    if not contact:
        raise HTTPException(status_code=404, detail="Contact not found")
    return contact


@dataclass(frozen=True)
class GlobalContactScope:
    user: User
    visible_client_ids: frozenset[int] | None


def _require_contact_read_section(current_user: User) -> None:
    """Contacts are shared by Pipeline and Delivery, but never section-less."""

    granted = max(
        section_access_for_user(current_user, ProductSection.pipeline),
        section_access_for_user(current_user, ProductSection.delivery),
    )
    if granted < SectionAccess.read:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "section_access_denied",
                "sections": [
                    ProductSection.pipeline.value,
                    ProductSection.delivery.value,
                ],
                "required": SectionAccess.read.name,
            },
        )


async def require_contact_read_access(
    current_user: User = Depends(get_current_user),
) -> User:
    _require_contact_read_section(current_user)
    return current_user


ContactReadUser = Annotated[User, Depends(require_contact_read_access)]


async def require_global_contact_access(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> GlobalContactScope:
    """Resolve global-contact visibility before the endpoint query executes."""

    _require_contact_read_section(current_user)
    visible_client_ids = await resolve_client_visible_client_ids(db, current_user)
    if visible_client_ids is not None and not visible_client_ids:
        raise deny("lista kontaktów wymaga jawnego przypisania klienta lub Joba")
    return GlobalContactScope(
        user=current_user,
        visible_client_ids=visible_client_ids,
    )


GlobalContactAccess = Annotated[
    GlobalContactScope,
    Depends(require_global_contact_access),
]


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.get("/contacts", response_model=list[AnyContactWithClientResponse])
async def list_all_contacts(
    scope: GlobalContactAccess,
    db: AsyncSession = Depends(get_db),
    search: Optional[str] = Query(None, alias="search"),
):
    """Kontakty cross-client (globalna wyszukiwarka).

    Admin, HoR, Finance i TCM widzą organizację w zakresie swojej projekcji.
    DL widzi klientów z portfela (25.09.2026), TAC swoje jawne przypisania, a
    recruiter/sourcer klientów osiągalnych przez Job. Pusty graf relacji jest
    deny-all.
    """
    current_user = scope.user
    visible_client_ids = scope.visible_client_ids
    # Runda 9 (R9-N4-2): ta sama reguła notatek co `GET /clients/{id}/contacts`
    # (`ClientAccess.can_view_contact_private_notes`), liczona raz na klienta.
    can_see_private_notes = await contact_private_notes_checker(db, current_user)

    query = (
        select(Contact, Client.name.label("client_name"))
        .join(Client, Contact.client_id == Client.id)
        .order_by(Contact.is_decision_maker.desc(), Contact.name)
    )
    if visible_client_ids is not None:
        query = query.where(Contact.client_id.in_(sorted(visible_client_ids)))
    if search:
        query = query.where(
            or_(
                Contact.name.ilike(f"%{search}%"),
                Contact.email.ilike(f"%{search}%"),
            )
        )
    result = await db.execute(query)
    rows = result.all()
    contacts_out: list[AnyContactWithClientResponse] = []
    for contact, client_name in rows:
        can_see_notes = can_see_private_notes(contact)
        model = (
            ContactWithClientResponse
            if can_see_notes
            else ContactWithClientSafeResponse
        )
        payload = model.model_validate(contact, from_attributes=True)
        contacts_out.append(payload.model_copy(update={"client_name": client_name}))
    return contacts_out


@router.get(
    "/clients/{client_id}/contacts",
    response_model=list[AnyContactResponse],
)
async def list_client_contacts(
    client_id: int,
    current_user: ContactReadUser,
    db: AsyncSession = Depends(get_db),
):
    await assert_client_exists(db, client_id)
    access = await resolve_client_access(db, current_user, client_id)
    if not access.can_view_contacts:
        raise deny("brak dostępu do kontaktów tego klienta")

    result = await db.execute(
        select(Contact)
        .where(Contact.client_id == client_id)
        .order_by(Contact.is_decision_maker.desc(), Contact.name)
    )
    return [_contact_projection(c, access) for c in result.scalars().all()]


@router.post(
    "/contacts",
    response_model=AnyContactResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_contact(
    data: ContactCreate,
    current_user: DeliverySectionUser,
    db: AsyncSession = Depends(get_db),
):
    await assert_client_exists(db, data.client_id)
    access = await resolve_client_access(db, current_user, data.client_id)
    if not access.can_edit_contacts:
        raise deny("tworzenie kontaktów wymaga roli admin lub Delivery Lead")
    # Runda 7 (R7-X5-4): kontakt usuniętego albo scalonego klienta nie trafi na
    # żaden profil.
    await assert_client_assignable(db, data.client_id)
    if (
        data.key_relationship_owner_id is not None
        and data.key_relationship_owner_id != current_user.id
        and not access.can_reassign_relationship_owner
    ):
        raise deny("ustawienie innego właściciela relacji wymaga roli admin")
    await _assert_relationship_owner_exists(db, data.key_relationship_owner_id)

    contact = Contact(**data.model_dump())
    db.add(contact)
    await db.flush()
    record_client_audit(
        db,
        client_id=contact.client_id,
        actor_id=current_user.id,
        action="contact_created",
        details={"contact_id": contact.id, "name": contact.name},
    )
    await db.flush()
    await db.refresh(contact)
    return _contact_projection(contact, access)


@router.put("/contacts/{contact_id}", response_model=AnyContactResponse)
async def update_contact(
    contact_id: int,
    data: ContactUpdate,
    current_user: DeliverySectionUser,
    db: AsyncSession = Depends(get_db),
):
    contact = await _load_contact(db, contact_id)
    access = await resolve_client_access(db, current_user, contact.client_id)

    payload = data.model_dump(exclude_unset=True)
    requested_fields = set(payload)

    # 1. Zmiana właściciela relacji — najbardziej chroniona operacja.
    owner_changed = (
        "key_relationship_owner_id" in payload
        and payload["key_relationship_owner_id"] != contact.key_relationship_owner_id
    )
    if owner_changed:
        is_self_claim = (
            contact.key_relationship_owner_id is None
            and payload["key_relationship_owner_id"] == current_user.id
        )
        if not access.can_reassign_relationship_owner and not (
            is_self_claim and access.can_edit_contacts
        ):
            raise deny("zmiana właściciela relacji wymaga roli admin")
        await _assert_relationship_owner_exists(
            db, payload["key_relationship_owner_id"]
        )

    # 2. Kto może edytować pozostałe pola.
    if not access.can_edit_contacts:
        if access.is_relationship_owner(contact):
            # Owner relacji: tylko pola relacyjne swojego kontaktu.
            # Niezmieniony owner_id (np. FE odsyła pełny obiekt) nie jest
            # traktowany jako próba przepisania.
            tolerated = {"key_relationship_owner_id"} if not owner_changed else set()
            illegal = requested_fields - _OWNER_EDITABLE_FIELDS - tolerated
            if illegal:
                raise deny(
                    "właściciel relacji może edytować tylko pola relacyjne "
                    f"swojego kontaktu (niedozwolone: {sorted(illegal)})"
                )
        else:
            raise deny("edycja kontaktu wymaga roli admin lub Delivery Lead")

    for k, v in payload.items():
        setattr(contact, k, v)

    action = "contact_owner_reassigned" if owner_changed else "contact_updated"
    record_client_audit(
        db,
        client_id=contact.client_id,
        actor_id=current_user.id,
        action=action,
        details={
            "contact_id": contact.id,
            "fields": sorted(requested_fields),
        },
    )
    await db.flush()
    await db.refresh(contact)
    return _contact_projection(contact, access)


@router.delete("/contacts/{contact_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_contact(
    contact_id: int,
    current_user: DeliverySectionUser,
    db: AsyncSession = Depends(get_db),
):
    contact = await _load_contact(db, contact_id)
    access = await resolve_client_access(db, current_user, contact.client_id)
    if not access.can_edit_contacts:
        raise deny("usunięcie kontaktu wymaga roli admin lub Delivery Lead")

    record_client_audit(
        db,
        client_id=contact.client_id,
        actor_id=current_user.id,
        action="contact_deleted",
        details={"contact_id": contact.id, "name": contact.name},
    )
    if contact.external_source == "traffit" and contact.external_id:
        # Runda 10 (R10-N11-4): nagrobek — nocny import nie odtworzy kontaktu.
        from app.services.contact_duplicate_merge import (
            add_deleted_traffit_contact,
        )

        await add_deleted_traffit_contact(db, str(contact.external_id))
    await db.delete(contact)
