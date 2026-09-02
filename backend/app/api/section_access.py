"""Central section-level RBAC for the NEXUS product shell.

Endpoint-specific guards still decide whether a permitted user may execute a
particular action.  This module owns the coarser product boundary: whether the
persona may enter Sourcing, Pipeline, Delivery, Insights, Finance or technical
administration at all.

The Delivery boundary is enforced on every router backing that UI section.
It deliberately treats safe HTTP methods as read access and every other method
as write access.  Talent Community Manager therefore gets organization-wide,
finance-redacted Delivery reads, while mutations fail before a handler runs.
Delivery Lead keeps write access, with client assignment enforced by the
existing resource-scope guards underneath this dependency.
"""

from __future__ import annotations

from enum import IntEnum, StrEnum
from typing import Annotated, Iterable

from fastapi import Depends, HTTPException, Request, status

from app.api.deps import get_current_user
from app.models.user import User, UserRole


class ProductSection(StrEnum):
    sourcing = "sourcing"
    pipeline = "pipeline"
    delivery = "delivery"
    insights = "insights"
    finance = "finance"
    system_admin = "system_admin"


class SectionAccess(IntEnum):
    none = 0
    read = 1
    write = 2


_NONE = {section: SectionAccess.none for section in ProductSection}


def _policy(**overrides: SectionAccess) -> dict[ProductSection, SectionAccess]:
    policy = dict(_NONE)
    policy.update(
        {ProductSection(section): access for section, access in overrides.items()}
    )
    return policy


# Primary role -> section ceiling.  Multi-role users receive the union, while
# endpoint and resource guards below this layer may still narrow individual
# actions or data rows.  Keep the frontend mirror in
# ``frontend/src/lib/section-access.ts``; parity tests cover both matrices.
ROLE_SECTION_ACCESS: dict[UserRole, dict[ProductSection, SectionAccess]] = {
    UserRole.admin: _policy(
        sourcing=SectionAccess.write,
        pipeline=SectionAccess.write,
        delivery=SectionAccess.write,
        insights=SectionAccess.write,
        finance=SectionAccess.write,
        system_admin=SectionAccess.write,
    ),
    UserRole.finance: _policy(
        sourcing=SectionAccess.write,
        pipeline=SectionAccess.write,
        delivery=SectionAccess.write,
        insights=SectionAccess.read,
        finance=SectionAccess.write,
    ),
    UserRole.head_of_recruitment: _policy(
        sourcing=SectionAccess.write,
        pipeline=SectionAccess.write,
        insights=SectionAccess.write,
    ),
    UserRole.delivery_lead: _policy(
        sourcing=SectionAccess.write,
        pipeline=SectionAccess.write,
        delivery=SectionAccess.write,
        insights=SectionAccess.read,
    ),
    UserRole.talent_community_manager: _policy(
        sourcing=SectionAccess.write,
        pipeline=SectionAccess.write,
        delivery=SectionAccess.read,
        insights=SectionAccess.read,
    ),
    UserRole.tac: _policy(
        sourcing=SectionAccess.write,
        pipeline=SectionAccess.write,
        insights=SectionAccess.read,
    ),
    UserRole.recruiter: _policy(
        sourcing=SectionAccess.write,
        pipeline=SectionAccess.write,
        insights=SectionAccess.read,
    ),
    UserRole.sourcer: _policy(
        sourcing=SectionAccess.write,
        pipeline=SectionAccess.write,
        insights=SectionAccess.read,
    ),
    # Deprecated compatibility persona: keep only the already-public-to-all
    # sourcing tools.  No new provisioning is allowed.
    UserRole.user: _policy(
        sourcing=SectionAccess.read,
        pipeline=SectionAccess.read,
        insights=SectionAccess.read,
    ),
}


def section_access_for_roles(
    roles: Iterable[UserRole], section: ProductSection
) -> SectionAccess:
    return max(
        (ROLE_SECTION_ACCESS.get(role, _NONE)[section] for role in roles),
        default=SectionAccess.none,
    )


def section_access_for_user(user: User, section: ProductSection) -> SectionAccess:
    return section_access_for_roles(user.get_all_roles(), section)


_READ_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def require_section_access(section: ProductSection):
    """Require section read/write according to the incoming HTTP method."""

    async def _check(
        request: Request,
        current_user: User = Depends(get_current_user),
    ) -> User:
        required = (
            SectionAccess.read
            if request.method.upper() in _READ_METHODS
            else SectionAccess.write
        )
        granted = section_access_for_user(current_user, section)
        if granted < required:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "code": "section_access_denied",
                    "section": section.value,
                    "required": required.name,
                    "granted": granted.name,
                },
            )
        return current_user

    return _check


DELIVERY_SECTION_DEPENDENCIES = [
    Depends(require_section_access(ProductSection.delivery))
]


DeliverySectionUser = Annotated[
    User, Depends(require_section_access(ProductSection.delivery))
]
