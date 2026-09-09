from types import SimpleNamespace

from app.services.requirement_contract import (
    apply_requirement_source_update,
    invalidate_changed_requirements,
    requirements_for_job,
)
from tests.test_scoring_service import make_job


def test_saved_empty_requirements_override_original_text():
    job = make_job(must_skills=["Python"])
    job.matching_requirements = {
        "version": 1,
        "reviewed": True,
        "all_of": [],
        "missing_evidence_policy": "review",
    }
    assert requirements_for_job(job).all_of == []
    assert requirements_for_job(job).reviewed


def test_source_edit_invalidates_previous_approval_but_budget_edit_does_not():
    job = SimpleNamespace(
        description="Python",
        matching_requirements={"reviewed": True},
        requirements_reviewed=True,
    )
    updates = {"description": "Java"}
    invalidate_changed_requirements(job, updates)
    assert updates["matching_requirements"] is None
    assert updates["requirements_reviewed"] is False
    unchanged = {"description": "Python", "rate_budget_hourly": 150}
    invalidate_changed_requirements(job, unchanged)
    assert "matching_requirements" not in unchanged


def test_review_flag_follows_saved_contract_and_champion_updates_invalidate_it():
    job = SimpleNamespace(
        champion_profile={"role_name": "Old"},
        matching_requirements={"reviewed": True},
        requirements_reviewed=True,
    )
    updates = {
        "matching_requirements": {"reviewed": False},
        "requirements_reviewed": True,
    }
    invalidate_changed_requirements(job, updates)
    assert updates["requirements_reviewed"] is False
    apply_requirement_source_update(job, "champion_profile", {"role_name": "New"})
    assert job.matching_requirements is None and not job.requirements_reviewed


def test_champion_process_metadata_does_not_clear_reviewed_requirements():
    job = SimpleNamespace(
        champion_profile={"role_name": "Python", "verification": {"status": "draft"}},
        matching_requirements={"reviewed": True},
        requirements_reviewed=True,
    )
    apply_requirement_source_update(
        job,
        "champion_profile",
        {"role_name": "Python", "verification": {"status": "approved"}},
    )
    assert job.matching_requirements == {"reviewed": True}
    assert job.requirements_reviewed
