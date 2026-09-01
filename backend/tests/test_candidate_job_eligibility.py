"""Unit tests for the pure candidate↔job eligibility policy (SEARCH-P0-04).

Pure logic — no DB, no app import — so these run on any Python.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.services.candidate_job_eligibility import (
    ConflictInput,
    EligibilityInput,
    EligibilityReason,
    Severity,
    Visibility,
    evaluate_eligibility,
    extract_excluded_client_ids,
)

NOW = datetime(2026, 7, 15, 12, 0, tzinfo=timezone.utc)


def _eval(**kwargs):
    return evaluate_eligibility(EligibilityInput(**kwargs), NOW)


class TestGlobalBlacklist:
    def test_blacklisted_is_hard_hidden_non_overridable(self):
        d = _eval(candidate_status="blacklisted", job_client_id=5)
        assert not d.eligible
        assert d.visibility is Visibility.hidden
        assert not d.assignment_allowed
        assert d.severity is Severity.hard
        assert d.reason_code is EligibilityReason.blacklisted
        assert not d.override_allowed

    def test_blacklist_wins_over_conflict(self):
        d = _eval(
            candidate_status="blacklisted",
            job_client_id=5,
            conflicts=(ConflictInput(type="nda", client_id=5),),
        )
        assert d.reason_code is EligibilityReason.blacklisted


class TestClientHardConflict:
    def test_active_blacklist_conflict_blocks_assignment_but_visible(self):
        d = _eval(
            candidate_status="active",
            job_client_id=5,
            conflicts=(ConflictInput(type="blacklist", client_id=5),),
        )
        assert not d.eligible
        assert d.visibility is Visibility.warn
        assert not d.assignment_allowed
        assert d.severity is Severity.hard
        assert d.reason_code is EligibilityReason.client_blacklist
        assert d.override_allowed  # authorised roles may override (audited)

    def test_nda_and_competitor_are_hard(self):
        for ctype, rc in [
            ("nda", EligibilityReason.client_nda),
            ("competitor", EligibilityReason.client_competitor),
        ]:
            d = _eval(
                candidate_status="active",
                job_client_id=7,
                conflicts=(ConflictInput(type=ctype, client_id=7),),
            )
            assert d.reason_code is rc
            assert not d.assignment_allowed

    def test_conflict_for_other_client_does_not_block(self):
        d = _eval(
            candidate_status="active",
            job_client_id=5,
            conflicts=(ConflictInput(type="blacklist", client_id=999),),
        )
        assert d.eligible
        assert d.reason_code is EligibilityReason.eligible

    def test_expired_conflict_does_not_block(self):
        expired = ConflictInput(
            type="blacklist", client_id=5, expires_at=NOW - timedelta(days=1)
        )
        d = _eval(candidate_status="active", job_client_id=5, conflicts=(expired,))
        assert d.eligible

    def test_future_expiry_still_blocks(self):
        active = ConflictInput(
            type="blacklist", client_id=5, expires_at=NOW + timedelta(days=1)
        )
        d = _eval(candidate_status="active", job_client_id=5, conflicts=(active,))
        assert not d.assignment_allowed
        assert d.reason_code is EligibilityReason.client_blacklist

    def test_inactive_conflict_does_not_block(self):
        d = _eval(
            candidate_status="active",
            job_client_id=5,
            conflicts=(ConflictInput(type="nda", client_id=5, active=False),),
        )
        assert d.eligible


class TestSoftSignals:
    def test_current_employment_is_warning_not_block(self):
        d = _eval(
            candidate_status="active",
            job_client_id=5,
            conflicts=(ConflictInput(type="current_employment", client_id=5),),
        )
        assert d.eligible
        assert d.assignment_allowed
        assert d.visibility is Visibility.warn
        assert d.severity is Severity.warning
        assert d.reason_code is EligibilityReason.client_current_employment

    def test_candidate_excluded_client_is_warning(self):
        d = _eval(
            candidate_status="active",
            job_client_id=5,
            excluded_client_ids=frozenset({5}),
        )
        assert d.eligible
        assert d.assignment_allowed
        assert d.reason_code is EligibilityReason.client_excluded_by_candidate

    def test_hard_conflict_keeps_current_employment_as_secondary(self):
        d = _eval(
            candidate_status="active",
            job_client_id=5,
            conflicts=(
                ConflictInput(type="nda", client_id=5),
                ConflictInput(type="current_employment", client_id=5),
            ),
        )
        assert d.reason_code is EligibilityReason.client_nda
        assert EligibilityReason.client_current_employment in d.secondary_reasons


class TestAlreadyInJob:
    def test_already_in_job_is_hidden_and_blocked(self):
        d = _eval(candidate_status="active", job_client_id=5, already_in_job=True)
        assert not d.eligible
        assert d.visibility is Visibility.hidden
        assert not d.assignment_allowed
        assert d.reason_code is EligibilityReason.already_in_job
        assert not d.override_allowed

    def test_hard_conflict_outranks_already_in_job(self):
        d = _eval(
            candidate_status="active",
            job_client_id=5,
            conflicts=(ConflictInput(type="blacklist", client_id=5),),
            already_in_job=True,
        )
        assert d.reason_code is EligibilityReason.client_blacklist


class TestExtractExcludedClientIds:
    def test_reads_int_list(self):
        assert extract_excluded_client_ids(
            {"excluded_clients": [1, 2, 3]}
        ) == frozenset({1, 2, 3})

    def test_reads_digit_strings(self):
        assert extract_excluded_client_ids(
            {"excluded_clients": ["5", "7"]}
        ) == frozenset({5, 7})

    def test_ignores_bools_and_junk(self):
        got = extract_excluded_client_ids(
            {"excluded_clients": [1, True, "abc", None, 2.5, 9]}
        )
        assert got == frozenset({1, 9})

    def test_missing_key_or_wrong_shape(self):
        assert extract_excluded_client_ids({}) == frozenset()
        assert extract_excluded_client_ids({"excluded_clients": "5"}) == frozenset()
        assert extract_excluded_client_ids(None) == frozenset()
        assert extract_excluded_client_ids("nope") == frozenset()


class TestEligibleBaseline:
    def test_clean_active_candidate_is_eligible(self):
        d = _eval(candidate_status="active", job_client_id=5)
        assert d.eligible
        assert d.assignment_allowed
        assert d.visibility is Visibility.visible
        assert d.severity is Severity.none
        assert d.reason_code is EligibilityReason.eligible

    def test_passive_candidate_is_eligible(self):
        d = _eval(candidate_status="passive", job_client_id=5)
        assert d.eligible

    def test_no_job_client_skips_client_rules(self):
        # Global search with no job context: only global blacklist can hide.
        d = _eval(
            candidate_status="active",
            job_client_id=None,
            conflicts=(ConflictInput(type="blacklist", client_id=5),),
        )
        assert d.eligible
        assert d.reason_code is EligibilityReason.eligible


class TestHiringManagerVeto:
    """The manager who interviewed and rejected this candidate must not be
    offered them again — but the recruiter must still see why."""

    def test_veto_blocks_assignment_yet_stays_visible(self):
        d = _eval(
            candidate_status="active",
            job_client_id=5,
            rejected_by_hiring_manager=True,
        )
        assert not d.eligible
        assert not d.assignment_allowed
        assert d.severity is Severity.hard
        assert d.reason_code is EligibilityReason.rejected_by_hiring_manager
        # Visible, never hidden: hiding sends the recruiter hunting for the
        # same person again and reads to them as data loss.
        assert d.visibility is Visibility.warn

    def test_veto_is_not_overridable(self):
        # An override would recreate the very irritation this rule prevents.
        d = _eval(
            candidate_status="active",
            job_client_id=5,
            rejected_by_hiring_manager=True,
        )
        assert not d.override_allowed

    def test_label_names_the_manager_not_the_blacklist(self):
        d = _eval(
            candidate_status="active",
            job_client_id=5,
            rejected_by_hiring_manager=True,
        )
        assert "Hiring manager" in d.reason
        assert "czarnej liście" not in d.reason

    def test_absent_veto_changes_nothing(self):
        d = _eval(candidate_status="active", job_client_id=5)
        assert d.eligible
        assert d.reason_code is EligibilityReason.eligible

    def test_global_blacklist_still_wins(self):
        d = _eval(
            candidate_status="blacklisted",
            job_client_id=5,
            rejected_by_hiring_manager=True,
        )
        assert d.reason_code is EligibilityReason.blacklisted
        assert d.visibility is Visibility.hidden

    def test_hard_client_conflict_still_wins_but_veto_is_carried(self):
        d = _eval(
            candidate_status="active",
            job_client_id=5,
            conflicts=(ConflictInput(type="nda", client_id=5),),
            rejected_by_hiring_manager=True,
        )
        assert d.reason_code is EligibilityReason.client_nda
        # The badge must survive the harder block outranking it.
        assert EligibilityReason.rejected_by_hiring_manager in d.secondary_reasons

    def test_already_in_job_outranks_veto(self):
        # Otherwise a candidate merely already in this job would lose `hidden`
        # and reappear in the "add candidate" search as a duplicate.
        d = _eval(
            candidate_status="active",
            job_client_id=5,
            already_in_job=True,
            rejected_by_hiring_manager=True,
        )
        assert d.reason_code is EligibilityReason.already_in_job
        assert d.visibility is Visibility.hidden
        assert EligibilityReason.rejected_by_hiring_manager in d.secondary_reasons

    def test_veto_outranks_soft_warnings(self):
        d = _eval(
            candidate_status="active",
            job_client_id=5,
            conflicts=(ConflictInput(type="current_employment", client_id=5),),
            excluded_client_ids=frozenset({5}),
            rejected_by_hiring_manager=True,
        )
        assert d.reason_code is EligibilityReason.rejected_by_hiring_manager
        assert not d.assignment_allowed
        # ...and the soft signals ride along, minus the dominant one.
        assert EligibilityReason.client_current_employment in d.secondary_reasons
        assert EligibilityReason.rejected_by_hiring_manager not in d.secondary_reasons
