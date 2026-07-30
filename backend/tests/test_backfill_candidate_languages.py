from __future__ import annotations

import app.models  # noqa: F401

from app.models.candidate_language import CandidateLanguage
from app.services.candidate_language_writer import normalize_language_payload
from scripts.backfill_candidate_languages import parse_args, parity_matches


def test_backfill_is_dry_run_by_default():
    args = parse_args([])

    assert args.apply is False
    assert args.resume is False


def test_parity_compares_normalized_facts_not_display_spelling():
    expected, _ = normalize_language_payload(
        [{"code": "EN", "name": "English", "level": "B2"}]
    )
    actual = [
        CandidateLanguage(
            candidate_id=1,
            language_code="en",
            language_name="Angielski",
            cefr_level="B2",
            is_native=False,
            is_level_unknown=False,
            provenance="legacy",
            manual_lock=False,
            version=1,
        )
    ]

    assert parity_matches(expected, actual) is True


def test_parity_reports_unknown_vs_cefr_difference():
    expected, _ = normalize_language_payload(
        [{"code": "EN", "name": "English", "level": "advanced"}]
    )
    actual = [
        CandidateLanguage(
            candidate_id=1,
            language_code="en",
            language_name="English",
            cefr_level="C1",
            is_native=False,
            is_level_unknown=False,
            provenance="legacy",
            manual_lock=False,
            version=1,
        )
    ]

    assert parity_matches(expected, actual) is False
