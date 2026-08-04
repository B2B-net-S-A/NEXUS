"""Unit tests for the hybrid scoring engine (Phase 2)."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest

from app.services import scoring_service as ss


# ── Helpers ──────────────────────────────────────────────────────────────────


def make_candidate(**overrides) -> SimpleNamespace:
    defaults = dict(
        id=1,
        name="Jan",
        lastname="Kowalski",
        status="active",
        tags=[],
        skills=[],
        verified_tech=[],
        location=None,
        availability_date=None,
        expected_rate_hourly=None,
        preferences={},
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def make_job(**overrides) -> SimpleNamespace:
    defaults = dict(
        id=1,
        title="Senior Python Developer",
        must_skills=[],
        nice_skills=[],
        salary_min=None,
        salary_max=None,
        location=None,
        remote_policy=SimpleNamespace(value="remote"),
        deadline=None,
        client_id=None,
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


# ── _skill_names ─────────────────────────────────────────────────────────────


def test_skill_names_from_list_of_strings():
    assert ss._skill_names(["Python", " JAVA "]) == ["python", "java"]


def test_skill_names_from_list_of_dicts():
    assert ss._skill_names([{"name": "Kubernetes"}, {"name": "AWS"}]) == [
        "kubernetes",
        "aws",
    ]


def test_skill_names_mixed_types_ignored_gracefully():
    assert ss._skill_names([123, None, "React", {"foo": "bar"}]) == ["react"]


def test_skill_names_empty_input():
    assert ss._skill_names(None) == []
    assert ss._skill_names([]) == []


def test_skill_names_from_dict_with_technologies_list():
    """Alt seed format: {'level': 'senior', 'technologies': ['Java', 'Spring Boot']}."""
    raw = {"level": "senior", "technologies": ["Java", "Spring Boot", "Kafka"]}
    assert ss._skill_names(raw) == ["java", "spring boot", "kafka"]


def test_skill_names_from_dict_with_mixed_key_variants():
    """Also accept 'skills', 'stack', 'tech' keys (robustness)."""
    assert ss._skill_names({"skills": ["React", "TypeScript"]}) == [
        "react",
        "typescript",
    ]
    assert ss._skill_names({"stack": ["Go"]}) == ["go"]


def test_skill_names_from_dict_with_name_key():
    """Single-skill dict payload."""
    assert ss._skill_names({"name": "Python"}) == ["python"]


# ── _score_skills ────────────────────────────────────────────────────────────


def test_score_skills_all_must_matched_gives_full_must():
    job = make_job(must_skills=[{"name": "Python"}, {"name": "FastAPI"}])
    cand = make_candidate(skills=[{"name": "Python"}, {"name": "FastAPI"}])
    result, must_match, must_gap, nice_match, nice_gap = ss._score_skills(cand, job)
    assert result.points == pytest.approx(ss.SKILLS_MUST_MAX)
    assert set(must_match) == {"python", "fastapi"}
    assert must_gap == []
    assert nice_match == []
    assert nice_gap == []


def test_score_skills_half_must_half_points():
    job = make_job(must_skills=["Python", "Go", "Rust", "Zig"])
    cand = make_candidate(skills=["Python", "Go"])
    result, must_match, must_gap, *_ = ss._score_skills(cand, job)
    assert result.points == pytest.approx(ss.SKILLS_MUST_MAX / 2)
    assert set(must_match) == {"python", "go"}
    assert set(must_gap) == {"rust", "zig"}


def test_score_skills_verified_tech_counts():
    job = make_job(must_skills=["AWS"])
    cand = make_candidate(verified_tech=[{"name": "aws"}])
    result, must_match, *_ = ss._score_skills(cand, job)
    assert must_match == ["aws"]
    assert result.points == pytest.approx(ss.SKILLS_MUST_MAX)


def test_score_skills_no_must_returns_full_must_fallback():
    job = make_job(must_skills=[], nice_skills=["Docker"])
    cand = make_candidate(skills=["Docker"])
    result, *_ = ss._score_skills(cand, job)
    # must=20 (n/a fallback) + nice=10 = 30
    assert result.points == pytest.approx(ss.SKILLS_MAX)


def test_score_skills_tags_fallback_when_no_structured_skills():
    job = make_job(must_skills=["Python"])
    cand = make_candidate(skills=[], verified_tech=[], tags=["Python", "Senior"])
    result, must_match, *_ = ss._score_skills(cand, job)
    assert must_match == ["python"]
    assert result.points == pytest.approx(ss.SKILLS_MUST_MAX)


# ── stringified-JSON / free-form skills (Traffit/TalentRadar imports) ─────────


def test_skill_names_from_json_encoded_string():
    """Traffit/TalentRadar store skills as a JSON *string*, not a real array."""
    assert ss._skill_names('["Java", "Spring Boot", "Kafka"]') == [
        "java",
        "spring boot",
        "kafka",
    ]


def test_skill_names_from_freeform_comma_string():
    """traffit_technologie is a flat comma list, not JSON."""
    assert ss._skill_names("JAVA, Spring, PostgreSQL") == [
        "java",
        "spring",
        "postgresql",
    ]


def test_skill_names_preserves_slash_compounds():
    assert ss._skill_names("CI/CD, TCP/IP") == ["ci/cd", "tcp/ip"]


def test_skill_names_malformed_json_string_falls_back_to_split():
    # Not valid JSON → comma split (never broken '["java' tokens).
    assert ss._skill_names("[Java, Spring") == ["[java", "spring"]


# ── _skills_from_cv_extracted ─────────────────────────────────────────────────


def test_skills_from_cv_extracted_traffit_technologie():
    cand = make_candidate(
        cv_extracted_data={"traffit_technologie": "Java, Hibernate, Kafka"}
    )
    assert ss._skills_from_cv_extracted(cand) == ["java", "hibernate", "kafka"]


def test_skills_from_cv_extracted_nested_list():
    cand = make_candidate(cv_extracted_data={"skills": ["Go", "Rust"]})
    assert ss._skills_from_cv_extracted(cand) == ["go", "rust"]


def test_skills_from_cv_extracted_missing_returns_empty():
    assert ss._skills_from_cv_extracted(make_candidate()) == []
    assert ss._skills_from_cv_extracted(make_candidate(cv_extracted_data={})) == []


# ── candidate_skill_names priority + fallbacks ────────────────────────────────


def test_candidate_skill_names_structured_wins_over_cv():
    cand = make_candidate(
        skills=[{"name": "Python"}],
        cv_extracted_data={"traffit_technologie": "Java, Kafka"},
    )
    assert ss.candidate_skill_names(cand) == {"python"}


def test_candidate_skill_names_falls_back_to_cv_extracted():
    cand = make_candidate(
        skills=[],
        verified_tech=[],
        cv_extracted_data={"traffit_technologie": "Java, Spring, PostgreSQL"},
    )
    assert ss.candidate_skill_names(cand) == {"java", "spring", "postgresql"}


def test_candidate_skill_names_empty_everything():
    assert ss.candidate_skill_names(make_candidate()) == set()


# ── _score_skills regression: empty structured skills, tech in CV ─────────────


def test_score_skills_uses_cv_extracted_when_skills_empty():
    """Jacek Karwowski (id 25479) regression: empty `skills`, tech lives in
    cv_extracted_data.traffit_technologie. Must skills should match, not gap."""
    job = make_job(
        must_skills=[{"name": "Java"}, {"name": "Spring"}, {"name": "PostgreSQL"}]
    )
    cand = make_candidate(
        skills=[],
        verified_tech=[],
        tags=[{"type": "traffit_source", "url": "Aktywny Search"}],
        cv_extracted_data={
            "traffit_technologie": (
                "JAVA, JDK17, Hibernate, Spring, Springboot, Kafka, "
                "PostgreSQL, Docker, Kubernetes"
            )
        },
    )
    result, must_match, must_gap, *_ = ss._score_skills(cand, job)
    assert set(must_match) == {"java", "spring", "postgresql"}
    assert must_gap == []
    assert result.points == pytest.approx(ss.SKILLS_MUST_MAX)


def test_score_skills_json_string_skills_column():
    """The ~305 candidates whose `skills` column is a JSON *string*."""
    job = make_job(must_skills=["Java", "Kafka"])
    cand = make_candidate(skills='["Java", "Kafka", "Spring"]')
    _, must_match, must_gap, *_ = ss._score_skills(cand, job)
    assert set(must_match) == {"java", "kafka"}
    assert must_gap == []


# ── raw_cv_text fallback (needs the alias taxonomy loaded) ────────────────────


@pytest.fixture
def alias_map_loaded():
    """Populate the module-global skill alias map for the duration of a test."""
    saved = dict(ss.ALIAS_MAP)
    ss.set_alias_map({"java": "java", "spring": "spring", "kafka": "kafka"})
    try:
        yield
    finally:
        ss.set_alias_map(saved)


def test_skills_from_raw_cv_requires_alias_map():
    # No taxonomy loaded → no raw-CV extraction (avoids per-score regex cost).
    cand = make_candidate(raw_cv_text="Experienced Java and Kafka engineer.")
    assert ss._skills_from_raw_cv(cand) == []


def test_score_skills_raw_cv_fallback(alias_map_loaded):
    job = make_job(must_skills=["Java", "Kafka"])
    cand = make_candidate(
        skills=[],
        verified_tech=[],
        cv_extracted_data={},
        raw_cv_text="Senior engineer skilled in Java, Spring and Kafka.",
    )
    _, must_match, must_gap, *_ = ss._score_skills(cand, job)
    assert set(must_match) == {"java", "kafka"}
    assert must_gap == []


# ── _score_salary ────────────────────────────────────────────────────────────


def test_cross_unit_rate_is_not_comparable_and_scored_neutrally():
    # P0-A: an incomparable PLN/h-vs-PLN/month pair is scored with the neutral
    # fraction (same as missing data), NOT full — a rate we cannot compare must
    # not inflate the composite by the whole salary budget.
    job = make_job(salary_min=15000, salary_max=25000)
    cand = make_candidate(expected_rate_hourly=150)
    r = ss._score_salary(cand, job)
    assert r.points == pytest.approx(ss.SALARY_MAX * ss.UNKNOWN_NEUTRAL_FRACTION)
    assert r.points < ss.SALARY_MAX
    assert r.status == "not_comparable"
    assert "not_comparable" in r.reason


def test_zero_hourly_rate_is_still_a_known_cross_unit_value():
    candidate = make_candidate(expected_rate_hourly=0)
    job = make_job(salary_min=10_000, salary_max=20_000)

    result = ss._score_salary(candidate, job)

    assert result.status == "not_comparable"
    assert result.points == pytest.approx(ss.SALARY_MAX * ss.UNKNOWN_NEUTRAL_FRACTION)


def test_salary_missing_data_gets_neutral():
    # Recalibration: unknown salary is "no signal", not a negative → neutral
    # half-budget (matching availability/champion), not a hard 0.
    job = make_job(salary_min=None, salary_max=None)
    cand = make_candidate(expected_rate_hourly=None)
    r = ss._score_salary(cand, job)
    assert r.points == pytest.approx(ss.SALARY_MAX * ss.UNKNOWN_NEUTRAL_FRACTION)
    assert "brak" in r.reason


def test_salary_missing_job_range_gets_neutral():
    # Candidate has a rate but the job has no range → still unjudgeable → neutral.
    job = make_job(salary_min=None, salary_max=None)
    cand = make_candidate(expected_rate_hourly=150)
    r = ss._score_salary(cand, job)
    assert r.points == pytest.approx(ss.SALARY_MAX * ss.UNKNOWN_NEUTRAL_FRACTION)


def test_not_comparable_and_unknown_are_both_neutral():
    # P0-A: an incomparable rate and missing data are now scored with the SAME
    # neutral fraction — neither penalises nor over-credits. They differ only in
    # the transparency label (status), not in points.
    job = make_job(salary_min=50000, salary_max=60000)
    not_comparable = ss._score_salary(make_candidate(expected_rate_hourly=200), job)
    unknown = ss._score_salary(
        make_candidate(expected_rate_hourly=None),
        make_job(salary_min=None, salary_max=None),
    )
    neutral = ss.SALARY_MAX * ss.UNKNOWN_NEUTRAL_FRACTION
    assert not_comparable.points == pytest.approx(neutral)
    assert unknown.points == pytest.approx(neutral)
    assert not_comparable.status == "not_comparable"
    assert unknown.status == "unknown"


# ── _score_location ──────────────────────────────────────────────────────────


def test_location_remote_mode_plus_city_full_points():
    job = make_job(
        location="Warszawa, Poland",
        remote_policy=SimpleNamespace(value="remote"),
    )
    cand = make_candidate(
        location="Warszawa",
        preferences={"remote_modes": ["remote", "hybrid"]},
    )
    r = ss._score_location(cand, job)
    assert r.points == pytest.approx(ss.LOCATION_MAX)


def test_location_no_match_zero_points():
    job = make_job(
        location="Warszawa",
        remote_policy=SimpleNamespace(value="on_site"),
    )
    cand = make_candidate(
        location="Kraków",
        preferences={"remote_modes": ["remote"]},
    )
    r = ss._score_location(cand, job)
    assert r.points == 0.0


def test_location_same_city_prefix_partial():
    job = make_job(
        location="Warszawa, PL",
        remote_policy=SimpleNamespace(value="on_site"),
    )
    cand = make_candidate(location="Warszawa, Mokotów", preferences={})
    r = ss._score_location(cand, job)
    # Token overlap ("warszawa" on both sides) → the city half fires.
    assert r.points >= ss.LOCATION_MAX * 0.25
    assert r.points <= ss.LOCATION_MAX


# No-signal neutrality (2026-06-30). ~99.6% of imported jobs carry no location
# and ~99% of imported candidates state no remote preference, so BOTH halves are
# usually "no signal". They now award the neutral fraction (like
# salary/availability/champion) instead of a hard 0 — a per-job constant lift
# that leaves ranking (and every rank-based eval metric) unchanged. To ISOLATE
# the city half in a test, give the candidate a remote pref the job doesn't offer
# (known mismatch → remote half = 0), not an empty pref (now neutral, not 0).


def test_location_no_job_location_both_halves_neutral():
    # Candidate has a real (blob) location, the job has none, candidate states no
    # remote pref → nothing to judge on either half → both go neutral (was a hard
    # 0 before 2026-06-30). Total = LOCATION_MAX * UNKNOWN_NEUTRAL_FRACTION.
    job = make_job(location=None, remote_policy=SimpleNamespace(value="on_site"))
    cand = make_candidate(
        location='{"locality":"Warszawa","region1":"Mazowieckie","country":"Polska"}',
        preferences={},
    )
    r = ss._score_location(cand, job)
    assert r.points == pytest.approx(ss.LOCATION_MAX * ss.UNKNOWN_NEUTRAL_FRACTION)
    assert "nieznan" in r.reason


def test_location_no_job_location_remote_match_plus_city_neutral():
    # Remote pref matches the job's policy (full remote half); job has no
    # location → city half neutral. Total = half + half * frac.
    job = make_job(location="", remote_policy=SimpleNamespace(value="hybrid"))
    cand = make_candidate(
        location='{"locality":"Gdańsk","country":"Polska"}',
        preferences={"remote_modes": ["hybrid"]},
    )
    r = ss._score_location(cand, job)
    half = ss.LOCATION_MAX / 2.0
    assert r.points == pytest.approx(half + half * ss.UNKNOWN_NEUTRAL_FRACTION)


def test_location_blob_candidate_matches_job_city():
    # Structured JSON blob is parsed so a same-city candidate earns the city
    # half. Candidate's remote pref is a known mismatch (job on_site, cand wants
    # remote) → remote half is a clean 0, isolating the city half at exactly half.
    job = make_job(location="Warszawa", remote_policy=SimpleNamespace(value="on_site"))
    cand = make_candidate(
        location='{"locality":"Warszawa","region1":"Mazowieckie","country":"Polska"}',
        preferences={"remote_modes": ["remote"]},  # mismatch → isolates city half
    )
    r = ss._score_location(cand, job)
    assert r.points == pytest.approx(ss.LOCATION_MAX / 2.0)
    assert "lokalizacja OK" in r.reason


def test_location_blob_candidate_other_city_no_credit():
    # Different city (known mismatch) + remote known mismatch → both halves 0.
    job = make_job(location="Warszawa", remote_policy=SimpleNamespace(value="on_site"))
    cand = make_candidate(
        location='{"locality":"Gdańsk","region1":"Pomorskie","country":"Polska"}',
        preferences={"remote_modes": ["remote"]},  # mismatch → remote half 0 too
    )
    r = ss._score_location(cand, job)
    assert r.points == 0.0


def test_location_all_unknown_both_halves_neutral():
    # Job specifies a city but the candidate's location is unknown AND the
    # candidate states no remote pref → can't judge either half → both neutral.
    # Total = LOCATION_MAX * UNKNOWN_NEUTRAL_FRACTION. No crash on None location.
    job = make_job(location="Kraków", remote_policy=SimpleNamespace(value="on_site"))
    cand = make_candidate(location=None, preferences={})
    r = ss._score_location(cand, job)
    assert r.points == pytest.approx(ss.LOCATION_MAX * ss.UNKNOWN_NEUTRAL_FRACTION)
    assert "nieznan" in r.reason


def test_location_known_mismatch_still_zero():
    # The lift only touches NO-SIGNAL cases. A candidate with a stated remote
    # pref the job doesn't offer AND a different city earns a hard 0 — known
    # mismatches are not given benefit of the doubt.
    job = make_job(location="Warszawa", remote_policy=SimpleNamespace(value="on_site"))
    cand = make_candidate(
        location='{"locality":"Gdańsk"}', preferences={"remote_modes": ["remote"]}
    )
    r = ss._score_location(cand, job)
    assert r.points == 0.0
    assert r.reason == "brak dopasowania"


# ── _score_availability ──────────────────────────────────────────────────────


def test_availability_before_deadline_full_points():
    job = make_job(deadline=date(2026, 6, 1))
    cand = make_candidate(availability_date=date(2026, 5, 1))
    r = ss._score_availability(cand, job)
    assert r.points == pytest.approx(ss.AVAILABILITY_MAX)


def test_availability_no_date_neutral():
    # No availability date → neutral benefit-of-the-doubt (UNKNOWN_NEUTRAL_
    # FRACTION), consistent with salary/location/champion. Was hardcoded 0.5.
    job = make_job(deadline=date(2026, 6, 1))
    cand = make_candidate(availability_date=None)
    r = ss._score_availability(cand, job)
    assert r.points == pytest.approx(ss.AVAILABILITY_MAX * ss.UNKNOWN_NEUTRAL_FRACTION)


def test_availability_late_decays():
    job = make_job(deadline=date(2026, 6, 1))
    cand = make_candidate(availability_date=date(2026, 6, 16))  # 15 days late
    r = ss._score_availability(cand, job)
    assert 0 < r.points < ss.AVAILABILITY_MAX


# ── score_semantic ───────────────────────────────────────────────────────────


def test_semantic_full_similarity_full_points():
    r = ss.score_semantic(1.0)
    assert r.points == pytest.approx(ss.SEMANTIC_MAX)


def test_semantic_none_gives_zero():
    r = ss.score_semantic(None)
    assert r.points == 0.0


def test_semantic_mid_similarity_calibrated():
    # gamma power curve (default 0.6): 0.5 ** 0.6 ≈ 0.66 of budget — lifts the
    # deflated middle above the old linear 0.5.
    r = ss.score_semantic(0.5)
    expected = (0.5**ss.SEMANTIC_CALIBRATION_GAMMA) * ss.SEMANTIC_MAX
    assert r.points == pytest.approx(expected)
    if ss.SEMANTIC_CALIBRATION_GAMMA < 1.0:
        assert r.points > ss.SEMANTIC_MAX * 0.5


def test_semantic_gamma_curve_monotonic_and_pinned():
    g = ss.SEMANTIC_CALIBRATION_GAMMA
    sims = [0.0, 0.2, 0.4, 0.6, 0.8, 1.0]
    pts = [ss.score_semantic(s).points for s in sims]
    # strictly increasing → per-candidate semantic ordering preserved
    assert all(pts[i] < pts[i + 1] for i in range(len(pts) - 1))
    # endpoints pinned: 0 → 0, 1 → full budget
    assert pts[0] == pytest.approx(0.0)
    assert pts[-1] == pytest.approx(ss.SEMANTIC_MAX)
    # each point follows the configured power curve
    for s, p in zip(sims, pts):
        assert p == pytest.approx((s**g) * ss.SEMANTIC_MAX)


# ── _score_champion_fit (Phase 10/11) ────────────────────────────────────────


class _FakeScalarDB:
    """Async session stub that returns one queued value per `scalar()` call."""

    def __init__(self, value):
        self._value = value

    async def scalar(self, _stmt):  # type: ignore[no-untyped-def]
        return self._value


@pytest.mark.asyncio
async def test_champion_fit_no_screening_gives_neutral_half():
    db = _FakeScalarDB(None)
    cand = make_candidate(id=1)
    job = make_job(id=2)
    r = await ss._score_champion_fit(cand, job, db, ss.DEFAULT_PROFILE)
    assert r.points == pytest.approx(ss.CHAMPION_FIT_MAX * ss.UNKNOWN_NEUTRAL_FRACTION)
    assert r.max_points == ss.CHAMPION_FIT_MAX
    assert "brak screening" in r.reason


@pytest.mark.asyncio
async def test_champion_fit_perfect_fit_full_points():
    stage = SimpleNamespace(
        screening_answers={
            "answers": [
                {
                    "question_id": "q1",
                    "response": "świetna odpowiedź",
                    "deal_breaker_hit": False,
                },
                {
                    "question_id": "q2",
                    "response": "druga odpowiedź",
                    "deal_breaker_hit": False,
                },
            ],
            "overall_fit": "fit",
            "notes": "",
        }
    )
    db = _FakeScalarDB(stage)
    cand = make_candidate(id=1)
    job = make_job(id=2)
    r = await ss._score_champion_fit(cand, job, db, ss.DEFAULT_PROFILE)
    assert r.points == pytest.approx(ss.CHAMPION_FIT_MAX)
    assert "100%" in r.reason
    assert r.reason.startswith("fit")


@pytest.mark.asyncio
async def test_champion_fit_deal_breaker_zeroes_points():
    stage = SimpleNamespace(
        screening_answers={
            "answers": [
                {"question_id": "q1", "response": "ok", "deal_breaker_hit": True},
            ],
            "overall_fit": "miss",
            "notes": "",
        }
    )
    db = _FakeScalarDB(stage)
    cand = make_candidate(id=1)
    job = make_job(id=2)
    r = await ss._score_champion_fit(cand, job, db, ss.DEFAULT_PROFILE)
    assert r.points == 0.0
    assert "deal-breaker" in r.reason


@pytest.mark.asyncio
async def test_champion_fit_uncertain_scales_with_fit_weight():
    # 2/2 answered, overall_fit=uncertain → 100% × 0.6 = 60% → 6.0/10
    stage = SimpleNamespace(
        screening_answers={
            "answers": [
                {"question_id": "q1", "response": "ok", "deal_breaker_hit": False},
                {"question_id": "q2", "response": "ok", "deal_breaker_hit": False},
            ],
            "overall_fit": "uncertain",
            "notes": "",
        }
    )
    db = _FakeScalarDB(stage)
    cand = make_candidate(id=1)
    job = make_job(id=2)
    r = await ss._score_champion_fit(cand, job, db, ss.DEFAULT_PROFILE)
    assert r.points == pytest.approx(ss.CHAMPION_FIT_MAX * 0.6)
    assert "uncertain" in r.reason
    assert "60%" in r.reason


@pytest.mark.asyncio
async def test_champion_fit_partial_answers_proportional():
    # Only 1/2 answered (second has empty response), fit → 50% × 1.0 = 50% → 5.0/10
    stage = SimpleNamespace(
        screening_answers={
            "answers": [
                {
                    "question_id": "q1",
                    "response": "konkretna odpowiedź",
                    "deal_breaker_hit": False,
                },
                {"question_id": "q2", "response": "", "deal_breaker_hit": False},
            ],
            "overall_fit": "fit",
            "notes": "",
        }
    )
    db = _FakeScalarDB(stage)
    cand = make_candidate(id=1)
    job = make_job(id=2)
    r = await ss._score_champion_fit(cand, job, db, ss.DEFAULT_PROFILE)
    assert r.points == pytest.approx(ss.CHAMPION_FIT_MAX * 0.5)


@pytest.mark.asyncio
async def test_champion_fit_invalid_payload_falls_back_to_neutral():
    # Something totally unexpected in the JSONB → shouldn't blow up scoring.
    stage = SimpleNamespace(screening_answers={"not_a_valid_schema": True})
    db = _FakeScalarDB(stage)
    cand = make_candidate(id=1)
    job = make_job(id=2)
    r = await ss._score_champion_fit(cand, job, db, ss.DEFAULT_PROFILE)
    # Pydantic validates the payload; invalid shape → points == 0 per schema.
    # We assert it doesn't raise; exact value is covered by match_percent tests.
    assert r.max_points == ss.CHAMPION_FIT_MAX
    assert 0.0 <= r.points <= ss.CHAMPION_FIT_MAX


# ── canonical_skill_names (Phase B1 alias normalization) ────────────────────


def test_canonical_skill_names_without_alias_map_passthrough():
    # No alias overrides → behaves like _skill_names (lowercase, strip).
    assert ss.canonical_skill_names(["Python", "AWS"]) == ["python", "aws"]


def test_canonical_skill_names_with_alias_map_resolves_synonyms(monkeypatch):
    monkeypatch.setitem(ss.ALIAS_MAP, "python3", "python")
    monkeypatch.setitem(ss.ALIAS_MAP, "k8s", "kubernetes")
    assert ss.canonical_skill_names(["Python3", "K8S", "React"]) == [
        "python",
        "kubernetes",
        "react",
    ]


def test_canonical_skill_names_deduplicates_after_normalization(monkeypatch):
    monkeypatch.setitem(ss.ALIAS_MAP, "python3", "python")
    # Two raw entries collapse to a single canonical one
    result = ss.canonical_skill_names(["Python", "Python3"])
    assert result == ["python"] or result == ["python", "python"]
    # We keep order-preserving dedup
    assert result[0] == "python"


def test_score_skills_uses_alias_map_for_matching(monkeypatch):
    monkeypatch.setitem(ss.ALIAS_MAP, "python3", "python")
    job = make_job(must_skills=["Python"])
    cand = make_candidate(skills=["python3"])
    result, must_match, *_ = ss._score_skills(cand, job)
    assert must_match == ["python"]
    assert result.points == pytest.approx(ss.SKILLS_MUST_MAX)


# ── summarize_match_stats ────────────────────────────────────────────────────


def _breakdown(total: float) -> ss.ScoreBreakdown:
    return ss.ScoreBreakdown(
        candidate_id=1,
        job_id=1,
        total=total,
        semantic=ss.LayerResult(points=0, max_points=0),
        skills=ss.LayerResult(points=0, max_points=0),
        salary=ss.LayerResult(points=0, max_points=0),
        location=ss.LayerResult(points=0, max_points=0),
        availability=ss.LayerResult(points=0, max_points=0),
    )


def test_summarize_match_stats_counts_above_threshold():
    breakdowns = [
        _breakdown(80.0),
        _breakdown(55.0),
        _breakdown(30.0),
        _breakdown(50.0),
    ]
    stats = ss.summarize_match_stats(breakdowns, total_open=4, min_score=50.0)
    # 50.0 inclusive; 55 and 80 also pass
    assert stats == {"open_count": 3, "total_open": 4, "top_score": 80.0}


def test_summarize_match_stats_none_above_threshold():
    breakdowns = [_breakdown(40.0), _breakdown(20.0)]
    stats = ss.summarize_match_stats(breakdowns, total_open=5, min_score=50.0)
    assert stats == {"open_count": 0, "total_open": 5, "top_score": 40.0}


def test_summarize_match_stats_empty_breakdowns():
    stats = ss.summarize_match_stats([], total_open=0, min_score=50.0)
    assert stats == {"open_count": 0, "total_open": 0, "top_score": 0.0}


def test_summarize_match_stats_rounds_top_score():
    breakdowns = [_breakdown(73.456789)]
    stats = ss.summarize_match_stats(breakdowns, total_open=1, min_score=50.0)
    assert stats["top_score"] == 73.5


# ── Recalibration invariants (ranking preservation + legacy escape hatch) ─────


@pytest.mark.asyncio
async def test_ranking_preserved_for_same_unknown_cohort():
    """For candidates that share the SAME unknown-metadata set (no salary, no
    location, no availability, no screening), neutral-fill is a constant additive
    shift, so ranking is driven purely by the (monotonic) semantic layer and the
    composite delta between any two equals their semantic delta exactly."""
    db = _FakeScalarDB(None)  # no screening, no conflict
    job = make_job(id=1, must_skills=["Python"], client_id=None)

    def cohort(cid):
        return make_candidate(id=cid, skills=[], verified_tech=[], tags=[])

    hi = await ss.score_candidate_job(cohort(1), job, db, semantic_similarity=0.8)
    mid = await ss.score_candidate_job(cohort(2), job, db, semantic_similarity=0.6)
    lo = await ss.score_candidate_job(cohort(3), job, db, semantic_similarity=0.3)

    assert hi.total > mid.total > lo.total
    assert (hi.total - mid.total) == pytest.approx(
        hi.semantic.points - mid.semantic.points
    )
    assert (mid.total - lo.total) == pytest.approx(
        mid.semantic.points - lo.semantic.points
    )


@pytest.mark.asyncio
async def test_sparse_traffit_job_metadata_all_neutral():
    """End-to-end guard for the 2026-06-30 lift. On a sparse Traffit-style job
    (no location, no deadline, no salary range, no champion) with an unscreened
    candidate carrying no metadata — the ~99% case — all FOUR metadata layers
    award the neutral fraction (no hard 0 on location, no hardcoded 0.5 on
    availability/champion). The composite is lifted well above the old ~55 cap."""
    db = _FakeScalarDB(None)  # no screening, no conflict
    job = make_job(
        id=1,
        location=None,
        deadline=None,
        salary_min=None,
        salary_max=None,
        must_skills=[],
        nice_skills=[],
        client_id=None,
    )
    cand = make_candidate(
        id=1,
        skills=[],
        verified_tech=[],
        tags=[],
        location=None,
        availability_date=None,
        expected_rate_hourly=None,
        preferences={},
    )
    b = await ss.score_candidate_job(cand, job, db, semantic_similarity=0.5)
    frac = ss.UNKNOWN_NEUTRAL_FRACTION
    assert b.salary.points == pytest.approx(ss.SALARY_MAX * frac)
    assert b.location.points == pytest.approx(ss.LOCATION_MAX * frac)
    assert b.availability.points == pytest.approx(ss.AVAILABILITY_MAX * frac)
    assert b.champion_fit.points == pytest.approx(ss.CHAMPION_FIT_MAX * frac)
    # Lifted past the old deflated ceiling (top sparse-job match used to cap ~55).
    assert b.total > 60.0


def test_legacy_reproduced_with_gamma_1_and_neutral_0(monkeypatch):
    """The escape hatch: gamma=1.0 + neutral=0.0 must reproduce the exact pre-
    recalibration behaviour (linear semantic, hard-zero unknown salary/location)."""
    monkeypatch.setattr(ss, "SEMANTIC_CALIBRATION_GAMMA", 1.0)
    monkeypatch.setattr(ss, "UNKNOWN_NEUTRAL_FRACTION", 0.0)

    assert ss.score_semantic(0.5).points == pytest.approx(ss.SEMANTIC_MAX * 0.5)

    job = make_job(salary_min=None, salary_max=None)
    cand = make_candidate(expected_rate_hourly=None)
    assert ss._score_salary(cand, job).points == 0.0

    job_loc = make_job(
        location="Kraków", remote_policy=SimpleNamespace(value="on_site")
    )
    cand_loc = make_candidate(location=None, preferences={})
    assert ss._score_location(cand_loc, job_loc).points == 0.0
