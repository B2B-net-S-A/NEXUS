"""v3 bez [NOTES] — wariant kontrolny do pomiaru przecieku (26.09.2026).

`AI_TEXT_SCHEMA_V3_NOTES=false` daje tekst v3 bez sekcji notatek — wyłącznie do
A/B (docs/embedding-v3-ab-runbook.md). Domyślnie (True) tekst ma być bajt
w bajt taki jak przed wprowadzeniem przełącznika.
"""

from __future__ import annotations

from types import SimpleNamespace

from app.services import canonical_text as ct


def _cand() -> SimpleNamespace:
    return SimpleNamespace(
        competence_category="data_ai",
        years_it_experience=4,
        skills=["Python"],
        verified_tech=None,
        experience=[{"role": "Data Engineer", "company": "Acme", "desc": "ETL"}],
        preferences=None,
        ai_summary=None,
        raw_cv_text="Pelne CV kandydata: Spark, Airflow.",
        cv_extracted_data={
            "_notes_insights": {
                "skills_evidenced": [{"name": "Terraform"}],
                "certifications": ["CKA"],
                "languages_observed": ["angielski C1"],
            }
        },
    )


# Wynik buildera v3 z origin/main sprzed przełącznika (sprawdzone 26.09.2026
# porównaniem z wersją z origin/main). Domyślne wywołanie MUSI dawać dokładnie
# ten tekst — inaczej hasz treści (payload `content_hash`, `desired_hash`
# outboxu) zmieniłby się bez żadnej decyzji, a cień v3 zbudowany dziś nie
# pasowałby do tekstu liczonego jutro.
_V3_GOLDEN = (
    "[ROLE] data_ai\n"
    "[SENIORITY] 4+ years (mid-level)\n"
    "[SKILLS] Python\n"
    "[EXPERIENCE] Data Engineer — Acme: ETL\n"
    "[NOTES] Terraform, CKA, angielski C1\n"
    "[CV] Pelne CV kandydata: Spark, Airflow."
)


def test_default_is_notes_on():
    from app.core.config import Settings

    assert Settings.model_fields["AI_TEXT_SCHEMA_V3_NOTES"].default is True


def test_v3_default_output_is_byte_identical_to_before_the_notes_switch(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "AI_TEXT_SCHEMA_V3_NOTES", True)
    assert ct.build_candidate_text_v3(_cand()) == _V3_GOLDEN
    assert ct.build_candidate_text_v3(_cand(), include_notes=True) == _V3_GOLDEN


def test_v3_without_notes_drops_only_the_notes_section():
    text = ct.build_candidate_text_v3(_cand(), include_notes=False)
    assert "[NOTES]" not in text
    assert text == _V3_GOLDEN.replace("[NOTES] Terraform, CKA, angielski C1\n", "")


def test_explicit_argument_wins_over_the_setting(monkeypatch):
    """Budowa cienia podaje wariant jawnie — env kontenera nie może go zmienić."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "AI_TEXT_SCHEMA_V3_NOTES", False)
    assert ct.build_candidate_text_v3(_cand(), include_notes=True) == _V3_GOLDEN
    monkeypatch.setattr(settings, "AI_TEXT_SCHEMA_V3_NOTES", True)
    assert "[NOTES]" not in ct.build_candidate_text_v3(_cand(), include_notes=False)


def test_notes_setting_drives_the_dispatcher(monkeypatch):
    from app.core.config import settings
    from app.services import embedding_service as emb

    monkeypatch.setattr(settings, "AI_TEXT_SCHEMA_V3", True)
    monkeypatch.setattr(settings, "AI_TEXT_SCHEMA_V3_NOTES", False)
    assert "[NOTES]" not in emb._build_candidate_text(_cand())
    monkeypatch.setattr(settings, "AI_TEXT_SCHEMA_V3_NOTES", True)
    assert emb._build_candidate_text(_cand()) == _V3_GOLDEN


def test_active_text_schema_follows_the_dispatcher_order(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "AI_TEXT_SCHEMA_V2", False)
    monkeypatch.setattr(settings, "AI_TEXT_SCHEMA_V3", False)
    monkeypatch.setattr(settings, "AI_TEXT_SCHEMA_V3_NOTES", True)
    assert ct.active_text_schema() == ct.TEXT_SCHEMA_V1
    monkeypatch.setattr(settings, "AI_TEXT_SCHEMA_V2", True)
    assert ct.active_text_schema() == ct.TEXT_SCHEMA_V2
    monkeypatch.setattr(settings, "AI_TEXT_SCHEMA_V3", True)
    assert ct.active_text_schema() == ct.TEXT_SCHEMA_V3
    monkeypatch.setattr(settings, "AI_TEXT_SCHEMA_V3_NOTES", False)
    assert ct.active_text_schema() == ct.TEXT_SCHEMA_V3_NO_NOTES


def test_notes_switch_stays_out_of_the_scoring_cache_digest():
    """Nowy klucz w digeście unieważniłby cały cache score'ów przy wdrożeniu.

    Wariant bez notatek żyje we własnej kolekcji, a QDRANT_COLLECTION jest
    w digeście — klucz cache i tak się różni.
    """
    from app.services.scoring_service import _SCORING_CACHE_INPUTS

    assert "AI_TEXT_SCHEMA_V3_NOTES" not in _SCORING_CACHE_INPUTS
    assert "QDRANT_COLLECTION" in _SCORING_CACHE_INPUTS
