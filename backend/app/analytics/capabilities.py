"""Analytics capabilities — jedyne źródło prawdy o dostępie do statystyk.

Macierz z planu (docs/analytics-statistics-claude-implementation-plan-2026-07-16.md,
sekcja 4.3). Backend definiuje capability enum; ``/api/auth/me`` zwraca
``analytics_capabilities``; frontend używa ich wyłącznie do routingu i gate'owania
zapytań — NIGDY jako substytutu guardów backendowych.

Zasady:
- capability wynika z ról (``User.get_all_roles()`` — multi-role = suma uprawnień),
- guardy NIE są wyłączalne feature flagiem,
- sekcja DynaReportera (``users.allowed_sections``) może dostęp tylko ZAWĘZIĆ,
  nigdy poszerzyć: wynik = capability ∩ allowed_sections (admin bez zawężenia),
- puste / błędne ``allowed_sections`` ⇒ brak dostępu (fail-closed).
"""

from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING

from fastapi import Depends, HTTPException, status

from app.api.deps import get_current_user
from app.models.user import User, UserRole

if TYPE_CHECKING:
    pass


class AnalyticsCapability(str, Enum):
    """Klasy dostępu do danych analitycznych (patrz macierz w planie §4.3)."""

    # Bezpieczne agregaty operacyjne bez PII i bez finansów — każdy zalogowany.
    VIEW_OPERATIONAL_AGGREGATES = "view_operational_aggregates"
    # Własne KPI rekrutacyjne (rozmowy, weryfikacje, rekomendacje...).
    VIEW_OWN_RECRUITMENT_KPI = "view_own_recruitment_kpi"
    # Własne KPI delivery.
    VIEW_OWN_DELIVERY_KPI = "view_own_delivery_kpi"
    # Imienny ranking rekruterów/sourcerów.
    VIEW_RECRUITMENT_RANKING = "view_recruitment_ranking"
    # KPI innych osób (zespół/organizacja — zakres doprecyzowany per endpoint).
    VIEW_TEAM_KPI = "view_team_kpi"
    # Dane klientów/delivery BEZ pól finansowych.
    VIEW_CLIENT_OPERATIONS = "view_client_operations"
    # Stawki, MRR, marża, P&L.
    VIEW_FINANCE = "view_finance"
    # Mutacje księgi, stawek, faktur i korekt finansowych.
    MANAGE_FINANCE = "manage_finance"
    # Zatwierdzanie korekt i innych finansowych wyjątków.
    APPROVE_FINANCE = "approve_finance"
    # Zarządczy, przekrojowy widok biznesu.
    VIEW_EXECUTIVE = "view_executive"
    # Przetargi bez wartości (wartości wymagają VIEW_FINANCE).
    VIEW_TENDERS_OPERATIONAL = "view_tenders_operational"
    # Administracja analytics (korekty, backfill, cutover).
    ADMIN_ANALYTICS = "admin_analytics"


_ALL: frozenset[AnalyticsCapability] = frozenset(AnalyticsCapability)

# Macierz rola → capabilities (plan §4.3). Multi-role = unia.
ROLE_CAPABILITIES: dict[UserRole, frozenset[AnalyticsCapability]] = {
    # Expand/contract compatibility only. Existing viewers are migrated to
    # recruiter; until then this persona receives no dashboard capability.
    UserRole.user: frozenset(),
    UserRole.recruiter: frozenset(
        {
            AnalyticsCapability.VIEW_OPERATIONAL_AGGREGATES,
            AnalyticsCapability.VIEW_OWN_RECRUITMENT_KPI,
            AnalyticsCapability.VIEW_RECRUITMENT_RANKING,
        }
    ),
    UserRole.sourcer: frozenset(
        {
            AnalyticsCapability.VIEW_OPERATIONAL_AGGREGATES,
            AnalyticsCapability.VIEW_OWN_RECRUITMENT_KPI,
            AnalyticsCapability.VIEW_RECRUITMENT_RANKING,
        }
    ),
    UserRole.tac: frozenset(
        {
            AnalyticsCapability.VIEW_OPERATIONAL_AGGREGATES,
            AnalyticsCapability.VIEW_OWN_RECRUITMENT_KPI,
            AnalyticsCapability.VIEW_RECRUITMENT_RANKING,
            AnalyticsCapability.VIEW_CLIENT_OPERATIONS,
            AnalyticsCapability.VIEW_TENDERS_OPERATIONAL,
        }
    ),
    UserRole.delivery_lead: frozenset(
        {
            AnalyticsCapability.VIEW_OPERATIONAL_AGGREGATES,
            AnalyticsCapability.VIEW_OWN_DELIVERY_KPI,
            AnalyticsCapability.VIEW_TEAM_KPI,
            AnalyticsCapability.VIEW_CLIENT_OPERATIONS,
            AnalyticsCapability.VIEW_TENDERS_OPERATIONAL,
        }
    ),
    UserRole.talent_community_manager: frozenset(
        {
            AnalyticsCapability.VIEW_OPERATIONAL_AGGREGATES,
            AnalyticsCapability.VIEW_OWN_RECRUITMENT_KPI,
            AnalyticsCapability.VIEW_RECRUITMENT_RANKING,
            AnalyticsCapability.VIEW_TEAM_KPI,
            AnalyticsCapability.VIEW_CLIENT_OPERATIONS,
            AnalyticsCapability.VIEW_TENDERS_OPERATIONAL,
        }
    ),
    UserRole.head_of_recruitment: frozenset(
        {
            AnalyticsCapability.VIEW_OPERATIONAL_AGGREGATES,
            AnalyticsCapability.VIEW_RECRUITMENT_RANKING,
            AnalyticsCapability.VIEW_TEAM_KPI,
            AnalyticsCapability.VIEW_CLIENT_OPERATIONS,
        }
    ),
    UserRole.finance: frozenset(
        {
            AnalyticsCapability.VIEW_OPERATIONAL_AGGREGATES,
            AnalyticsCapability.VIEW_RECRUITMENT_RANKING,
            AnalyticsCapability.VIEW_TEAM_KPI,
            AnalyticsCapability.VIEW_CLIENT_OPERATIONS,
            AnalyticsCapability.VIEW_FINANCE,
            AnalyticsCapability.MANAGE_FINANCE,
            AnalyticsCapability.VIEW_EXECUTIVE,
            AnalyticsCapability.VIEW_TENDERS_OPERATIONAL,
        }
    ),
    UserRole.admin: _ALL,
}


def capabilities_for(user: User) -> frozenset[AnalyticsCapability]:
    """Unia capabilities ze wszystkich ról usera (primary + dodatkowe)."""
    caps: set[AnalyticsCapability] = set()
    for role in user.get_all_roles():
        caps |= ROLE_CAPABILITIES.get(role, frozenset())
    return frozenset(caps)


def user_has_capability(user: User, cap: AnalyticsCapability) -> bool:
    return cap in capabilities_for(user)


def require_capability(cap: AnalyticsCapability):
    """Dependency factory: 403 gdy user nie ma danej capability.

    Celowo NIE ma tu żadnego feature flaga — R0 containment musi być
    niewyłączalny (plan §PR1: "Nie mogą być wyłączane feature flagem").
    """

    async def _check(current_user: User = Depends(get_current_user)) -> User:
        if not user_has_capability(current_user, cap):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requires analytics capability: {cap.value}",
            )
        return current_user

    return _check


# Kanoniczna lista sekcji DynaReportera — lustro typu DynaReporterSection
# z frontend/src/store/auth.ts. Nieznana sekcja w allowed_sections jest
# ignorowana (fail-closed: nie daje dostępu do niczego).
DYNAREPORTER_SECTIONS: frozenset[str] = frozenset(
    {
        "body-leasing",
        "sales",
        "delivery-lead",
        "placements",
        "clients-mrr",
        "competitions",
        "przetargi",
        "board",
        "sales-mgmt",
        "mindy",
        "admin",
    }
)


def require_dynareporter_section(section: str, cap: AnalyticsCapability):
    """Centralny guard legacy DynaReportera: capability ∩ allowed_sections.

    - user musi mieć wymaganą capability (wynikającą z ról), ORAZ
    - sekcję w ``users.allowed_sections`` (admin bez zawężenia sekcyjnego),
    - Finance po pomyślnym capability checku widzi każdą sekcję biznesową;
      techniczna sekcja ``admin`` pozostaje wyłączona.
    Sekcja nigdy nie zwiększa prawa wynikającego z roli; puste lub błędne
    ``allowed_sections`` oznacza brak dostępu.
    """
    if section not in DYNAREPORTER_SECTIONS:  # pragma: no cover — błąd programisty
        raise ValueError(f"Unknown DynaReporter section: {section}")

    async def _check(current_user: User = Depends(get_current_user)) -> User:
        if not user_has_capability(current_user, cap):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requires analytics capability: {cap.value}",
            )
        if current_user.has_role(UserRole.admin):
            return current_user
        if current_user.has_role(UserRole.finance):
            if section not in {"admin", "mindy"}:
                return current_user
            if section == "admin":
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="DynaReporter admin section is reserved for administrators",
                )
            # MINDY uses paid external model calls and persists usage counters.
            # It remains an explicitly assigned action surface, not an implicit
            # consequence of organization-wide business reads.
        sections = current_user.allowed_sections
        if not isinstance(sections, list) or section not in sections:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"DynaReporter section '{section}' not granted",
            )
        return current_user

    return _check
