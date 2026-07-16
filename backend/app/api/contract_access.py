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

**Fix:** replace bare ``CurrentUser`` on these surfaces with a role gate limited
to the legal team. The set mirrors ``client_access.can_view_legal_documents``
(``is_admin_like OR is_client_team`` = admin + head_of_recruitment +
delivery_lead + tac) — the same personas already trusted with client legal
documents in ``client_framework_contracts`` (the audit's "positive pattern to
keep"). Recruiter/sourcer (delivery) and the ``user`` viewer are excluded.

Owner/admin checks that already gate mutating ``generated`` rows
(PATCH/DELETE) stay in place as a second layer; this guard only ensures the
caller is legal-team at all.

Per-contract client scope (restricting a TAC to their assigned clients) is
deliberately NOT added here: legal-document access is intentionally global for
the legal team in NEXUS today (delivery_lead/tac see legal docs of every client
— ``CLIENT_TEAM_ROLES`` is a global role check, not per-assignment). Narrowing
that is a separate policy decision for the command-service wave (plan fala C+),
tracked in section 21. Do NOT add a feature flag that reverts these guards to
plain ``CurrentUser``.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends

from app.api.deps import require_roles
from app.models.user import User, UserRole

# Legal-team personas trusted with contract legal documents. Mirrors
# ``client_access.can_view_legal_documents`` (admin_like ∪ client_team).
CONTRACT_LEGAL_ROLES: tuple[UserRole, ...] = (
    UserRole.admin,
    UserRole.head_of_recruitment,
    UserRole.delivery_lead,
    UserRole.tac,
)


def user_is_contract_legal_team(user: User) -> bool:
    """Non-raising check for in-endpoint branching (multi-role aware)."""
    return user.has_any_role(*CONTRACT_LEGAL_ROLES)


# Read + generate + render + download of B2B contracts, contract templates and
# their legal numbers. Excludes the ``user`` viewer and recruiter/sourcer.
ContractLegalAccess = Annotated[User, Depends(require_roles(*CONTRACT_LEGAL_ROLES))]
