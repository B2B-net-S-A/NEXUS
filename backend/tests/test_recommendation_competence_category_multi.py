"""Multi-value `competence_category` semantics for the recommendation filter.

Direct unit tests on `_competence_category_matches` — fast, no DB needed.
"""

from __future__ import annotations

import pytest

from app.services.recommendation_filters import _competence_category_matches


class _StubJob:
    """Minimal duck-type — only the fields the predicate reads."""

    def __init__(self, *, title: str = "", subcategory=None, industry=None) -> None:
        self.title = title
        self.subcategory = subcategory
        self.industry = industry


def test_empty_targets_matches_anything():
    job = _StubJob(title="Senior Backend Engineer")
    assert _competence_category_matches(job, []) is True
    # Whitespace-only entries also count as empty.
    assert _competence_category_matches(job, ["   ", ""]) is True


def test_single_target_matches_when_substring_present():
    job = _StubJob(title="Senior Backend Engineer")
    assert _competence_category_matches(job, ["Backend"]) is True
    assert _competence_category_matches(job, ["Frontend"]) is False


def test_multiple_targets_or_combined():
    """Any matching needle keeps the job — OR semantics."""
    job = _StubJob(title="DevOps Lead")
    # Backend doesn't match the title, but DevOps does — OR keeps the job.
    assert _competence_category_matches(job, ["Backend", "DevOps"]) is True
    # Neither matches → drop.
    assert _competence_category_matches(job, ["Frontend", "Mobile"]) is False


def test_match_is_case_insensitive():
    job = _StubJob(subcategory="backend services")
    assert _competence_category_matches(job, ["BACKEND"]) is True


def test_match_against_multiple_job_fields():
    job = _StubJob(title="Senior Engineer", subcategory=None, industry="FinTech")
    assert _competence_category_matches(job, ["fintech"]) is True
