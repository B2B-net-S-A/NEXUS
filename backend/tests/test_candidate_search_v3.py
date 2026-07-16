"""Contract tests: ``CandidateSearchQueryV3`` ↔ ``CandidateSearchRequest``.

The two properties the DSL migration relies on (see candidate_search_v3.py):
V3 is canonical through the cycle, and legacy round-trips losslessly in its
canonical form (flat ``q_any`` ≡ group 0 of ``any_groups``).
"""

from __future__ import annotations

from datetime import date

from app.models.candidate import AvailabilityStatus, CandidateStatus
from app.schemas.candidate_search import CandidateSearchRequest, LanguageRequirement
from app.schemas.candidate_search_v3 import (
    CandidateSearchQueryV3,
    SoftPreference,
    from_legacy,
    to_legacy,
)


def full_request() -> CandidateSearchRequest:
    return CandidateSearchRequest(
        q="data engineer",
        q_all=["python"],
        q_any=["react", "vue"],
        q_any_groups=[["java", "kotlin"]],
        q_none=["junior"],
        competence_category_ids=[2, 3],
        skills_must=["Python", "AWS"],
        skills_any=["Kafka"],
        skills_none=["PHP"],
        experience_years_min=5,
        experience_years_max=15,
        languages=[LanguageRequirement(code="EN", min_level="B2")],
        location_cities=["Warszawa", "Kraków"],
        location_countries=["PL"],
        status=[CandidateStatus.active],
        availability_status=[AvailabilityStatus.actively_looking],
        availability_date_before=date(2026, 12, 31),
        notice_period_max=30,
        salary_min=10000,
        salary_max=25000,
        salary_currency="PLN",
        rate_hourly_min=90,
        rate_hourly_max=150,
        sources=["linkedin"],
        tags=["urgent"],
        has_cv=True,
        has_linkedin=False,
        is_champion=True,
        open_to_side_projects=True,
        cv_parsed_after=date(2026, 1, 1),
        exclude_in_job_id=42,
        exclude_blacklisted=True,
        sort="recent",
        page=2,
        page_size=25,
        search_mode="hybrid",
    )


class TestLegacyRoundTrip:
    def test_default_request_round_trips(self):
        req = CandidateSearchRequest()
        assert to_legacy(from_legacy(req)) == req

    def test_full_request_round_trips(self):
        req = full_request()
        assert to_legacy(from_legacy(req)) == req

    def test_q_any_groups_normalise_to_group_zero(self):
        # groups-only input folds into the flat bucket — an EQUIVALENT
        # predicate ((java) AND'd alone) — the one documented normalisation.
        req = CandidateSearchRequest(q_any_groups=[["java"]])
        rt = to_legacy(from_legacy(req))
        assert rt.q_any == ["java"]
        assert rt.q_any_groups == []


class TestV3Canonical:
    def test_v3_survives_the_cycle(self):
        v3 = from_legacy(full_request())
        assert from_legacy(to_legacy(v3)) == v3

    def test_default_v3_survives_the_cycle(self):
        v3 = from_legacy(CandidateSearchRequest())
        assert from_legacy(to_legacy(v3)) == v3


class TestRateUnits:
    def test_units_are_kept_separate(self):
        v3 = from_legacy(full_request())
        units = {r.unit for r in v3.hard_filters.rates}
        assert units == {"hour", "month"}
        hourly = next(r for r in v3.hard_filters.rates if r.unit == "hour")
        monthly = next(r for r in v3.hard_filters.rates if r.unit == "month")
        assert (hourly.min, hourly.max) == (90, 150)
        assert (monthly.min, monthly.max, monthly.currency) == (10000, 25000, "PLN")

    def test_hourly_only_maps_back_to_hourly_fields(self):
        req = CandidateSearchRequest(rate_hourly_max=120)
        rt = to_legacy(from_legacy(req))
        assert rt.rate_hourly_max == 120
        assert rt.salary_max is None


class TestV3OnlyRichnessIsDroppedExplicitly:
    def test_soft_preferences_do_not_leak_into_legacy(self):
        v3 = from_legacy(CandidateSearchRequest(q="x"))
        enriched = v3.model_copy(
            update={"soft_preferences": [SoftPreference(key="aws", weight=0.5)]}
        )
        legacy = to_legacy(enriched)
        # legacy cannot express soft preferences — projection drops them...
        assert to_legacy(v3) == legacy
        # ...and re-upgrading yields a V3 without them (documented lossy edge).
        assert from_legacy(legacy).soft_preferences == []

    def test_version_marker(self):
        assert CandidateSearchQueryV3().version == 3
