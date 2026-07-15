"""Unified candidate ↔ job eligibility policy (SEARCH-P0-04).

Today the "can this candidate be shown / assigned to this job?" decision is
scattered and inconsistent:

* ``api/proposals_bulk.py`` gates bulk-add on ``Candidate.status == blacklisted``
  and already-in-job only — it never looks at ``CandidateConflict``.
* ``services/recommendation_filters.py`` hard-drops ``blacklist``/``competitor``/
  ``nda`` conflicts and soft-warns ``current_employment`` — and honours
  ``expires_at``.
* ``services/scoring_service.py`` penalises blacklist / active conflict /
  ``preferences.excluded_clients`` — but IGNORES ``expires_at``.
* ``api/search.py`` applies NO eligibility filter at all.
* single-assign and pipeline-move have no eligibility gate.

This module is the single source of truth for that policy. It is a **pure
function** over already-loaded inputs (no DB, no I/O) so it is trivially
unit-testable and can be reused by search prefilters, bulk-add, single-assign
and pipeline-move without each re-deriving the rules. Callers are responsible
for loading the inputs (conflicts, excluded clients, in-job flag) and for
enforcing the returned decision transactionally at write time.

The default policy mirrors the *existing* recommendation-filter semantics so
this is a consolidation, not a behaviour change:

* global ``blacklisted`` status → non-overridable hard block, hidden from search;
* active (non-expired) client ``blacklist``/``nda``/``competitor`` conflict →
  hard block on assignment, visible-with-warning, overridable by an authorised
  role with an audited reason;
* active ``current_employment`` conflict → soft warning, assignment allowed;
* candidate-declared ``excluded_clients`` → soft warning, assignment allowed;
* already in this job (any stage) → duplicate, hidden from the job search and
  blocked from re-assignment.

Which rules are *legal* hard blocks vs. warnings is ultimately a process-owner
decision; the mapping here is the documented default and is easy to adjust.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class Visibility(str, Enum):
    """How a candidate should surface in search results."""

    visible = "visible"  # normal result, no eligibility annotation
    warn = "warn"  # shown, but with an eligibility warning badge
    hidden = "hidden"  # must not appear in job-scoped search results


class Severity(str, Enum):
    none = "none"
    warning = "warning"
    hard = "hard"


class EligibilityReason(str, Enum):
    eligible = "eligible"
    blacklisted = "blacklisted"  # global Candidate.status
    client_blacklist = "client_blacklist"  # CandidateConflict(type=blacklist)
    client_nda = "client_nda"
    client_competitor = "client_competitor"
    client_current_employment = "client_current_employment"
    client_excluded_by_candidate = "client_excluded_by_candidate"  # preferences
    already_in_job = "already_in_job"


# Conflict types that block assignment to the client (visible-with-warning).
_HARD_CONFLICT_REASONS: dict[str, EligibilityReason] = {
    "blacklist": EligibilityReason.client_blacklist,
    "nda": EligibilityReason.client_nda,
    "competitor": EligibilityReason.client_competitor,
}

_REASON_LABELS_PL: dict[EligibilityReason, str] = {
    EligibilityReason.eligible: "Brak przeciwwskazań",
    EligibilityReason.blacklisted: "Kandydat na globalnej czarnej liście",
    EligibilityReason.client_blacklist: "Konflikt: klient ma kandydata na czarnej liście",
    EligibilityReason.client_nda: "Konflikt: NDA z klientem",
    EligibilityReason.client_competitor: "Konflikt: klient konkurencyjny",
    EligibilityReason.client_current_employment: "Kandydat obecnie pracuje u tego klienta",
    EligibilityReason.client_excluded_by_candidate: "Kandydat wykluczył tego klienta",
    EligibilityReason.already_in_job: "Kandydat jest już w tej rekrutacji",
}


@dataclass(frozen=True)
class ConflictInput:
    """A single ``CandidateConflict`` row, reduced to what the policy needs."""

    type: str  # blacklist | current_employment | nda | competitor
    client_id: int
    active: bool = True
    expires_at: Optional[datetime] = None

    def is_active_at(self, now: datetime) -> bool:
        """Active AND not expired. Mirrors ``recommendation_filters`` (and,
        unlike ``scoring_service``, actually honours ``expires_at``)."""
        return self.active and (self.expires_at is None or self.expires_at > now)


@dataclass(frozen=True)
class EligibilityInput:
    candidate_status: str  # active | passive | blacklisted
    job_client_id: Optional[int] = None
    conflicts: tuple[ConflictInput, ...] = ()
    excluded_client_ids: frozenset[int] = field(default_factory=frozenset)
    already_in_job: bool = False


@dataclass(frozen=True)
class EligibilityDecision:
    eligible: bool
    visibility: Visibility
    assignment_allowed: bool
    severity: Severity
    reason_code: EligibilityReason
    reason: str
    override_allowed: bool
    # Secondary applicable signals (e.g. a current-employment warning that sits
    # underneath a dominant hard conflict), for transparent UI annotation.
    secondary_reasons: tuple[EligibilityReason, ...] = ()


def _decision(
    reason_code: EligibilityReason,
    *,
    eligible: bool,
    visibility: Visibility,
    assignment_allowed: bool,
    severity: Severity,
    override_allowed: bool,
    secondary_reasons: tuple[EligibilityReason, ...] = (),
) -> EligibilityDecision:
    return EligibilityDecision(
        eligible=eligible,
        visibility=visibility,
        assignment_allowed=assignment_allowed,
        severity=severity,
        reason_code=reason_code,
        reason=_REASON_LABELS_PL[reason_code],
        override_allowed=override_allowed,
        secondary_reasons=secondary_reasons,
    )


def evaluate_eligibility(inp: EligibilityInput, now: datetime) -> EligibilityDecision:
    """Return the dominant eligibility decision for a candidate/job pair.

    ``now`` is passed in (not read from the clock) so the function stays pure
    and deterministic for tests. Priority, most-blocking first:

    1. global blacklist, 2. hard client conflict, 3. already-in-job,
    4. current-employment warning, 5. candidate-excluded-client warning,
    6. eligible.
    """
    # 1. Global blacklist — non-overridable hard block, hidden everywhere.
    if inp.candidate_status == "blacklisted":
        return _decision(
            EligibilityReason.blacklisted,
            eligible=False,
            visibility=Visibility.hidden,
            assignment_allowed=False,
            severity=Severity.hard,
            override_allowed=False,
        )

    # Collect active client-scoped conflicts for THIS job's client.
    active_types: set[str] = set()
    if inp.job_client_id is not None:
        active_types = {
            c.type
            for c in inp.conflicts
            if c.client_id == inp.job_client_id and c.is_active_at(now)
        }

    # Secondary (warning-level) signals recorded even when a harder block wins.
    secondary: list[EligibilityReason] = []
    if "current_employment" in active_types:
        secondary.append(EligibilityReason.client_current_employment)
    if inp.job_client_id is not None and inp.job_client_id in inp.excluded_client_ids:
        secondary.append(EligibilityReason.client_excluded_by_candidate)

    # 2. Hard client conflict — blocked from assignment, visible with a warning,
    #    overridable by an authorised role (audited).
    for ctype, reason_code in _HARD_CONFLICT_REASONS.items():
        if ctype in active_types:
            return _decision(
                reason_code,
                eligible=False,
                visibility=Visibility.warn,
                assignment_allowed=False,
                severity=Severity.hard,
                override_allowed=True,
                secondary_reasons=tuple(secondary),
            )

    # 3. Already in this job — duplicate; hidden from the job search, blocked
    #    from re-assignment (not overridable — it's a dedup, not a policy call).
    if inp.already_in_job:
        return _decision(
            EligibilityReason.already_in_job,
            eligible=False,
            visibility=Visibility.hidden,
            assignment_allowed=False,
            severity=Severity.warning,
            override_allowed=False,
            secondary_reasons=tuple(secondary),
        )

    # 4. Current employment at this client — soft warning, assignment allowed.
    if EligibilityReason.client_current_employment in secondary:
        rest = tuple(
            r for r in secondary if r != EligibilityReason.client_current_employment
        )
        return _decision(
            EligibilityReason.client_current_employment,
            eligible=True,
            visibility=Visibility.warn,
            assignment_allowed=True,
            severity=Severity.warning,
            override_allowed=False,
            secondary_reasons=rest,
        )

    # 5. Candidate declared this client excluded — soft warning.
    if EligibilityReason.client_excluded_by_candidate in secondary:
        return _decision(
            EligibilityReason.client_excluded_by_candidate,
            eligible=True,
            visibility=Visibility.warn,
            assignment_allowed=True,
            severity=Severity.warning,
            override_allowed=False,
        )

    # 6. No contraindication.
    return _decision(
        EligibilityReason.eligible,
        eligible=True,
        visibility=Visibility.visible,
        assignment_allowed=True,
        severity=Severity.none,
        override_allowed=False,
    )
