"""Unit tests for ``app.services.structured_candidate_search``.

Pure SQL-clause inspection — no DB roundtrip. Each test compiles the
clause(s) to a parameterless string and asserts on substrings; this catches
clause shape regressions without needing fixtures or a postgres connection.
"""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import and_
from sqlalchemy.dialects import postgresql

from app.models.candidate import AvailabilityStatus, CandidateStatus
from app.schemas.candidate_search import (
    CandidateSearchRequest,
    LanguageRequirement,
)
from app.services.structured_candidate_search import (
    build_filter_groups,
    build_structured_filter,
)


def _compile(clauses):
    """Render the AND-of-clauses as a string for substring assertions."""
    if not clauses:
        return ""
    return str(
        and_(*clauses).compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )


class TestEmptyRequest:
    def test_no_clauses_when_all_default(self):
        req = CandidateSearchRequest()
        assert build_structured_filter(req) == []


class TestCompetenceCategory:
    def test_single_id_emits_IN_clause(self):
        req = CandidateSearchRequest(competence_category_ids=[2])
        sql = _compile(build_structured_filter(req))
        assert "competence_category_id" in sql
        assert "IN (2)" in sql or "= 2" in sql

    def test_multiple_ids_in_list(self):
        req = CandidateSearchRequest(competence_category_ids=[1, 2, 3])
        sql = _compile(build_structured_filter(req))
        assert "competence_category_id" in sql
        assert "1" in sql and "2" in sql and "3" in sql


class TestSkills:
    def test_skills_must_emits_one_clause_per_skill(self):
        req = CandidateSearchRequest(skills_must=["Python", "FastAPI"])
        clauses = build_structured_filter(req)
        # one clause per must-skill
        assert len(clauses) == 2
        sql = _compile(clauses)
        assert "Python" in sql and "FastAPI" in sql

    def test_skills_any_emits_single_OR_clause(self):
        req = CandidateSearchRequest(skills_any=["React", "Vue", "Angular"])
        clauses = build_structured_filter(req)
        assert len(clauses) == 1
        sql = _compile(clauses)
        assert "OR" in sql.upper()
        assert "React" in sql and "Vue" in sql and "Angular" in sql

    def test_skills_none_emits_NOT_per_skill(self):
        req = CandidateSearchRequest(skills_none=["junior", "stażysta"])
        clauses = build_structured_filter(req)
        sql = _compile(clauses)
        assert sql.upper().count("NOT") >= 2


class TestExperienceRange:
    def test_min_only(self):
        req = CandidateSearchRequest(experience_years_min=5)
        sql = _compile(build_structured_filter(req))
        assert "years_it_experience" in sql
        assert ">=" in sql

    def test_max_only(self):
        req = CandidateSearchRequest(experience_years_max=10)
        sql = _compile(build_structured_filter(req))
        assert "years_it_experience" in sql
        assert "<=" in sql

    def test_both(self):
        req = CandidateSearchRequest(experience_years_min=5, experience_years_max=10)
        clauses = build_structured_filter(req)
        assert len(clauses) == 2


class TestLanguages:
    def test_language_clause_emits_pattern_or(self):
        req = CandidateSearchRequest(
            languages=[LanguageRequirement(code="EN", min_level="B2")]
        )
        sql = _compile(build_structured_filter(req))
        # Accepted levels for B2: B2, C1, C2, native
        assert "B2" in sql
        assert "C1" in sql
        assert "EN" in sql

    def test_lower_threshold_widens_accepted_levels(self):
        req = CandidateSearchRequest(
            languages=[LanguageRequirement(code="DE", min_level="A2")]
        )
        sql = _compile(build_structured_filter(req))
        # A2 threshold: A2, B1, B2, C1, C2, native
        for lvl in ("A2", "B1", "B2", "C1", "C2"):
            assert lvl in sql


class TestLocation:
    def test_cities_match_city_or_location_columns(self):
        req = CandidateSearchRequest(location_cities=["Warszawa"])
        sql = _compile(build_structured_filter(req))
        assert "city" in sql.lower()
        assert "location" in sql.lower()
        assert "Warszawa" in sql

    def test_countries_uppercased(self):
        req = CandidateSearchRequest(location_countries=["pl", "ua"])
        sql = _compile(build_structured_filter(req))
        assert "PL" in sql and "UA" in sql


class TestStatusFilters:
    def test_candidate_status(self):
        req = CandidateSearchRequest(status=[CandidateStatus.active])
        sql = _compile(build_structured_filter(req))
        assert "status" in sql.lower()
        assert "active" in sql

    def test_availability_status(self):
        req = CandidateSearchRequest(
            availability_status=[AvailabilityStatus.actively_looking]
        )
        sql = _compile(build_structured_filter(req))
        assert "availability_status" in sql.lower()
        assert "actively_looking" in sql


class TestAvailabilityWindow:
    def test_availability_date_before_includes_nulls(self):
        req = CandidateSearchRequest(availability_date_before=date(2026, 12, 31))
        sql = _compile(build_structured_filter(req)).lower()
        assert "availability_date" in sql
        # NULL availability is treated as "available" — clause must allow IS NULL
        assert "is null" in sql

    def test_notice_period_max_includes_nulls(self):
        req = CandidateSearchRequest(notice_period_max=14)
        sql = _compile(build_structured_filter(req)).lower()
        assert "notice_period" in sql
        assert "is null" in sql


class TestBoolToggles:
    @pytest.mark.parametrize(
        "field",
        [
            "is_champion",
            "is_ambassador",
            "open_to_side_projects",
            "open_to_sales_support",
            "open_to_expert_consult",
        ],
    )
    def test_true_emits_is_true(self, field):
        req = CandidateSearchRequest(**{field: True})
        sql = _compile(build_structured_filter(req))
        assert "true" in sql.lower() or "= TRUE" in sql.upper() or "1" in sql

    def test_has_cv_true(self):
        req = CandidateSearchRequest(has_cv=True)
        sql = _compile(build_structured_filter(req))
        assert "cv_filename" in sql
        assert "is not null" in sql.lower()

    def test_has_cv_false(self):
        req = CandidateSearchRequest(has_cv=False)
        sql = _compile(build_structured_filter(req))
        assert "cv_filename" in sql
        assert "is null" in sql.lower()

    def test_has_linkedin_true(self):
        req = CandidateSearchRequest(has_linkedin=True)
        sql = _compile(build_structured_filter(req))
        assert "linkedin" in sql
        assert "is not null" in sql.lower()


class TestSalaryRange:
    def test_min_max_currency(self):
        req = CandidateSearchRequest(
            salary_min=10000, salary_max=25000, salary_currency="pln"
        )
        sql = _compile(build_structured_filter(req)).lower()
        assert "salary_expectation" in sql
        assert "10000" in sql and "25000" in sql
        assert "pln" in sql


class TestHourlyRate:
    """SEARCH-P0-01: hourly rate filters on ``expected_rate_hourly`` (NOT the
    monthly ``salary_expectation``) and treats a missing rate as included."""

    def test_min_only_targets_hourly_column(self):
        req = CandidateSearchRequest(rate_hourly_min=90)
        sql = _compile(build_structured_filter(req)).lower()
        assert "expected_rate_hourly" in sql
        assert "90" in sql
        # Must NOT touch the monthly expectation column.
        assert "salary_expectation" not in sql

    def test_max_only_targets_hourly_column(self):
        req = CandidateSearchRequest(rate_hourly_max=150)
        sql = _compile(build_structured_filter(req)).lower()
        assert "expected_rate_hourly" in sql
        assert "150" in sql
        assert "salary_expectation" not in sql

    def test_missing_rate_is_included(self):
        req = CandidateSearchRequest(rate_hourly_min=90, rate_hourly_max=150)
        # single clause: (rate IS NULL) OR (rate >= 90 AND rate <= 150)
        clauses = build_structured_filter(req)
        assert len(clauses) == 1
        sql = _compile(clauses).lower()
        assert "is null" in sql
        assert "90" in sql and "150" in sql

    def test_hourly_is_independent_of_monthly_salary(self):
        req = CandidateSearchRequest(
            salary_min=10000, salary_max=25000, rate_hourly_min=90
        )
        sql = _compile(build_structured_filter(req)).lower()
        # both columns present, distinct filters
        assert "salary_expectation" in sql
        assert "expected_rate_hourly" in sql


class TestExcludeBlacklisted:
    """SEARCH-P0-04: job-context search hides globally-blacklisted candidates."""

    def test_off_by_default_emits_no_clause(self):
        req = CandidateSearchRequest()
        assert build_structured_filter(req) == []

    def test_on_emits_status_not_blacklisted(self):
        req = CandidateSearchRequest(exclude_blacklisted=True)
        clauses = build_structured_filter(req)
        assert len(clauses) == 1
        sql = _compile(clauses).lower()
        assert "status" in sql
        assert "blacklisted" in sql
        assert "!=" in sql or "<>" in sql

    def test_composes_with_status_filter(self):
        # An explicit status filter and the blacklist exclusion coexist.
        req = CandidateSearchRequest(
            exclude_blacklisted=True, status=[CandidateStatus.active]
        )
        clauses = build_structured_filter(req)
        assert len(clauses) == 2


class TestSources:
    def test_sources_in_list(self):
        req = CandidateSearchRequest(sources=["linkedin", "referral"])
        sql = _compile(build_structured_filter(req))
        assert "linkedin" in sql and "referral" in sql


class TestTagsAndCvDate:
    def test_tags_emit_one_ilike_per_tag(self):
        req = CandidateSearchRequest(tags=["urgent", "senior"])
        clauses = build_structured_filter(req)
        # one ilike per tag
        sql = _compile(clauses)
        assert "urgent" in sql and "senior" in sql

    def test_cv_parsed_after(self):
        req = CandidateSearchRequest(cv_parsed_after=date(2026, 1, 1))
        sql = _compile(build_structured_filter(req))
        assert "cv_parsed_at" in sql
        assert "2026-01-01" in sql


class TestFilterGroups:
    """SEARCH-P1-04: build_filter_groups labels/groups clauses for the
    exclusion waterfall, and flattening it must equal build_structured_filter."""

    def test_empty_request_has_no_groups(self):
        assert build_filter_groups(CandidateSearchRequest()) == []

    def test_groups_are_keyed_and_labelled(self):
        req = CandidateSearchRequest(
            competence_category_ids=[2],
            skills_must=["Python"],
            location_cities=["Warszawa"],
            rate_hourly_max=150,
        )
        groups = build_filter_groups(req)
        keys = [g.key for g in groups]
        assert keys == ["competence_category", "skills", "location", "rate_hourly"]
        for g in groups:
            assert g.label  # every group carries a human label
            assert g.clauses  # never emit an empty group

    def test_flatten_equals_build_structured_filter(self):
        req = CandidateSearchRequest(
            competence_category_ids=[2],
            skills_must=["Python", "AWS"],
            skills_any=["React", "Vue"],
            experience_years_min=5,
            location_cities=["Warszawa"],
            rate_hourly_min=90,
            rate_hourly_max=150,
            exclude_blacklisted=True,
            tags=["urgent"],
        )
        flat = [c for g in build_filter_groups(req) for c in g.clauses]
        direct = build_structured_filter(req)
        assert len(flat) == len(direct)
        assert _compile(flat) == _compile(direct)

    def test_group_order_is_stable(self):
        req = CandidateSearchRequest(
            tags=["a"],
            skills_must=["Python"],
            competence_category_ids=[1],
            rate_hourly_max=100,
        )
        keys = [g.key for g in build_filter_groups(req)]
        # competence before skills before rate before tags, regardless of the
        # order fields were set on the request.
        assert keys.index("competence_category") < keys.index("skills")
        assert keys.index("skills") < keys.index("rate_hourly")
        assert keys.index("rate_hourly") < keys.index("tags")


class TestCombined:
    def test_cc_plus_skills_plus_status_compose_with_AND(self):
        req = CandidateSearchRequest(
            competence_category_ids=[2],
            skills_must=["Python"],
            status=[CandidateStatus.active],
        )
        clauses = build_structured_filter(req)
        # CC + 1 skill + status = 3 clauses (AND-ed by caller)
        assert len(clauses) == 3
        sql = _compile(clauses)
        assert "competence_category_id" in sql
        assert "Python" in sql
        assert "active" in sql
