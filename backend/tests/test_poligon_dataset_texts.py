"""Teksty zestawu Poligonu, które ekran czyta jak napis (`scripts/build_poligon_dataset.py`).

Bez bazy. 25.11.2026 „Edytuj” Profilu Championa na Poligonie kończyło się
„Coś poszło nie tak” (`countSentences(draft.project.about)` → `null.trim()`),
bo generator zostawiał wycięty opis projektu jako `null`, a prawdziwe API
oddaje tu `""` (`app/schemas/champion.py`). Lekcja „Najważniejsze zadanie
w tej roli” była przez to nie do zrobienia.
"""

from __future__ import annotations

import json
from pathlib import Path

from scripts import build_poligon_dataset as build

ROOT = Path(__file__).resolve().parents[2]
DATASET = ROOT / "frontend/src/lib/poligon/dataset.json"


def _nulls(value, path: str = "") -> list[str]:
    if isinstance(value, dict):
        return [
            p
            for k, v in value.items()
            for p in ([f"{path}.{k}"] if v is None and k in build.EMPTY_TEXT_KEYS else _nulls(v, f"{path}.{k}"))
        ]
    if isinstance(value, list):
        return [p for i, v in enumerate(value) for p in _nulls(v, f"{path}[{i}]")]
    return []


def test_teksty_czytane_jak_napis_nie_sa_null():
    responses = json.loads(DATASET.read_text())["responses"]
    wrong = [p for key, body in responses.items() for p in _nulls(body, key)]
    assert wrong == [], f"przebuduj: python3 scripts/build_poligon_dataset.py --practice-only ({wrong[:5]})"


def test_profil_championa_ma_opis_projektu_jako_napis():
    responses = json.loads(DATASET.read_text())["responses"]
    profile = responses[f"GET /api/jobs/{build.POLIGON_JOB}/champion-profile"]
    project = profile["champion_profile"]["project"]
    assert isinstance(project["about"], str)


def test_wyciety_tekst_z_tej_listy_zostaje_pusty():
    assert build.blank_empty_texts({"a": [{"about": None, "x": None}]}) == {"a": [{"about": "", "x": None}]}
