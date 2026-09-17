"""Plakietka dopuszczalności — jedna definicja dla wszystkich powierzchni."""

from __future__ import annotations

from datetime import datetime, timezone

from app.services.candidate_job_eligibility import (
    ConflictInput,
    EligibilityInput,
    evaluate_eligibility,
)
from app.services.eligibility_annotation import eligibility_annotation

NOW = datetime(2026, 9, 17, 12, tzinfo=timezone.utc)


def _ann(**kwargs):
    return eligibility_annotation(evaluate_eligibility(EligibilityInput(**kwargs), NOW))


def test_clean_candidate_has_no_badge():
    assert _ann(candidate_status="active", job_client_id=5) is None
    assert eligibility_annotation(None) is None


def test_pure_current_employment_has_a_badge():
    # Regresja: przed 17.09.2026 czyste obecne zatrudnienie nie miało plakietki.
    ann = _ann(
        candidate_status="active",
        job_client_id=5,
        conflicts=(ConflictInput(type="current_employment", client_id=5),),
    )
    assert ann is not None
    assert ann["reason_code"] == "client_current_employment"
    assert ann["assignment_allowed"] is True


def test_nda_badge_is_an_assignable_warning():
    ann = _ann(
        candidate_status="active",
        job_client_id=5,
        conflicts=(ConflictInput(type="nda", client_id=5),),
    )
    assert ann == {
        "reason_code": "client_nda",
        "reason": "Konflikt: NDA z klientem",
        "assignment_allowed": True,
        "visibility": "warn",
        "severity": "warning",
        "secondary": [],
    }


def test_veto_badge_blocks_assignment():
    ann = _ann(
        candidate_status="active",
        job_client_id=5,
        rejected_by_hiring_manager=True,
    )
    assert ann["assignment_allowed"] is False
    assert ann["severity"] == "hard"
