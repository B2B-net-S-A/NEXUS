"""Unit tests for the CV enrichment pure-function (Phase D4).

Covers the `_apply_cv_enrichment` seam: how parsed LLM output is folded
into a Candidate record. The background-task wrapper is integration-tested
via test_candidates.py — here we stay schema-level.
"""

from __future__ import annotations

from app.api.candidates import _apply_cv_enrichment
from app.models.candidate import Candidate


def _bare_candidate(**overrides) -> Candidate:
    return Candidate(
        id=overrides.get("id", 1),
        name="Jan",
        lastname="Kowalski",
        raw_cv_text="whatever",
        experience=overrides.get("experience", []),
        cv_extracted_data=overrides.get("cv_extracted_data", {}),
        ai_summary=overrides.get("ai_summary"),
    )


# ── Happy path ──────────────────────────────────────────────────────────────


def test_apply_populates_summary_companies_and_experience():
    c = _bare_candidate()
    parsed = {
        "years_it_experience": 8,
        "current_position": "Senior Python Developer",
        "skills": [{"name": "Python", "level": "senior", "years": 8}],
        "education": [],
        "languages": [],
        "companies": ["Acme Corp", "Globex"],
        "career_summary": "8 lat Pythona w fintechu.",
        "_source": "claude:cv_enrichment:v2",
    }

    written = _apply_cv_enrichment(c, parsed)

    assert written == 2
    assert c.ai_summary == "8 lat Pythona w fintechu."
    assert c.years_it_experience == 8
    assert c.cv_extracted_data["companies"] == ["Acme Corp", "Globex"]
    assert c.cv_extracted_data["_source"] == "claude:cv_enrichment:v2"
    assert [e["company"] for e in c.experience] == ["Acme Corp", "Globex"]
    assert all(e["role"] is None for e in c.experience)
    assert c.cv_parsed_at is not None


def test_apply_empty_parse_result_preserves_candidate():
    c = _bare_candidate(ai_summary="pre-existing")
    parsed = {
        "years_it_experience": None,
        "current_position": None,
        "skills": [],
        "education": [],
        "languages": [],
        "companies": [],
        "career_summary": None,
        "_source": "regex",
    }
    written = _apply_cv_enrichment(c, parsed)
    assert written == 0
    # Null career_summary should NOT overwrite a pre-existing summary.
    assert c.ai_summary == "pre-existing"
    assert c.experience == []


# ── Manual override guard ───────────────────────────────────────────────────


def test_apply_respects_manual_override_flag():
    """When recruiter flagged experience, AI must not overwrite it."""
    rich_experience = [
        {
            "company": "MyCompany",
            "role": "Lead Engineer",
            "start": "2020-01-01",
            "end": None,
            "desc": "Curated by hand",
        }
    ]
    c = _bare_candidate(
        experience=rich_experience,
        cv_extracted_data={"_manual_override_experience": True},
    )
    parsed = {
        "years_it_experience": 10,
        "current_position": None,
        "skills": [],
        "education": [],
        "languages": [],
        "companies": ["DifferentCompany"],
        "career_summary": "summary",
        "_source": "claude:cv_enrichment:v2",
    }

    written = _apply_cv_enrichment(c, parsed)

    assert written == 0
    assert c.ai_summary == "summary"  # non-contested field still updated
    assert c.experience == rich_experience  # contested field preserved
    # Flag survives across writes.
    assert c.cv_extracted_data["_manual_override_experience"] is True


def test_apply_preserves_rich_experience_when_ai_has_only_strings():
    """Bulk-import data with roles must not be downgraded by AI's flat list."""
    rich = [
        {
            "company": "Acme Corp",
            "role": "Senior Developer",
            "start": "2019-01-01",
            "end": "2022-12-31",
            "desc": "Led migrations.",
        }
    ]
    c = _bare_candidate(experience=rich)
    parsed = {
        "companies": ["Acme Corp", "Globex"],
        "career_summary": "s",
        "skills": [],
        "education": [],
        "languages": [],
        "years_it_experience": None,
        "current_position": None,
        "_source": "claude:cv_enrichment:v2",
    }
    written = _apply_cv_enrichment(c, parsed)
    assert written == 0
    assert c.experience == rich


def test_apply_overwrites_experience_when_only_placeholders_present():
    """If existing experience has no roles (AI seed from older run), allow
    refresh with newer company list."""
    placeholders = [
        {"company": "OldCorp", "role": None, "start": None, "end": None, "desc": None}
    ]
    c = _bare_candidate(experience=placeholders)
    parsed = {
        "companies": ["NewCorp1", "NewCorp2"],
        "career_summary": None,
        "skills": [],
        "education": [],
        "languages": [],
        "years_it_experience": None,
        "current_position": None,
        "_source": "claude:cv_enrichment:v2",
    }
    written = _apply_cv_enrichment(c, parsed)
    assert written == 2
    assert [e["company"] for e in c.experience] == ["NewCorp1", "NewCorp2"]


# ── Skills / education / languages guards ───────────────────────────────────


def test_apply_does_not_overwrite_skills_with_empty_list():
    """Empty skill list from a regex miss must not clobber curated skills."""
    c = _bare_candidate()
    c.skills = [{"name": "Python", "level": "senior", "years": 5}]
    parsed = {
        "skills": [],
        "companies": [],
        "career_summary": None,
        "education": [],
        "languages": [],
        "years_it_experience": None,
        "current_position": None,
        "_source": "regex",
    }
    _apply_cv_enrichment(c, parsed)
    assert c.skills == [{"name": "Python", "level": "senior", "years": 5}]


# ── v4: contact field backfill (email / phone / name / city) ───────────────


def _blank_candidate() -> Candidate:
    """A fresh candidate with empty contact fields — mirrors /from-cv insert."""
    return Candidate(
        id=42,
        name="Nieznane",      # placeholder written by /from-cv when LLM returned null
        lastname="Nieznane",
        email=None,
        phone=None,
        location=None,
        city=None,
        raw_cv_text="whatever",
        experience=[],
        cv_extracted_data={},
    )


def test_apply_fills_empty_contact_fields():
    c = _blank_candidate()
    parsed = {
        "first_name": "Anna",
        "last_name": "Nowak",
        "email": "anna.nowak@example.com",
        "phone": "+48 600 123 456",
        "city": "Warszawa",
        "skills": [],
        "education": [],
        "languages": [],
        "companies": [],
        "years_it_experience": None,
        "current_position": None,
        "career_summary": None,
        "_source": "claude:cv_enrichment:v4",
    }

    _apply_cv_enrichment(c, parsed)

    assert c.name == "Anna"
    assert c.lastname == "Nowak"
    assert c.email == "anna.nowak@example.com"
    assert c.phone == "+48 600 123 456"
    assert c.city == "Warszawa"
    assert c.location == "Warszawa"  # legacy column mirrors city


def test_apply_preserves_manually_typed_contact_fields():
    """Recruiter-typed email/phone/name must NEVER be overwritten by CV re-parse."""
    c = Candidate(
        id=7,
        name="Jan",
        lastname="Kowalski",
        email="jan@typed.pl",
        phone="123456789",
        city="Kraków",
        location="Kraków",
        raw_cv_text="x",
        experience=[],
        cv_extracted_data={},
    )
    parsed = {
        "first_name": "Janusz",
        "last_name": "Nowak",
        "email": "janusz@cv.pl",
        "phone": "+48 999 888 777",
        "city": "Warszawa",
        "skills": [],
        "education": [],
        "languages": [],
        "companies": [],
        "years_it_experience": None,
        "current_position": None,
        "career_summary": None,
        "_source": "claude:cv_enrichment:v4",
    }

    _apply_cv_enrichment(c, parsed)

    assert c.name == "Jan"
    assert c.lastname == "Kowalski"
    assert c.email == "jan@typed.pl"
    assert c.phone == "123456789"
    assert c.city == "Kraków"


def test_apply_respects_per_field_manual_override_flag():
    """Explicit _manual_override_<field> blocks backfill even if value looks empty."""
    c = Candidate(
        id=9,
        name="Nieznane",
        lastname="Nieznane",
        email=None,
        phone=None,
        raw_cv_text="x",
        experience=[],
        cv_extracted_data={
            "_manual_override_email": True,
            "_manual_override_first_name": True,
        },
    )
    parsed = {
        "first_name": "Ala",
        "last_name": "Kot",
        "email": "cv@cv.pl",
        "phone": "+48 111 222 333",
        "city": None,
        "skills": [],
        "education": [],
        "languages": [],
        "companies": [],
        "years_it_experience": None,
        "current_position": None,
        "career_summary": None,
        "_source": "claude:cv_enrichment:v4",
    }

    _apply_cv_enrichment(c, parsed)

    # Locked fields stay blank
    assert c.name == "Nieznane"
    assert c.email is None
    # Unlocked fields get filled
    assert c.lastname == "Kot"
    assert c.phone == "+48 111 222 333"
    # Flags survive into the next cv_extracted_data snapshot
    assert c.cv_extracted_data["_manual_override_email"] is True
    assert c.cv_extracted_data["_manual_override_first_name"] is True


def test_apply_truncates_long_contact_values():
    c = _blank_candidate()
    parsed = {
        "first_name": "A" * 200,     # name column is VARCHAR(100)
        "last_name": "B" * 300,
        "email": "x@" + "y" * 260 + ".pl",  # > 255
        "phone": "+48 " + "9" * 100,        # > 30
        "city": "C" * 200,                  # > 120
        "skills": [],
        "education": [],
        "languages": [],
        "companies": [],
        "years_it_experience": None,
        "current_position": None,
        "career_summary": None,
        "_source": "regex",
    }
    _apply_cv_enrichment(c, parsed)
    assert len(c.name) == 100
    assert len(c.lastname) == 100
    assert len(c.email) <= 255
    assert len(c.phone) <= 30
    assert len(c.city) <= 120
