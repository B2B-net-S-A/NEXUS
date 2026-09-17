"""Unified candidate ↔ job eligibility policy (SEARCH-P0-04).

Historically the "can this candidate be shown / assigned to this job?" decision
was scattered across bulk-add, recommendation filters, scoring and search, each
with its own rules (and scoring ignored ``expires_at``).

This module is the single source of truth for that policy. It is a **pure
function** over already-loaded inputs (no DB, no I/O) so it is trivially
unit-testable and can be reused by search prefilters, bulk-add, single-assign
and pipeline-move without each re-deriving the rules. Callers are responsible
for loading the inputs (conflicts, excluded clients, in-job flag) and for
enforcing the returned decision transactionally at write time.

The policy (decision of 17.09.2026 — client conflicts are warnings, not blocks):

* global ``blacklisted`` status → non-overridable hard block, hidden from search;
* already in this job (any stage) → duplicate, hidden from the job search and
  blocked from re-assignment;
* rejected after an interview by *this job's* hiring manager → hard block on
  assignment, visible-with-warning — the ONLY "visible but blocked" state left;
* active (non-expired) client ``blacklist``/``nda``/``competitor`` conflict,
  ``current_employment`` at the client and candidate-declared
  ``excluded_clients`` → **soft warnings**: visible with a badge, assignable.
  When several apply, the dominant one is the most serious
  (``blacklist > nda > competitor > current_employment > excluded``), the rest
  ride in ``secondary_reasons``.

``override_allowed`` stays in the decision shape for API stability but is always
``False``: there is no override endpoint, and after 17.09.2026 nothing left to
override (a client conflict no longer blocks).
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
    # This job's hiring manager already interviewed and rejected the candidate
    # on an earlier recruitment (see ``services.hiring_manager_verdicts``).
    rejected_by_hiring_manager = "rejected_by_hiring_manager"


# Client-scoped conflict types → reason, in DOMINANCE order (most serious first).
# All of them are soft warnings since 17.09.2026 — none blocks assignment.
_CLIENT_CONFLICT_REASONS: dict[str, EligibilityReason] = {
    "blacklist": EligibilityReason.client_blacklist,
    "nda": EligibilityReason.client_nda,
    "competitor": EligibilityReason.client_competitor,
    "current_employment": EligibilityReason.client_current_employment,
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
    EligibilityReason.rejected_by_hiring_manager: (
        "Hiring manager tej rekrutacji już odrzucił tego kandydata po rozmowie"
    ),
}


def extract_excluded_client_ids(preferences: object) -> frozenset[int]:
    """Read ``Candidate.preferences.excluded_clients`` (JSONB) into a set of
    client ids for :class:`EligibilityInput`.

    Defensive: the JSONB shape is loosely typed across importers, so accept
    ints and digit-strings and ignore anything else (bools included, since
    ``bool`` is an ``int`` subclass in Python)."""
    if not isinstance(preferences, dict):
        return frozenset()
    raw = preferences.get("excluded_clients")
    if not isinstance(raw, list):
        return frozenset()
    out: set[int] = set()
    for c in raw:
        if isinstance(c, bool):
            continue
        if isinstance(c, int):
            out.add(c)
        elif isinstance(c, str) and c.isdigit():
            out.add(int(c))
    return frozenset(out)


@dataclass(frozen=True)
class ConflictInput:
    """A single ``CandidateConflict`` row, reduced to what the policy needs."""

    type: str  # blacklist | current_employment | nda | competitor
    client_id: int
    active: bool = True
    expires_at: Optional[datetime] = None

    def is_active_at(self, now: datetime) -> bool:
        """Active AND not expired — the same rule as
        ``CandidateConflict.active_unexpired_clause`` on the SQL side."""
        return self.active and (self.expires_at is None or self.expires_at > now)


@dataclass(frozen=True)
class EligibilityInput:
    candidate_status: str  # active | passive | blacklisted
    job_client_id: Optional[int] = None
    conflicts: tuple[ConflictInput, ...] = ()
    excluded_client_ids: frozenset[int] = field(default_factory=frozenset)
    already_in_job: bool = False
    # This job's hiring manager rejected the candidate after meeting them on a
    # *different* recruitment, for a reason flagged as disqualifying the person.
    # A bare bool by design: the caller loads the details (who, when, why) and
    # carries them separately, so ``EligibilityDecision`` keeps its shape.
    rejected_by_hiring_manager: bool = False


@dataclass(frozen=True)
class EligibilityDecision:
    eligible: bool
    visibility: Visibility
    assignment_allowed: bool
    severity: Severity
    reason_code: EligibilityReason
    reason: str
    # Always ``False`` — kept for API shape; there is no override endpoint.
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
    secondary_reasons: tuple[EligibilityReason, ...] = (),
) -> EligibilityDecision:
    return EligibilityDecision(
        eligible=eligible,
        visibility=visibility,
        assignment_allowed=assignment_allowed,
        severity=severity,
        reason_code=reason_code,
        reason=_REASON_LABELS_PL[reason_code],
        override_allowed=False,
        secondary_reasons=secondary_reasons,
    )


def evaluate_eligibility(inp: EligibilityInput, now: datetime) -> EligibilityDecision:
    """Return the dominant eligibility decision for a candidate/job pair.

    ``now`` is passed in (not read from the clock) so the function stays pure
    and deterministic for tests. Priority, most-blocking first:

    1. global blacklist (hidden, hard), 2. already-in-job (hidden),
    3. rejected by this job's hiring manager (visible, hard),
    4. dominant soft signal — client blacklist > NDA > competitor >
       current employment > candidate-excluded client (visible, assignable),
    5. eligible.
    """
    # 1. Global blacklist — non-overridable hard block, hidden everywhere.
    if inp.candidate_status == "blacklisted":
        return _decision(
            EligibilityReason.blacklisted,
            eligible=False,
            visibility=Visibility.hidden,
            assignment_allowed=False,
            severity=Severity.hard,
        )

    # Active client-scoped conflicts for THIS job's client.
    active_types: set[str] = set()
    if inp.job_client_id is not None:
        active_types = {
            c.type
            for c in inp.conflicts
            if c.client_id == inp.job_client_id and c.is_active_at(now)
        }

    # Soft signals in dominance order. Client conflicts stopped blocking on
    # 17.09.2026 — they are warnings like current employment.
    soft: list[EligibilityReason] = [
        reason
        for ctype, reason in _CLIENT_CONFLICT_REASONS.items()
        if ctype in active_types
    ]
    if inp.job_client_id is not None and inp.job_client_id in inp.excluded_client_ids:
        soft.append(EligibilityReason.client_excluded_by_candidate)

    # The veto rides first so its badge survives even when a duplicate outranks it.
    secondary: list[EligibilityReason] = []
    if inp.rejected_by_hiring_manager:
        secondary.append(EligibilityReason.rejected_by_hiring_manager)
    secondary.extend(soft)

    # 2. Already in this job — duplicate; hidden from the job search, blocked
    #    from re-assignment (not overridable — it's a dedup, not a policy call).
    if inp.already_in_job:
        return _decision(
            EligibilityReason.already_in_job,
            eligible=False,
            visibility=Visibility.hidden,
            assignment_allowed=False,
            severity=Severity.warning,
            secondary_reasons=tuple(secondary),
        )

    # 3. This job's hiring manager already met this candidate and rejected
    #    them. Hard block on assignment, but deliberately **visible**: hiding
    #    the candidate would make the recruiter hunt for the same person again
    #    and reads to them as data loss. Not overridable — an override would
    #    recreate the exact irritation this rule exists to prevent.
    #
    #    Ranked below `already_in_job` on purpose: otherwise a candidate who is
    #    merely already in this job would lose `hidden` and reappear in the
    #    "add candidate" search as a duplicate.
    if inp.rejected_by_hiring_manager:
        return _decision(
            EligibilityReason.rejected_by_hiring_manager,
            eligible=False,
            visibility=Visibility.warn,
            assignment_allowed=False,
            severity=Severity.hard,
            secondary_reasons=tuple(soft),
        )

    # 4. Soft signal — visible with a badge, assignment allowed.
    if soft:
        return _decision(
            soft[0],
            eligible=True,
            visibility=Visibility.warn,
            assignment_allowed=True,
            severity=Severity.warning,
            secondary_reasons=tuple(soft[1:]),
        )

    # 5. No contraindication.
    return _decision(
        EligibilityReason.eligible,
        eligible=True,
        visibility=Visibility.visible,
        assignment_allowed=True,
        severity=Severity.none,
    )
