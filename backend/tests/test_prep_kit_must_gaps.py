"""M03-B04: prep-kit twierdził „profil pasuje do wymagań" dla kandydata bez
umiejętności, bez CV i z brakującymi MUST — luki liczyły się wyłącznie z bazy
wiedzy klienta i screeningu, z pominięciem wymagań samej rekrutacji."""

from types import SimpleNamespace

import pytest

from app.api.prep_kit import _must_have_gaps, _no_gaps_message

pytestmark = pytest.mark.unit


def _job(must=None):
    return SimpleNamespace(
        id=7,
        must_skills=must,
        nice_skills=None,
        matching_requirements=None,
        requirements_reviewed=False,
        champion_profile=None,
    )


def _candidate(skills=None):
    return SimpleNamespace(
        skills=skills,
        verified_tech=None,
        cv_extracted_data=None,
        raw_cv_text=None,
        tags=None,
        skills_manually_curated=False,
    )


def test_missing_must_skills_are_listed_as_gaps():
    gaps = _must_have_gaps(
        _job(["Python", "PostgreSQL", "Docker"]), _candidate([{"name": "Python"}])
    )
    assert gaps == [
        "Brak PostgreSQL (MUST rekrutacji) w profilu — może być pytanie",
        "Brak Docker (MUST rekrutacji) w profilu — może być pytanie",
    ]


def test_candidate_without_skill_data_is_named_not_matched():
    gaps = _must_have_gaps(_job(["Python", "Docker"]), _candidate(None))
    assert len(gaps) == 1
    assert gaps[0].startswith("Brak danych o umiejętnościach kandydata")
    assert "Python, Docker" in gaps[0]
    assert "pasuje" not in _no_gaps_message(_job(["Python"]), _candidate(None))


def test_prose_requirements_are_not_reported_as_missing_skills():
    job = _job(["apache kafka – minimum 4 lata komercyjnego doświadczenia"])
    assert _must_have_gaps(job, _candidate([{"name": "Java"}])) == []
    assert "nie ma wymagań MUST" in _no_gaps_message(
        job, _candidate([{"name": "Java"}])
    )


def test_full_coverage_says_what_was_checked():
    job = _job(["Python"])
    candidate = _candidate([{"name": "Python"}])
    assert _must_have_gaps(job, candidate) == []
    assert _no_gaps_message(job, candidate) == (
        "Brak zidentyfikowanych luk — profil obejmuje wymagania MUST rekrutacji."
    )
