from types import SimpleNamespace

import pytest

from scripts.eval_full_search_quality import (
    evaluate,
    prepare_labels,
    request_data_fingerprint,
)


def run(size=3):
    return SimpleNamespace(
        id="r",
        state="complete",
        population_size=size,
        request_fingerprint="algorithm-v1",
        request_context={
            "job_data": {"id": 7, "title": "Python"},
            "weights": {"semantic": 70},
        },
    )


def row(cid, score=80, **kwargs):
    return SimpleNamespace(
        candidate_id=cid,
        candidate_version="v1",
        state=kwargs.get("state", "evaluated"),
        eligible=kwargs.get("eligible", True),
        fit_score=score,
        measurement="measured" if score is not None else "missing_index",
    )


def labels(search, verdicts):
    return {
        "schema": "search-quality-labels-v1",
        "request_data_fingerprint": request_data_fingerprint(search),
        "judgments": [
            {
                "candidate_id": cid,
                "candidate_version": "v1",
                "verdict": verdict,
                "reviewer": "Human reviewer",
                "reviewed_at": "2026-09-09T10:00:00+00:00",
            }
            for cid, verdict in verdicts.items()
        ],
    }


def test_unknown_top20_is_not_counted_as_a_bad_candidate():
    search = run()
    report = evaluate(
        search,
        [row(9), row(2), row(5)],
        labels(search, {2: "relevant", 5: "not_relevant"}),
    )
    assert report["top20_candidate_ids"] == [2, 5, 9]
    assert report["precision_at_20"] is None
    assert report["precision_among_judged_top20"] == 0.5
    assert report["top20_judgment_coverage"] == 2 / 3
    assert not report["quality_review_complete"]
    assert "Human reviewer" not in str(report)


def test_recall_distinguishes_full_retrieval_from_top20():
    search = run(30)
    records = [row(cid, 100 - cid) for cid in range(1, 31)]
    report = evaluate(search, records, labels(search, {1: "relevant", 30: "relevant"}))
    assert report["known_positive_recall_at_20"] == 0.5
    assert report["known_positive_recall_all_results"] == 1


def test_filter_loss_and_partial_failure_remain_visible():
    search = run()
    search.state = "partial"
    report = evaluate(
        search,
        [row(1, None), row(2, None, eligible=False), row(3, None, state="failed")],
        labels(search, {1: "relevant", 2: "relevant", 3: "relevant", 4: "relevant"}),
    )
    assert report["known_positive_recall_all_results"] == 0.25
    assert report["known_positive_excluded"] == 1
    assert report["known_positive_outside_population"] == 1
    assert report["missing_positive_candidate_ids"] == [2, 3, 4]
    assert not report["ranking_complete"] and not report["coverage_complete"]
    assert not report["quality_review_complete"]


def test_frozen_labels_allow_new_algorithm_but_reject_changed_facts():
    search = run(1)
    frozen = labels(search, {1: "relevant"})
    search.request_fingerprint = "algorithm-v2"
    search.request_context["weights"] = {"semantic": 60}
    assert evaluate(search, [row(1)], frozen)["quality_review_complete"]
    search.request_context["job_data"]["title"] = "Java"
    with pytest.raises(ValueError, match="different request facts"):
        evaluate(search, [row(1)], frozen)


def test_changed_candidate_and_duplicate_judgments_are_rejected():
    search = run(1)
    frozen = labels(search, {1: "relevant"})
    record = row(1)
    record.candidate_version = "v2"
    with pytest.raises(ValueError, match="candidate version"):
        evaluate(search, [record], frozen)
    frozen["judgments"] *= 2
    with pytest.raises(ValueError, match="duplicate judgment"):
        evaluate(search, [row(1)], frozen)


def test_review_sheet_includes_known_candidate_beyond_top20_without_invented_labels():
    search = run(30)
    records = [row(cid, 100 - cid) for cid in range(1, 31)]
    sheet = prepare_labels(search, records, [30])
    assert [j["candidate_id"] for j in sheet["judgments"]] == list(range(1, 21)) + [30]
    assert all(
        j["verdict"] == "unknown" and j["reviewer"] == "" for j in sheet["judgments"]
    )
    with pytest.raises(ValueError):
        evaluate(search, records, sheet)
