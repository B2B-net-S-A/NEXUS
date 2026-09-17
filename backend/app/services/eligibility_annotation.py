"""UI annotation of an eligibility decision — one shape for every surface.

Ranking rows (``/ai-matches``, proposals, full search, Talent Radar, similar
recruitments) and the manual search render this dict as a badge; the action
is disabled only when ``assignment_allowed`` is ``False`` (global blacklist is
never shown, so in practice: a hiring-manager veto).

The badge exists for EVERY non-``eligible`` decision. Before 17.09.2026 the
helper returned ``None`` for ``eligible=True`` decisions without secondary
reasons, so a pure current-employment warning had no badge — and after client
conflicts became soft warnings (``eligible=True``) the NDA badge would have
vanished everywhere.
"""

from __future__ import annotations

from typing import Optional

from app.services.candidate_job_eligibility import (
    EligibilityDecision,
    EligibilityReason,
)


def eligibility_annotation(decision: Optional[EligibilityDecision]) -> dict | None:
    if decision is None:
        return None
    if (
        decision.reason_code is EligibilityReason.eligible
        and not decision.secondary_reasons
    ):
        return None
    return {
        "reason_code": decision.reason_code.value,
        "reason": decision.reason,
        "assignment_allowed": decision.assignment_allowed,
        "visibility": decision.visibility.value,
        "severity": decision.severity.value,
        "secondary": [r.value for r in decision.secondary_reasons],
    }
