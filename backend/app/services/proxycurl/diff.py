"""Pure change-detection between two LinkedIn profile snapshots.

Unit-testable, no DB, no network. Given the *previous* persisted
`ProxycurlProfile` (or None for first run) and the *current* one, classify
the diff so the sync service knows whether to set
`Candidate.linkedin_employment_changed_at` and which badge to render.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from typing import Optional

from rapidfuzz import fuzz

from app.core.config import settings
from app.models.linkedin_snapshot import LinkedinChangeKind
from app.services.proxycurl.client import ProxycurlProfile

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ChangeResult:
    """Outcome of comparing a new profile against its predecessor."""

    change_kind: LinkedinChangeKind
    current_company: Optional[str]
    current_title: Optional[str]
    current_started_at: Optional[date]

    @property
    def changed_from_previous(self) -> bool:
        return self.change_kind in (
            LinkedinChangeKind.new_company,
            LinkedinChangeKind.new_title_same_company,
        )


def compute_change(
    prev: Optional[ProxycurlProfile],
    curr: ProxycurlProfile,
    *,
    company_fuzz_threshold: Optional[int] = None,
) -> ChangeResult:
    """Classify the diff between two profile snapshots.

    Ordering:
      - No previous snapshot → `first_snapshot`
      - No current company on new snapshot → `no_change` (cannot classify)
      - Same company (fuzzy) + same title → `no_change`
      - Same company (fuzzy) + different title → `new_title_same_company`
      - Different company → `new_company`
    """

    threshold = (
        company_fuzz_threshold
        if company_fuzz_threshold is not None
        else settings.PROXYCURL_COMPANY_FUZZ_THRESHOLD
    )

    if prev is None:
        return ChangeResult(
            change_kind=LinkedinChangeKind.first_snapshot,
            current_company=curr.current_company,
            current_title=curr.current_title,
            current_started_at=curr.current_started_at,
        )

    # If the new snapshot has no current employer, we cannot meaningfully
    # classify the diff — record as no_change so we do not pollute the
    # "recently changed jobs" filter on noisy Proxycurl responses.
    if not curr.current_company:
        return ChangeResult(
            change_kind=LinkedinChangeKind.no_change,
            current_company=curr.current_company,
            current_title=curr.current_title,
            current_started_at=curr.current_started_at,
        )

    same_company = companies_equal(
        prev.current_company, curr.current_company, threshold=threshold
    )
    same_title = _titles_equal(prev.current_title, curr.current_title)

    if same_company and same_title:
        kind = LinkedinChangeKind.no_change
    elif same_company and not same_title:
        kind = LinkedinChangeKind.new_title_same_company
    else:
        kind = LinkedinChangeKind.new_company

    return ChangeResult(
        change_kind=kind,
        current_company=curr.current_company,
        current_title=curr.current_title,
        current_started_at=curr.current_started_at,
    )


def companies_equal(
    a: Optional[str], b: Optional[str], *, threshold: int = 90
) -> bool:
    """Fuzzy equality check for company names.

    Uses `rapidfuzz.fuzz.token_set_ratio` so order / punctuation / legal
    suffixes ("Sp. z o.o.", "Inc.", "GmbH") don't cause false-positive
    "new employer" alerts. Both None → True (we can't say they differ).
    """

    if not a and not b:
        return True
    if not a or not b:
        return False
    na, nb = _normalize_company(a), _normalize_company(b)
    if na == nb:
        return True
    score = fuzz.token_set_ratio(na, nb)
    return score >= threshold


def _normalize_company(name: str) -> str:
    stripped = name.strip().lower()
    # Collapse common legal suffix dots/commas so "Acme Sp. z o.o." matches
    # "Acme sp z o o" even below fuzz threshold on unusual punctuation mixes.
    for ch in (",", ".", "(", ")", "/"):
        stripped = stripped.replace(ch, " ")
    return " ".join(stripped.split())


def _titles_equal(a: Optional[str], b: Optional[str]) -> bool:
    if not a and not b:
        return True
    if not a or not b:
        return False
    return a.strip().lower() == b.strip().lower()
