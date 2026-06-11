"""Unit tests for `similar_job_notify` (szybkie przepinanie, Faza 1).

Pure-function coverage of the alert decision (`build_alert`) and message
rendering (`build_message`) — no DB. The IO wrapper
(`notify_similar_job_candidates`) is exercised indirectly on prod via the
POST /jobs background task; its building blocks (fetch_historical_candidates,
emit) have their own suites.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.models.recruitment_pipeline import PipelineStage
from app.services.similar_job_candidates import (
    HistoricalCandidate,
    HistoricalSource,
    SimilarJobRef,
)
from app.services.similar_job_notify import build_alert, build_message


def _source(
    *,
    job_id: int = 100,
    stage: PipelineStage,
    client_id: int | None = None,
    similarity: float = 0.8,
) -> HistoricalSource:
    return HistoricalSource(
        job_id=job_id,
        job_title=f"Job {job_id}",
        stage=stage,
        similarity=similarity,
        months_ago=1.0,
        moved_at=datetime.now(timezone.utc),
        stage_weight=0.5,
        contribution=0.4,
        client_id=client_id,
    )


def _candidate(
    *,
    candidate_id: int,
    tier: str = "A",
    stage: PipelineStage = PipelineStage.cv_sent,
    same_client: bool = False,
    rejected_by_same_client: bool = False,
    client_id: int | None = None,
) -> HistoricalCandidate:
    return HistoricalCandidate(
        candidate_id=candidate_id,
        historical_score=1.0,
        tier=tier,  # type: ignore[arg-type]
        negative_signal=rejected_by_same_client,
        sources=(_source(stage=stage, client_id=client_id),),
        same_client=same_client,
        rejected_by_same_client=rejected_by_same_client,
    )


def _refs_tier_a() -> list[SimilarJobRef]:
    return [
        SimilarJobRef(job_id=100, title="Java Dev — Bank", similarity=0.87, tier="A")
    ]


@pytest.mark.unit
def test_build_alert_fires_for_client_facing_tier_a_candidate() -> None:
    ranked = [_candidate(candidate_id=1, stage=PipelineStage.cv_sent)]
    alert = build_alert(ranked, _refs_tier_a())
    assert alert is not None
    assert alert.candidate_ids == (1,)
    assert alert.top_similar_title == "Java Dev — Bank"
    assert alert.top_similarity == pytest.approx(0.87)


@pytest.mark.unit
def test_build_alert_skips_screening_only_history() -> None:
    """Screening/interview wewnętrzne ≠ "poszedł do klienta" — bez alertu."""
    ranked = [_candidate(candidate_id=1, stage=PipelineStage.screening)]
    assert build_alert(ranked, _refs_tier_a()) is None


@pytest.mark.unit
def test_build_alert_skips_tier_b_candidates() -> None:
    ranked = [_candidate(candidate_id=1, tier="B", stage=PipelineStage.hired)]
    refs = [
        SimilarJobRef(job_id=100, title="Job", similarity=0.60, tier="B"),
    ]
    assert build_alert(ranked, refs) is None


@pytest.mark.unit
def test_build_alert_excludes_rejected_by_same_client() -> None:
    ranked = [
        _candidate(
            candidate_id=1,
            stage=PipelineStage.cv_sent,
            same_client=True,
            rejected_by_same_client=True,
        )
    ]
    assert build_alert(ranked, _refs_tier_a()) is None


@pytest.mark.unit
def test_build_alert_counts_same_client_candidates() -> None:
    ranked = [
        _candidate(candidate_id=1, stage=PipelineStage.cv_sent, same_client=True),
        _candidate(candidate_id=2, stage=PipelineStage.hired),
    ]
    alert = build_alert(ranked, _refs_tier_a())
    assert alert is not None
    assert set(alert.candidate_ids) == {1, 2}
    assert alert.same_client_count == 1


@pytest.mark.unit
def test_build_message_mentions_counts_and_similarity() -> None:
    ranked = [
        _candidate(candidate_id=1, stage=PipelineStage.cv_sent, same_client=True),
        _candidate(candidate_id=2, stage=PipelineStage.hired),
    ]
    alert = build_alert(ranked, _refs_tier_a())
    assert alert is not None
    msg = build_message("Senior Java", alert, available_count=1)
    assert "Senior Java" in msg
    assert "Java Dev — Bank" in msg
    assert "87%" in msg
    assert "2 kandydat" in msg
    assert "1 u tego klienta" in msg
    assert "1 oznaczonych jako dostępni" in msg
