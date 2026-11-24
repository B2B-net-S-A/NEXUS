"""Teksty osoby-szablonu na Poligonie (`scripts/poligon_person_texts.py`, 24.11.2026).

Bez bazy. 24.11.2026 profil Laury pisał „null · poziom nieznany”, a arkusz
rozmowy Bartosza wcześniejszą odpowiedź „„null””: filtr nagrania zostawia
`null` w miejscu wyciętego tekstu. Pilnuje, że zestaw w repo ma te pola
wypełnione z generatora i że nazwy języków są te same co w NEXUSIE.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.services.candidate_language_writer import _LANGUAGE_CODES
from scripts import poligon_person_texts as texts

ROOT = Path(__file__).resolve().parents[2]
DATASET = ROOT / "frontend/src/lib/poligon/dataset.json"


def _dataset() -> tuple[dict, dict]:
    data = json.loads(DATASET.read_text())
    return data["meta"], data["responses"]


def test_stale_zgodne_z_osoba_szablonem_zestawu():
    meta, _ = _dataset()
    assert texts.TEMPLATE_CANDIDATE == meta["template_candidate_id"]
    assert texts.TEMPLATE_ENTRY == meta["template_entry_id"]


def test_zestaw_w_repo_jest_aktualny():
    meta, stored = _dataset()
    responses, fiction = texts.person_texts(stored)
    assert set(fiction) <= set(meta["fiction_responses"])
    for key, body in responses.items():
        assert stored[key] == body, (
            f"przebuduj: python3 scripts/build_poligon_dataset.py --practice-only ({key})"
        )


def test_kazdy_jezyk_ma_nazwe_a_kazda_wczesniejsza_odpowiedz_tresc():
    _, stored = _dataset()
    languages = stored[texts.LANGUAGES_KEY]["languages"]
    assert languages and all(row["language_name"] for row in languages)
    suggestions = stored[texts.EARLIER_ANSWERS_KEY]["suggestions"]
    assert suggestions and all(item["text"] for item in suggestions)


def test_nazwy_jezykow_jak_w_nexusie():
    for code, (name, level) in texts.LANGUAGES.items():
        assert _LANGUAGE_CODES[name] == code, name
        assert level is None or level in {"A1", "A2", "B1", "B2", "C1", "C2"}


def test_jezyk_bez_nazwy_i_pytanie_spoza_rekrutacji_wypadaja():
    languages = texts.with_language_names(
        {"languages": [{"language_code": "xx", "language_name": None}]}
    )
    assert languages["languages"] == []
    answers = texts.with_earlier_answers(
        {"suggestions": [{"question_id": "q9", "text": None}]}
    )
    assert answers["suggestions"] == []


def test_odpowiedzi_bez_rodzaju_gramatycznego():
    """Odczyt osoby-szablonu dostaje każda osoba ćwiczebna (Helena, Bartosz…)."""
    gendered = ("łam", "łem")  # „prowadziłam”, „przygotowałem”
    for qid, answer in texts.EARLIER_ANSWERS.items():
        words = answer.lower().replace(",", " ").replace(".", " ").split()
        assert not [w for w in words if w.endswith(gendered)], qid
