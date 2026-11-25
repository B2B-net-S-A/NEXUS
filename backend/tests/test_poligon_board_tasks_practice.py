"""„Czeka na Ciebie” na Poligonie (`scripts/poligon_board_tasks_practice.py`).

Bez bazy. 24.11.2026 lekcja „Pracuj po kolei” była nie do zrobienia dla osoby
bez własnych kart (Delivery Lead, TCM): Poligon brał „Czeka na Ciebie”
z prawdziwego API. Test pilnuje, że zestaw ma odpowiedź z osobami ćwiczebnymi.
"""

from __future__ import annotations

import json
from pathlib import Path

from scripts import build_poligon_dataset as build
from scripts import poligon_board_tasks_practice as bt

ROOT = Path(__file__).resolve().parents[2]
DATASET = ROOT / "frontend/src/lib/poligon/dataset.json"


def test_stale_zgodne_z_generatorem_zestawu():
    assert bt.POLIGON_JOB == build.POLIGON_JOB
    assert bt.JOB_TITLE == build.JOB_TITLE
    assert bt.CLIENT_NAME == build.CLIENT_NAME


def test_zestaw_w_repo_jest_aktualny():
    data = json.loads(DATASET.read_text())
    responses, fiction = bt.board_tasks_practice(data["responses"])
    for key, body in responses.items():
        assert data["responses"][key] == body, (
            f"przebuduj: python3 scripts/build_poligon_dataset.py --practice-only ({key})"
        )
    assert set(fiction) <= set(data["meta"]["fiction_responses"])


def test_kolejka_to_osoby_cwiczebne_z_tablicy():
    data = json.loads(DATASET.read_text())
    flow = data["responses"][bt.KEY]["flow"]
    people = {p["candidate_id"]: f"{p['name']} {p['lastname']}" for p in data["meta"]["people"]}
    rows = flow["screening"] + flow["verified"]
    assert len(flow["screening"]) >= 1
    assert all(people[r["candidate_id"]] == r["candidate_name"] for r in rows)
    assert {r["job_id"] for r in rows} == {bt.POLIGON_JOB}
