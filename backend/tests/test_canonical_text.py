"""Tests for canonical v2 embedding text (plan PR7).

Pure builders (no DB) plus the flag-driven dispatcher in embedding_service.
"""

from __future__ import annotations

from types import SimpleNamespace

from app.services import canonical_text as ct


def _cand(**kw) -> SimpleNamespace:
    base = dict(
        name="Jan",
        lastname="Kowalski",
        email="jan.kowalski@example.com",
        phone="+48123456789",
        city="Warszawa",
        competence_category="software_development",
        years_it_experience=8,
        skills=[{"name": "Python"}, {"name": "FastAPI"}],
        verified_tech=["PostgreSQL"],
        experience=[{"role": "Senior Dev", "company": "Acme", "desc": "Built APIs"}],
        preferences={"industries": ["fintech"]},
        tags=["backend"],
        ai_summary="Experienced backend engineer.",
        raw_cv_text="Jan Kowalski CV ...",
    )
    base.update(kw)
    return SimpleNamespace(**base)


def test_candidate_v2_excludes_pii():
    text = ct.build_candidate_text_v2(_cand())
    for pii in ("Jan", "Kowalski", "jan.kowalski@example.com", "+48123456789", "Warszawa"):
        assert pii not in text, f"PII leaked: {pii}"


def test_candidate_v2_has_labeled_sections_and_skills():
    text = ct.build_candidate_text_v2(_cand())
    assert "[ROLE] software_development" in text
    assert "[SENIORITY] 8+ years (senior)" in text
    assert "[SKILLS] Python, FastAPI" in text
    assert "[VERIFIED] PostgreSQL" in text
    assert "Built APIs" in text
    assert "[DOMAINS] fintech" in text


def test_skill_names_normalises_all_shapes():
    assert ct._skill_names([{"name": "Go"}, "Rust"]) == ["Go", "Rust"]
    assert ct._skill_names({"technologies": ["Java", "Kafka"]}) == ["Java", "Kafka"]
    assert ct._skill_names("C#, .NET; SQL") == ["C#", ".NET", "SQL"]
    # De-dupe case-insensitively, preserving first spelling.
    assert ct._skill_names(["Python", "python"]) == ["Python"]


def test_looks_like_junk():
    assert ct.looks_like_junk("(cid:12)(cid:9)(cid:44)") is True
    assert ct.looks_like_junk("   ") is True
    assert ct.looks_like_junk("Senior Python engineer") is False


def test_junk_summary_is_dropped():
    text = ct.build_candidate_text_v2(_cand(ai_summary="(cid:1)(cid:2)(cid:3)"))
    assert "SUMMARY" not in text


def test_raw_cv_used_only_as_fallback():
    # Structured sections present → raw CV not appended.
    assert "[CV]" not in ct.build_candidate_text_v2(_cand())
    # No structured content → fall back to (clean) raw CV.
    bare = SimpleNamespace(
        name="X",
        lastname="Y",
        competence_category=None,
        years_it_experience=None,
        skills=None,
        verified_tech=None,
        experience=None,
        preferences=None,
        ai_summary=None,
        raw_cv_text="Backend engineer with 10 years building distributed systems.",
    )
    out = ct.build_candidate_text_v2(bare)
    assert out.startswith("[CV]")
    assert "distributed systems" in out


def test_content_hash_stable():
    a = ct.content_hash("hello")
    assert a == ct.content_hash("hello")
    assert a != ct.content_hash("world")


def test_job_v2_strips_ref_noise_and_labels():
    job = SimpleNamespace(
        title="Senior Python Developer REF: ABC-123",
        seniority=SimpleNamespace(value="senior"),
        subcategory="backend",
        industry="fintech",
        must_skills=[{"name": "Python"}],
        nice_skills=[{"name": "Kafka"}],
        description="Build services.",
        requirements="Python, FastAPI",
        champion_profile={"project_context": {"about": "Great team"}},
    )
    text = ct.build_job_text_v2(job)
    assert "ABC-123" not in text  # ref noise stripped
    assert "[TITLE] Senior Python Developer" in text
    assert "[MUST_SKILLS] Python" in text
    assert "[NICE_SKILLS] Kafka" in text
    assert "[CHAMPION] Great team" in text


def test_dispatcher_selects_by_flag(monkeypatch):
    from app.core.config import settings
    from app.services import embedding_service as emb

    cand = _cand()
    monkeypatch.setattr(settings, "AI_TEXT_SCHEMA_V2", False)
    legacy = emb._build_candidate_text(cand)
    assert "Jan" in legacy  # legacy includes the name

    monkeypatch.setattr(settings, "AI_TEXT_SCHEMA_V2", True)
    v2 = emb._build_candidate_text(cand)
    assert "Jan" not in v2  # canonical excludes PII
    assert "[SKILLS]" in v2


# ── v3: pełne CV + fakty z notatek (runda 2) ─────────────────────────────────


def test_candidate_v3_includes_full_cv_always():
    """v2 dawał CV tylko jako fallback pustego szkieletu; v3 — zawsze."""
    long_cv = "Projekt migracji hurtowni danych. " * 300  # ~10k znaków
    cand = _cand(raw_cv_text=long_cv)
    v2 = ct.build_candidate_text_v2(cand)
    v3 = ct.build_candidate_text_v3(cand)
    assert "[CV] " not in v2, "v2: struktura niepusta ⇒ CV nie wchodzi"
    assert "[CV] " in v3
    # Cap 12k zamiast 3000 z buildera v1 — sekcja niesie realnie długi tekst.
    cv_line = next(line for line in v3.split("\n") if line.startswith("[CV] "))
    assert len(cv_line) > 5000


def test_candidate_v3_cv_cap_and_junk_gate():
    cand = _cand(raw_cv_text="x" * 50_000)
    v3 = ct.build_candidate_text_v3(cand)
    # Symbol soup (0% liter to nie, ale "x"*n to 100% liter — cap testujemy tu,
    # junk niżej).
    cv_line = next(line for line in v3.split("\n") if line.startswith("[CV] "))
    assert len(cv_line) <= len("[CV] ") + ct._V3_CV_CAP

    junk = _cand(raw_cv_text="(cid:12)(cid:13) 1234 5678 !!!")
    assert "[CV] " not in ct.build_candidate_text_v3(junk)


def test_candidate_v3_notes_section_from_insights():
    cand = _cand(
        cv_extracted_data={
            "_notes_insights": {
                "skills_evidenced": [
                    {"name": "Terraform", "evidence": "prowadził moduł IaC"},
                    {"name": "AWS"},
                ],
                "certifications": ["CKA"],
                "languages_observed": ["angielski C1"],
                # Pola wrażliwe/negatywne — NIE mogą wejść do tekstu:
                "expected_rate": 180,
                "skills_gaps_observed": ["Kubernetes"],
                "client_vetoes": ["Acme Corp"],
            }
        }
    )
    v3 = ct.build_candidate_text_v3(cand)
    assert "[NOTES] " in v3
    for wanted in ("Terraform", "AWS", "CKA", "angielski C1"):
        assert wanted in v3
    assert "180" not in v3
    assert "Kubernetes" not in v3, "luka obserwowana to sygnał NEGATYWNY"
    assert "Acme Corp" not in v3


def test_candidate_v3_survives_list_shaped_extracted_data():
    """cv_extracted_data na prodzie bywa LISTĄ — v3 nie może się wywrócić."""
    cand = _cand(cv_extracted_data=["legacy", "list", "shape"])
    v3 = ct.build_candidate_text_v3(cand)
    assert "[NOTES] " not in v3
    assert "[SKILLS]" in v3


def test_candidate_v3_still_excludes_pii():
    v3 = ct.build_candidate_text_v3(_cand())
    for pii in ("Kowalski", "jan.kowalski@example.com", "+48123456789"):
        assert pii not in v3.replace("Jan Kowalski CV", "")  # poza treścią CV
    # Imię może wystąpić WEWNĄTRZ surowego CV (to treść dokumentu), ale nie
    # jako osobne pole — brak sekcji z name/lastname/city.
    assert "Warszawa" not in v3.split("[CV] ")[0]


def test_dispatcher_v3_takes_precedence(monkeypatch):
    from app.core.config import settings
    from app.services import embedding_service as emb

    cand = _cand(raw_cv_text="Unikalna fraza z pelnego CV. " * 200)
    monkeypatch.setattr(settings, "AI_TEXT_SCHEMA_V2", True)
    monkeypatch.setattr(settings, "AI_TEXT_SCHEMA_V3", True, raising=False)
    text = emb._build_candidate_text(cand)
    assert "[CV] " in text, "v3 wygrywa z v2 (v2 nie dałby CV przy strukturze)"


def test_v3_flag_and_collection_are_scoring_cache_inputs():
    """Flip v3/kolekcji zmienia skalę semantyki ⇒ MUSI unieważnić cache."""
    from app.services.scoring_service import _SCORING_CACHE_INPUTS

    assert "AI_TEXT_SCHEMA_V3" in _SCORING_CACHE_INPUTS
    assert "QDRANT_COLLECTION" in _SCORING_CACHE_INPUTS


# ── warianty zapytań multi-query (runda 2) ───────────────────────────────────


def _job(**kw) -> SimpleNamespace:
    base = dict(
        title="Senior Python Developer (ref: ABC-123)",
        seniority=SimpleNamespace(value="senior"),
        must_skills=[{"name": "Python"}, {"name": "FastAPI"}],
        nice_skills=[{"name": "Kafka"}],
    )
    base.update(kw)
    return SimpleNamespace(**base)


def test_query_variants_shapes():
    variants = ct.build_job_query_variants(_job(), base_text="pelny tekst oferty")
    assert len(variants) == 2
    title_v, skills_v = variants
    assert "Python Developer" in title_v and "senior" in title_v
    assert "ABC-123" not in title_v, "ref noise odpada jak w buildarach"
    assert skills_v == "Python, FastAPI, Kafka"


def test_query_variants_drop_empty_and_duplicates():
    empty = ct.build_job_query_variants(
        SimpleNamespace(title="", seniority=None, must_skills=None, nice_skills=None)
    )
    assert empty == []
    # Wariant identyczny z tekstem głównym odpada (nic by nie wnosił).
    j = SimpleNamespace(
        title="Python", seniority=None, must_skills=None, nice_skills=None
    )
    assert ct.build_job_query_variants(j, base_text="Python") == []
