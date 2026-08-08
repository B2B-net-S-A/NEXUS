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
    NULL_POLICY,
    NullPolicy,
    build_filter_groups,
    build_structured_filter,
    experience_soft_rank,
    location_soft_rank,
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
    def test_skills_must_is_soft_no_hard_clause(self):
        # SEARCH-P0-03: skills_must is a soft ranking signal, not a hard filter.
        req = CandidateSearchRequest(skills_must=["Python", "FastAPI"])
        assert build_structured_filter(req) == []

    def test_skills_any_is_soft_no_hard_clause(self):
        # SEARCH-P0-03: skills_any no longer emits a hard OR clause.
        req = CandidateSearchRequest(skills_any=["React", "Vue", "Angular"])
        assert build_structured_filter(req) == []

    def test_skills_none_emits_NOT_per_skill(self):
        # Exclusion stays a hard filter — "must NOT have X" is a real constraint.
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
        """Both bounds now live in ONE NULL-tolerant clause, not two.

        Previously this asserted `len(clauses) == 2` — two bare comparisons.
        They were merged into a single `nullable(col, >=min, <=max)` so a
        candidate who never stated their experience is no longer dropped
        (the column is filled for 1.2% of the base).
        """
        req = CandidateSearchRequest(experience_years_min=5, experience_years_max=10)
        clauses = build_structured_filter(req)
        assert len(clauses) == 1
        sql = _compile(clauses)
        assert "years_it_experience IS NULL" in sql
        assert ">= 5" in sql and "<= 10" in sql


class TestLanguages:
    def test_language_clause_emits_pattern_or(self):
        req = CandidateSearchRequest(
            languages=[LanguageRequirement(code="EN", min_level="B2")]
        )
        sql = _compile(build_structured_filter(req))
        assert "candidate_languages" in sql
        assert "deleted_at IS NULL" in sql
        assert "is_native IS true" in sql
        # Accepted CEFR levels for B2: B2, C1, C2; native is a separate flag.
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


class TestHourlyRate:
    """Global rate is B2B PLN net/hour and missing data stays included."""

    def test_min_only_targets_hourly_column(self):
        req = CandidateSearchRequest(rate_hourly_min=90)
        sql = _compile(build_structured_filter(req)).lower()
        assert "expected_rate_hourly" in sql
        assert "90" in sql

    def test_max_only_targets_hourly_column(self):
        req = CandidateSearchRequest(rate_hourly_max=150)
        sql = _compile(build_structured_filter(req)).lower()
        assert "expected_rate_hourly" in sql
        assert "150" in sql

    def test_missing_rate_is_included(self):
        req = CandidateSearchRequest(rate_hourly_min=90, rate_hourly_max=150)
        # single clause: (rate IS NULL) OR (rate >= 90 AND rate <= 150)
        clauses = build_structured_filter(req)
        assert len(clauses) == 1
        sql = _compile(clauses).lower()
        assert "is null" in sql
        assert "90" in sql and "150" in sql


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
        # skills_none is the remaining hard skill clause (skills_must/any are
        # soft now, SEARCH-P0-03), so use it to exercise the skills group.
        req = CandidateSearchRequest(
            competence_category_ids=[2],
            skills_none=["junior"],
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
            skills_none=["junior"],  # skills_must/any are soft (SEARCH-P0-03)
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
        # skills_must is soft now (SEARCH-P0-03) — use skills_none for the hard
        # skill clause so the AND-composition still has all three.
        req = CandidateSearchRequest(
            competence_category_ids=[2],
            skills_none=["Python"],
            status=[CandidateStatus.active],
        )
        clauses = build_structured_filter(req)
        # CC + 1 skill-exclusion + status = 3 clauses (AND-ed by caller)
        assert len(clauses) == 3
        sql = _compile(clauses)
        assert "competence_category_id" in sql
        # Dopasowanie umiejętności jest bezwielkoznakowe: predykat sprowadza do
        # małych liter i kolumny, i szukaną wartość, więc w zapytaniu stoi
        # `python`, nie `Python`. Asercja na samą obecność nazwy, nie na jej
        # zapis — ten drugi był artefaktem poprzedniej implementacji (ILIKE ze
        # wzorcem wstawianym bez zmiany wielkości liter).
        assert "python" in sql.lower()
        assert "active" in sql


# ── NULL policy contract ─────────────────────────────────────────────────────
# These four tests are the actual fix. `nullable()` on its own stops nothing:
# the next author writes `Candidate.x >= v` directly and the helper never sees
# it. What prevents recurrence is that a filter group with no registry entry
# fails the build — turning "someone forgot" into a red test instead of a
# silent 99% cut that nobody notices for months.


def _maximal_request() -> CandidateSearchRequest:
    """A request that populates EVERY filter group, so none can hide."""
    return CandidateSearchRequest(
        competence_category_ids=[1],
        skills_none=["COBOL"],
        experience_years_min=2,
        experience_years_max=6,
        languages=[LanguageRequirement(code="en", min_level="B2")],
        location_cities=["Kraków"],
        location_countries=["PL"],
        exclude_blacklisted=True,
        status=[CandidateStatus.active],
        availability_status=[AvailabilityStatus.unknown],
        availability_date_before=date(2030, 1, 1),
        notice_period_max=30,
        rate_hourly_min=100,
        rate_hourly_max=200,
        sources=["traffit"],
        tags=["vip"],
        has_cv=True,
    )


def test_every_filter_group_declares_a_null_policy():
    missing = [
        g.key for g in build_filter_groups(_maximal_request()) if g.key not in NULL_POLICY
    ]
    assert not missing, (
        f"Filter group(s) {missing} declare no NULL policy. Add an entry to "
        "NULL_POLICY. The default is `include` — a candidate whose field is "
        "empty stays in the results — because most structured columns on this "
        "dataset are blank for the large majority of rows, so dropping NULLs "
        "filters on bookkeeping rather than on relevance. Choosing `exclude` "
        "requires a justification string saying why absence is real evidence."
    )


def test_exclude_policy_requires_a_justification():
    offenders = [
        key
        for key, pol in NULL_POLICY.items()
        if pol.policy is NullPolicy.exclude and not pol.justification.strip()
    ]
    assert not offenders, (
        f"{offenders} exclude candidates with a missing value but give no "
        "reason. Say why absence is evidence, not an accident of data entry."
    )


def test_registry_has_no_entries_for_groups_that_do_not_exist():
    """Guard the guard: a stale entry would make the first test pass for a
    group that no longer materialises, hiding a real gap."""
    live = {g.key for g in build_filter_groups(_maximal_request())}
    stale = set(NULL_POLICY) - live
    assert not stale, (
        f"NULL_POLICY has entries for non-existent groups: {sorted(stale)}. "
        "Either _maximal_request no longer populates them, or they were removed."
    )


def _is_null_tolerant(clause) -> bool:
    """Walk the SQLAlchemy expression for a disjunction containing IS NULL.

    Deliberately not a substring check on the compiled SQL: `coalesce(col,'')
    ILIKE '%x%'` contains no "IS NULL" yet excludes every NULL row, and that is
    precisely the shape that made the location filter silently drop 85% of the
    database while looking safe.
    """
    from sqlalchemy import BooleanClauseList
    from sqlalchemy.sql.elements import UnaryExpression
    from sqlalchemy.sql.operators import or_ as or_op

    def _has_is_null(node) -> bool:
        if isinstance(node, UnaryExpression) and node.operator is not None:
            if "IS NULL" in str(node.compile(dialect=postgresql.dialect())).upper():
                return True
        if isinstance(node, BooleanClauseList):
            return any(_has_is_null(c) for c in node.clauses)
        try:
            return "IS NULL" in str(
                node.compile(dialect=postgresql.dialect())
            ).upper()
        except Exception:
            return False

    if isinstance(clause, BooleanClauseList) and clause.operator is or_op:
        return any(_has_is_null(c) for c in clause.clauses)
    return _has_is_null(clause)


@pytest.mark.parametrize("group_key", ["experience", "location", "rate_hourly"])
def test_include_policy_groups_keep_rows_with_a_missing_value(group_key):
    groups = {g.key: g for g in build_filter_groups(_maximal_request())}
    assert NULL_POLICY[group_key].policy is NullPolicy.include
    group = groups[group_key]
    assert all(_is_null_tolerant(c) for c in group.clauses), (
        f"Group '{group_key}' is declared `include` but at least one of its "
        f"clauses drops rows whose value is NULL:\n{_compile(group.clauses)}"
    )


def test_experience_bound_no_longer_excludes_unstated_experience():
    req = CandidateSearchRequest(experience_years_min=2, experience_years_max=6)
    sql = _compile(build_structured_filter(req))
    assert "years_it_experience IS NULL" in sql
    assert ">= 2" in sql and "<= 6" in sql


def test_location_chip_keeps_candidates_with_no_location_at_all():
    req = CandidateSearchRequest(location_cities=["Kraków"])
    sql = _compile(build_structured_filter(req))
    assert "city IS NULL" in sql and "location IS NULL" in sql


def test_location_chip_still_drops_a_known_mismatching_city():
    """Softening must not turn the filter off: a candidate who DID state a
    different city is still excluded — only the unknowns are kept."""
    req = CandidateSearchRequest(location_cities=["Kraków"])
    sql = _compile(build_structured_filter(req))
    # `literal_binds` doubles the wildcard (%% ), so match the operator and the
    # city rather than a hand-written pattern.
    assert "ILIKE" in sql and "Kraków" in sql


# ── Soft ranking (the other half of softening a filter) ──────────────────────


def test_experience_soft_rank_is_none_without_a_bound():
    assert experience_soft_rank(CandidateSearchRequest()) is None


def test_experience_soft_rank_rewards_a_stated_matching_range():
    expr = experience_soft_rank(
        CandidateSearchRequest(experience_years_min=2, experience_years_max=6)
    )
    sql = str(expr.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
    # Must require a stated value: NULL scores 0, not 1, or the ranking is a
    # no-op and the 45 real matches stay buried among 11 046 unknowns.
    assert "IS NOT NULL" in sql
    assert ">= 2" in sql and "<= 6" in sql


def test_location_soft_rank_counts_matching_cities():
    expr = location_soft_rank(CandidateSearchRequest(location_cities=["Kraków", "Wrocław"]))
    sql = str(expr.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
    assert sql.count("CASE") == 2


def test_location_soft_rank_is_none_without_cities():
    assert location_soft_rank(CandidateSearchRequest()) is None
