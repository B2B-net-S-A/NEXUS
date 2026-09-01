"""Unit tests for `app.services.proxycurl.diff.compute_change`.

Pure functions — no DB, no network. Covers:
- first snapshot (no previous)
- identical company+title → no_change
- fuzzy-matched company rebrand → no_change (anti-false-positive)
- title change at same company → new_title_same_company (promotion)
- real employer change → new_company (triggers "changed jobs" filter)
- missing current company on new snapshot → no_change (defensive)
"""

from __future__ import annotations

from datetime import date

import pytest

from app.models.linkedin_snapshot import LinkedinChangeKind
from app.services.proxycurl.client import ProxycurlProfile
from app.services.proxycurl.diff import (
    ChangeResult,
    companies_equal,
    compute_change,
)


def _profile(
    company: str | None, title: str | None, started: date | None
) -> ProxycurlProfile:
    return ProxycurlProfile(
        raw={},
        current_company=company,
        current_title=title,
        current_started_at=started,
    )


def test_first_snapshot_has_no_previous() -> None:
    curr = _profile("Acme", "Senior Engineer", date(2024, 3, 1))
    result = compute_change(None, curr)
    assert result.change_kind is LinkedinChangeKind.first_snapshot
    assert result.changed_from_previous is False
    assert result.current_company == "Acme"


def test_identical_snapshot_is_no_change() -> None:
    prev = _profile("Acme", "Senior Engineer", date(2024, 3, 1))
    curr = _profile("Acme", "Senior Engineer", date(2024, 3, 1))
    result = compute_change(prev, curr)
    assert result.change_kind is LinkedinChangeKind.no_change
    assert result.changed_from_previous is False


def test_company_rebrand_with_legal_suffix_does_not_trigger_new_company() -> None:
    """Acme rebrand 'Acme Sp. z o.o.' ↔ 'Acme sp z o o' — fuzzy match must hold."""
    prev = _profile("Acme Sp. z o.o.", "Senior Engineer", date(2024, 3, 1))
    curr = _profile("Acme sp z o o", "Senior Engineer", date(2024, 3, 1))
    result = compute_change(prev, curr)
    assert result.change_kind is LinkedinChangeKind.no_change


def test_promotion_same_company_new_title() -> None:
    prev = _profile("Acme", "Senior Engineer", date(2024, 3, 1))
    curr = _profile("Acme", "Staff Engineer", date(2024, 3, 1))
    result = compute_change(prev, curr)
    assert result.change_kind is LinkedinChangeKind.new_title_same_company
    assert result.changed_from_previous is True


def test_real_new_company_triggers_new_company_kind() -> None:
    prev = _profile("Acme", "Senior Engineer", date(2024, 3, 1))
    curr = _profile("Beta Corp", "Staff Engineer", date(2026, 4, 1))
    result = compute_change(prev, curr)
    assert result.change_kind is LinkedinChangeKind.new_company
    assert result.changed_from_previous is True
    assert result.current_company == "Beta Corp"


def test_missing_current_company_in_new_snapshot_is_no_change() -> None:
    """Defensive: Proxycurl may return a profile with no current experience.

    We refuse to mis-classify this as a job change — the signal is too noisy.
    """
    prev = _profile("Acme", "Senior Engineer", date(2024, 3, 1))
    curr = _profile(None, None, None)
    result = compute_change(prev, curr)
    assert result.change_kind is LinkedinChangeKind.no_change


def test_company_match_ignores_punctuation_case_and_spacing() -> None:
    assert companies_equal("Google Inc.", "google inc")
    assert companies_equal("Acme Sp. z o.o.", "ACME SP Z O O")
    assert companies_equal("  Acme  ", "Acme")


def test_company_match_rejects_truly_different_names() -> None:
    assert not companies_equal("Google", "Microsoft")
    assert not companies_equal("Acme", "Beta Corp")


def test_custom_threshold_overrides_default() -> None:
    """Lowering the threshold makes us more permissive; raising it, stricter."""
    # At default threshold 90, these may or may not match.
    prev = _profile("Foobar Software", "Dev", None)
    curr = _profile("Foobar Solutions", "Dev", None)
    loose = compute_change(prev, curr, company_fuzz_threshold=50)
    strict = compute_change(prev, curr, company_fuzz_threshold=99)
    # Loose should collapse to no_change; strict to new_company.
    assert loose.change_kind in (
        LinkedinChangeKind.no_change,
        LinkedinChangeKind.new_title_same_company,
    )
    assert strict.change_kind is LinkedinChangeKind.new_company


def test_result_dataclass_is_frozen() -> None:
    result = ChangeResult(
        change_kind=LinkedinChangeKind.no_change,
        current_company="Acme",
        current_title="Engineer",
        current_started_at=None,
    )
    with pytest.raises(Exception):
        result.change_kind = LinkedinChangeKind.new_company  # type: ignore[misc]
