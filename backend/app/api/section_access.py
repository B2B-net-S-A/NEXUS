"""Central section-level RBAC for the NEXUS product shell.

Endpoint-specific guards still decide whether a permitted user may execute a
particular action.  This module owns the coarser product boundary: whether the
persona may enter Sourcing, Pipeline, Delivery, Insights, Finance or technical
administration at all.

The Delivery boundary is enforced on every router backing that UI section.
It deliberately treats safe HTTP methods as read access and every other method
as write access.

Od migracji 0409 poziom Delivery i Finansów wynika z uprawnień z ekranu
(``permission_catalog.derive_sections``): sam podgląd daje odczyt, a każde
uprawnienie do zmiany (klienci, kontrakty i zamówienia, status kontraktu,
kwoty) daje zapis. Bramka sekcji jest więc sufitem, a o konkretnej operacji
decyduje bramka uprawnienia na trasie (``permission_access``).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, Request, status

from app.api.deps import get_current_user
from app.models.user import User, UserRole
from app.services.action_permissions import (
    ActionAccess,
    ProductAction,
    action_access_for_user,
)
from app.services.request_semantics import is_read_only_http_request
from app.services.section_permissions import (
    ProductSection,
    SectionAccess,
    section_access_for_user,
)


_TERMINATION_RECOVERY_COMMANDS = frozenset(
    {"termination-reversal", "return-after-break"}
)


def _is_contract_termination_recovery(request: Request, current_user: User) -> bool:
    """„Cofnij zakończenie" / „Powrót po przerwie" dla Finansów i TCM.

    Obie role czytają Delivery, ale nie mają w nim zapisu. Ticket 09.2026
    daje im te dwie korekty wprost — i TYLKO je: rola na samym endpoincie
    (Admin, Finanse, TCM) jest drugą połową bramki.
    """

    parts = request.url.path.strip("/").split("/")
    return (
        request.method.upper() == "POST"
        and len(parts) == 4
        and parts[:2] == ["api", "contracts"]
        and parts[2].isdigit()
        and parts[3] in _TERMINATION_RECOVERY_COMMANDS
        and current_user.has_any_role(
            UserRole.talent_community_manager, UserRole.finance
        )
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
        # „Cofnij zakończenie” / „Powrót po przerwie” to wąski wyjątek zapisu
        # WEWNĄTRZ Delivery, nie obejście: konto bez podglądu Delivery go nie ma.
        # (Osobny wyjątek dla zmiany statusu przez TCM zniknął w 0409 — status
        # jest uprawnieniem, z którego wynika zapis w sekcji.)
        if (
            section is ProductSection.delivery
            and granted >= SectionAccess.read
            and _is_contract_termination_recovery(request, current_user)
        ):
            return current_user
        parts = request.url.path.strip("/").split("/")
        if (
            section is ProductSection.sourcing
            and granted >= SectionAccess.read
            and request.method.upper() == "POST"
            and len(parts) == 5
            and parts[:3] == ["api", "b2b-generator", "generated"]
            and parts[3].isdigit()
            and parts[4] == "confirm-fully-signed"
            and action_access_for_user(
                current_user, ProductAction.b2b_signature_confirmation
            )
            >= ActionAccess.manage
            and action_access_for_user(
                current_user, ProductAction.b2b_contract_generator
            )
            >= ActionAccess.view
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


def require_section_access_any_read(*sections: ProductSection):
    """Admit a shared read workflow available from any of several sections.

    Explicitly read-only even for POST searches; resource/write/PII gates are
    still owned by the route. Existing method-based section gates are unchanged.
    """
    if not sections:
        raise ValueError("At least one section is required")

    async def _check(current_user: User = Depends(get_current_user)) -> User:
        if not any(
            section_access_for_user(current_user, section) >= SectionAccess.read
            for section in sections
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "code": "section_access_denied",
                    "required": "read",
                    "any_section": [section.value for section in sections],
                },
            )
        return current_user

    return _check


def require_section_access_any(*sections: ProductSection):
    """Jak ``require_section_access``, ale wystarcza DOWOLNA z sekcji.

    Poziom (odczyt/zapis) wynika z metody HTTP. Dla powierzchni, której
    zapisujący siedzą w różnych sekcjach — np. przypisania DL↔klient edytuje
    Delivery Lead (Delivery) i Head of Recruitment (bez Delivery, z Pipeline).
    """
    if not sections:
        raise ValueError("At least one section is required")

    async def _check(
        request: Request,
        current_user: User = Depends(get_current_user),
    ) -> User:
        is_read = is_read_only_http_request(request.method, request.url.path)
        required = SectionAccess.read if is_read else SectionAccess.write
        if not any(
            section_access_for_user(current_user, section) >= required
            for section in sections
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "code": "section_access_denied",
                    "required": required.name,
                    "any_section": [section.value for section in sections],
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
