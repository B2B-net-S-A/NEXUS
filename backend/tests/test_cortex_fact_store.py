"""Unit tests for Cortex fact-store normalization (pure, no DB).

Covers the exact-token normalization contract from docs/cortex/00-discovery.md:
alias resolution, canonical self-match, parenthetical stripping, the 'go'
alias safety (exact tokens only — no substring scanning), and value clamps.
"""

from __future__ import annotations

import pytest

from app.services.cortex.extractor_traffit import split_traffit_technologie
from app.services.cortex.fact_store import (
    Taxonomy,
    clamp_confidence,
    clamp_level,
    clamp_years,
    normalize_token,
)


@pytest.fixture
def taxonomy() -> Taxonomy:
    return Taxonomy(
        alias_to_canonical={
            "python3": "python",
            "python": "python",
            "go": "go",
            "golang": "go",
            ".net": ".net",
            "dotnet": ".net",
            "ci/cd": "ci/cd",
        },
        canonical_to_id={"python": 1, "go": 2, ".net": 3, "ci/cd": 4},
    )


class TestNormalizeToken:
    def test_alias_resolves_to_canonical_id(self, taxonomy):
        assert normalize_token(taxonomy, "python3") == (1, "python3")
        assert normalize_token(taxonomy, "golang") == (2, "golang")

    def test_canonical_matches_itself_case_insensitive(self, taxonomy):
        assert normalize_token(taxonomy, ".NET")[0] == 3
        assert normalize_token(taxonomy, "Python")[0] == 1

    def test_trailing_parenthetical_is_stripped(self, taxonomy):
        skill_id, token = normalize_token(taxonomy, "Python (3 lata)")
        assert skill_id == 1
        assert token == "python"

    def test_unmatched_returns_none_with_token(self, taxonomy):
        skill_id, token = normalize_token(taxonomy, "Jakiś Framework")
        assert skill_id is None
        assert token == "jakiś framework"

    def test_go_matches_only_as_exact_token(self, taxonomy):
        # Exact CSV token → match; prose-like token → no substring hit.
        assert normalize_token(taxonomy, "go")[0] == 2
        assert normalize_token(taxonomy, "go to market")[0] is None

    def test_compound_names_survive(self, taxonomy):
        assert normalize_token(taxonomy, "CI/CD")[0] == 4

    def test_whitespace_and_dots_trimmed(self, taxonomy):
        assert normalize_token(taxonomy, "  python.  ")[0] == 1

    def test_empty_token(self, taxonomy):
        assert normalize_token(taxonomy, "   ") == (None, "")


class TestSplitTraffitTechnologie:
    def test_splits_on_commas_semicolons_newlines(self):
        assert split_traffit_technologie("Java, Spring; Kafka\nDocker") == [
            "Java",
            "Spring",
            "Kafka",
            "Docker",
        ]

    def test_preserves_original_casing_for_evidence(self):
        assert split_traffit_technologie("SAP TM, ABAP") == ["SAP TM", "ABAP"]

    def test_slash_compounds_not_split(self):
        assert split_traffit_technologie("CI/CD, TCP/IP") == ["CI/CD", "TCP/IP"]

    def test_empty_input(self):
        assert split_traffit_technologie("") == []
        assert split_traffit_technologie(None) == []  # type: ignore[arg-type]


class TestClamps:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("junior", "junior"),
            ("MID", "mid"),
            ("senior", "senior"),
            ("expert", None),
            (None, None),
            ("", None),
        ],
    )
    def test_clamp_level(self, raw, expected):
        assert clamp_level(raw) == expected

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [(5, 5), (0, 0), (-3, 0), (99, 40), (None, None), ("7", 7), ("x", None)],
    )
    def test_clamp_years(self, raw, expected):
        assert clamp_years(raw) == expected

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [(0.9, 0.9), (0.0, 0.1), (5.0, 1.0), ("bad", 0.5)],
    )
    def test_clamp_confidence(self, raw, expected):
        assert clamp_confidence(raw) == expected
