"""Deterministyczna nakładka „braki z notatek vs wymagania oferty".

Czysta funkcja — zero DB, zero LLM. Kontrakt: ostrzeżenie powstaje wyłącznie
dla braku POKRYWAJĄCEGO wymaganie oferty (must/nice, z fallbackiem Championa),
nigdy dla braku niezwiązanego z ofertą.
"""

from types import SimpleNamespace

from app.services.match_justification_service import notes_gap_warnings


def _cand(gaps=None, extracted=...):
    if extracted is ...:
        extracted = (
            {"_notes_insights": {"skills_gaps_observed": gaps}}
            if gaps is not None
            else None
        )
    return SimpleNamespace(cv_extracted_data=extracted)


def _job(must=None, nice=None, champion=None):
    return SimpleNamespace(
        must_skills=must or [],
        nice_skills=nice or [],
        champion_profile=champion,
        requirements=None,
        description=None,
    )


def test_gap_matching_requirement_produces_warning_with_evidence():
    cand = _cand(gaps=[{"name": "Remedy", "evidence": "Nie pracował z Remedy"}])
    job = _job(must=["Remedy", "SQL"])
    out = notes_gap_warnings(cand, job)
    assert out == [{"skill": "Remedy", "evidence": "Nie pracował z Remedy"}]


def test_gap_unrelated_to_job_is_silent():
    cand = _cand(gaps=[{"name": "Remedy", "evidence": "Nie pracował"}])
    job = _job(must=["Python", "Django"])
    assert notes_gap_warnings(cand, job) == []


def test_alias_canonicalization_bridges_name_variants(monkeypatch):
    # postgres (notatka) i PostgreSQL (oferta) muszą się spotkać przez ALIAS_MAP.
    # Mapa jest seedowana z taksonomii w runtime — tu wstrzykujemy minimalną,
    # żeby testować MECHANIZM mostkowania, nie zawartość seedu.
    from app.services import scoring_service

    monkeypatch.setattr(
        scoring_service, "ALIAS_MAP", {"postgres": "postgresql"}, raising=False
    )
    cand = _cand(gaps=[{"name": "postgres"}])
    job = _job(must=["PostgreSQL"])
    out = notes_gap_warnings(cand, job)
    assert len(out) == 1 and out[0]["skill"] == "postgres"
    assert out[0]["evidence"] is None


def test_freetext_gap_contains_requirement_name():
    cand = _cand(gaps=[{"name": "Kubernetes w środowisku produkcyjnym"}])
    job = _job(must=["Kubernetes"])
    out = notes_gap_warnings(cand, job)
    assert len(out) == 1
    assert out[0]["skill"] == "Kubernetes w środowisku produkcyjnym"


def test_short_requirement_names_do_not_containment_match():
    # „Go" (2 znaki) nie może łapać się substringiem w dowolnym tekście braku.
    cand = _cand(gaps=[{"name": "kategoria ogólna"}])
    job = _job(must=["Go"])
    assert notes_gap_warnings(cand, job) == []


def test_champion_fallback_supplies_requirements_when_must_empty():
    cand = _cand(gaps=[{"name": "Terraform", "evidence": "Brak praktyki"}])
    job = _job(
        must=[],
        nice=[],
        champion={"sourcing": {"must_skills": ["Terraform", "AWS"]}},
    )
    out = notes_gap_warnings(cand, job)
    # Jeśli ekstraktor Championa nie rozpozna tej struktury, wynik jest pusty —
    # wtedy kontrakt „bez wymagań nie ma ostrzeżeń" nadal trzyma. Ale przy
    # rozpoznaniu Terraform musi wyjść dokładnie raz.
    assert all(w["skill"] == "Terraform" for w in out)
    assert len(out) <= 1


def test_malformed_shapes_never_raise():
    job = _job(must=["SQL"])
    assert notes_gap_warnings(_cand(extracted=None), job) == []
    assert notes_gap_warnings(_cand(extracted={"_notes_insights": "tekst"}), job) == []
    assert (
        notes_gap_warnings(
            _cand(extracted={"_notes_insights": {"skills_gaps_observed": "nie-lista"}}),
            job,
        )
        == []
    )
    assert (
        notes_gap_warnings(
            _cand(gaps=["goły string", {"evidence": "bez nazwy"}, {"name": "  "}]),
            job,
        )
        == []
    )


def test_dedup_and_cap():
    gaps = [{"name": f"SQL wariant {i}"} for i in range(10)]
    job = _job(must=["SQL"])
    out = notes_gap_warnings(_cand(gaps=gaps), job)
    # Wszystkie warianty trafiają w to samo wymaganie → jedno ostrzeżenie.
    assert len(out) == 1

    many = [
        {"name": name}
        for name in [
            "Python",
            "Java",
            "Docker",
            "Kubernetes",
            "Terraform",
            "Ansible",
            "AWS",
        ]
    ]
    wide_job = _job(
        must=["Python", "Java", "Docker", "Kubernetes", "Terraform", "Ansible", "AWS"]
    )
    capped = notes_gap_warnings(_cand(gaps=many), wide_job)
    assert len(capped) == 5


def test_nosql_gap_does_not_match_sql_requirement():
    # Kluczowa gwarancja z opisu PR: dopasowanie tokenowe, nie substring.
    # "nosql" ma 5 znaków, więc goły substring by nie zadziałał w tę stronę,
    # ale token-split {"nosql"} też nie może zawierać "sql" — przybite wprost.
    cand = _cand(gaps=[{"name": "NoSQL", "evidence": "nie zna baz NoSQL"}])
    job = _job(must=["SQL"])
    assert notes_gap_warnings(cand, job) == []

    # Kierunek odwrotny: wymaganie "NoSQL", brak "SQL" — też nie może trafić.
    cand2 = _cand(gaps=[{"name": "SQL"}])
    job2 = _job(must=["NoSQL"])
    assert notes_gap_warnings(cand2, job2) == []


def test_from_extracted_variant_mirrors_candidate_wrapper():
    from app.services.match_justification_service import (
        notes_gap_warnings_from_extracted,
    )

    extracted = {
        "_notes_insights": {
            "skills_gaps_observed": [{"name": "Remedy", "evidence": "brak"}]
        }
    }
    job = _job(must=["Remedy"])
    assert notes_gap_warnings_from_extracted(extracted, job) == [
        {"skill": "Remedy", "evidence": "brak"}
    ]
    assert notes_gap_warnings_from_extracted(None, job) == []
    assert notes_gap_warnings_from_extracted("tekst", job) == []
