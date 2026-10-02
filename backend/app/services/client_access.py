"""Centralny resolver uprawnień per klient (Moduł 1, PR 1/7 — containment RBAC).

Zamyka M1-SEC-01/02: do tej pory kontakty, wiedza, materiały i umowy ramowe
klienta były czytane/zapisywane przy samym ``CurrentUser`` (każdy aktywny,
zalogowany użytkownik — także rola ``user``/viewer). Ten moduł jest jedynym
źródłem decyzji "kto może co" per klient; routery mają pytać ``ClientAccess``
zamiast utrzymywać lokalne warunki.

Od migracji 0410 decyzję składają dwie rzeczy:

**1. Uprawnienia z ekranu** (``permission_catalog``) mówią, CO konto może:

- „Klienci, kontrakty i zamówienia: podgląd” — odczyt kontaktów, wiedzy
  i materiałów klienta,
- „Klienci: dodawanie i edycja” — zapis tych samych rzeczy,
- „Stawki i kwoty: podgląd” — dokumenty prawne i pliki (mogą nieść stawki),
- „Kontrakty i zamówienia: tworzenie i edycja” razem z podglądem kwot —
  zapis dokumentów prawnych (umowy ramowe, aneksy, umowy wykonawcze).

**2. Zakres klientów** mówi, U KOGO. Konto z rolą Delivery Leada działa
u klientów z przypisania (od 25.09.2026, ``DL_CLIENT_SCOPE``;
``purpose="org"`` = wszyscy klienci dla narzędzi rekrutacji i generatora B2B);
konsekwentne zapisy prawne wymagają u niego jawnego przypisania. Każdy inny
posiadacz uprawnienia działa u wszystkich klientów.

Obok tego zostaje historyczny graf organizacyjny, z którego korzystają
współdzielone narzędzia Sourcing/Pipeline (te trasy nie stoją za sekcją
Delivery, więc uprawnienia z ekranu ich nie dotyczą):

- ``admin`` / ``head_of_recruitment`` — odczyt każdego klienta,
- ``tac`` — klient z jawnym ``ClientTacAssignment``; brak przypisań jest
  prawdziwym deny-all, nigdy fallbackiem do całej organizacji,
- ``recruiter`` / ``sourcer`` — odczyt bezpiecznej projekcji w kontekście
  stanowiska tego klienta (recruiter_id / delivery_lead_id / tac_id /
  created_by / JobCollaborator),
- ``user`` (viewer) — brak dostępu.

Reguły, które zostają przy ROLI, bo dotyczą danych prywatnych, nie pracy:

- Prywatne notatki relacyjne kontaktu czyta właściciel relacji, admin oraz
  Finanse (organizacyjnie); Talent Community Manager nie czyta ich wcale.
- Zmiana ownera relacji — wyłącznie admin; wyjątek: użytkownik z prawem
  edycji może "zaklaimować" pustego ownera na siebie (None → self).

Generator umów B2B (``purpose="org"``) czyta własne pola
``generator_can_*`` liczone formułą sprzed 0410 — jego dostęp się nie zmienił.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal, Optional

from fastapi import Depends, HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.api.financial_access import has_financial_access
from app.api.section_access import (
    ProductSection,
    SectionAccess,
    section_access_for_user,
)
from app.core.database import get_db
from app.models.activity import Activity
from app.models.client import Client
from app.models.contact import Contact
from app.models.job import Job
from app.models.job_collaborator import JobCollaborator
from app.models.user import User, UserRole
from app.services.client_identity import client_display_name
from app.services.access_scope import (
    delivery_lead_scope_is_assigned,
    delivery_lead_sees_whole_delivery,
    is_delivery_lead_governed,
    resolve_delivery_lead_assigned_client_ids,
)
from app.services.action_permissions import ProductAction, has_permission
from app.services.permission_denial import permission_denied

# ``delivery`` = moduły Delivery (Klienci, Kontrakty, Zamówienia): DL tylko
# swoich klientów. ``org`` = narzędzia rekrutacji i generator B2B: DL
# wszystkich klientów (rekrutacje są otwarte, decyzja 23.09.2026).
ClientScopePurpose = Literal["delivery", "org"]

# Historyczny graf organizacyjny używany również przez współdzielone narzędzia
# Pipeline. Prawa Delivery wynikają dodatkowo z centralnej bramki sekcji.
ADMIN_LIKE_ROLES = (UserRole.admin, UserRole.head_of_recruitment)
# Historyczny graf zespołu klienta; zapis Delivery ma osobny section ceiling.
CLIENT_TEAM_ROLES = (UserRole.delivery_lead,)
# Role operacyjne delivery — odczyt w kontekście przypisanego stanowiska.
DELIVERY_ROLES = (UserRole.recruiter,)
# Prywatne notatki relacyjne (dane osobiste kontaktu) czyta organizacyjnie
# wyłącznie persona Finanse. To reguła o danych, nie o pracy — zostaje przy
# roli i NIE wynika z uprawnienia „podgląd” (które może dostać każdy).
PRIVATE_NOTES_ORGANIZATION_ROLES = (UserRole.finance,)

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
    is_delivery_lead_assigned: bool
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
    private_contact_notes_allowed: bool
    # Finanse czytają prywatne notatki relacyjne w całej organizacji (rola).
    reads_private_notes_org_wide: bool = False
    # Generator umów B2B (``purpose="org"``): formuła sprzed 0410, niezależna
    # od uprawnień Delivery — patrz ``contract_access``.
    generator_can_view_legal: bool = False
    generator_can_edit_legal: bool = False
    # Czego brakuje do edycji / dokumentów — do nazwanej odmowy.
    missing_edit_permission: str | None = None
    missing_legal_view_permission: str | None = None
    missing_legal_edit_permission: str | None = None

    def can_view_contact_private_notes(self, contact: Contact) -> bool:
        """Prywatne notatki relacyjne: admin/owner z właściwym ceilingiem.

        Zawierają dane osobiste (urodziny, rodzina, hobby) — domyślnie
        widzi je tylko owner i administracja (rekomendacja audytu, pkt 19.4).

        Notatki NIE-zaklaimowane (owner is None — UI historycznie nie
        ustawiało ownera) widzą role z prawem edycji kontaktów. Inaczej
        DL/TAC, który sam je zapisał, dostawałby pusty formularz i przy
        zapisie po cichu WYMAZAŁ istniejącą treść (dialog odsyła całość).
        """
        if not self.private_contact_notes_allowed:
            return False
        # Finance keeps its established organization-wide read of client
        # contacts, including private relationship notes, without gaining any
        # contact write capability. TCM is stopped by the guard above.
        if self.reads_private_notes_org_wide or (
            self.is_admin_like and self.can_edit_contacts
        ):
            return True
        if contact.key_relationship_owner_id is None:
            return self.can_edit_contacts
        return contact.key_relationship_owner_id == self.user_id

    def is_relationship_owner(self, contact: Contact) -> bool:
        return (
            contact.key_relationship_owner_id is not None
            and contact.key_relationship_owner_id == self.user_id
        )

    def edit_denial(self, detail: str) -> HTTPException:
        """Odmowa edycji kontaktów, wiedzy albo materiałów klienta.

        Gdy brakuje uprawnienia — odmowa nazywa je. Gdy uprawnienie jest,
        a klient leży poza portfelem — dotychczasowy komunikat z ``detail``.
        """

        if self.missing_edit_permission is not None:
            return permission_denied(self.missing_edit_permission)
        return deny(detail)

    def legal_denial(self, detail: str, *, write: bool = False) -> HTTPException:
        """Odmowa dostępu do dokumentów prawnych klienta (odczyt albo zapis)."""

        missing = (
            self.missing_legal_edit_permission
            if write
            else self.missing_legal_view_permission
        )
        if missing is not None:
            return permission_denied(missing)
        return deny(detail)


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
    *,
    purpose: ClientScopePurpose = "delivery",
) -> frozenset[int] | None:
    """Resolve the client graph for DL/TAC client-team capabilities.

    ``None`` means unrestricted Admin or plain Head of Recruitment oversight.
    Delivery Lead receives a concrete set; keeping a set preserves fail-closed
    handling for client-less legal entities and the role's narrow finance
    exceptions. For ``purpose="delivery"`` the set is the DL's assigned
    clients (any assignment, 25.09.2026) unless ``DL_CLIENT_SCOPE=all`` or the
    account also reads Delivery org-wide (TCM); ``purpose="org"`` is every
    client. A plain TAC still receives only its ``ClientTacAssignment`` rows.
    """

    if user.has_role(UserRole.admin) or (
        user.has_role(UserRole.head_of_recruitment)
        and not user.has_role(UserRole.delivery_lead)
    ):
        return None

    client_ids: set[int] = set()
    if user.has_role(UserRole.delivery_lead):
        if (
            purpose == "delivery"
            and delivery_lead_scope_is_assigned()
            and not delivery_lead_sees_whole_delivery(user)
            and not user.has_role(UserRole.finance)
        ):
            assigned = await resolve_delivery_lead_assigned_client_ids(user, db)
            return frozenset(assigned or ())
        client_ids.update((await db.scalars(select(Client.id))).all())
        return frozenset(int(client_id) for client_id in client_ids)
    # Do 0411 konto z rolą TAC dostawało tu klientów ze swoich przypisań
    # (`ClientTacAssignment`). Roli nie ma, a rekruter nie należy do zespołu
    # klienta — przypisania zostają w bazie bez wpływu na dostęp.
    return frozenset(int(client_id) for client_id in client_ids)


def reads_delivery_organization_wide(user: User) -> bool:
    """Podgląd Delivery u WSZYSTKICH klientów.

    Uprawnienie „Klienci, kontrakty i zamówienia: podgląd” bez portfela
    Delivery Leada. Domyślnie: Finanse i Talent Community Manager; każde konto,
    któremu admin nada podgląd, czyta tak samo. Konto z rolą DL zostaje przy
    swoich klientach (``resolve_delivery_lead_client_ids``).
    """

    return has_permission(
        user, ProductAction.delivery_view
    ) and not is_delivery_lead_governed(user)


async def resolve_client_visible_client_ids(
    db: AsyncSession,
    user: User,
    *,
    purpose: ClientScopePurpose = "delivery",
) -> frozenset[int] | None:
    """Resolve all clients whose operational surface the user may read.

    Admin/HoR and organization readers (the Delivery view permission without
    the Delivery Lead portfolio) remain unrestricted. Delivery Lead gets
    the client-team set of ``purpose`` (assigned clients for Delivery, every
    client for ``org``). TAC contributes only explicit relationship
    assignments. Recruiter/Sourcer contribute only clients reached through
    their exact Job or JobCollaborator membership, unless the account also
    holds Delivery Lead — then the DL set applies.
    Empty is authoritative deny-all and never means organization-wide fallback.
    """

    delivery_scoped = is_delivery_lead_governed(user)
    if reads_delivery_organization_wide(user):
        return None

    client_ids = await resolve_client_team_client_ids(db, user, purpose=purpose)
    if client_ids is None:
        return None

    visible = set(client_ids)
    if not delivery_scoped and user.has_any_role(*DELIVERY_ROLES):
        visible.update(await _job_assigned_client_ids(db, user.id))
    return frozenset(visible)


@dataclass(frozen=True)
class _UserClientFacts:
    """Część decyzji dostępu, która nie zależy od klienta (liczona raz)."""

    is_admin_like: bool
    is_organization_reader: bool
    reads_private_notes_org_wide: bool
    is_read_only_tcm: bool
    is_delivery_scoped: bool
    delivery_lead_assignment_required: bool
    is_delivery: bool
    has_financial_access: bool
    # Uprawnienia z ekranu (po domknięciu zależności).
    can_edit_clients: bool
    can_view_amounts: bool
    can_edit_contracts: bool
    # Generator umów B2B — formuła sprzed 0410.
    legacy_is_finance_reader: bool
    legacy_has_delivery_write: bool


def _user_client_facts(user: User) -> _UserClientFacts:
    delivery_scoped = is_delivery_lead_governed(user)
    return _UserClientFacts(
        is_admin_like=user.has_any_role(*ADMIN_LIKE_ROLES) and not delivery_scoped,
        is_organization_reader=reads_delivery_organization_wide(user),
        reads_private_notes_org_wide=(
            user.has_any_role(*PRIVATE_NOTES_ORGANIZATION_ROLES) and not delivery_scoped
        ),
        is_read_only_tcm=(
            user.has_role(UserRole.talent_community_manager)
            and not user.has_any_role(UserRole.admin, UserRole.delivery_lead)
        ),
        is_delivery_scoped=delivery_scoped,
        delivery_lead_assignment_required=(
            user.has_role(UserRole.delivery_lead) and not user.has_role(UserRole.admin)
        ),
        is_delivery=user.has_any_role(*DELIVERY_ROLES) and not delivery_scoped,
        has_financial_access=has_financial_access(user),
        can_edit_clients=has_permission(user, ProductAction.clients_edit),
        can_view_amounts=has_permission(user, ProductAction.amounts_view),
        can_edit_contracts=has_permission(user, ProductAction.contracts_orders_edit),
        legacy_is_finance_reader=(
            user.has_role(UserRole.finance) and has_financial_access(user)
        ),
        legacy_has_delivery_write=(
            section_access_for_user(user, ProductSection.delivery)
            >= SectionAccess.write
        ),
    )


def _build_client_access(
    user: User,
    client_id: int,
    facts: _UserClientFacts,
    *,
    is_client_team: bool,
    is_delivery_lead_assigned: bool,
    is_job_assigned: bool,
) -> ClientAccess:
    is_admin_like = facts.is_admin_like
    can_view_team_surfaces = (
        is_admin_like
        or facts.is_organization_reader
        or is_client_team
        or is_job_assigned
    )
    # Zakres: konto z rolą Delivery Leada działa u klientów ze swojego zbioru
    # (``is_client_team`` niesie ``purpose``), każde inne — u wszystkich.
    in_scope = not facts.is_delivery_scoped or is_client_team
    assigned = not facts.delivery_lead_assignment_required or is_delivery_lead_assigned
    can_edit = facts.can_edit_clients and in_scope
    can_view_legal = facts.can_view_amounts and in_scope
    can_edit_legal = facts.can_edit_contracts and facts.can_view_amounts and assigned

    missing_legal_edit: str | None = None
    if not facts.can_edit_contracts:
        missing_legal_edit = ProductAction.contracts_orders_edit.value
    elif not facts.can_view_amounts:
        missing_legal_edit = ProductAction.amounts_view.value

    legacy_can_edit = facts.legacy_has_delivery_write and (
        is_admin_like or is_client_team
    )

    return ClientAccess(
        user_id=user.id,
        client_id=client_id,
        is_admin_like=is_admin_like,
        is_organization_reader=facts.is_organization_reader,
        is_client_team=is_client_team,
        is_delivery_lead_assigned=is_delivery_lead_assigned,
        is_job_assigned=is_job_assigned,
        can_view_contacts=can_view_team_surfaces,
        can_edit_contacts=can_edit,
        can_reassign_relationship_owner=is_admin_like and facts.can_edit_clients,
        can_view_knowledge=can_view_team_surfaces,
        can_edit_knowledge=can_edit,
        # Materiały klienta są częścią jego powierzchni operacyjnej. Recruiter
        # i sourcer widzą je wyłącznie przez przypisany Job tego klienta.
        can_view_materials=can_view_team_surfaces,
        can_edit_materials=can_edit,
        # Dokumenty prawne i pliki mogą nieść stawki — wymagają podglądu kwot.
        can_view_legal_documents=can_view_legal,
        can_edit_legal_documents=can_edit_legal,
        can_view_financials=can_view_team_surfaces and facts.has_financial_access,
        can_manage_client=is_admin_like and facts.can_edit_clients,
        private_contact_notes_allowed=not facts.is_read_only_tcm,
        reads_private_notes_org_wide=facts.reads_private_notes_org_wide,
        generator_can_view_legal=(
            not facts.is_read_only_tcm
            and (is_admin_like or facts.legacy_is_finance_reader or is_client_team)
        ),
        generator_can_edit_legal=legacy_can_edit and assigned,
        missing_edit_permission=(
            None if facts.can_edit_clients else ProductAction.clients_edit.value
        ),
        missing_legal_view_permission=(
            None if facts.can_view_amounts else ProductAction.amounts_view.value
        ),
        missing_legal_edit_permission=missing_legal_edit,
    )


async def resolve_client_access(
    db: AsyncSession,
    user: User,
    client_id: int,
    *,
    purpose: ClientScopePurpose = "delivery",
) -> ClientAccess:
    """Zbuduj decyzję dostępu. Zakłada, że klient istnieje (404 wcześniej)."""
    facts = _user_client_facts(user)
    client_team_client_ids = await resolve_client_team_client_ids(
        db, user, purpose=purpose
    )
    is_client_team = (
        client_team_client_ids is None or client_id in client_team_client_ids
    )
    is_delivery_lead_assigned = False
    if facts.delivery_lead_assignment_required:
        assigned_client_ids = await resolve_delivery_lead_assigned_client_ids(user, db)
        is_delivery_lead_assigned = (
            assigned_client_ids is not None and client_id in assigned_client_ids
        )

    # Query o przypisanie do Joba tylko gdy może zmienić decyzję.
    is_job_assigned = False
    if not facts.is_admin_like and not is_client_team and facts.is_delivery:
        is_job_assigned = await _user_assigned_to_client_job(db, user.id, client_id)

    return _build_client_access(
        user,
        client_id,
        facts,
        is_client_team=is_client_team,
        is_delivery_lead_assigned=is_delivery_lead_assigned,
        is_job_assigned=is_job_assigned,
    )


async def contact_private_notes_checker(
    db: AsyncSession, user: User
) -> Callable[[Contact], bool]:
    """``ClientAccess.can_view_contact_private_notes`` dla listy wielu klientów.

    Runda 9 (R9-N4-2): globalna lista kontaktów (``GET /api/contacts``) miała
    własną kopię reguły i liczyła „admin-like” bez wyjątku persony DL, więc
    hybryda HoR+DL widziała notatki relacyjne kontaktów cudzego DL-a, których
    ``GET /clients/{id}/contacts`` jej nie pokazywał. Ta funkcja liczy decyzję
    TYM SAMYM builderem co ``resolve_client_access`` — fakty użytkownika
    i zespół klientów raz, potem per klient bez zapytań. Pola przypisania do
    rekrutacji / portfela DL nie wpływają na notatki, więc zostają ``False``.
    """
    facts = _user_client_facts(user)
    team_ids = await resolve_client_team_client_ids(db, user)
    cache: dict[int, ClientAccess] = {}

    def check(contact: Contact) -> bool:
        access = cache.get(contact.client_id)
        if access is None:
            access = _build_client_access(
                user,
                contact.client_id,
                facts,
                is_client_team=team_ids is None or contact.client_id in team_ids,
                is_delivery_lead_assigned=False,
                is_job_assigned=False,
            )
            cache[contact.client_id] = access
        return access.can_view_contact_private_notes(contact)

    return check


async def assert_client_exists(db: AsyncSession, client_id: int) -> None:
    """404 dla nieistniejącego klienta.

    Polityka ujawniania: istnienie klienta nie jest tajemnicą (lista klientów
    jest widoczna operacyjnie), chronione są dane. Dlatego brak encji → 404,
    brak prawa do operacji → 403.
    """
    result = await db.execute(select(Client.id).where(Client.id == client_id))
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Client not found")


CLIENT_NOT_WRITABLE_DETAIL = "Klient nie istnieje albo został usunięty lub scalony."


async def assert_client_writable(
    db: AsyncSession, client_id: int, *, lock: bool = False
) -> Client:
    """404 dla klienta, którego nie da się już zmieniać.

    Jeden strażnik dla KAŻDEGO zapisu na kliencie (karta, materiały, wiedza,
    zespół, umowy ramowe i wykonawcze, aneksy, PATCH klienta): klient
    USUNIĘTY (``deleted_at``, reguła 0307) nie ma profilu ani zapisów (audyt
    24.09.2026, S1). Klient ukryty, zarchiwizowany albo scalony zostaje
    zapisywalny — karta klienta świadomie przyjmuje zapis dla ukrytego
    i scalonego (``test_client_playbooks_api``), a „Nieaktywni” mają profil.
    ``lock`` blokuje wiersz klienta do końca transakcji.
    """

    stmt = select(Client).where(Client.id == client_id)
    if lock:
        stmt = stmt.with_for_update()
    client = await db.scalar(stmt)
    if client is None or client.deleted_at is not None:
        raise HTTPException(status_code=404, detail=CLIENT_NOT_WRITABLE_DETAIL)
    return client


async def assert_client_assignable(
    db: AsyncSession, client_id: Optional[int]
) -> Optional[Client]:
    """422, gdy nowy zapis wskazuje klienta usuniętego albo scalonego.

    Runda 7 (R7-X5-4): rekrutacje, kontrakty, kontakty i odczyt maila klienta
    przyjmowały ``client_id`` z ciała żądania i sprawdzały najwyżej samo
    istnienie wiersza. Karta otwarta przed usunięciem klienta zakładała wtedy
    rekrutację albo kontrakt, którego nie widać w żadnym rejestrze, a kontrakt
    i tak liczył się do MRR. Scalonego klienta NIE przekierowujemy po cichu na
    rekord główny (tak robi tylko nocny import Traffita) — zapis ręczny ma
    wskazać rekord główny świadomie, więc komunikat go nazywa.

    Brak klienta (``None`` albo nieistniejące id) zostawia wołającemu —
    endpointy mają własne odpowiedzi na ten przypadek.
    """

    if client_id is None:
        return None
    client = await db.scalar(select(Client).where(Client.id == client_id))
    if client is None:
        return None
    name = client_display_name(client)
    if client.deleted_at is not None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "client_deleted",
                "message": f"Klient „{name}” został usunięty — wybierz innego klienta.",
            },
        )
    if client.merged_into_client_id is not None:
        target = await db.scalar(
            select(Client).where(Client.id == client.merged_into_client_id)
        )
        target_name = client_display_name(target) if target is not None else None
        message = (
            f"Klient „{name}” został scalony z „{target_name}” — "
            f"wybierz „{target_name}”."
            if target_name
            else f"Klient „{name}” został scalony z innym rekordem — "
            "wybierz rekord główny."
        )
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "client_merged",
                "message": message,
                "merged_into_client_id": client.merged_into_client_id,
            },
        )
    return client


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
