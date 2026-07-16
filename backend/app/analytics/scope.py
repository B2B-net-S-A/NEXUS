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


class ScopeKind(str, Enum):
    organization = "organization"
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

    def as_payload(self) -> dict:
        payload: dict = {"kind": self.kind.value}
        if self.client_id is not None:
            payload["client_id"] = self.client_id
        if self.user_id is not None:
            payload["user_id"] = self.user_id
        return payload

    def cache_token(self) -> str:
        """Deterministyczny składnik klucza cache (plan §4.6)."""
        return f"{self.kind.value}:c{self.client_id or 0}:u{self.user_id or 0}"


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
    if user.has_any_role(UserRole.admin, UserRole.head_of_recruitment, UserRole.tac):
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


def ensure_user_scope(user: User, target_user_id: int) -> Scope:
    """Zwróć scope KPI pojedynczego usera albo 403.

    self — zawsze; cudze — VIEW_TEAM_KPI (admin/HoR/DL; scoping DL→zespół
    doprecyzuje kanoniczny model zespołu w PR 4).
    """
    if target_user_id == user.id:
        return Scope(kind=ScopeKind.own, user_id=user.id)
    if user_has_capability(user, AnalyticsCapability.VIEW_TEAM_KPI):
        return Scope(kind=ScopeKind.user, user_id=target_user_id)
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="KPI innego użytkownika wymagają uprawnień zespołowych",
    )


def organization_scope() -> Scope:
    return Scope(kind=ScopeKind.organization)
