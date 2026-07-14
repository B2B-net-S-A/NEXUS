"""Analytics capabilities and the single role-to-capability mapping.

Capabilities describe what a caller may see.  They deliberately do not encode
row scope (self/team/client assignment); endpoint services still have to apply
the appropriate scope after the capability check.
"""

from __future__ import annotations

from enum import Enum
from typing import Protocol

from app.models.user import UserRole


class AnalyticsCapability(str, Enum):
    """Stable, API-facing capability identifiers."""

    view_operational_aggregates = "view_operational_aggregates"
    view_personal_recruitment_kpis = "view_personal_recruitment_kpis"
    view_personal_delivery_kpis = "view_personal_delivery_kpis"
    view_recruitment_team = "view_recruitment_team"
    view_client_operations = "view_client_operations"
    view_finance = "view_finance"
    view_tenders = "view_tenders"
    manage_analytics = "manage_analytics"


class _AnalyticsUser(Protocol):
    """Minimal user surface needed by the pure capability resolver."""

    role: UserRole

    def get_all_roles(self) -> set[UserRole]: ...


_ROLE_CAPABILITIES: dict[UserRole, frozenset[AnalyticsCapability]] = {
    UserRole.user: frozenset({AnalyticsCapability.view_operational_aggregates}),
    UserRole.sourcer: frozenset(
        {
            AnalyticsCapability.view_operational_aggregates,
            AnalyticsCapability.view_personal_recruitment_kpis,
            AnalyticsCapability.view_recruitment_team,
        }
    ),
    UserRole.recruiter: frozenset(
        {
            AnalyticsCapability.view_operational_aggregates,
            AnalyticsCapability.view_personal_recruitment_kpis,
            AnalyticsCapability.view_recruitment_team,
        }
    ),
    UserRole.tac: frozenset(
        {
            AnalyticsCapability.view_operational_aggregates,
            AnalyticsCapability.view_personal_recruitment_kpis,
            AnalyticsCapability.view_recruitment_team,
            AnalyticsCapability.view_client_operations,
            AnalyticsCapability.view_tenders,
        }
    ),
    UserRole.delivery_lead: frozenset(
        {
            AnalyticsCapability.view_operational_aggregates,
            AnalyticsCapability.view_personal_delivery_kpis,
            AnalyticsCapability.view_recruitment_team,
            AnalyticsCapability.view_client_operations,
            AnalyticsCapability.view_finance,
            AnalyticsCapability.view_tenders,
        }
    ),
    UserRole.head_of_recruitment: frozenset(
        {
            AnalyticsCapability.view_operational_aggregates,
            AnalyticsCapability.view_recruitment_team,
            AnalyticsCapability.view_client_operations,
        }
    ),
    UserRole.admin: frozenset(AnalyticsCapability),
}


def capabilities_for_user(user: _AnalyticsUser) -> frozenset[AnalyticsCapability]:
    """Return the union of capabilities granted by all valid user roles.

    ``User.get_all_roles`` already ignores stale/unknown JSON role values.  A
    defensive primary-role fallback keeps this helper convenient for lightweight
    test doubles and old ORM objects.
    """

    get_roles = getattr(user, "get_all_roles", None)
    roles = get_roles() if callable(get_roles) else {user.role}
    granted: set[AnalyticsCapability] = set()
    for role in roles:
        granted.update(_ROLE_CAPABILITIES.get(role, ()))
    return frozenset(granted)


def analytics_capability_values(user: _AnalyticsUser) -> list[str]:
    """Return deterministic strings suitable for ``/api/auth/me`` JSON."""

    return sorted(capability.value for capability in capabilities_for_user(user))


def has_analytics_capability(
    user: _AnalyticsUser, capability: AnalyticsCapability
) -> bool:
    """Check one capability without importing FastAPI dependencies."""

    return capability in capabilities_for_user(user)
