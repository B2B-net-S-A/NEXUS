"""Odczyt CV v9 (07.11.2026): pola zbierane raz, przed ponownym odczytem bazy.

Kontrakty:

- stanowisko niesie branżę, wielkość prowadzonego zespołu i regulacje;
- kandydat ma poziom seniority w kanonie `Job.seniority` i obywatelstwo
  tylko z CV, które je nazywa;
- regulacja bez śladu w CV wypada przed zapisem;
- słabszy odczyt (szablon masowy) nie kasuje pól v9 z wcześniejszego pełnego;
- karta rekomendacji bierze obywatelstwo z CV dopiero po karcie i Traffcie.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from app.api.recommendation_cards import _nationality_suggestion
from app.services import cv_enrichment as ce
from app.services.cv_parser import _normalize_cv_output, drop_untraced_profile_facts
from app.services.llm_prompts import CV_ENRICHMENT

V9 = "claude:cv_enrichment:v9"


@pytest.fixture(autouse=True)
def _no_location_writer(monkeypatch):
    monkeypatch.setattr(
        ce, "apply_candidate_location_from_source", lambda *a, **k: None
    )


def _candidate(**overrides):
    base = dict(
        cv_extracted_data={},
        experience=[],
        skills=[],
        education=[],
        years_it_experience=None,
        ai_summary=None,
        linkedin=None,
        name="?",
        lastname=None,
        email=None,
        phone=None,
        city=None,
        country=None,
        location=None,
        cv_parsed_at=None,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _v9_parse(**overrides):
    raw = {
        "_source": V9,
        "seniority_level": "Senior",
        "nationality": "polskie",
        "experience": [
            {
                "company": "Bank X",
                "role": "Team Lead",
                "start": "2020-01",
                "end": "present",
                "technologies": ["Java"],
                "sector": "banking",
                "team_size": "6",
                "regulations": ["PSD2", "KNF"],
            }
        ],
        "sectors": [f"Sektor {i}" for i in range(12)],
    }
    raw.update(overrides)
    return _normalize_cv_output(raw)


def test_prompt_v9_asks_for_new_fields():
    rendered = CV_ENRICHMENT.render(cv_text="x")
    assert CV_ENRICHMENT.version == 9
    for field in (
        '"sector"',
        '"team_size"',
        '"regulations"',
        '"seniority_level"',
        '"nationality"',
    ):
        assert field in rendered
    assert "(max 8)" in rendered


def test_normalization_keeps_role_facts_and_caps_sectors():
    parsed = _v9_parse()
    role = parsed["experience"][0]
    assert role["sector"] == "banking"
    assert role["team_size"] == 6
    assert role["regulations"] == ["PSD2", "KNF"]
    assert parsed["seniority_level"] == "senior"
    assert parsed["nationality"] == "polskie"
    assert len(parsed["sectors"]) == 8


@pytest.mark.parametrize("raw", [0, -3, 10_000, True, "kilku", 2.5, None])
def test_team_size_outside_range_or_not_a_number_is_dropped(raw):
    role = _v9_parse(
        experience=[{"company": "Firma", "role": "Dev", "team_size": raw}]
    )["experience"][0]
    assert "team_size" not in role


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Senior", "senior"),
        ("regular", "mid"),
        ("intern", "junior"),
        ("principal", None),
        (3, None),
    ],
)
def test_seniority_maps_to_job_seniority_canon(raw, expected):
    assert _v9_parse(seniority_level=raw)["seniority_level"] == expected


def test_v8_output_has_no_v9_keys():
    parsed = _normalize_cv_output(
        {"experience": [{"company": "Firma", "role": "Dev", "start": "2020"}]}
    )
    assert set(parsed["experience"][0]) == {"company", "role", "start", "end"}
    assert "seniority_level" not in parsed
    assert "nationality" not in parsed


def test_nationality_without_cue_in_cv_is_dropped():
    parsed = {"nationality": "Ukrainian", "experience": []}
    drop_untraced_profile_facts(parsed, "Jan Kowalenko, Kijów, Java developer")
    assert parsed["nationality"] is None


def test_nationality_with_cue_in_cv_is_kept():
    parsed = {"nationality": "polskie", "experience": []}
    drop_untraced_profile_facts(parsed, "Dane osobowe\nObywatelstwo: polskie")
    assert parsed["nationality"] == "polskie"


def test_regulations_without_trace_are_dropped_aliases_and_norm_numbers_kept():
    parsed = {
        "experience": [
            {"company": "Bank", "regulations": ["GDPR", "ISO 27001", "PSD2", "", 7]}
        ]
    }
    cv = "Wdrożenie zgodności z RODO. Audyt ISO/IEC 27001:2013 w banku."
    drop_untraced_profile_facts(parsed, cv)
    assert parsed["experience"][0]["regulations"] == ["GDPR", "ISO 27001"]


def test_rich_v9_read_writes_role_facts_and_profile_keys():
    candidate = _candidate()
    ce._apply_cv_enrichment(candidate, _v9_parse())
    role = candidate.experience[0]
    assert (role["sector"], role["team_size"], role["regulations"]) == (
        "banking",
        6,
        ["PSD2", "KNF"],
    )
    assert candidate.cv_extracted_data["seniority_level"] == "senior"
    assert candidate.cv_extracted_data["nationality"] == "polskie"


def test_weaker_read_keeps_v9_profile_keys():
    candidate = _candidate()
    ce._apply_cv_enrichment(candidate, _v9_parse())
    bulk = {"_source": "claude:cv_enrichment_bulk:v2", "skills": [{"name": "Go"}]}
    ce._apply_cv_enrichment(candidate, bulk, policy=ce.CvWritePolicy.FILL_EMPTY)
    assert candidate.cv_extracted_data["seniority_level"] == "senior"
    assert candidate.cv_extracted_data["nationality"] == "polskie"


class _NoCards:
    async def execute(self, _stmt):
        return SimpleNamespace(all=lambda: [])


def _suggest(extracted):
    candidate = SimpleNamespace(id=1, cv_extracted_data=extracted)
    return asyncio.run(_nationality_suggestion(_NoCards(), candidate, job_id=2))


def test_card_uses_cv_nationality_only_after_traffit():
    assert _suggest({"nationality": "polskie"}) == "polskie"
    assert _suggest({"traffit_nationality": "PL", "nationality": "polskie"}) == "PL"
    assert _suggest({"nationality": "  "}) is None
    assert _suggest(["nie słownik"]) is None
