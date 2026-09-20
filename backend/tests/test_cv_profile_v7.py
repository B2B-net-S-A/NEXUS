"""Pełny profil kandydata z odczytu CV v7 (17.09.2026).

Kontrakty:

- prompt v7 prosi o technologie per stanowisko, certyfikaty, projekty i daty
  użycia skilli; bieg masowy (`CV_ENRICHMENT_BULK`) zostaje bez zmian;
- długie CV trafia do modelu z zachowanym KOŃCEM (wykształcenie, certyfikaty);
- odczyt v6 ma dokładnie ten sam kształt co przed zmianą, a stare profile
  dają bajt w bajt ten sam tekst embeddingu (zero ponownego indeksowania);
- oś technologii liczy Python z dat, nie model;
- opis stanowiska z CV nie blokuje nadpisania historii nowym CV, opis z importu
  Traffita blokuje jak dotąd;
- waga świeżości skilli działa tylko za flagą i tylko dla profili v7.
"""

from __future__ import annotations

import os
from datetime import date
from types import SimpleNamespace

import pytest

from app.core.config import settings
from app.services import canonical_text as ct
from app.services import cv_enrichment as ce
from app.services import profile_projection as pp
from app.services.cv_parser import (
    _cv_input_for,
    _max_tokens_for,
    _normalize_cv_output,
    _window_cv_text,
)
from app.services.embedding_service import _build_candidate_text_v1
from app.services.llm_prompts import CV_ENRICHMENT, CV_ENRICHMENT_BULK

V7 = "claude:cv_enrichment:v7"


def _rich_parse(**overrides):
    raw = {
        "_source": V7,
        "first_name": "Anna",
        "years_it_experience": 9,
        "experience": [
            {
                "company": "Allegro sp. z o.o.",
                "role": "Senior Backend Developer",
                "start": "2021-03",
                "end": "present",
                "technologies": ["Kafka", "Java", "Kubernetes"],
                "description": "Płatności i rozliczenia.",
                "employment_type": "B2B",
                "location": "Poznań",
            },
            {
                "company": "ING Bank Śląski S.A.",
                "role": "Java Developer",
                "start": "2016",
                "end": "2021-02",
                "technologies": ["Java", "Oracle"],
                "client": "ING Tech",
            },
        ],
        "skills": [
            {"name": "Java", "level": "senior", "years": 9},
            {"name": "COBOL", "first_used": "2010", "last_used": "2012"},
        ],
        "education": [
            {
                "degree": "mgr inż.",
                "field": "Informatyka",
                "school": "Politechnika Poznańska",
                "start_year": 2011,
                "end_year": 2016,
                "level": "master",
            }
        ],
        "certifications": [{"name": "CKA", "issuer": "CNCF", "year": 2023}],
        "projects": [{"name": "Nowy system płatności", "technologies": ["Go"]}],
        "achievements": ["Skrócenie czasu rozliczeń o 40%"],
        "sectors": ["e-commerce", "banking"],
    }
    raw.update(overrides)
    return _normalize_cv_output(raw)


def _blank_candidate(**overrides):
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


@pytest.fixture(autouse=True)
def _no_location_writer(monkeypatch):
    monkeypatch.setattr(ce, "apply_candidate_location_from_source", lambda *a, **k: None)


# ── prompt i wejście ─────────────────────────────────────────────────────────


def test_v7_prompt_asks_for_the_full_profile_and_bulk_template_is_untouched():
    rendered = CV_ENRICHMENT.render(cv_text="x")
    for key in (
        '"certifications"',
        '"projects"',
        '"achievements"',
        '"first_used"',
        '"last_used"',
        '"employment_type"',
        '"start_year"',
    ):
        assert key in rendered, key
    bulk = CV_ENRICHMENT_BULK.render(cv_text="x")
    assert '"certifications"' not in bulk
    assert _max_tokens_for(CV_ENRICHMENT_BULK) == 3000
    # 8000 od 18.09.2026 (było 6000). Zmierzone na produkcji 16–18.09: 52
    # wywołania `outcome='truncated'` ($3,64) przy średnim wyjściu 5885 tokenów,
    # czyli tuż pod dawnym sufitem — normalne CV, nie monstrualne. Ucięta
    # odpowiedź jest zapłacona i bezużyteczna (JSON się nie parsuje, ścieżka
    # spada do regexu). Bieg masowy zostaje przy 3000 — jego prompt nie prosi
    # o pola generatywne, więc tam sufit nie był problemem.
    assert _max_tokens_for(CV_ENRICHMENT) == 8000


def test_long_cv_keeps_its_tail_for_the_rich_read_only():
    text = "HEAD" + "a" * 40_000 + "CERTYFIKATY CKA"
    windowed = _cv_input_for(CV_ENRICHMENT, text)
    assert len(windowed) == settings.CV_PARSER_INPUT_CHAR_CAP
    assert windowed.startswith("HEAD")
    assert windowed.endswith("CERTYFIKATY CKA")
    assert "[…]" in windowed
    assert _cv_input_for(CV_ENRICHMENT_BULK, text) == text[:8000]
    assert _window_cv_text("krótkie", 100) == "krótkie"


# ── normalizacja ─────────────────────────────────────────────────────────────


def test_v6_shaped_experience_keeps_exactly_the_old_keys():
    out = _normalize_cv_output(
        {"experience": [{"company": "Acme", "role": "Dev", "start": "2019", "end": "2020"}]}
    )
    assert out["experience"] == [
        {"company": "Acme", "role": "Dev", "start": "2019", "end": "2020"}
    ]


def test_rich_fields_are_validated_and_capped():
    out = _rich_parse(
        certifications=["AWS SAA", {"name": "aws saa"}, {"issuer": "bez nazwy"}],
        achievements=["  jedno  ", 5, ""],
        education=[{"school": "PW", "end_year": "1066"}, "Liceum im. Kopernika", 7],
    )
    assert [c["name"] for c in out["certifications"]] == ["AWS SAA"]
    assert out["achievements"] == ["jedno"]
    assert out["education"][0] == {
        "degree": None,
        "field": None,
        "school": "PW",
        "year": None,
    }
    assert out["education"][1]["school"] == "Liceum im. Kopernika"
    entry = _rich_parse()["experience"][0]
    assert entry["employment_type"] == "b2b"
    assert entry["technologies"] == ["Kafka", "Java", "Kubernetes"]


def test_skill_dates_are_normalized_and_bad_ones_dropped():
    out = _normalize_cv_output(
        {
            "skills": [
                {"name": "Go", "first_used": "03.2020", "last_used": "obecnie"},
                {"name": "Perl", "first_used": "kiedyś", "last_used": None},
            ]
        }
    )
    assert out["skills"][0]["first_used"] == "2020-03"
    assert out["skills"][0]["last_used"] == "present"
    assert "first_used" not in out["skills"][1]
    assert ce.normalize_llm_skills(out["skills"])[0]["last_used"] == "present"


# ── zapis profilu ────────────────────────────────────────────────────────────


def test_rich_parse_writes_full_experience_timeline_and_schema_stamp():
    candidate = _blank_candidate()
    ce._apply_cv_enrichment(candidate, _rich_parse(), policy=ce.CvWritePolicy.REFRESH)

    first, second = candidate.experience
    assert first["desc"] == "Płatności i rozliczenia."
    assert first["technologies"] == ["Kafka", "Java", "Kubernetes"]
    assert first["is_current"] is True
    assert first["company_norm"] == "allegro"
    assert first["source"] == "cv"
    assert second["client"] == "ING Tech"
    assert second["is_current"] is False

    extracted = candidate.cv_extracted_data
    assert extracted["_profile_schema"] == pp.PROFILE_SCHEMA_VERSION
    assert extracted["certifications"][0]["name"] == "CKA"
    assert extracted["projects"][0]["name"] == "Nowy system płatności"
    skills = {row["skill"]: row for row in extracted["skill_timeline"]}
    assert skills["Java"]["first_used"] == "2016"
    assert skills["Java"]["is_current"] is True
    assert skills["Oracle"]["last_used"] == "2021-02"
    assert skills["COBOL"]["last_used"] == "2012"
    assert candidate.education[0]["end_year"] == 2016


def test_v6_parse_does_not_stamp_the_rich_schema():
    candidate = _blank_candidate()
    parsed = _normalize_cv_output(
        {
            "_source": "claude:cv_enrichment:v6",
            "experience": [
                {"company": "Acme", "role": "Dev", "start": "2019", "end": "present"}
            ],
        }
    )
    ce._apply_cv_enrichment(candidate, parsed, policy=ce.CvWritePolicy.REFRESH)
    assert "_profile_schema" not in candidate.cv_extracted_data
    assert "skill_timeline" not in candidate.cv_extracted_data
    assert candidate.experience == [
        {"company": "Acme", "role": "Dev", "start": "2019", "end": "present", "desc": None}
    ]


def test_cv_description_does_not_freeze_history_but_traffit_description_does():
    candidate = _blank_candidate()
    ce._apply_cv_enrichment(candidate, _rich_parse(), policy=ce.CvWritePolicy.REFRESH)
    newer = _rich_parse(
        experience=[
            {"company": "Nowa Firma", "role": "Architect", "start": "2025", "end": "present"}
        ]
    )
    ce._apply_cv_enrichment(candidate, newer, policy=ce.CvWritePolicy.REFRESH)
    assert candidate.experience[0]["company"] == "Nowa Firma"

    imported = _blank_candidate(
        experience=[{"company": "Stara", "role": "Dev", "desc": "z Traffita"}]
    )
    ce._apply_cv_enrichment(imported, newer, policy=ce.CvWritePolicy.REFRESH)
    assert imported.experience[0]["company"] == "Stara"


def test_manual_certifications_lock_survives_a_new_cv():
    candidate = _blank_candidate(
        cv_extracted_data={
            "_manual_override_certifications": True,
            "certifications": [{"name": "Wpisany ręcznie"}],
        }
    )
    ce._apply_cv_enrichment(candidate, _rich_parse(), policy=ce.CvWritePolicy.REFRESH)
    assert candidate.cv_extracted_data["certifications"] == [{"name": "Wpisany ręcznie"}]
    assert candidate.cv_extracted_data["_manual_override_certifications"] is True


def test_quarantine_rebuilds_the_exact_written_experience_shape():
    """Kwarantanna tożsamości cofa zapis, porównując z `cv_experience_entries`."""
    candidate = _blank_candidate()
    ce._apply_cv_enrichment(candidate, _rich_parse(), policy=ce.CvWritePolicy.REFRESH)
    assert ce.cv_experience_entries(candidate.cv_extracted_data) == candidate.experience


# ── oś technologii ───────────────────────────────────────────────────────────


def test_timeline_counts_overlapping_periods_once_and_sorts_by_recency():
    timeline = pp.build_skill_timeline(
        experience=[
            {"company": "A", "role": "x", "start": "2020-01", "end": "2020-12", "technologies": ["Go"]},
            {"company": "B", "role": "y", "start": "2020-06", "end": "2021-05", "technologies": ["Go"]},
            {"company": "C", "role": "z", "start": "2015-01", "end": "2015-12", "technologies": ["PHP"]},
        ],
        skills=[],
        today=date(2026, 9, 17),
    )
    assert [row["skill"] for row in timeline] == ["Go", "PHP"]
    assert timeline[0]["months"] == 17
    assert timeline[0]["first_used"] == "2020-01"
    assert timeline[0]["last_used"] == "2021-05"
    assert len(timeline[0]["contexts"]) == 2


def test_missing_end_date_is_not_counted_as_ongoing():
    timeline = pp.build_skill_timeline(
        experience=[{"company": "A", "role": "x", "start": "2018", "end": None, "technologies": ["Rust"]}],
        skills=[],
        today=date(2026, 9, 17),
    )
    assert timeline[0]["months"] is None
    assert timeline[0]["is_current"] is False
    assert timeline[0]["last_used"] == "2018"


def test_undated_skill_stays_off_the_timeline():
    assert (
        pp.build_skill_timeline(
            experience=[{"company": "A", "role": "x", "technologies": ["Scala"]}],
            skills=[{"name": "Haskell"}],
        )
        == []
    )


def test_skill_usage_rows_need_the_rich_schema_and_dedupe():
    extracted = {
        "_profile_schema": 2,
        "cv_highlights": {"source_hash": "abc"},
        "skill_timeline": [
            {"skill": "Kafka", "first_used": "2021-03", "last_used": "2026-09", "months": 67, "is_current": True},
            {"skill": "kafka", "first_used": "2019", "last_used": "2019"},
        ],
    }
    rows = pp.skill_usage_rows(7, extracted)
    assert len(rows) == 1
    assert rows[0]["first_used"] == date(2021, 3, 1)
    assert rows[0]["last_used"] == date(2026, 9, 1)
    assert rows[0]["source_ref"] == "abc"
    assert pp.skill_usage_rows(7, {"skill_timeline": extracted["skill_timeline"]}) == []


# ── tekst embeddingu ─────────────────────────────────────────────────────────


def _embedding_candidate(**overrides):
    base = dict(
        name="Jan",
        lastname="Kowalski",
        competence_category="software_development",
        years_it_experience=8,
        skills=[{"name": "Python"}],
        verified_tech=[],
        experience=[{"role": "Dev", "company": "Acme", "desc": "APIs"}],
        tags=[],
        preferences={},
        ai_summary="Backend.",
        raw_cv_text="CV",
        cv_extracted_data=None,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def test_legacy_profile_text_is_byte_for_byte_unchanged():
    """Stary profil (także z `cv_highlights` z odczytu v6) nie zmienia tekstu."""
    plain = _embedding_candidate()
    with_v6 = _embedding_candidate(
        cv_extracted_data={
            "cv_highlights": {"sectors": ["banking"], "generated_at": "2026-01-01"},
            "certifications": [{"name": "CKA"}],
        }
    )
    assert _build_candidate_text_v1(plain) == _build_candidate_text_v1(with_v6)
    assert ct.build_candidate_text_v2(plain) == ct.build_candidate_text_v2(with_v6)


def test_rich_profile_text_carries_certs_sectors_role_tech_and_recent_skills():
    candidate = _blank_candidate()
    ce._apply_cv_enrichment(candidate, _rich_parse(), policy=ce.CvWritePolicy.REFRESH)
    rich = _embedding_candidate(
        experience=candidate.experience, cv_extracted_data=candidate.cv_extracted_data
    )
    v1 = _build_candidate_text_v1(rich)
    assert "certifications: CKA" in v1
    assert "sectors: e-commerce, banking" in v1
    assert "Kubernetes" in v1
    assert "recent:" in v1 and "COBOL" not in v1.split("recent:")[1]
    v2 = ct.build_candidate_text_v2(rich)
    assert "[CERTIFICATIONS] CKA" in v2
    assert "[Kafka, Java, Kubernetes]" in v2


def test_recent_skills_are_anchored_to_the_parse_date_not_the_clock():
    extracted = {
        "_profile_schema": 2,
        "cv_highlights": {"generated_at": "2020-05-01T00:00:00+00:00"},
        "skill_timeline": [
            {"skill": "Angular", "last_used": "2018"},
            {"skill": "jQuery", "last_used": "2012"},
        ],
    }
    facts = pp.rich_profile_text_facts(SimpleNamespace(cv_extracted_data=extracted))
    assert facts["recent_skills"] == ["Angular"]


# ── scoring: waga świeżości ──────────────────────────────────────────────────


def _scored_candidate(timeline):
    return SimpleNamespace(
        cv_extracted_data={"_profile_schema": 2, "skill_timeline": timeline}
        if timeline is not None
        else None
    )


def test_recency_weights_are_off_by_default_and_neutral_for_legacy(monkeypatch):
    from app.services import scoring_service as ss

    old = [{"skill": "Java", "last_used": "2012"}]
    monkeypatch.setattr(settings, "AI_SCORING_SKILL_RECENCY", False)
    assert ss._skill_recency_weights(_scored_candidate(old), object(), ["Java"]) == {}
    monkeypatch.setattr(settings, "AI_SCORING_SKILL_RECENCY", True)
    assert ss._skill_recency_weights(_scored_candidate(None), object(), ["Java"]) == {}


def test_recency_weights_discount_long_unused_skills(monkeypatch):
    from app.services import scoring_service as ss

    monkeypatch.setattr(settings, "AI_SCORING_SKILL_RECENCY", True)
    this_year = date.today().year
    timeline = [
        {"skill": "Java", "last_used": str(this_year)},
        {"skill": "Scala", "last_used": str(this_year - 5)},
        {"skill": "PostgreSQL", "last_used": str(this_year - 10)},
    ]
    weights = ss._skill_recency_weights(
        _scored_candidate(timeline), object(), ["Java", "Scala", "postgres", "Rust"]
    )
    assert weights == {"Scala": 0.75, "postgres": 0.5}
    assert "AI_SCORING_SKILL_RECENCY" in ss._SCORING_CACHE_INPUTS


# ── indeks w bazie ───────────────────────────────────────────────────────────


@pytest.mark.skipif(
    not os.environ.get("DATABASE_URL"), reason="wymaga PostgreSQL (candidate_skill_usage)"
)
async def test_replace_skill_usage_is_idempotent():
    from sqlalchemy import func, select

    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from app.models.candidate_skill_usage import CandidateSkillUsage

    async with AsyncSessionLocal() as db:
        try:
            candidate = Candidate(name="Oś", lastname="Technologii")
            db.add(candidate)
            await db.flush()
            ce._apply_cv_enrichment(candidate, _rich_parse(), policy=ce.CvWritePolicy.REFRESH)
            first = await pp.replace_skill_usage(db, candidate)
            second = await pp.replace_skill_usage(db, candidate)
            stored = await db.scalar(
                select(func.count())
                .select_from(CandidateSkillUsage)
                .where(CandidateSkillUsage.candidate_id == candidate.id)
            )
            assert first == second == stored
            assert stored >= 4
        finally:
            await db.rollback()


def test_weaker_parse_keeps_rich_profile_but_explicit_refresh_drops_it():
    candidate = _blank_candidate()
    ce._apply_cv_enrichment(candidate, _rich_parse(), policy=ce.CvWritePolicy.REFRESH)
    weaker = _normalize_cv_output({"_source": "regex", "first_name": "Anna"})

    ce._apply_cv_enrichment(candidate, weaker, policy=ce.CvWritePolicy.FILL_EMPTY)
    kept = candidate.cv_extracted_data
    assert kept["_profile_schema"] == pp.PROFILE_SCHEMA_VERSION
    assert kept["certifications"][0]["name"] == "CKA"
    assert kept["skill_timeline"]

    ce._apply_cv_enrichment(candidate, weaker, policy=ce.CvWritePolicy.REFRESH)
    assert "_profile_schema" not in candidate.cv_extracted_data
    assert pp.skill_usage_rows(1, candidate.cv_extracted_data) == []
