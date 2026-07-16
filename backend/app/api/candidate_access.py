"""Central capability guards for the candidate/talent module (M2 audit, PR 1).

P0 containment (audit ``docs/candidate-talent-module-audit-and-claude-
implementation-plan-2026-07-16.md``): the ``user`` role is a read-only
viewer/client persona (QC, klient) and must NOT have access to the global
candidate base — PII, contact data, CV/documents, rates — nor perform any
candidate-related mutation (notes, source events, talent pools, tags).

These dependencies replace bare ``CurrentUser`` on candidate-module routes.
Every guard is built on ``require_roles`` which evaluates the union of the
primary ``User.role`` and secondary ``User.roles`` via ``has_any_role`` —
a hybrid delivery_lead+TAC persona passes both capability sets.

Capability → allowed roles:

- **read/search/PII/documents** — all internal operational roles
  (admin, head_of_recruitment, delivery_lead, tac, recruiter, sourcer).
  ``user`` is excluded everywhere.
- **write** (profile fields, notes, source events, talent pools, tags) —
  parity with the existing ``RecruiterPlus`` contract (admin, delivery_lead,
  tac, recruiter, sourcer).
- **export** — admin, head_of_recruitment, delivery_lead, tac. Recruiter and
  sourcer intentionally lose bulk export (matrix section 9 of the audit:
  "domyślnie nie recruiter"); exports are audited via ``candidate_audit``.
- **finance** (client-facing pricing, e.g. „stawka do klienta") — admin,
  delivery_lead, tac. The candidate's own expected rate stays a write-level
  operation because the kanban verified-stage flow sets it (RecruiterPlus
  parity with POST /api/pipeline/move).
- **privacy execute** (anonymize / erase / hard delete) — NOBODY until the
  PR 2 privacy executor lands. Endpoints answer 409 with a clear message;
  see ``privacy_workflow_unavailable``.

Do NOT add a feature flag that reverts any of these guards to plain
``CurrentUser`` — the audit explicitly forbids a rollback path that would
re-expose PII to viewers.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, status

from app.api.deps import require_roles
from app.models.user import User, UserRole

# ── Capability role sets ─────────────────────────────────────────────────────

# Everyone except the read-only viewer/client role `user`.
_INTERNAL_OPERATIONAL_ROLES: tuple[UserRole, ...] = (
    UserRole.admin,
    UserRole.head_of_recruitment,
    UserRole.delivery_lead,
    UserRole.tac,
    UserRole.recruiter,
    UserRole.sourcer,
)

CANDIDATE_READ_ROLES: tuple[UserRole, ...] = _INTERNAL_OPERATIONAL_ROLES
CANDIDATE_DOCUMENT_ROLES: tuple[UserRole, ...] = _INTERNAL_OPERATIONAL_ROLES

# Parity with deps.RecruiterPlus (head_of_recruitment does not perform
# operational candidate writes today — do not widen in a containment PR).
CANDIDATE_WRITE_ROLES: tuple[UserRole, ...] = (
    UserRole.admin,
    UserRole.delivery_lead,
    UserRole.tac,
    UserRole.recruiter,
    UserRole.sourcer,
)

CANDIDATE_EXPORT_ROLES: tuple[UserRole, ...] = (
    UserRole.admin,
    UserRole.head_of_recruitment,
    UserRole.delivery_lead,
    UserRole.tac,
)

CANDIDATE_FINANCE_ROLES: tuple[UserRole, ...] = (
    UserRole.admin,
    UserRole.delivery_lead,
    UserRole.tac,
)


def user_has_candidate_read(user: User) -> bool:
    """Non-raising capability check for mixed-entity surfaces.

    Global search returns jobs/clients/contacts too — those sections stay
    available to every logged-in role, but the candidates section must be
    skipped entirely for users without candidate read capability.
    """
    return user.has_any_role(*CANDIDATE_READ_ROLES)


def privacy_workflow_unavailable(operation: str) -> HTTPException:
    """409 for destructive privacy-adjacent operations disabled until PR 2.

    ``anonymize_pii`` only blanked a few contact fields while leaving CV,
    documents, notes, vectors and integration payloads in place (M2-PRIV-01),
    and hard delete cascades through contracts and audit history while
    leaving storage/Qdrant orphans (M2-PRIV-02). Neither may run as a regular
    action; the real privacy executor (preview → approval → manifest → retry)
    ships in PR 2 of the module plan.
    """
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=(
            f"Operacja „{operation}” została wyłączona — wymaga workflow "
            "prywatności (RODO/DSAR z manifestem artefaktów), który jest w "
            "przygotowaniu. Do tego czasu użyj statusu 'blacklisted' aby "
            "wyłączyć kandydata z sourcingu."
        ),
    )


# ── FastAPI dependencies ─────────────────────────────────────────────────────

# Callable-style dependencies for routes using the `= Depends(...)` idiom
# (keeps signatures with already-defaulted params valid without reordering).
require_candidate_read = require_roles(*CANDIDATE_READ_ROLES)
require_candidate_write = require_roles(*CANDIDATE_WRITE_ROLES)

# Search / list summaries (no viewer access — closes M2-SEC-01).
CandidateSearchAccess = Annotated[User, Depends(require_roles(*CANDIDATE_READ_ROLES))]

# Full profile / timeline / history (contact data, PII).
CandidatePIIAccess = Annotated[User, Depends(require_roles(*CANDIDATE_READ_ROLES))]

# CV + document listing/content/presigned URLs/ZIP.
CandidateDocumentAccess = Annotated[
    User, Depends(require_roles(*CANDIDATE_DOCUMENT_ROLES))
]

# Mutations: notes, source events, talent pools, tags, engagement, location.
CandidateWriteAccess = Annotated[User, Depends(require_roles(*CANDIDATE_WRITE_ROLES))]

# Bulk exports (CSV/XLSX) — audited, TAC and up.
CandidateExportAccess = Annotated[User, Depends(require_roles(*CANDIDATE_EXPORT_ROLES))]

# Client-facing pricing mutations („stawka do klienta").
CandidateFinanceAccess = Annotated[
    User, Depends(require_roles(*CANDIDATE_FINANCE_ROLES))
]
