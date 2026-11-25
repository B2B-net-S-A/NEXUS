"""Osoba w „CV wysłane” na Poligonie (`scripts/poligon_terms_practice.py`).

Bez bazy. 25.11.2026 lekcja „Terminy przy ruchu” kazała przesunąć kartę
z „CV wysłane”, a ta kolumna rekrutacji ćwiczebnej była pusta. Test pilnuje,
że zestaw w repo ma tę osobę, że zgadza się z generatorem i że lekcja
prowadzi na tę Tablicę.
"""

from __future__ import annotations

import json
from pathlib import Path

from scripts import build_poligon_dataset as build
from scripts import poligon_terms_practice as tp

ROOT = Path(__file__).resolve().parents[2]
DATASET = ROOT / "frontend/src/lib/poligon/dataset.json"
META = ROOT / "frontend/src/lib/poligon/meta.json"
LESSONS = ROOT / "backend/app/data/novelties/lessons.json"


def test_osoba_zgodna_z_generatorem_zestawu():
    assert tp.POLIGON_JOB == build.POLIGON_JOB
    index = build.ALL_PEOPLE.index(build.TERMS_PERSON)
    assert tp.PERSON["candidate_id"] == build.FIRST_CANDIDATE + index
    assert tp.PERSON["entry_id"] == build.FIRST_ENTRY + index
    assert (tp.PERSON["name"], tp.PERSON["lastname"]) == build.TERMS_PERSON


def test_zestaw_w_repo_jest_aktualny():
    data = json.loads(DATASET.read_text())
    responses, people = tp.terms_practice(data["responses"], data["meta"]["people"])
    for key, body in responses.items():
        assert data["responses"][key] == body, (
            f"przebuduj: python3 scripts/build_poligon_dataset.py --practice-only ({key})"
        )
    assert data["meta"]["people"] == people
    assert json.loads(META.read_text())["people"] == people


def test_lekcja_terminow_ma_karte_w_cv_wyslane():
    lessons = {lesson["id"]: lesson for lesson in json.loads(LESSONS.read_text())}
    lesson = lessons["lekcja-terminy-przy-ruchu"]
    assert lesson["check"] == {
        **lesson["check"],
        "kind": "move",
        "to": "client_interview",
    }
    assert lesson["solo_href"] == f"/jobs/{tp.POLIGON_JOB}"
    columns = json.loads(DATASET.read_text())["responses"][tp.KANBAN_KEY]["columns"]
    cv_sent = next(c for c in columns if c["stage"] == tp.TARGET_STAGE)
    assert [i["candidate_id"] for i in cv_sent["items"]] == [tp.PERSON["candidate_id"]]
    assert cv_sent["count"] == 1
    # Bez plakietki przedwstępnej: stop rekrutacji dotyczy wysyłki CV, ta karta jest już za nim.
    assert cv_sent["items"][0]["pre_contract"] is None


def test_drugie_wywolanie_niczego_nie_doklada():
    data = json.loads(DATASET.read_text())
    once = tp.with_terms_card(data["responses"][tp.KANBAN_KEY])
    assert tp.with_terms_card(once) == once
