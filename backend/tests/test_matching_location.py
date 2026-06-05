"""Unit tests for location-aware AI matching helpers (app.api.matching).

Covers the two shapes of ``candidate.location`` seen in production:
  • structured JSON blob from Traffit/TalentRadar imports (~99% of located rows)
  • plain text ("Warszawa", "Kraków / remote")
and the request-side fallback / substring tolerance used to filter matches.
"""

from __future__ import annotations

import pytest

from app.api.matching import _location_matches, _location_tokens

WARSAW_BLOB = (
    '{"latitude":"52.235840","longitude":"21.011959","locality":"Warszawa",'
    '"iso":"pl","region1":"Mazowieckie","region2":"Warszawa",'
    '"region3":"Warszawa","postcode":"00-002","country":"Polska"}'
)
GDANSK_BLOB = (
    '{"latitude":"54.337570","longitude":"18.719660","locality":"Gdańsk",'
    '"iso":"pl","region1":"Pomorskie","country":"Polska"}'
)


@pytest.mark.unit
class TestLocationTokens:
    def test_json_blob_extracts_place_tokens(self) -> None:
        tokens = _location_tokens(WARSAW_BLOB)
        assert "warszawa" in tokens
        assert "mazowieckie" in tokens
        assert "polska" in tokens
        # Coordinates / postcode are not place tokens.
        assert "52.235840" not in tokens
        assert "00-002" not in tokens

    def test_plain_text_single(self) -> None:
        assert _location_tokens("Warszawa") == {"warszawa"}

    def test_plain_text_split_on_separators(self) -> None:
        assert _location_tokens("Kraków / remote") == {"kraków", "remote"}
        assert _location_tokens("Gdańsk, Pomorskie") == {"gdańsk", "pomorskie"}

    @pytest.mark.parametrize("raw", [None, "", "   ", "{not valid json"])
    def test_empty_or_unparseable(self, raw) -> None:
        # Unparseable JSON ("{...") yields no tokens; empty inputs too.
        result = _location_tokens(raw)
        if raw == "{not valid json":
            assert result == set()
        else:
            assert result == set()


@pytest.mark.unit
class TestLocationMatches:
    def test_no_request_tokens_passes_everyone(self) -> None:
        # Empty filter → no filtering (legacy behaviour preserved).
        assert _location_matches(set(), WARSAW_BLOB) is True
        assert _location_matches(set(), None) is True

    def test_blob_candidate_matches_city_request(self) -> None:
        req = _location_tokens("Warszawa")
        assert _location_matches(req, WARSAW_BLOB) is True

    def test_blob_candidate_rejects_other_city(self) -> None:
        req = _location_tokens("Warszawa")
        assert _location_matches(req, GDANSK_BLOB) is False

    def test_candidate_without_location_excluded_under_active_filter(self) -> None:
        req = _location_tokens("Warszawa")
        assert _location_matches(req, None) is False
        assert _location_matches(req, "") is False

    def test_region_request_matches_blob(self) -> None:
        req = _location_tokens("Mazowieckie")
        assert _location_matches(req, WARSAW_BLOB) is True

    def test_substring_tolerance_both_directions(self) -> None:
        # request "warszawa" vs candidate "warszawa, mazowieckie"
        assert _location_matches({"warszawa"}, "Warszawa, Mazowieckie") is True
        # request "warszawa, mazowieckie" vs candidate "warszawa"
        assert _location_matches({"warszawa", "mazowieckie"}, "Warszawa") is True

    def test_plain_text_candidate_match(self) -> None:
        assert _location_matches({"warszawa"}, "Warszawa") is True
        assert _location_matches({"gdańsk"}, "Warszawa") is False
