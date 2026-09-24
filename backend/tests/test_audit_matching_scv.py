"""SCV-01/02/03 (audyt 22.09.2026): C/C++/C#, miasto zamiast kraju, kafelki CV.

Czyste testy jednostkowe — bez bazy.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services import scoring_service as ss
from app.services.cv_generator_b2b.requirement_map import build_requirements
from app.services.dealbreaker_filters import missing_must_skills
from app.services.location_utils import city_tokens


def _cand(**kw):
    base = dict(
        id=1,
        name="Jan",
        lastname="Kowalski",
        status="active",
        tags=[],
        skills=[],
        verified_tech=[],
        location=None,
        city=None,
        availability_date=None,
        expected_rate_hourly=None,
        expected_rate_currency=None,
        preferences={},
        cv_extracted_data=None,
        raw_cv_text=None,
        max_onsite_days_per_week=None,
    )
    base.update(kw)
    return SimpleNamespace(**base)


def _job(**kw):
    base = dict(
        id=1,
        title="Developer",
        must_skills=[],
        nice_skills=[],
        salary_min=None,
        salary_max=None,
        location=None,
        remote_policy=SimpleNamespace(value="onsite"),
        deadline=None,
        client_id=None,
        champion_profile=None,
        matching_requirements=None,
        requirements_reviewed=True,
        requirements=None,
        description=None,
    )
    base.update(kw)
    return SimpleNamespace(**base)


# ── SCV-01 ───────────────────────────────────────────────────────────────────

_LANGS = ["C", "C++", "C#"]


@pytest.mark.parametrize("required", _LANGS)
@pytest.mark.parametrize("has", _LANGS)
def test_c_family_matrix_skill_present(required, has):
    assert ss.skill_present(required, [has]) is (required == has)


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("C++", "cpp"),
        ("c ++", "C++"),
        ("C#", "csharp"),
        ("C#", "C sharp"),
        (".NET", "dotnet"),
        ("F#", "fsharp"),
        ("postgresql", "Postgres"),
        ("Node.js", "nodejs"),
    ],
)
def test_significant_signs_still_match_their_aliases(a, b):
    assert ss._canon_skill(a) == ss._canon_skill(b)


def test_dotnet_prefix_does_not_swallow_asp_net():
    assert ss._canon_skill("ASP.NET") != ss._canon_skill(".NET")


@pytest.mark.parametrize("required", _LANGS)
@pytest.mark.parametrize("has", _LANGS)
def test_c_family_matrix_dealbreaker(required, has):
    cand = _cand(skills=[{"name": has}])
    expected = [] if required == has else [required]
    assert missing_must_skills(cand, [required]) == expected


@pytest.mark.parametrize("required", _LANGS)
@pytest.mark.parametrize("has", _LANGS)
def test_c_family_matrix_gap_must(required, has):
    job = _job(must_skills=[required])
    cand = _cand(skills=[{"name": has}])
    _layer, matching, gap, _mn, _gn = ss._score_skills(cand, job)
    if required == has:
        assert gap == [] and len(matching) == 1
    else:
        assert matching == [] and len(gap) == 1


def test_scoring_cache_version_changed_for_canon():
    # Stale cached scores (C++ credited as C#) must recompute.
    from app.services.requirement_contract import MUST_GATE_POLICY_VERSION

    assert MUST_GATE_POLICY_VERSION == "known-technology-gap-v4"
    assert ss.scoring_algorithm_version()  # digest includes the new contracts


# ── SCV-02 ───────────────────────────────────────────────────────────────────


def _city_half(cand, job):
    # Kandydat chce zdalnie, oferta onsite → połowa remote = 0; zostaje miasto.
    return ss._score_location(cand, job).points


def test_same_country_different_city_earns_no_city_credit():
    job = _job(location="Warszawa, Polska")
    cand = _cand(location="Kraków, Polska", preferences={"remote_modes": ["remote"]})
    assert _city_half(cand, job) == 0.0


def test_blob_country_and_region_do_not_match_other_city():
    job = _job(
        location='{"locality":"Warszawa","region1":"Mazowieckie","country":"Polska"}'
    )
    cand = _cand(
        location='{"locality":"Radom","region1":"Mazowieckie","country":"Polska"}',
        preferences={"remote_modes": ["remote"]},
    )
    assert _city_half(cand, job) == 0.0


def test_same_city_earns_full_city_half():
    job = _job(location="Warszawa, Polska")
    cand = _cand(
        location='{"locality":"Warszawa","country":"Polska"}',
        preferences={"remote_modes": ["remote"]},
    )
    assert _city_half(cand, job) == pytest.approx(ss.LOCATION_MAX / 2.0)


def test_country_only_candidate_is_unknown_not_mismatch():
    job = _job(location="Warszawa")
    cand = _cand(location="Polska", preferences={"remote_modes": ["remote"]})
    assert _city_half(cand, job) == pytest.approx(
        ss.LOCATION_MAX / 2.0 * ss.UNKNOWN_NEUTRAL_FRACTION
    )


def test_city_tokens_drop_country_region_and_modes():
    assert city_tokens("Kraków, Małopolskie, Polska / remote") == {"kraków"}
    assert city_tokens("województwo mazowieckie") == set()
    assert city_tokens('{"locality":"Gdańsk","region1":"Pomorskie"}') == {"gdańsk"}


# ── SCV-03 ───────────────────────────────────────────────────────────────────


def test_requirement_map_reads_matching_requirements_contract():
    job = _job(
        must_skills=["Cobol"],
        nice_skills=["Fortran"],
        matching_requirements={
            "reviewed": True,
            "all_of": [
                {"any_of": ["python"], "level": "must"},
                {"any_of": ["docker"], "level": "nice"},
            ],
        },
    )
    reqs = build_requirements(job)
    assert reqs == [
        {"name": "python", "kind": "must"},
        {"name": "docker", "kind": "nice"},
    ]


def test_empty_stored_contract_does_not_resurrect_old_columns():
    job = _job(
        must_skills=["Cobol"],
        nice_skills=["Fortran"],
        matching_requirements={"reviewed": True, "all_of": []},
    )
    assert build_requirements(job) == []


def test_requirement_map_keeps_display_case_from_columns():
    job = _job(must_skills=["Python", "Kafka"], nice_skills=["Docker"])
    assert build_requirements(job) == [
        {"name": "Python", "kind": "must"},
        {"name": "Kafka", "kind": "must"},
        {"name": "Docker", "kind": "nice"},
    ]


def test_requirement_map_falls_back_to_champion_stack_must_and_nice():
    job = _job(
        requirements_reviewed=False,
        champion_profile={"stack": {"must": ["Java"], "nice": ["Spring"]}},
    )
    assert build_requirements(job) == [
        {"name": "Java", "kind": "must"},
        {"name": "Spring", "kind": "nice"},
    ]
