"""Stop do podpisu przedwstępnej na Poligonie (`scripts/poligon_pre_contract_practice.py`).

Bez bazy. Pilnuje, że zestaw w repo jest aktualny względem generatora, że
osoby i trenerzy to te z generatora zestawu i że lekcje nowości prowadzą na
rekrutację ćwiczebną, gdzie jest karta zatrzymana do podpisu.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.services.pre_contracts import NEEDED_BEFORE_LABEL, STATE_LABEL
from scripts import build_poligon_dataset as build
from scripts import poligon_pre_contract_practice as pc

ROOT = Path(__file__).resolve().parents[2]
DATASET = ROOT / "frontend/src/lib/poligon/dataset.json"
NOVELTIES = ROOT / "backend/app/data/novelties/novelties.json"
LESSONS = ROOT / "backend/app/data/novelties/lessons.json"


def test_stale_zgodne_z_generatorem_zestawu():
    assert pc.POLIGON_JOB == build.POLIGON_JOB
    assert pc.CLIENT_ID == build.POLIGON_CLIENT
    assert pc.TRAINER_DL == build.TRAINERS["dl"]
    assert pc.TRAINER_REC == build.TRAINERS["rec"]
    names = [f"{a} {b}" for a, b in build.PEOPLE]
    for person in (pc.STOPPED, pc.SIGNED):
        index = names.index(person["name"])
        assert person["candidate_id"] == build.FIRST_CANDIDATE + index
        assert person["entry_id"] == build.FIRST_ENTRY + index


def test_napisy_jak_na_serwerze():
    assert pc.JOB_RULE["needed_before_label"] == NEEDED_BEFORE_LABEL["cv_sent"]
    assert pc.STOPPED_BADGE["detail"] == STATE_LABEL["sent"]


def test_zestaw_w_repo_jest_aktualny():
    data = json.loads(DATASET.read_text())
    meta, stored = data["meta"], data["responses"]
    responses, fiction = pc.pre_contract_practice(stored)
    assert set(fiction) <= set(meta["fiction_responses"])
    for key, body in responses.items():
        assert stored[key] == body, (
            f"przebuduj: python3 scripts/build_poligon_dataset.py --practice-only ({key})"
        )


def test_karta_szymona_stoi_przed_wyslaniem_cv_a_weroniki_nie():
    stored = json.loads(DATASET.read_text())["responses"]
    items = {
        i["candidate_id"]: (column["name"], i["pre_contract"])
        for column in stored[pc.KANBAN_KEY]["columns"]
        for i in column["items"]
    }
    column, meta = items[pc.STOPPED["candidate_id"]]
    assert column == "QC CV" and meta["stop_column"] == "cv_sent"
    column, meta = items[pc.SIGNED["candidate_id"]]
    assert column == "QC CV" and meta["stop_column"] is None
    # Pozostali nie mają plakietki przedwstępnej.
    others = [
        m
        for cid, (_, m) in items.items()
        if cid not in {pc.STOPPED["candidate_id"], pc.SIGNED["candidate_id"]}
    ]
    assert all(m is None for m in others)


def test_lekcje_nowosci_prowadza_na_rekrutacje_cwiczebna():
    novelties = {n["id"]: n for n in json.loads(NOVELTIES.read_text())}
    lessons = {lesson["id"]: lesson for lesson in json.loads(LESSONS.read_text())}
    for lid in (
        "lekcja-stop-do-podpisu-przedwstepnej",
        "lekcja-stop-przedwstepnej-na-karcie",
    ):
        assert lessons[lid]["solo_href"] == f"/jobs/{pc.POLIGON_JOB}"
    exception = novelties["przedwstepna-stop-wyjatek-dla-osoby"]
    assert exception["practice_href"] == (
        f"/jobs/{pc.POLIGON_JOB}?candidate={pc.STOPPED['candidate_id']}"
    )
