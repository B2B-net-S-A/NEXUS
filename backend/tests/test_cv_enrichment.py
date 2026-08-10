"""Unit tests for the CV enrichment pure-function (Phase D4).

Covers the `_apply_cv_enrichment` seam: how parsed LLM output is folded
into a Candidate record. The background-task wrapper is integration-tested
via test_candidates.py — here we stay schema-level.
"""

from __future__ import annotations

from app.api.candidates import CvWritePolicy, _apply_cv_enrichment
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
    assert c.ai_summary == (
        "8 lat Pythona w fintechu.\nAktualna rola: Senior Python Developer."
    )
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
    assert c.ai_summary == (
        "summary · 10 lat doświadczenia."
    )  # non-contested field still updated
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
        name="Nieznane",  # placeholder written by /from-cv when LLM returned null
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


def test_apply_cv_city_respects_manual_lock_and_rebuilds_projection():
    c = Candidate(
        id=43,
        name="Anna",
        lastname="Nowak",
        city="Kraków",
        country="PL",
        location="legacy-stale",
        raw_cv_text="whatever",
        experience=[],
        cv_extracted_data={"_manual_override_city": True},
    )

    _apply_cv_enrichment(
        c,
        {
            "city": "Warszawa",
            "skills": [],
            "education": [],
            "languages": [],
            "companies": [],
        },
    )

    assert c.city == "Kraków"
    assert c.country == "PL"
    assert c.location == "Kraków, PL"


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
        "first_name": "A" * 200,  # name column is VARCHAR(100)
        "last_name": "B" * 300,
        "email": "x@" + "y" * 260 + ".pl",  # > 255
        "phone": "+48 " + "9" * 100,  # > 30
        "city": "C" * 200,  # > 120
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


# ── Write policy: the fix for the silent-overwrite defect ───────────────────
#
# Until 2026-08-10 `skills`, `education`, `years_it_experience` and `ai_summary`
# were written unconditionally, while this module's docstring promised
# "Never clobbers recruiter-curated data". Every CV upload replaced whatever a
# recruiter had typed. These tests pin the corrected behaviour so the regression
# is a red build rather than silent data loss across the base.


def _curated_candidate() -> Candidate:
    c = _bare_candidate()
    c.skills = [{"name": "Rust", "level": "expert", "years": 5}]
    c.education = [{"school": "PW", "degree": "mgr", "field": "IT", "year": 2015}]
    c.years_it_experience = 12
    c.ai_summary = "Ręcznie napisane przez rekrutera."
    return c


_AI_PARSE = {
    "years_it_experience": 3,
    "skills": [{"name": "Python", "level": "junior", "years": 3}],
    "education": [{"school": "UW", "degree": "lic", "field": "X", "year": 2020}],
    "career_summary": "Trzy lata Pythona.",
    "_source": "claude:cv_enrichment:v5",
}


def test_fill_empty_is_the_default_and_protects_curated_values():
    """A caller that forgets the policy must degrade to backfill-only."""
    c = _curated_candidate()

    _apply_cv_enrichment(c, _AI_PARSE)  # no policy passed on purpose

    assert c.skills == [{"name": "Rust", "level": "expert", "years": 5}]
    assert c.education[0]["school"] == "PW"
    assert c.years_it_experience == 12
    assert c.ai_summary == "Ręcznie napisane przez rekrutera."


def test_fill_empty_writes_into_empty_slots():
    c = _bare_candidate()
    c.skills, c.education, c.years_it_experience, c.ai_summary = None, None, None, None

    _apply_cv_enrichment(c, _AI_PARSE, policy=CvWritePolicy.FILL_EMPTY)

    assert c.skills[0]["name"] == "Python"
    assert c.education[0]["school"] == "UW"
    assert c.years_it_experience == 3
    assert c.ai_summary


def test_empty_list_counts_as_empty():
    """Load-bearing: 33 625 prod rows hold `skills = []` against 273 real lists.

    Treating `[]` as a value would make the backfill skip 99% of its targets.
    """
    c = _bare_candidate()
    c.skills, c.education = [], []
    c.years_it_experience, c.ai_summary = None, None

    _apply_cv_enrichment(c, _AI_PARSE, policy=CvWritePolicy.FILL_EMPTY)

    assert c.skills[0]["name"] == "Python"
    assert c.education[0]["school"] == "UW"


def test_zero_years_counts_as_empty():
    c = _bare_candidate()
    c.years_it_experience = 0

    _apply_cv_enrichment(c, _AI_PARSE, policy=CvWritePolicy.FILL_EMPTY)

    assert c.years_it_experience == 3


def test_refresh_overwrites_but_still_honours_locks():
    """The upload/re-parse paths keep their old behaviour — minus locked fields."""
    c = _curated_candidate()
    c.cv_extracted_data = {"_manual_override_skills": True}

    _apply_cv_enrichment(c, _AI_PARSE, policy=CvWritePolicy.REFRESH)

    assert c.skills == [{"name": "Rust", "level": "expert", "years": 5}], (
        "a locked field must survive even an explicit REFRESH"
    )
    assert c.years_it_experience == 3, "unlocked fields are refreshed as before"


def test_every_manual_override_flag_survives_not_just_a_hardcoded_list():
    """`_manual_override_country` used to be dropped on every parse.

    The old code copied only `_CV_CONTACT_FIELDS`, silently unlocking a field
    that both importers set and the location writer reads. The fix is a prefix
    rule, so an invented flag must survive too — that is the difference between
    fixing one field and fixing the class.
    """
    c = _bare_candidate()
    c.cv_extracted_data = {
        "_manual_override_country": True,
        "_manual_override_zzz_future_field": True,
        "traffit_custom": "keep me",
    }

    _apply_cv_enrichment(c, _AI_PARSE)

    assert c.cv_extracted_data["_manual_override_country"] is True
    assert c.cv_extracted_data["_manual_override_zzz_future_field"] is True
    assert c.cv_extracted_data["traffit_custom"] == "keep me"


def test_provenance_recorded_only_for_fields_actually_written():
    c = _bare_candidate()
    c.skills = [{"name": "Rust"}]  # non-empty → must be skipped under FILL_EMPTY
    c.years_it_experience = None  # empty → will be written

    _apply_cv_enrichment(c, _AI_PARSE, policy=CvWritePolicy.FILL_EMPTY)

    prov = c.cv_extracted_data["_field_provenance"]
    assert "years_it_experience" in prov
    assert "skills" not in prov, "a skipped field must not claim AI provenance"
    assert prov["years_it_experience"]["source"] == "claude:cv_enrichment:v5"


def test_provenance_merges_across_runs():
    c = _bare_candidate()
    c.years_it_experience = None
    c.cv_extracted_data = {
        "_field_provenance": {"city": {"source": "earlier-run", "at": "2026-01-01"}}
    }

    _apply_cv_enrichment(c, _AI_PARSE)

    prov = c.cv_extracted_data["_field_provenance"]
    assert prov["city"]["source"] == "earlier-run", "untouched fields keep their stamp"
    assert "years_it_experience" in prov
