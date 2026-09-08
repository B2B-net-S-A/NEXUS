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
resource-scope guards only for finance and consequential legal operations.
Ordinary client operations are organization-wide for every Delivery Lead.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, Request, status

from app.api.deps import get_current_user
from app.models.user import User, UserRole
from app.services.request_semantics import is_read_only_http_request
from app.services.section_permissions import (
    ProductSection,
    SectionAccess,
    section_access_for_user,
)


def _is_tcm_contract_status_command(request: Request, current_user: User) -> bool:
    """Admit only the dedicated, non-financial contract-status command."""

    parts = request.url.path.strip("/").split("/")
    return (
        request.method.upper() == "PATCH"
        and len(parts) == 4
        and parts[:2] == ["api", "contracts"]
        and parts[2].isdigit()
        and parts[3] == "status"
        and current_user.has_role(UserRole.talent_community_manager)
    )


def require_section_access(section: ProductSection):
    """Require section read/write according to the incoming HTTP method."""

    async def _check(
        request: Request,
        current_user: User = Depends(get_current_user),
    ) -> User:
        is_read = is_read_only_http_request(request.method, request.url.path)
        required = SectionAccess.read if is_read else SectionAccess.write
        granted = section_access_for_user(current_user, section)
        if (
            section is ProductSection.delivery
            and _is_tcm_contract_status_command(request, current_user)
        ):
            return current_user
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
SOURCING_SECTION_DEPENDENCIES = [
    Depends(require_section_access(ProductSection.sourcing))
]
PIPELINE_SECTION_DEPENDENCIES = [
    Depends(require_section_access(ProductSection.pipeline))
]
INSIGHTS_SECTION_DEPENDENCIES = [
    Depends(require_section_access(ProductSection.insights))
]
FINANCE_SECTION_DEPENDENCIES = [Depends(require_section_access(ProductSection.finance))]


DeliverySectionUser = Annotated[
    User, Depends(require_section_access(ProductSection.delivery))
]

FinanceSectionUser = Annotated[
    User, Depends(require_section_access(ProductSection.finance))
]
