"""Pure-function unit tests for the candidate-risk service.

Tests the categorization + level math without any DB. The full integration
flow (compute_risk → DB query → UPSERT) is exercised by the live-server
integration test in test_pipeline.py:test_withdrawn_requires_reason.
"""

from app.models.candidate_risk import CandidateOfferResponse, RiskLevel
from app.models.recruitment_pipeline import PipelineStage
from app.services.candidate_risk import _categorize, _level_from_score


# ── _level_from_score ─────────────────────────────────────────────────────────


def test_level_low_at_zero() -> None:
    assert _level_from_score(0) == RiskLevel.low


def test_level_low_at_two() -> None:
    assert _level_from_score(2) == RiskLevel.low


def test_level_medium_at_three() -> None:
    assert _level_from_score(3) == RiskLevel.medium


def test_level_medium_at_nine() -> None:
    assert _level_from_score(9) == RiskLevel.medium


def test_level_high_at_ten() -> None:
    assert _level_from_score(10) == RiskLevel.high


def test_level_high_at_twenty() -> None:
    assert _level_from_score(20) == RiskLevel.high


# ── _categorize ───────────────────────────────────────────────────────────────


def test_categorize_early_from_new() -> None:
    assert _categorize(PipelineStage.new, None) == "early"


def test_categorize_early_from_screening() -> None:
    assert _categorize(PipelineStage.screening, None) == "early"


def test_categorize_early_from_verified() -> None:
    assert _categorize(PipelineStage.verified, None) == "early"


def test_categorize_interview_from_interview() -> None:
    assert _categorize(PipelineStage.interview, None) == "interview"


def test_categorize_interview_from_cv_sent() -> None:
    assert _categorize(PipelineStage.cv_sent, None) == "interview"


def test_categorize_interview_from_client_interview() -> None:
    assert _categorize(PipelineStage.client_interview, None) == "interview"


def test_categorize_post_accept_requires_declined() -> None:
    """post_accept tylko gdy candidate explicitly odmówił po akcepcie."""
    assert (
        _categorize(PipelineStage.acceptance, CandidateOfferResponse.declined)
        == "post_accept"
    )
    assert (
        _categorize(PipelineStage.negotiation, CandidateOfferResponse.declined)
        == "post_accept"
    )
    assert (
        _categorize(PipelineStage.onboarding, CandidateOfferResponse.declined)
        == "post_accept"
    )


def test_categorize_post_accept_skipped_without_declined() -> None:
    """Wycofanie z acceptance bez 'declined' nie liczy się jako post_accept."""
    assert _categorize(PipelineStage.acceptance, None) is None
    assert (
        _categorize(PipelineStage.acceptance, CandidateOfferResponse.accepted)
        is None
    )
    assert (
        _categorize(PipelineStage.acceptance, CandidateOfferResponse.pending)
        is None
    )


def test_categorize_terminal_stages_are_none() -> None:
    """Wycofanie z hired/rejected/withdrawn nie ma sensu — None."""
    assert _categorize(PipelineStage.hired, None) is None
    assert _categorize(PipelineStage.rejected, None) is None
    assert _categorize(PipelineStage.withdrawn, None) is None


def test_categorize_no_previous_stage_is_none() -> None:
    """Bez previous stage (pierwszy ruch = withdrawn) nie kategoryzujemy."""
    assert _categorize(None, None) is None
    assert _categorize(None, CandidateOfferResponse.declined) is None


# ── Score arithmetic via levels ───────────────────────────────────────────────


def test_score_2_early_dropouts_is_low() -> None:
    """2 × early (1pt) = 2pt → low."""
    assert _level_from_score(2 * 1) == RiskLevel.low


def test_score_1_early_1_interview_is_medium() -> None:
    """1 × early (1pt) + 1 × interview (3pt) = 4pt → medium."""
    assert _level_from_score(1 * 1 + 1 * 3) == RiskLevel.medium


def test_score_3_interviews_is_medium() -> None:
    """3 × interview = 9pt → medium (boundary)."""
    assert _level_from_score(3 * 3) == RiskLevel.medium


def test_score_one_post_accept_is_high() -> None:
    """1 × post_accept (10pt) = 10pt → high."""
    assert _level_from_score(1 * 10) == RiskLevel.high


def test_score_combined_scenario_high() -> None:
    """1 early + 2 interview + 1 post_accept = 1 + 6 + 10 = 17pt → high."""
    assert _level_from_score(1 + 6 + 10) == RiskLevel.high
