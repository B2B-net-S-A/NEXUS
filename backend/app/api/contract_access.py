"""Central capability guard for legal-document surfaces of the contracts module
(Moduł 5 audit, PR-01).

P0.11 containment (audit ``docs/contracts-engagement-onboarding-billing-
offboarding-module-audit-and-claude-implementation-plan-2026-07-16.md``): the
B2B contract generator and the contract-template render endpoints used bare
``CurrentUser``. That let the read-only viewer/client persona ``user`` — and the
delivery ``recruiter``/``sourcer`` personas — do things they must not:

- ``POST /b2b-contract-generator/generate`` with a passed ``contract_id`` loaded
  **any** Contract (only checking it was type ``b2b``) and then mutated
  ``start_date``, ``rate_candidate``, ``currency`` and **replaced** the whole
  candidate rate schedule → horizontal privilege escalation + rate tampering.
- ``GET .../contracts/{id}/detail`` and ``.../docx`` exposed candidate rate and
  the full legal DOCX (partner PII, terms) of any contract.
- ``GET .../generated`` and ``.../generated/{id}/docx`` exposed partner/client
  PII and let anyone re-render a legal document.
- ``POST /render`` and ``GET /next-number`` allocated a legal contract number to
  any logged-in user.
- ``contract_templates`` ``GET .../render`` rendered any template + Contract.

**Fix:** legal surfaces use the same authoritative client relationship graph as
``client_access.can_view_legal_documents``. Admin/Head of Recruitment keep
organization oversight. Delivery Lead and TAC require an explicit assignment
for the concrete client; an empty graph is deny-all. Recruiter/Sourcer,
Finance, and the legacy viewer are excluded from legal PII.

Owner/admin checks that already gate mutating ``generated`` rows
(PATCH/DELETE) stay in place as a second layer; this guard only ensures the
caller is legal-team at all.

Global catalogs (role names, templates, numbering helpers) require at least one
explicit client assignment for DL/TAC. Entity routes additionally resolve the
exact client before reading, rendering, mutating, or downloading a document.
Rows without an authoritative ``client_id`` are visible only to Admin/HoR.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.user import User, UserRole
from app.services.client_access import (
    ADMIN_LIKE_ROLES,
    deny,
    resolve_client_access,
    resolve_client_team_client_ids,
)

# Legal-team personas trusted with contract legal documents. Mirrors
# ``client_access.can_view_legal_documents`` (admin_like ∪ client_team).
CONTRACT_LEGAL_ROLES: tuple[UserRole, ...] = (
    UserRole.admin,
    UserRole.head_of_recruitment,
    UserRole.delivery_lead,
    UserRole.tac,
)


def user_is_contract_legal_team(user: User) -> bool:
    """Role-only preflight; entity authorization still requires DB scope."""
    return user.has_any_role(*CONTRACT_LEGAL_ROLES)


async def require_contract_legal_access(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Gate global legal tools; empty DL/TAC assignment graphs fail closed."""

    client_ids = await resolve_client_team_client_ids(db, current_user)
    if client_ids is None or client_ids:
        return current_user
    raise deny("dostęp prawny wymaga jawnego przypisania klienta")


async def assert_contract_legal_client_access(
    db: AsyncSession,
    user: User,
    client_id: int | None,
    *,
    write: bool = False,
) -> None:
    """Authorize one legal entity against its authoritative client relation."""

    if client_id is None:
        if user.has_any_role(*ADMIN_LIKE_ROLES):
            return
        raise deny("dokument prawny bez klienta jest dostępny tylko Admin/HoR")

    access = await resolve_client_access(db, user, client_id)
    allowed = (
        access.can_edit_legal_documents if write else access.can_view_legal_documents
    )
    if not allowed:
        operation = "edycja" if write else "odczyt"
        raise deny(f"{operation} dokumentu wymaga jawnego przypisania klienta")


async def apply_contract_legal_client_scope(
    statement,
    client_column,
    db: AsyncSession,
    user: User,
):
    """Scope legal list queries before sorting/limiting."""

    client_ids = await resolve_client_team_client_ids(db, user)
    if client_ids is None:
        return statement
    return statement.where(client_column.in_(sorted(client_ids) or [-1]))


# Read + generate + render + download of B2B contracts, contract templates and
# their legal numbers. Excludes Finance/viewer/recruiter/sourcer and an
# unassigned DL/TAC before the endpoint body runs.
ContractLegalAccess = Annotated[User, Depends(require_contract_legal_access)]
