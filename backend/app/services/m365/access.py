"""Fail-closed owner eligibility checks for Microsoft 365 operations.

An active ``M365Connection`` is only a credential record.  It must never be
treated as current authorization: the owning Nexus user can move to Finance or
the legacy viewer role while tokens, subscriptions and queued work still
exist.  Every Graph execution path re-reads the owner and applies the same
candidate-domain boundary used by the HTTP API.

Skrzynka handlowca (decyzja Artura 28.10.2026, „tak, jak w Atlasie”): konto
z „Sprzedaż: podgląd” bez dostępu do kandydatów też podłącza Outlooka, ale
jego poczta idzie wyłącznie do Sprzedaży. Dopuszczają ją tylko ścieżki, które
jawnie podają ``sales_ok=True`` (podłączenie, synchronizacja, subskrypcje
Graph). Wszystko inne — dopasowanie do kandydatów, CV z załączników, wysyłka,
rozmowy, nagrania — zostaje przy bramce kandydatów.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.api.candidate_access import (
    READ_ONLY_ROLES,
    user_can_access_candidate_domain,
)
from app.models.m365 import M365Connection
from app.models.user import User
from app.services.action_permissions import ProductAction, has_permission
from app.services.section_permissions import resolve_effective_section_access


def can_own_mailbox(user: User) -> bool:
    """Czy konto może mieć podłączoną skrzynkę, z której poczta trafia do bazy.

    Domena kandydatów, ale bez ról tylko do odczytu (0446: „Automatyzacje”
    czytają kandydatów, a poczty nie wnoszą — także konto przerobione
    z rekrutera, którego połączenie dalej istnieje).
    """

    return user_can_access_candidate_domain(user) and not user.has_any_role(
        *READ_ONLY_ROLES
    )


def can_own_sales_mailbox(user: User) -> bool:
    """Czy poczta konta trafia do Sprzedaży (maile i spotkania przy firmach)."""

    return bool(
        user.is_active
        and not user.has_any_role(*READ_ONLY_ROLES)
        and has_permission(user, ProductAction.sales_view)
    )


@dataclass(frozen=True)
class MailboxScope:
    """Dokąd wolno nieść pocztę właściciela skrzynki."""

    candidates: bool
    sales: bool

    @property
    def any(self) -> bool:
        return self.candidates or self.sales


def mailbox_scope(user: User) -> MailboxScope:
    """Wymaga polityki z ``resolve_effective_section_access`` na ``user``."""

    return MailboxScope(
        candidates=can_own_mailbox(user), sales=can_own_sales_mailbox(user)
    )


def can_connect_mailbox(user: User) -> bool:
    return mailbox_scope(user).any


#: Zakres skrzynki sprzed Sprzedaży — domyślny dla ścieżek, które go nie podają.
CANDIDATE_SCOPE = MailboxScope(candidates=True, sales=False)
NO_SCOPE = MailboxScope(candidates=False, sales=False)


async def connection_mailbox_scope(
    db: AsyncSession, connection: M365Connection
) -> MailboxScope:
    """Bieżący zakres skrzynki według ról i uprawnień właściciela (świeży odczyt)."""

    owner = await db.get(User, connection.user_id, populate_existing=True)
    if owner is None:
        return NO_SCOPE
    await resolve_effective_section_access(db, owner)
    return mailbox_scope(owner)


class M365OwnerIneligible(RuntimeError):
    """Raised before Graph access when the connection owner is not eligible."""


async def eligible_m365_owner(
    db: AsyncSession, user_id: int, *, sales_ok: bool = False
) -> User | None:
    """Return the current eligible owner, or ``None`` without mutating state.

    ``sales_ok=True`` dopuszcza też skrzynkę handlowca bez dostępu do
    kandydatów — tylko dla ścieżek, które same pilnują zakresu poczty.
    """

    # ``populate_existing`` forces a SELECT even when this session already has
    # the user in its identity map. Role changes happen in other requests and
    # a cached pre-cutover User object must not authorize a Graph call.
    owner = await db.get(User, user_id, populate_existing=True)
    if owner is None:
        return None
    await resolve_effective_section_access(db, owner)
    scope = mailbox_scope(owner)
    if not (scope.any if sales_ok else scope.candidates):
        return None
    return owner


async def connection_owner_is_eligible(
    db: AsyncSession,
    connection: M365Connection,
    *,
    sales_ok: bool = False,
) -> bool:
    """Check an M365 connection against its owner's current effective roles."""

    return (
        await eligible_m365_owner(db, connection.user_id, sales_ok=sales_ok) is not None
    )


async def require_eligible_connection_owner(
    db: AsyncSession,
    connection: M365Connection,
    *,
    sales_ok: bool = False,
) -> User:
    """Fail before token/Graph use when the current owner cannot access PII."""

    owner = await eligible_m365_owner(db, connection.user_id, sales_ok=sales_ok)
    if owner is None:
        raise M365OwnerIneligible(
            f"M365 connection {connection.id} owner is outside candidate domain"
        )
    return owner
