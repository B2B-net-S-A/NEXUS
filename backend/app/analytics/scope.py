"""Scope zapytań analitycznych (plan §4.3/§4.6).

Scope opisuje ZAKRES danych, o które pyta user (organizacja / zespół DL /
klient / pojedynczy user) — ortogonalny do capability, które mówi CO wolno
zobaczyć. Multi-role daje sumę capabilities, ale NIGDY nie poszerza
automatycznie zakresu klienta ani zespołu.

W PR 2 (fundament) scope jest strukturą + walidacją; egzekwowanie per
endpoint dochodzi z routerem Analytics v1 (PR 3).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.capabilities import (
    AnalyticsCapability,
    user_has_capability,
)
from app.models.team_structure import DeliveryLeadClientAssignment
from app.models.user import User, UserRole
from app.services.access_scope import (
    ScopeKind as DashboardScopeKind,
    resolve_dashboard_scope,
)


class ScopeKind(str, Enum):
    organization = "organization"
    delivery_clients = "delivery_clients"
    client = "client"
    user = "user"
    own = "own"


@dataclass(frozen=True)
class Scope:
    """Rozwiązany zakres danych. ``as_payload`` trafia do koperty odpowiedzi."""

    kind: ScopeKind
    # client_id dla kind=client; user_id dla kind=user/own; None dla organization.
    client_id: int | None = None
    user_id: int | None = None
    # Exact Delivery Lead relationship boundary.  Keeping the pairs (rather
    # than only the independent client/TAC unions) prevents a cartesian scope
    # expansion when a DL has e.g. (client A, TAC 1) and (client B, TAC 2).
    allowed_user_ids: frozenset[int] = frozenset()
    client_tac_pairs: frozenset[tuple[int, int]] = frozenset()

    def as_payload(self) -> dict:
        payload: dict = {"kind": self.kind.value}
        if self.client_id is not None:
            payload["client_id"] = self.client_id
        if self.user_id is not None:
            payload["user_id"] = self.user_id
        if self.kind is ScopeKind.delivery_clients:
            payload["allowed_user_ids"] = sorted(self.allowed_user_ids)
            payload["client_tac_pairs"] = [
                {"client_id": client_id, "tac_user_id": tac_user_id}
                for client_id, tac_user_id in sorted(self.client_tac_pairs)
            ]
        return payload

    def cache_token(self) -> str:
        """Deterministyczny składnik klucza cache (plan §4.6)."""
        users = ",".join(str(value) for value in sorted(self.allowed_user_ids))
        pairs = ",".join(
            f"{client_id}-{tac_user_id}"
            for client_id, tac_user_id in sorted(self.client_tac_pairs)
        )
        return (
            f"{self.kind.value}:c{self.client_id or 0}:u{self.user_id or 0}:"
            f"a={users}:p={pairs}"
        )


async def ensure_client_scope(db: AsyncSession, user: User, client_id: int) -> Scope:
    """Zwróć scope klienta albo 403.

    Zasady (plan §4.3):
    - admin / head_of_recruitment — każdy klient,
    - delivery_lead — wyłącznie klient z własnym
      ``DeliveryLeadClientAssignment`` (sekundarna rola DL u hybrydy nie
      poszerza listy przypisań — przypisania są per-user, nie per-rola),
    - tac — każdy klient operacyjnie (VIEW_CLIENT_OPERATIONS), bez finansów
      (finanse per endpoint przez VIEW_FINANCE),
    - pozostali — brak dostępu.
    """
    if not user_has_capability(user, AnalyticsCapability.VIEW_CLIENT_OPERATIONS):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Brak uprawnień do danych klientów",
        )
    # Finance ma globalne VIEW_CLIENT_OPERATIONS (jak HoR) i od 19.08 pełny
    # dostęp operacyjny — dawny bounce na osobny „finance-safe" endpoint
    # zdjęty; wchodzi tym samym torem co role globalno-klienckie.
    if user.has_any_role(
        UserRole.admin,
        UserRole.head_of_recruitment,
        UserRole.tac,
        UserRole.finance,
    ):
        return Scope(kind=ScopeKind.client, client_id=client_id)
    # delivery_lead: tylko przypisani klienci
    assigned = await db.scalar(
        select(DeliveryLeadClientAssignment.id).where(
            DeliveryLeadClientAssignment.delivery_lead_user_id == user.id,
            DeliveryLeadClientAssignment.client_id == client_id,
        )
    )
    if assigned is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Klient poza Twoim przypisaniem delivery",
        )
    return Scope(kind=ScopeKind.client, client_id=client_id)


def ensure_finance_client_scope(user: User, client_id: int) -> Scope:
    """Return organization-wide client scope for the finance-safe projection.

    This endpoint is deliberately independent from historical
    ``DeliveryLeadClientAssignment`` rows.  Only Admin or the exclusive Finance
    persona may use it; a legacy/hybrid role combination cannot borrow Finance
    capability to widen a Delivery Lead scope.
    """

    if not user_has_capability(user, AnalyticsCapability.VIEW_FINANCE):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Brak uprawnień do danych finansowych klienta",
        )
    roles = set(user.get_all_roles())
    if UserRole.admin not in roles and roles != {UserRole.finance}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Finance must be an exclusive persona for client finance",
        )
    return Scope(kind=ScopeKind.client, client_id=client_id)


async def ensure_team_scope(db: AsyncSession, user: User) -> Scope:
    """Resolve the manager boundary for team aggregates.

    Admin and Head of Recruitment retain their explicit organization/recruitment
    oversight.  A Delivery Lead receives only TAC users that occur in the exact
    client–TAC relationships reachable through their assigned clients.  An
    empty relationship set is deny-all data (an empty team), never a fallback
    to the organization.
    """

    if not user_has_capability(user, AnalyticsCapability.VIEW_TEAM_KPI):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Brak uprawnień do KPI zespołu",
        )
    if user.has_any_role(
        UserRole.admin,
        UserRole.head_of_recruitment,
        UserRole.finance,
    ):
        return organization_scope()
    if not user.has_role(UserRole.delivery_lead):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Brak menedżerskiego zakresu KPI",
        )

    dashboard_scope = await resolve_dashboard_scope(user, db)
    if (
        dashboard_scope.kind is not DashboardScopeKind.delivery_clients
        or dashboard_scope.user_id != user.id
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Zakres delivery należy do innego użytkownika",
        )
    pairs = dashboard_scope.allowed_client_tac_pairs
    return Scope(
        kind=ScopeKind.delivery_clients,
        user_id=user.id,
        allowed_user_ids=frozenset(tac_user_id for _, tac_user_id in pairs),
        client_tac_pairs=pairs,
    )


async def ensure_recruitment_user_scope(
    db: AsyncSession,
    user: User,
    target_user_id: int,
) -> Scope:
    """Resolve access to one person's recruitment KPI without DL IDOR."""

    if target_user_id == user.id and user_has_capability(
        user, AnalyticsCapability.VIEW_OWN_RECRUITMENT_KPI
    ):
        return Scope(kind=ScopeKind.own, user_id=user.id)

    if not user_has_capability(user, AnalyticsCapability.VIEW_TEAM_KPI):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="KPI innego użytkownika wymagają uprawnień zespołowych",
        )
    if user.has_any_role(
        UserRole.admin,
        UserRole.head_of_recruitment,
        UserRole.finance,
    ):
        return Scope(kind=ScopeKind.user, user_id=target_user_id)

    team_scope = await ensure_team_scope(db, user)
    target_pairs = frozenset(
        pair for pair in team_scope.client_tac_pairs if pair[1] == target_user_id
    )
    if not target_pairs:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Użytkownik poza przypisanym zakresem delivery",
        )
    return Scope(
        kind=ScopeKind.delivery_clients,
        user_id=target_user_id,
        allowed_user_ids=frozenset({target_user_id}),
        client_tac_pairs=target_pairs,
    )


def ensure_user_scope(user: User, target_user_id: int) -> Scope:
    """Return a self-only scope.

    Manager access must use :func:`ensure_recruitment_user_scope`, which has a
    database-backed relationship boundary.  Keeping this helper self-only makes
    it impossible for a future call site to reintroduce the old arbitrary-ID
    Delivery Lead bypass.
    """
    if target_user_id == user.id:
        return Scope(kind=ScopeKind.own, user_id=user.id)
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Cudze KPI wymagają jawnego, relacyjnego zakresu menedżerskiego",
    )


def organization_scope() -> Scope:
    return Scope(kind=ScopeKind.organization)
