"""Unit tests for the candidate→job recommendation status filter + ranking.

The "Sugerowane rekrutacje" widget (GET /api/candidates/{id}/recommendations)
now surfaces draft jobs in addition to published ones — mirroring
``marketplace_service.scan_candidate_for_top_jobs`` — while keeping published as
the higher-priority signal so actionable openings rank first.

These are pure tests (no DB / Qdrant): they pin the eligible-status set and the
ordering key used to re-rank breakdowns before the top_k cap.
"""

from app.api.recommendations import (
    _RECOMMENDABLE_STATUSES,
    _recommendation_rank_key,
)
from app.models.job import JobStatus


def test_recommendable_statuses_are_draft_and_published():
    assert set(_RECOMMENDABLE_STATUSES) == {JobStatus.draft, JobStatus.published}
    # Closed jobs must never be recommended.
    assert JobStatus.closed not in _RECOMMENDABLE_STATUSES


def test_published_outranks_draft_even_with_lower_score():
    # A draft scores far higher, but published is the higher-priority signal:
    # the smaller sort key (published) must come first.
    published = _recommendation_rank_key(50.0, JobStatus.published)
    draft = _recommendation_rank_key(90.0, JobStatus.draft)
    assert published < draft


def test_within_same_status_higher_score_first():
    high = _recommendation_rank_key(90.0, JobStatus.published)
    low = _recommendation_rank_key(40.0, JobStatus.published)
    assert high < low


def test_sort_yields_published_block_then_drafts_each_by_score():
    rows = [
        (30.0, JobStatus.draft),
        (80.0, JobStatus.published),
        (95.0, JobStatus.draft),
        (60.0, JobStatus.published),
    ]
    ordered = sorted(rows, key=lambda r: _recommendation_rank_key(r[0], r[1]))
    assert ordered == [
        (80.0, JobStatus.published),
        (60.0, JobStatus.published),
        (95.0, JobStatus.draft),
        (30.0, JobStatus.draft),
    ]


def test_missing_status_is_treated_as_non_published():
    # Defensive: if a job_id falls out of the status map, it sorts as a draft
    # (priority bucket 1), never ahead of a real published job.
    assert _recommendation_rank_key(99.0, None)[0] == 1
