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
``client_access.can_view_legal_documents``. Admin/Head of Recruitment and
Finance keep organization-wide read oversight. Delivery Lead and TAC require
an explicit assignment for the concrete client; an empty graph is deny-all.
Recruiter/Sourcer and the legacy viewer are excluded from legal PII.

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

from fastapi import Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.contract import Contract
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

CONTRACT_LEGAL_READ_ROLES: tuple[UserRole, ...] = (
    *CONTRACT_LEGAL_ROLES,
    UserRole.finance,
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


async def require_contract_legal_read_access(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Read-only legal-document gate with organization-wide Finance access."""

    if current_user.has_role(UserRole.finance):
        return current_user
    return await require_contract_legal_access(current_user, db)


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


async def assert_contract_legal_contract_access(
    db: AsyncSession,
    user: User,
    contract_id: int,
    *,
    write: bool = False,
) -> None:
    """Resolve a contract id to its client before authorizing legal content."""

    client_id = await db.scalar(
        select(Contract.client_id).where(Contract.id == contract_id)
    )
    if client_id is None:
        raise HTTPException(status_code=404, detail="Contract not found")
    await assert_contract_legal_client_access(
        db,
        user,
        client_id,
        write=write,
    )


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


# Write/render/generate tools keep their historical legal-team gate. Finance's
# organization-wide authority is deliberately provided only by the GET alias
# below, never through this mutation-capable dependency.
ContractLegalAccess = Annotated[User, Depends(require_contract_legal_access)]

# GET-only counterpart.  Never use this alias on render/generate/mutation
# commands; entity writes still resolve ``can_edit_legal_documents``.
ContractLegalReadAccess = Annotated[
    User,
    Depends(require_contract_legal_read_access),
]


# Every current role except Delivery Lead admitted unconditionally to the
# sourcing-side generator. Explicit tuple
# rather than an implicit "everyone else" fallthrough — a bare `return
# current_user` default would silently hand full generator access to any
# *future* UserRole the moment it's added to the enum, with no callsite
# forcing a conscious decision (matches the discipline behind
# ``capabilities.ts``'s `ALL_ROLES` on the frontend). A role added to
# ``UserRole`` and left off this tuple fails closed here until someone
# deliberately widens it.
#
# Public (no leading underscore) because ``b2b_contract_generator``'s
# ``_generator_unscoped`` imports and reuses it directly, rather than keeping
# its own copy — auto-review on #1216 flagged two independently-maintained
# role tuples as a sync hazard: a role added to one but not the other would
# pass this entry gate and then hit a permanently empty list inside the
# generator. One tuple, two call sites, no drift possible.
B2B_GENERATOR_UNCONDITIONAL_ROLES: tuple[UserRole, ...] = (
    UserRole.admin,
    UserRole.head_of_recruitment,
    UserRole.talent_community_manager,
    UserRole.tac,
    UserRole.finance,
    UserRole.recruiter,
    UserRole.sourcer,
    UserRole.user,
)


async def require_b2b_generator_access(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Gate for the B2B contract generator specifically.

    Sourcing tooling open to every logged-in role (product decision, 20.08 —
    mirrors Talent Radar 19.08 and the finance full-access-tier decision,
    19.08). The sidebar entry for this tool has never carried a `roles`
    restriction ("Generator Umów B2B — dostępny dla wszystkich ról"), so the
    previous role gate here (Admin/HoR/TAC unconditionally, Delivery Lead only
    with a client assignment, everyone else denied) produced exactly the
    visible-link-but-403 gap already fixed once for Talent Radar: recruiter,
    sourcer, finance and the legacy `user` role saw the link and got 403.

    Delivery Lead keeps its established fail-closed contract: an empty DL
    client graph is denied, and concrete entities stay inside its portfolio.
    Talent Community Manager enters the global catalog, but rate-bearing
    generation/render/download commands have an additional explicit denial in
    ``b2b_contract_generator``. Its generated contract register remains
    non-financial and read-only for plain TCM.
    """

    if current_user.has_any_role(*B2B_GENERATOR_UNCONDITIONAL_ROLES):
        return current_user
    if current_user.has_role(UserRole.delivery_lead):
        client_ids = await resolve_client_team_client_ids(db, current_user)
        if client_ids:
            return current_user
        raise deny("dostęp prawny wymaga jawnego przypisania klienta")
    raise deny(
        "Generator umów B2B: nieznana rola bez jawnej decyzji dostępu "
        "(require_b2b_generator_access)"
    )


# Entry gate for the B2B generator surfaces. Every role in
# ``B2B_GENERATOR_UNCONDITIONAL_ROLES`` passes unconditionally; Delivery Lead
# still needs a non-empty client graph; anything else (a future role not yet
# triaged here) fails closed. Client-level scoping of individual entities/lists
# is intentionally disabled for the unconditional roles inside
# ``b2b_contract_generator`` (full-access tool, see ``_generator_unscoped``)
# — otherwise roles with no client-assignment graph at all
# (recruiter/sourcer/finance/user) would pass this gate and then hit a
# permanently empty list.
B2BGeneratorAccess = Annotated[User, Depends(require_b2b_generator_access)]
