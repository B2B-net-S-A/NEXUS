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
