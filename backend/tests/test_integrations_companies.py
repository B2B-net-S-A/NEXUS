"""Company-people integration endpoint — matching logic (ATLAS integration).

Pure unit tests against the normaliser and the relationship resolver; no DB
and no live FastAPI client. The DB-facing parts (`_resolve_client`, the route)
are thin wiring over predicates already covered by the candidate search tests.

The behaviour worth pinning here is the one the endpoint exists to guarantee:
a substring prefilter hit that does NOT survive canonical comparison must be
dropped. That is what keeps "IT Kontrakt" out of a lookup for "IT".
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.api.integrations_companies import (
    _match_experience,
    _normalize_nip,
    normalize_company_name,
)


def _candidate(
    experience=None,
    linkedin_current_company=None,
    linkedin_current_title=None,
    linkedin_current_started_at=None,
):
    """Minimal stand-in — `_match_experience` only touches these attributes."""
    return SimpleNamespace(
        experience=experience,
        linkedin_current_company=linkedin_current_company,
        linkedin_current_title=linkedin_current_title,
        linkedin_current_started_at=linkedin_current_started_at,
    )


class TestNormalizeCompanyName:
    """Must stay byte-for-byte compatible with ATLAS company_service."""

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("Nordea Bank Abp Sp. z o.o.", "nordea bank abp"),
            ("Żabka Polska S.A.", "zabka polska"),
            ("Comarch S.A.", "comarch"),
            ("Asseco Poland SA", "asseco poland"),
            ("  ACME   Ltd. ", "acme"),
            ("Łukasiewicz — PIT", "lukasiewicz pit"),
            ("", ""),
        ],
    )
    def test_canonical_forms(self, raw, expected):
        assert normalize_company_name(raw) == expected

    def test_diacritics_and_legal_form_collapse_to_same_key(self):
        assert normalize_company_name("Żabka Polska S.A.") == normalize_company_name(
            "Zabka Polska"
        )


class TestNormalizeNip:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("123-456-78-90", "1234567890"),
            ("PL 1234567890", "1234567890"),
            (None, ""),
            ("", ""),
        ],
    )
    def test_digits_only(self, raw, expected):
        assert _normalize_nip(raw) == expected


class TestMatchExperience:
    def test_linkedin_current_company_wins_as_current(self):
        candidate = _candidate(
            experience=[],
            linkedin_current_company="Nordea Bank Abp",
            linkedin_current_title="Senior Java Developer",
        )
        relationship, entry = _match_experience(candidate, {"nordea bank abp"})
        assert relationship == "current"
        assert entry["role"] == "Senior Java Developer"
        assert entry["end"] is None

    def test_end_null_entry_is_current(self):
        candidate = _candidate(
            experience=[
                {"company": "Comarch", "role": "Dev", "start": "2018", "end": "2020"},
                {"company": "Nordea", "role": "Lead", "start": "2020", "end": None},
            ]
        )
        relationship, entry = _match_experience(candidate, {"nordea"})
        assert relationship == "current"
        assert entry["role"] == "Lead"

    def test_closed_entry_is_past(self):
        candidate = _candidate(
            experience=[
                {
                    "company": "Comarch S.A.",
                    "role": "Dev",
                    "start": "2018",
                    "end": "2020",
                },
            ]
        )
        relationship, entry = _match_experience(candidate, {"comarch"})
        assert relationship == "past"
        assert entry["company"] == "Comarch S.A."

    def test_current_beats_past_for_same_company(self):
        """Rehire: the open stint must win over the closed one."""
        candidate = _candidate(
            experience=[
                {"company": "Nordea", "role": "Junior", "start": "2015", "end": "2017"},
                {"company": "Nordea", "role": "Lead", "start": "2021", "end": None},
            ]
        )
        relationship, entry = _match_experience(candidate, {"nordea"})
        assert relationship == "current"
        assert entry["role"] == "Lead"

    def test_substring_prefilter_hit_is_rejected(self):
        """The whole point of the exact pass.

        The SQL prefilter uses LIKE '%it%' and would surface this candidate for
        a lookup of "IT"; canonical comparison must throw it away rather than
        report a match to a sales rep.
        """
        candidate = _candidate(
            experience=[{"company": "IT Kontrakt", "role": "Dev", "end": "2020"}]
        )
        relationship, entry = _match_experience(candidate, {"it"})
        assert relationship is None
        assert entry is None

    def test_legal_form_difference_still_matches(self):
        candidate = _candidate(
            experience=[{"company": "Żabka Polska S.A.", "role": "Dev", "end": "2021"}]
        )
        relationship, _ = _match_experience(candidate, {"zabka polska"})
        assert relationship == "past"

    @pytest.mark.parametrize("bad", [None, "not-a-list", {"company": "X"}, 42])
    def test_non_array_experience_is_tolerated(self, bad):
        """Legacy rows hold scalars/objects — must not raise."""
        candidate = _candidate(experience=bad)
        assert _match_experience(candidate, {"nordea"}) == (None, None)

    def test_malformed_entries_are_skipped(self):
        candidate = _candidate(
            experience=[
                "junk",
                {"role": "no company key"},
                {"company": None},
                {"company": 123},
                {"company": "Nordea", "role": "Dev", "end": "2020"},
            ]
        )
        relationship, entry = _match_experience(candidate, {"nordea"})
        assert relationship == "past"
        assert entry["role"] == "Dev"

    def test_empty_string_end_counts_as_current(self):
        """CV parsers emit "" as often as null for an open-ended stint.

        Od 2026-09-16 pusty koniec liczy się jako „obecnie" tylko przy dacie
        początku — wpis bez ŻADNEJ daty to `unknown` (patrz TestUnknownPeriod).
        """
        candidate = _candidate(
            experience=[
                {"company": "Nordea", "role": "Lead", "start": "2021", "end": ""}
            ]
        )
        relationship, _ = _match_experience(candidate, {"nordea"})
        assert relationship == "current"

    def test_matches_any_of_several_aliases(self):
        candidate = _candidate(
            experience=[{"company": "Nordea Bank Abp", "role": "Dev", "end": "2020"}]
        )
        relationship, _ = _match_experience(
            candidate, {"nordea", "nordea bank abp", "nordea bank"}
        )
        assert relationship == "past"


class TestUnknownPeriod:
    """Wpis bez żadnej daty to „okres nieznany", nie „pracuje tam teraz".

    ~44k wierszy z Traffita ma `experience` z gołej listy pracodawców: każda
    firma bez `start` i bez `end`. `end IS NULL` = „obecna praca" jest tam
    artefaktem importu — do 2026-09-16 taki kandydat lądował w „current" dla
    KAŻDEJ firmy ze swojego CV.
    """

    def test_undated_entry_is_unknown(self):
        candidate = _candidate(
            experience=[
                {"company": "Sii", "role": None, "start": None, "end": None},
                {"company": "Shoper", "role": None, "start": None, "end": None},
            ]
        )
        relationship, entry = _match_experience(candidate, {"shoper"})
        assert relationship == "unknown"
        assert entry["company"] == "Shoper"

    def test_empty_end_string_without_start_is_unknown(self):
        candidate = _candidate(
            experience=[{"company": "Shoper", "role": "Dev", "start": "", "end": ""}]
        )
        assert _match_experience(candidate, {"shoper"})[0] == "unknown"

    def test_open_ended_entry_with_start_is_current(self):
        candidate = _candidate(
            experience=[
                {"company": "Shoper", "role": "Dev", "start": "2022-03", "end": None}
            ]
        )
        assert _match_experience(candidate, {"shoper"})[0] == "current"

    @pytest.mark.parametrize("end", ["present", "obecnie", " Obecnie ", "current"])
    def test_present_word_without_start_is_current(self, end):
        """CV mówi wprost, że praca trwa — brak daty początku tego nie unieważnia."""
        candidate = _candidate(
            experience=[{"company": "Shoper", "role": "Dev", "start": None, "end": end}]
        )
        assert _match_experience(candidate, {"shoper"})[0] == "current"

    def test_dated_past_beats_undated_duplicate(self):
        """Wiemy, że się skończyło — pusty wpis dla tej samej firmy tego nie cofa."""
        candidate = _candidate(
            experience=[
                {"company": "Shoper", "role": None, "start": None, "end": None},
                {
                    "company": "Shoper S.A.",
                    "role": "Dev",
                    "start": "2019",
                    "end": "2021",
                },
            ]
        )
        relationship, entry = _match_experience(candidate, {"shoper"})
        assert relationship == "past"
        assert entry["role"] == "Dev"

    def test_current_beats_unknown(self):
        candidate = _candidate(
            experience=[
                {"company": "Shoper", "role": None, "start": None, "end": None},
                {
                    "company": "Shoper",
                    "role": "Lead",
                    "start": "2023",
                    "end": "present",
                },
            ]
        )
        assert _match_experience(candidate, {"shoper"})[0] == "current"

    def test_linkedin_still_wins_over_undated_cv(self):
        candidate = _candidate(
            experience=[
                {"company": "Shoper", "role": None, "start": None, "end": None}
            ],
            linkedin_current_company="Shoper S.A.",
        )
        assert _match_experience(candidate, {"shoper", "shoper s.a."})[0] == "current"
