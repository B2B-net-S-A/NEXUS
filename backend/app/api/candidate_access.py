"""Central capability guards for the candidate/talent module (M2 audit, PR 1).

P0 containment (audit ``docs/candidate-talent-module-audit-and-claude-
implementation-plan-2026-07-16.md``): the ``user`` role is a read-only
viewer/client persona (QC, klient) and must NOT have access to the global
candidate base — PII, contact data, CV/documents, rates — nor perform any
candidate-related mutation (notes, source events, talent pools, tags).

These dependencies replace bare ``CurrentUser`` on candidate-module routes.
Every guard evaluates the union of primary ``User.role`` and secondary
``User.roles`` via ``has_any_role`` — a hybrid delivery_lead+TAC persona passes
both capability sets. The external ``user`` viewer remains rejected; Finance
has the organization-wide business reads described below.

Capability → allowed roles:

- **read/search/PII/documents** — all internal operational roles
  (admin, head_of_recruitment, delivery_lead, talent_community_manager, tac,
  recruiter, finance, sourcer).
  ``user`` is excluded everywhere.
- **write** (profile fields, notes, source events, talent pools, tags) —
  parity with the existing ``RecruiterPlus`` contract (admin, delivery_lead,
  talent_community_manager, tac, recruiter, finance, sourcer).
- **export** — admin, head_of_recruitment, delivery_lead,
  talent_community_manager, tac, finance. Recruiter and sourcer intentionally
  lose bulk export (matrix section 9 of the audit: "domyślnie nie recruiter");
  exports are audited via ``candidate_audit``.
- **candidate finance read** (candidate-specific pricing and conflict history)
  — internal operational role plus effective Finance read access; mutations
  remain admin only. The role defaults still grant this only to Admin/Finance,
  while an explicit per-user Finance exception can delegate the read. The
  candidate's own global B2B profile rate is a separate typed-fact capability.
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

from app.api.deps import get_current_user
from app.models.user import User, UserRole
from app.services.section_permissions import (
    ProductSection,
    SectionAccess,
    section_access_for_user,
)

# ── Capability role sets ─────────────────────────────────────────────────────

# Everyone except the read-only viewer/client role `user`.
_INTERNAL_OPERATIONAL_ROLES: tuple[UserRole, ...] = (
    UserRole.admin,
    UserRole.head_of_recruitment,
    UserRole.delivery_lead,
    UserRole.talent_community_manager,
    UserRole.tac,
    UserRole.recruiter,
    UserRole.finance,
    UserRole.sourcer,
)

CANDIDATE_READ_ROLES: tuple[UserRole, ...] = _INTERNAL_OPERATIONAL_ROLES
CANDIDATE_DOCUMENT_ROLES: tuple[UserRole, ...] = _INTERNAL_OPERATIONAL_ROLES

# Parity with deps.RecruiterPlus (head_of_recruitment does not perform
# operational candidate writes today — do not widen in a containment PR).
CANDIDATE_WRITE_ROLES: tuple[UserRole, ...] = (
    UserRole.admin,
    UserRole.delivery_lead,
    UserRole.talent_community_manager,
    UserRole.tac,
    UserRole.recruiter,
    UserRole.finance,
    UserRole.sourcer,
)

CANDIDATE_EXPORT_ROLES: tuple[UserRole, ...] = (
    UserRole.admin,
    UserRole.head_of_recruitment,
    UserRole.delivery_lead,
    UserRole.talent_community_manager,
    UserRole.tac,
    UserRole.finance,
)

CANDIDATE_FINANCE_READ_ROLES: tuple[UserRole, ...] = _INTERNAL_OPERATIONAL_ROLES
CANDIDATE_FINANCE_ROLES: tuple[UserRole, ...] = (UserRole.admin,)

# Global Talent 360 facts are a deliberately broader write capability than
# ordinary profile mutations. Product policy allows every internal operational
# role, including Head of Recruitment and sourcer, to maintain these facts.
CANDIDATE_PROFILE_FACT_WRITE_ROLES: tuple[UserRole, ...] = _INTERNAL_OPERATIONAL_ROLES


def user_has_candidate_read(user: User) -> bool:
    """Non-raising capability check for mixed-entity surfaces.

    Global search returns jobs/clients/contacts too — those sections stay
    available to every logged-in role, but the candidates section must be
    skipped entirely for users without candidate read capability.
    """
    # Decyzja produktowa Artura 19.08: Finance ma pełny dostęp operacyjny
    # (tier recruitera) — historyczne odcięcie od PII kandydatów zdjęte;
    # finance jest teraz w CANDIDATE_READ_ROLES jak pozostałe role operacyjne.
    if user.has_role(UserRole.admin):
        return True
    if user.has_role(UserRole.user):
        return False
    section_read = max(
        section_access_for_user(user, ProductSection.sourcing),
        section_access_for_user(user, ProductSection.pipeline),
    )
    return section_read >= SectionAccess.read and user.has_any_role(
        *CANDIDATE_READ_ROLES
    )


def user_can_access_candidate_domain(user: User) -> bool:
    """Current-user/fan-out eligibility for candidate and recruitment data.

    Role membership alone is insufficient for notification/WS fan-out because
    those paths operate on historical user ids without passing through JWT
    authentication first.
    """

    return bool(user.is_active and user_has_candidate_read(user))


# Job fields a read-only viewer (QC / client-side `user`) must not receive on
# the jobs list or detail. Financials, the whole champion sourcing profile, the
# internal close notes and the free-form custom fields. Redaction sets each to
# None rather than dropping the key, so the response SHAPE is unchanged and the
# frontend does not break on a missing field — the viewer simply sees blanks.
_VIEWER_REDACTED_JOB_FIELDS: tuple[str, ...] = (
    "salary_min",
    "salary_max",
    "rate_budget_hourly",
    "champion_profile",
    "close_notes",
    "close_reason",
    "custom_fields",
    "description",
    "requirements",
)


def redact_job_for_viewer(job_dict: dict, user: User) -> dict:
    """Blank sensitive job fields for callers without an operational role.

    Operational roles (recruiter and up) see everything. The read-only `user`
    role — which per deps.py may be a client-side account — keeps the fields it
    needs to make sense of the board (title, status, client, deadline,
    headcount, owners) but loses money, the champion profile and internal
    notes. Mutates and returns the same dict.
    """
    if user_has_candidate_read(user):
        return job_dict
    for field in _VIEWER_REDACTED_JOB_FIELDS:
        if field in job_dict:
            job_dict[field] = None
    # Staff assignment is internal too — a client viewer has no need for the
    # recruiter/collaborator roster with their e-mail addresses.
    if "primary_owner" in job_dict:
        job_dict["primary_owner"] = None
    if "collaborators" in job_dict:
        job_dict["collaborators"] = []
    return job_dict


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


def require_candidate_roles(
    *roles: UserRole,
    required_access: SectionAccess = SectionAccess.read,
):
    """Candidate-domain role guard with explicit viewer denial.

    The generic ``require_roles`` correctly treats Admin as a superuser, but
    its union semantics would also let a malformed historical Finance+Admin or
    viewer+recruiter account into candidate PII. Candidate access must remain
    fail-closed independently of the pending role-cleanup migration.
    """

    async def _check(current_user: User = Depends(get_current_user)) -> User:
        # Finance przechodzi przez zwykłe listy ról (decyzja 19.08) — dawny
        # bezwarunkowy bounce zdjęty razem z ekskluzywnością tej persony.
        if current_user.has_role(UserRole.admin):
            return current_user
        if current_user.has_role(UserRole.user) or not current_user.has_any_role(
            *roles
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requires candidate role: {[role.value for role in roles]}",
            )
        candidate_access = max(
            section_access_for_user(current_user, ProductSection.sourcing),
            section_access_for_user(current_user, ProductSection.pipeline),
        )
        if candidate_access < required_access:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "code": "section_access_denied",
                    "section": "sourcing_or_pipeline",
                    "required": required_access.name,
                    "granted": candidate_access.name,
                },
            )
        return current_user

    return _check


# Callable-style dependencies for routes using the `= Depends(...)` idiom
# (keeps signatures with already-defaulted params valid without reordering).
require_candidate_read = require_candidate_roles(*CANDIDATE_READ_ROLES)
require_candidate_write = require_candidate_roles(
    *CANDIDATE_WRITE_ROLES,
    required_access=SectionAccess.write,
)


async def require_candidate_finance_read(
    current_user: User = Depends(
        require_candidate_roles(*CANDIDATE_FINANCE_READ_ROLES)
    ),
) -> User:
    """Require candidate-domain visibility plus configured Finance read access."""

    granted = section_access_for_user(current_user, ProductSection.finance)
    if granted < SectionAccess.read:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "section_access_denied",
                "section": ProductSection.finance.value,
                "required": SectionAccess.read.name,
                "granted": granted.name,
            },
        )
    return current_user


# Search / list summaries (no viewer access — closes M2-SEC-01).
CandidateSearchAccess = Annotated[
    User, Depends(require_candidate_roles(*CANDIDATE_READ_ROLES))
]

# Full profile / timeline / history (contact data, PII).
CandidatePIIAccess = Annotated[
    User, Depends(require_candidate_roles(*CANDIDATE_READ_ROLES))
]

# CV + document listing/content/presigned URLs/ZIP.
CandidateDocumentAccess = Annotated[
    User, Depends(require_candidate_roles(*CANDIDATE_DOCUMENT_ROLES))
]

# Mutations: notes, source events, talent pools, tags, engagement, location.
CandidateWriteAccess = Annotated[
    User,
    Depends(
        require_candidate_roles(
            *CANDIDATE_WRITE_ROLES,
            required_access=SectionAccess.write,
        )
    ),
]

# Bulk exports (CSV/XLSX) — audited, management roles plus Finance business read.
CandidateExportAccess = Annotated[
    User, Depends(require_candidate_roles(*CANDIDATE_EXPORT_ROLES))
]

# Candidate-specific pricing/conflict reads.  Mutations keep the narrower alias
# below so Finance cannot write candidate rates by gaining read access.
CandidateFinanceReadAccess = Annotated[User, Depends(require_candidate_finance_read)]

# Client-facing pricing mutations („stawka do klienta").
CandidateFinanceAccess = Annotated[
    User,
    Depends(
        require_candidate_roles(
            *CANDIDATE_FINANCE_ROLES,
            required_access=SectionAccess.write,
        )
    ),
]

# Typed global profile facts are readable by every internal operational role.
CandidateProfileFactsReadAccess = Annotated[
    User, Depends(require_candidate_roles(*CANDIDATE_READ_ROLES))
]

# Their dedicated OCC writers deliberately use the product-specific role set,
# not the narrower generic CandidateWriteAccess or client-rate finance guard.
CandidateProfileFactsWriteAccess = Annotated[
    User,
    Depends(
        require_candidate_roles(
            *CANDIDATE_PROFILE_FACT_WRITE_ROLES,
            required_access=SectionAccess.write,
        )
    ),
]

# Releasing a source that is confirmed to describe another person is a
# management exception, not an ordinary candidate edit.
CandidateIdentityQuarantineOverrideAccess = Annotated[
    User,
    Depends(
        require_candidate_roles(
            UserRole.admin,
            UserRole.head_of_recruitment,
            required_access=SectionAccess.write,
        )
    ),
]

# Trwałe usunięcie profilu jest nieodwracalne, więc guard jest WĘŻSZY niż przy
# zwykłej edycji kandydata: wyłącznie `admin`, a nie `DeliveryLeadPlus`, którym
# ta trasa była chroniona wcześniej. `admin` to szczyt hierarchii ról
# (`ROLE_RANK`), więc „Admin lub wyższa" znaczy dokładnie tę jedną rolę.
# Przez `require_candidate_roles`, nie przez globalny `AdminUser`, żeby zachować
# fail-closed na rolach spoza modułu kandydata (`finance`, legacy `user`).
CandidateHardDeleteAccess = Annotated[
    User,
    Depends(
        require_candidate_roles(
            UserRole.admin,
            required_access=SectionAccess.write,
        )
    ),
]
