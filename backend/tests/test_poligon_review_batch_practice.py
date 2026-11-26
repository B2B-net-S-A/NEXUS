"""Porcja dnia na Poligonie (`scripts/poligon_review_batch_practice.py`).

Bez bazy. 26.11.2026 lekcje „Porcja…” brały porcję z prawdziwego API: kto miał
pustą porcję, kartę bez profilu albo żadnej rekrutacji niżej niż P0, nie
widział elementu z zadania („Oddaj do Nowych”: 3 z 3 zaliczeń furtką).
Testy pilnują, że zestaw ma porcję z osobami ćwiczebnymi i wszystkim, czego
potrzebuje każda z pięciu lekcji.
"""

from __future__ import annotations

import json
from pathlib import Path

from scripts import build_poligon_dataset as build
from scripts import poligon_review_batch_practice as rb

ROOT = Path(__file__).resolve().parents[2]
DATASET = ROOT / "frontend/src/lib/poligon/dataset.json"
LESSONS = ROOT / "backend/app/data/novelties/lessons.json"

#: Rangi poziomów jak `TIER_RANK` w `ReviewBatchScreen.tsx`.
TIER_RANK = {"p0": 0, "p1": 1, "p2": 2, "accepting": 3}


def _data() -> dict:
    return json.loads(DATASET.read_text())


def test_stale_zgodne_z_generatorem_zestawu():
    assert rb.POLIGON_JOB == build.POLIGON_JOB
    assert rb.JOB_TITLE == build.JOB_TITLE


def test_zestaw_w_repo_jest_aktualny():
    data = _data()
    responses, fiction = rb.review_batch_practice(data["responses"])
    for key, body in responses.items():
        assert data["responses"][key] == body, (
            f"przebuduj: python3 scripts/build_poligon_dataset.py --practice-only ({key})"
        )
    assert set(fiction) <= set(data["meta"]["fiction_responses"])


def test_karty_to_osoby_cwiczebne_z_nowych():
    data = _data()
    queue = data["responses"][rb.QUEUE_KEY]
    people = {
        p["candidate_id"]: f"{p['name']} {p['lastname']}"
        for p in data["meta"]["people"]
    }
    assert len(queue["items"]) >= 2
    assert all(people[i["candidate_id"]] == i["name"] for i in queue["items"])
    assert {i["job_id"] for i in queue["items"]} == {rb.POLIGON_JOB}


def test_kazda_lekcja_porcji_ma_swoj_element():
    data = _data()
    status = data["responses"][rb.STATUS_KEY]
    queue = data["responses"][rb.QUEUE_KEY]
    first = queue["items"][0]
    # „Porcja: karta” — profil „Kogo szukamy” rekrutacji pierwszej karty.
    assert str(first["job_id"]) in queue["job_profiles"]
    # „Wybierz rekrutację na dziś” stoi tylko bez wybranej rekrutacji.
    assert (
        status["focus"] is None and len(data["responses"][rb.FOCUS_KEY]["items"]) >= 2
    )
    # „Musi mieć” ze schodkami na pierwszej karcie.
    assert first["requirements"]["must"] and first["requirements"]["must_total"] > 0
    # „Oddaj … do Nowych”: osoby w „Do domknięcia” z rekrutacji niżej niż P0.
    rank = {job["job_id"]: TIER_RANK[job["group"]] for job in status["team_jobs"]}
    top = min(rank.values())
    assert any(rank[o["job_id"]] > top for o in status["open_today_screenings"])
    # Porcja działa i nie startuje na „Do domknięcia”.
    assert status["enabled"] and status["applies"] and not status["met"]


def test_lekcje_porcji_wskazuja_kotwice_z_zestawu():
    """Nowa lekcja na `/porcja` = przypadek w `test_kazda_lekcja_porcji_ma_swoj_element`."""
    anchors = {
        lesson["check"].get("anchor")
        for lesson in json.loads(LESSONS.read_text())
        if lesson.get("solo_href", "").startswith("/porcja")
    }
    assert anchors <= {
        "review-batch.role-profile",
        "review-batch.focus",
        "review-batch.reject",
        "review-batch.requirements",
        "review-batch.return-group",
    }
