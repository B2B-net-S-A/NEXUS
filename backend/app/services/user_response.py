"""Build the complete authenticated-user profile returned to the frontend."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.user import User, UserRole
from app.schemas.user import DashboardDataScope, DashboardPreset, UserResponse
from app.services.access_scope import resolve_dashboard_scope


def _dashboard_presets_for(user: User) -> list[DashboardPreset]:
    roles = set(user.get_all_roles())
    if UserRole.admin in roles:
        return [
            "admin-ops",
            "delivery-lead",
            "head-of-recruitment",
            "my-work",
            "finance",
        ]

    presets: list[DashboardPreset] = []
    if UserRole.finance in roles:
        presets.append("finance")
    if UserRole.head_of_recruitment in roles:
        presets.append("head-of-recruitment")
    elif UserRole.talent_community_manager in roles:
        presets.append("head-of-recruitment")
    if UserRole.delivery_lead in roles:
        presets.append("delivery-lead")
    if roles.intersection({UserRole.sourcer, UserRole.tac, UserRole.recruiter}):
        presets.append("my-work")
    return presets


async def build_user_response(user: User, db: AsyncSession) -> UserResponse:
    """Return the one canonical frontend auth/profile snapshot.

    Authentication dependencies attach section and action access before calling
    this builder. Administrative impersonation resolves the target snapshots
    explicitly, then uses the same enrichment path as ``/auth/me``.
    """

    from app.analytics.capabilities import capabilities_for  # noqa: PLC0415

    response = UserResponse.model_validate(user)
    capabilities = sorted(cap.value for cap in capabilities_for(user))
    response.capabilities = capabilities
    response.analytics_capabilities = capabilities
    presets = _dashboard_presets_for(user)
    response.available_dashboard_presets = presets
    response.default_dashboard_preset = presets[0] if presets else None
    # ``data_scope`` also drives client-level Delivery affordances. Any
    # account carrying Delivery Lead must expose its exact assigned portfolio,
    # even when its default dashboard preset is HoR/TCM.
    scope = await resolve_dashboard_scope(
        user,
        db,
        delivery_lead_persona=(
            user.has_role(UserRole.delivery_lead)
            and not user.has_any_role(UserRole.admin, UserRole.finance)
        ),
    )
    response.data_scope = DashboardDataScope(**scope.as_payload())
    response.analytics_v1_mode = settings.ANALYTICS_V1_MODE
    response.effective_section_access = dict(
        getattr(user, "effective_section_access", {})
    )
    response.effective_action_access = dict(
        getattr(user, "effective_action_access", {})
    )
    return response
