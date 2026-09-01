"""Tests for the candidate-search evaluation harness (Phase 0).

The harness is loaded by file path so importing it does NOT pull in the app /
DB engine (which needs Python 3.12 + Postgres). These tests validate:

* the metric math (recall/precision/mrr/dup/percentile),
* the golden fixture is well-formed and self-consistent,
* the reference oracle reproduces every labelled `expected_ids` exactly.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_MODULE_PATH = (
    Path(__file__).resolve().parent.parent / "scripts" / "eval_candidate_search.py"
)
_spec = importlib.util.spec_from_file_location("eval_candidate_search", _MODULE_PATH)
assert _spec and _spec.loader
ev = importlib.util.module_from_spec(_spec)
# Register before exec so dataclasses can resolve annotations via sys.modules.
sys.modules[_spec.name] = ev
_spec.loader.exec_module(ev)


# --------------------------------------------------------------------------- #
# Metric math
# --------------------------------------------------------------------------- #
class TestMetrics:
    def test_recall_full_and_partial(self):
        assert ev.recall_at_k([1, 2, 3], [1, 2, 3], 20) == 1.0
        assert ev.recall_at_k([1, 4, 5], [1, 2], 20) == 0.5
        assert ev.recall_at_k([], [1, 2], 20) == 0.0

    def test_recall_vacuous_when_no_positives(self):
        assert ev.recall_at_k([], [], 20) == 1.0

    def test_recall_respects_k_cutoff(self):
        assert ev.recall_at_k([9, 9, 9, 1], [1], 3) == 0.0
        assert ev.recall_at_k([9, 9, 1], [1], 3) == 1.0

    def test_precision(self):
        assert ev.precision_at_k([1, 2], [1, 2], 20) == 1.0
        assert ev.precision_at_k([1, 9], [1], 20) == 0.5
        assert ev.precision_at_k([], [], 20) == 1.0
        assert ev.precision_at_k([9], [1], 20) == 0.0

    def test_reciprocal_rank(self):
        assert ev.reciprocal_rank([5, 1, 2], [1]) == pytest.approx(0.5)
        assert ev.reciprocal_rank([1, 2], [1]) == 1.0
        assert ev.reciprocal_rank([7, 8], [1]) == 0.0

    def test_duplicate_rate(self):
        assert ev.duplicate_rate([1, 2, 3]) == 0.0
        assert ev.duplicate_rate([1, 1, 2, 2]) == 0.5
        assert ev.duplicate_rate([]) == 0.0

    def test_percentile(self):
        assert ev.percentile([], 50) == 0.0
        assert ev.percentile([10], 95) == 10
        assert ev.percentile([1, 2, 3, 4], 50) == pytest.approx(2.5)
        assert ev.percentile([1, 2, 3, 4], 100) == 4


# --------------------------------------------------------------------------- #
# Golden fixture + reference oracle
# --------------------------------------------------------------------------- #
class TestGoldenDataset:
    def setup_method(self):
        self.dataset = ev.load_dataset()
        self.runner = ev.make_reference_runner(self.dataset.candidates)

    def test_fixture_loads_and_has_content(self):
        assert len(self.dataset.candidates) >= 10
        assert len(self.dataset.queries) >= 8

    def test_candidate_ids_are_unique(self):
        ids = [c["id"] for c in self.dataset.candidates]
        assert len(ids) == len(set(ids))

    def test_no_personal_emails_or_phones_in_fixture(self):
        # Synthetic-only guardrail: the golden set must never carry PII.
        blob = ev.DEFAULT_FIXTURE.read_text(encoding="utf-8")
        assert "@" not in blob
        assert "+48" not in blob

    def test_expected_ids_reference_real_candidates(self):
        known = {c["id"] for c in self.dataset.candidates}
        for q in self.dataset.queries:
            assert set(q.expected_ids) <= known, q.id

    def test_reference_oracle_reproduces_every_label(self):
        # The oracle must reproduce each query's expected_ids exactly — this is
        # what makes the fixture a trustworthy baseline.
        for q in self.dataset.queries:
            got = self.runner(q.request)
            assert got == sorted(q.expected_ids), (
                f"{q.id}: oracle {got} != labelled {sorted(q.expected_ids)}"
            )

    def test_reference_run_scores_perfectly(self):
        results = ev.evaluate(self.dataset, self.runner)
        summary = ev.aggregate(results)
        assert summary["recall_at_20"] == 1.0
        assert summary["precision_at_20"] == 1.0
        assert summary["zero_result_accuracy"] == 1.0
        assert summary["errors"] == 0

    def test_go_does_not_match_django(self):
        # SEARCH-P0-03 intent: exact skill "Go" must not pull the Django dev.
        got = self.runner({"skills_must": ["Go"]})
        assert 4 not in got  # Tomasz Wójcik (Django, Python)
        assert set(got) == {2, 7}

    def test_hourly_null_rate_is_included(self):
        # SEARCH-P0-01: unknown rate must not be excluded by a rate filter.
        got = self.runner(
            {"skills_must": ["Python"], "rate_hourly_min": 100, "rate_hourly_max": 160}
        )
        assert 7 in got  # Agnieszka has expected_rate_hourly == null
