"""Centralny resolver uprawnień per klient (Moduł 1, PR 1/7 — containment RBAC).

Zamyka M1-SEC-01/02: do tej pory kontakty, wiedza, materiały i umowy ramowe
klienta były czytane/zapisywane przy samym ``CurrentUser`` (każdy aktywny,
zalogowany użytkownik — także rola ``user``/viewer). Ten moduł jest jedynym
źródłem decyzji "kto może co" per klient; routery mają pytać ``ClientAccess``
zamiast utrzymywać lokalne warunki.

Polityka (fail-closed; decyzje produktowe "wg polityki" domyślnie NA NIE):

- ``admin`` / ``head_of_recruitment`` — pełny dostęp.
- ``delivery_lead`` — zarządzanie kontaktami/wiedzą i wgląd w dokumenty
  prawne wyłącznie klienta z jawnym ``DeliveryLeadClientAssignment``.
- ``tac`` — ten sam zakres wyłącznie klienta z jawnym
  ``ClientTacAssignment``. Brak przypisań jest prawdziwym deny-all, nigdy
  fallbackiem do całej organizacji.
- ``recruiter`` / ``sourcer`` — tylko odczyt bezpiecznej projekcji i tylko
  w kontekście stanowiska tego klienta (przypisanie do Joba: recruiter_id /
  delivery_lead_id / tac_id / created_by / JobCollaborator).
- ``user`` (viewer, np. QC/klient) — brak dostępu do kontaktów, wiedzy,
  materiałów, dokumentów i finansów.
- Właściciel relacji (``Contact.key_relationship_owner_id``) — może czytać
  prywatne notatki i edytować pola relacyjne SWOJEGO kontaktu, ale nie może
  sam przepisać ownera.
- Zmiana ownera relacji — wyłącznie admin/HoR; wyjątek: użytkownik z prawem
  edycji może "zaklaimować" pustego ownera na siebie (None → self).
- Finanse — istniejący helper capability z ``app.api.financial_access``;
  wydzielona persona Finance korzysta z person-free API i nie otwiera przez
  samą capability mieszanych powierzchni klienta.
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.api.financial_access import has_financial_access
from app.core.database import get_db
from app.models.activity import Activity
from app.models.client import Client
from app.models.contact import Contact
from app.models.job import Job
from app.models.job_collaborator import JobCollaborator
from app.models.team_structure import (
    ClientTacAssignment,
    DeliveryLeadClientAssignment,
)
from app.models.user import User, UserRole

# Role "administracyjne" — pełny dostęp do modułu klienta.
ADMIN_LIKE_ROLES = (UserRole.admin, UserRole.head_of_recruitment)
# Role zaufane klientowo — zarządzają kontaktami/wiedzą/dokumentami.
CLIENT_TEAM_ROLES = (UserRole.delivery_lead, UserRole.tac)
# Role operacyjne delivery — odczyt w kontekście przypisanego stanowiska.
DELIVERY_ROLES = (UserRole.recruiter, UserRole.sourcer)

# Stabilny kod błędu w response 403 (kryterium akceptacji PR1) — frontend
# i monitoring mogą filtrować po prefiksie zamiast po polskim tekście.
FORBIDDEN_CODE = "client_access_denied"


@dataclass(frozen=True)
class ClientAccess:
    """Decyzja dostępu użytkownika do jednego klienta (immutable snapshot)."""

    user_id: int
    client_id: int
    is_admin_like: bool
    is_organization_reader: bool
    is_client_team: bool
    is_job_assigned: bool

    can_view_contacts: bool
    can_edit_contacts: bool
    can_reassign_relationship_owner: bool
    can_view_knowledge: bool
    can_edit_knowledge: bool
    can_view_materials: bool
    can_edit_materials: bool
    can_view_legal_documents: bool
    can_edit_legal_documents: bool
    can_view_financials: bool
    can_manage_client: bool

    def can_view_contact_private_notes(self, contact: Contact) -> bool:
        """Prywatne notatki relacyjne: admin/HoR + właściciel danej relacji.

        Zawierają dane osobiste (urodziny, rodzina, hobby) — domyślnie
        widzi je tylko owner i administracja (rekomendacja audytu, pkt 19.4).

        Notatki NIE-zaklaimowane (owner is None — UI historycznie nie
        ustawiało ownera) widzą role z prawem edycji kontaktów. Inaczej
        DL/TAC, który sam je zapisał, dostawałby pusty formularz i przy
        zapisie po cichu WYMAZAŁ istniejącą treść (dialog odsyła całość).
        """
        if self.is_admin_like or self.is_organization_reader:
            return True
        if contact.key_relationship_owner_id is None:
            return self.can_edit_contacts
        return contact.key_relationship_owner_id == self.user_id

    def is_relationship_owner(self, contact: Contact) -> bool:
        return (
            contact.key_relationship_owner_id is not None
            and contact.key_relationship_owner_id == self.user_id
        )


def deny(detail: str) -> HTTPException:
    """403 ze stabilnym kodem błędu (`client_access_denied: <powód>`)."""
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=f"{FORBIDDEN_CODE}: {detail}",
    )


async def _user_assigned_to_client_job(
    db: AsyncSession, user_id: int, client_id: int
) -> bool:
    """Czy user jest przypisany do jakiegokolwiek Joba tego klienta."""
    direct = (
        select(Job.id)
        .where(
            Job.client_id == client_id,
            or_(
                Job.recruiter_id == user_id,
                Job.delivery_lead_id == user_id,
                Job.tac_id == user_id,
                Job.created_by == user_id,
            ),
        )
        .exists()
    )
    collab = (
        select(JobCollaborator.id)
        .join(Job, Job.id == JobCollaborator.job_id)
        .where(Job.client_id == client_id, JobCollaborator.user_id == user_id)
        .exists()
    )
    result = await db.execute(select(or_(direct, collab)))
    return bool(result.scalar())


async def _job_assigned_client_ids(
    db: AsyncSession,
    user_id: int,
) -> frozenset[int]:
    """Clients reachable through the user's exact Job/JobCollaborator graph."""

    direct_ids = (
        await db.scalars(
            select(Job.client_id)
            .where(
                or_(
                    Job.recruiter_id == user_id,
                    Job.delivery_lead_id == user_id,
                    Job.tac_id == user_id,
                    Job.created_by == user_id,
                )
            )
            .distinct()
        )
    ).all()
    collaborator_ids = (
        await db.scalars(
            select(Job.client_id)
            .join(JobCollaborator, JobCollaborator.job_id == Job.id)
            .where(JobCollaborator.user_id == user_id)
            .distinct()
        )
    ).all()
    return frozenset(int(client_id) for client_id in (*direct_ids, *collaborator_ids))


async def resolve_client_team_client_ids(
    db: AsyncSession,
    user: User,
) -> frozenset[int] | None:
    """Resolve the explicit client graph for DL/TAC client-team capabilities.

    ``None`` means unrestricted Admin/Head of Recruitment oversight. Every
    other caller receives a concrete set: a Delivery Lead contributes only
    ``DeliveryLeadClientAssignment`` rows, a TAC only ``ClientTacAssignment``
    rows, and a valid hybrid receives the union of its two explicit graphs.
    An empty set is authoritative deny-all.
    """

    if user.has_any_role(*ADMIN_LIKE_ROLES):
        return None

    client_ids: set[int] = set()
    if user.has_role(UserRole.delivery_lead):
        client_ids.update(
            (
                await db.scalars(
                    select(DeliveryLeadClientAssignment.client_id).where(
                        DeliveryLeadClientAssignment.delivery_lead_user_id == user.id
                    )
                )
            ).all()
        )
    if user.has_role(UserRole.tac):
        client_ids.update(
            (
                await db.scalars(
                    select(ClientTacAssignment.client_id).where(
                        ClientTacAssignment.tac_user_id == user.id
                    )
                )
            ).all()
        )
    return frozenset(int(client_id) for client_id in client_ids)


async def resolve_client_visible_client_ids(
    db: AsyncSession,
    user: User,
) -> frozenset[int] | None:
    """Resolve all clients whose operational surface the user may read.

    Admin/HoR and Finance business read remain unrestricted. DL/TAC contribute
    only explicit relationship assignments. Recruiter/Sourcer contribute only
    clients reached through their exact Job or JobCollaborator membership.
    Empty is authoritative deny-all and never means organization-wide fallback.
    """

    if user.has_role(UserRole.finance):
        return None

    client_ids = await resolve_client_team_client_ids(db, user)
    if client_ids is None:
        return None

    visible = set(client_ids)
    if user.has_any_role(*DELIVERY_ROLES):
        visible.update(await _job_assigned_client_ids(db, user.id))
    return frozenset(visible)


async def resolve_client_access(
    db: AsyncSession, user: User, client_id: int
) -> ClientAccess:
    """Zbuduj decyzję dostępu. Zakłada, że klient istnieje (404 wcześniej)."""
    is_admin_like = user.has_any_role(*ADMIN_LIKE_ROLES)
    is_organization_reader = user.has_role(UserRole.finance)
    client_team_client_ids = await resolve_client_team_client_ids(db, user)
    is_client_team = (
        client_team_client_ids is None or client_id in client_team_client_ids
    )
    is_delivery = user.has_any_role(*DELIVERY_ROLES)

    # Query o przypisanie do Joba tylko gdy może zmienić decyzję.
    is_job_assigned = False
    if not is_admin_like and not is_client_team and is_delivery:
        is_job_assigned = await _user_assigned_to_client_job(db, user.id, client_id)

    can_view_team_surfaces = (
        is_admin_like or is_organization_reader or is_client_team or is_job_assigned
    )
    can_edit = is_admin_like or is_client_team

    return ClientAccess(
        user_id=user.id,
        client_id=client_id,
        is_admin_like=is_admin_like,
        is_organization_reader=is_organization_reader,
        is_client_team=is_client_team,
        is_job_assigned=is_job_assigned,
        can_view_contacts=can_view_team_surfaces,
        can_edit_contacts=can_edit,
        can_reassign_relationship_owner=is_admin_like,
        can_view_knowledge=can_view_team_surfaces,
        can_edit_knowledge=can_edit,
        # Materiały klienta są częścią jego powierzchni operacyjnej. Recruiter
        # i sourcer widzą je wyłącznie przez przypisany Job tego klienta.
        can_view_materials=can_view_team_surfaces,
        can_edit_materials=can_edit,
        can_view_legal_documents=(
            is_admin_like or is_organization_reader or is_client_team
        ),
        can_edit_legal_documents=can_edit,
        can_view_financials=can_view_team_surfaces and has_financial_access(user),
        can_manage_client=is_admin_like,
    )


async def assert_client_exists(db: AsyncSession, client_id: int) -> None:
    """404 dla nieistniejącego klienta.

    Polityka ujawniania: istnienie klienta nie jest tajemnicą (lista klientów
    jest widoczna operacyjnie), chronione są dane. Dlatego brak encji → 404,
    brak prawa do operacji → 403.
    """
    result = await db.execute(select(Client.id).where(Client.id == client_id))
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Client not found")


async def get_client_access(
    client_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ClientAccess:
    """FastAPI dependency dla tras z ``client_id`` w path (404 → decyzja)."""
    await assert_client_exists(db, client_id)
    return await resolve_client_access(db, current_user, client_id)


def record_client_audit(
    db: AsyncSession,
    *,
    client_id: int,
    actor_id: int,
    action: str,
    details: dict | None = None,
) -> None:
    """Audit event w istniejącym dzienniku ``activities``.

    ``details`` mają zawierać wyłącznie identyfikatory i NAZWY zmienionych pól
    — nigdy wartości pól prywatnych (relationship_notes itp.).
    """
    db.add(
        Activity(
            entity_type="client",
            entity_id=client_id,
            action=action,
            user_id=actor_id,
            details=details or {},
        )
    )
