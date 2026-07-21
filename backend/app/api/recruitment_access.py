"""Central capability guards for the recruitment-pipeline module (M4 audit, PR-01).

P0.3 containment (audit ``docs/recruitment-pipeline-submission-placement-
module-audit-and-claude-implementation-plan-2026-07-16.md``): lifecycle
endpoints used bare ``CurrentUser`` (scorecard, screening notes, calendar,
interview feedback, rejection-email preview) so the read-only viewer/client
persona ``user`` could read candidate PII and mutate assessments, and the
``sourcer`` role could execute terminal moves (``hired``) and edit rates.

These dependencies replace bare ``CurrentUser``/too-wide guards on the
lifecycle routes. Mirrors ``candidate_access.py`` (M2 PR 1): every guard is
built on ``require_roles`` which evaluates the union of primary ``User.role``
and secondary ``User.roles`` via ``has_any_role``.

Capability → allowed roles:

- **read** (kanban, SLA overview, pipelines of a candidate, funnel/TTH
  reports, screening notes, calendar, feedback, rejection-email timeline) —
  all internal operational roles; ``user`` (viewer) excluded everywhere.
- **transition** (non-terminal stage moves) — parity with the existing
  ``RecruiterPlus`` contract (admin, delivery_lead, tac, recruiter, sourcer).
  Do not widen or narrow in a containment PR.
- **terminal transition** (``hired``/``rejected``/``withdrawn`` or a
  stage-def with terminal semantics) — sourcer intentionally excluded
  (audit P0.3: "terminalny hired nie ma ownership scope"; sourcing persona
  must not close recruitments).
- **rate edit** (candidate expected rate: PATCH expected-rate and the
  rate-bearing move to ``verified``) — admin, delivery_lead, tac, recruiter.
  Sourcer intentionally excluded (audit P0.3: expected rate używa zbyt
  szerokiego CandidateWriteAccess obejmującego sourcera).
- **assessment write** (scorecard answers, screening notes, interview
  feedback) — RecruiterPlus parity (prep-call screening is sourcer work);
  viewer excluded (was: bare ``CurrentUser``).
- **calendar write** — RecruiterPlus parity; viewer excluded (was: bare
  ``CurrentUser`` on create/update/delete/import).
- **rejection-email oversight** (read/cancel someone else's scheduled
  rejection email incl. recipient/subject/body/last_error) — admin,
  delivery_lead, head_of_recruitment; the owning recruiter always retains
  access to their own rows (checked in-endpoint, not here).

Resource scope for the *pipeline* surfaces is enforced by
``ensure_job_membership`` below (P1-PIPE-01). The role guards above answer
"may this persona touch the recruitment module at all?"; the membership gate
answers "may this persona touch *this job's* pipeline?". They compose: an
ingress runs the role dependency first (viewer excluded) and then the
membership check (non-members of the job excluded). Do NOT add a feature flag
that reverts any of these guards to plain ``CurrentUser`` or that disables the
membership gate.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_roles
from app.models.user import User, UserRole
from app.services.job_membership import is_member_of_job

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

RECRUITMENT_READ_ROLES: tuple[UserRole, ...] = _INTERNAL_OPERATIONAL_ROLES

# Parity with deps.RecruiterPlus — the pre-existing move contract.
RECRUITMENT_TRANSITION_ROLES: tuple[UserRole, ...] = (
    UserRole.admin,
    UserRole.delivery_lead,
    UserRole.tac,
    UserRole.recruiter,
    UserRole.sourcer,
)

# Terminal lifecycle decisions (hired / rejected / withdrawn) — no sourcer.
# head_of_recruitment celowo NIEuwzględniony: route-level guard /move to
# RecruiterPlus (bez HoR), a containment nie poszerza dostępu — HoR w tym
# zbiorze byłby martwym wpisem sugerującym uprawnienie, którego nie ma.
RECRUITMENT_TERMINAL_ROLES: tuple[UserRole, ...] = (
    UserRole.admin,
    UserRole.delivery_lead,
    UserRole.tac,
    UserRole.recruiter,
)

# Candidate expected-rate edits (PATCH + rate-bearing `verified` move).
RECRUITMENT_RATE_EDIT_ROLES: tuple[UserRole, ...] = (
    UserRole.admin,
    UserRole.delivery_lead,
    UserRole.tac,
    UserRole.recruiter,
)

# Scorecards, screening notes, interview feedback.
RECRUITMENT_ASSESSMENT_WRITE_ROLES: tuple[UserRole, ...] = (
    UserRole.admin,
    UserRole.delivery_lead,
    UserRole.tac,
    UserRole.recruiter,
    UserRole.sourcer,
)

CALENDAR_WRITE_ROLES: tuple[UserRole, ...] = (
    UserRole.admin,
    UserRole.delivery_lead,
    UserRole.tac,
    UserRole.recruiter,
    UserRole.sourcer,
)

REJECTION_EMAIL_OVERSIGHT_ROLES: tuple[UserRole, ...] = (
    UserRole.admin,
    UserRole.delivery_lead,
    UserRole.head_of_recruitment,
)


def user_can_terminal_transition(user: User) -> bool:
    """Non-raising check used inside /move where terminality is data-driven."""
    return user.has_any_role(*RECRUITMENT_TERMINAL_ROLES)


def user_can_edit_rates(user: User) -> bool:
    """Non-raising check for the rate-bearing move to `verified`."""
    return user.has_any_role(*RECRUITMENT_RATE_EDIT_ROLES)


def user_has_rejection_email_oversight(user: User) -> bool:
    """Multi-role-aware oversight check (fixes primary-role-only comparison)."""
    return user.has_any_role(*REJECTION_EMAIL_OVERSIGHT_ROLES)


# ── FastAPI dependencies ─────────────────────────────────────────────────────

# Read surfaces of the lifecycle module (viewer excluded).
RecruitmentReadAccess = Annotated[User, Depends(require_roles(*RECRUITMENT_READ_ROLES))]

# Candidate expected-rate mutations.
RecruitmentRateEditAccess = Annotated[
    User, Depends(require_roles(*RECRUITMENT_RATE_EDIT_ROLES))
]

# Scorecard / screening / feedback mutations.
RecruitmentAssessmentWriteAccess = Annotated[
    User, Depends(require_roles(*RECRUITMENT_ASSESSMENT_WRITE_ROLES))
]

# Calendar event mutations (create/update/delete/import/m365 invite).
CalendarWriteAccess = Annotated[User, Depends(require_roles(*CALENDAR_WRITE_ROLES))]


# ── Resource scope: job membership (P1-PIPE-01) ─────────────────────────────

# Oversight roles that see every job's pipeline regardless of membership.
# admin already short-circuits inside ``is_member_of_job``; head_of_recruitment
# is the recruitment-wide oversight persona and is added here so it is not
# forced onto every job's collaborator list.
_JOB_MEMBERSHIP_BYPASS_ROLES: tuple[UserRole, ...] = (
    UserRole.admin,
    UserRole.head_of_recruitment,
)


async def ensure_job_membership(db: AsyncSession, user: User, job_id: int) -> None:
    """Enforce that ``user`` may read/mutate ``job_id``'s pipeline.

    Fills the resource scope that the role guards above deliberately leave to a
    dedicated check (P1-PIPE-01): every pipeline ingress (kanban read, stage
    history, ``/move``, ``/bulk-move``, interview feedback) must confirm the
    caller belongs to the job before touching its pipeline. Membership =
    owner / delivery_lead / TAC / active collaborator per
    :func:`app.services.job_membership.is_member_of_job` (multi-role aware via
    ``has_any_role``), plus the oversight roles admin / head_of_recruitment.

    A non-member gets a uniform **403** at every ingress — the same status the
    sibling resource-scope guard ``require_dl_assigned_or_admin`` returns, so
    the module speaks one language for "authenticated but out of scope". 403
    (not 404) is chosen for consistency and because job existence is already
    discoverable to any internal role through the jobs list; there is no
    enumeration surface to protect here.
    """
    if user.has_any_role(*_JOB_MEMBERSHIP_BYPASS_ROLES):
        return
    if await is_member_of_job(db, user, job_id):
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=(
            "Brak dostępu do tej rekrutacji — nie należysz do jej zespołu "
            "(właściciel / delivery lead / TAC / współpracownik)."
        ),
    )
