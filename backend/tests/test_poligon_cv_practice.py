"""CV na Poligonie (`scripts/poligon_cv_practice.py`, 22.11.2026).

Bez bazy. Pilnuje, że uwaga „Lata w punkcie 1” w zestawie to wynik serwera na
CV ćwiczebnym, że zestaw w repo jest aktualny względem generatora i że oba
wpisy Nowości prowadzą na rekrutację ćwiczebną.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from scripts import build_poligon_dataset as build
from scripts import poligon_cv_practice as cv

ROOT = Path(__file__).resolve().parents[2]
DATASET = ROOT / "frontend/src/lib/poligon/dataset.json"
CV_FICTION = ROOT / "frontend/src/lib/poligon/cv-fiction.ts"
NOVELTIES = ROOT / "backend/app/data/novelties/novelties.json"

# Dzień, z którego pochodzą miesiące roli „03.2021 – obecnie” w zestawie.
FIXED_TODAY = date(2026, 11, 22)


def _fiction_cv_html() -> str:
    """CV ćwiczebne w kształcie z `cv-fiction.ts`: punkt 1 i stanowiska."""
    roles = "".join(
        f'<p data-cv-section="role"><strong>{title}</strong> {dates}</p>'
        '<p data-cv-section="employer">Firma Przykładowa S.A.</p>'
        for title, dates, _, _ in cv.ROLES
    )
    return (
        "<h1>Senior Project Manager – Helena Wrzosek</h1>"
        '<h2 data-cv-section="why_points">DLACZEGO NASZ KANDYDAT?</h2>'
        f"<ul><li><p>{cv.POINT_ONE}</p></li></ul>"
        '<h2 data-cv-section="experience">DOŚWIADCZENIE</h2>' + roles
    )


def test_stale_zgodne_z_generatorem_zestawu():
    assert cv.POLIGON_JOB == build.POLIGON_JOB
    assert cv.POLIGON_CLIENT == build.POLIGON_CLIENT
    assert cv.TRAINER_REC == build.TRAINERS["rec"][1]
    index = [f"{a} {b}" for a, b in build.PEOPLE].index(cv.READY_CV_PERSON["name"])
    assert cv.READY_CV_PERSON["candidate_id"] == build.FIRST_CANDIDATE + index
    assert cv.READY_CV_PERSON["entry_id"] == build.FIRST_ENTRY + index


def test_uwaga_o_latach_to_wynik_serwera_na_cv_cwiczebnym():
    from app.services import cv_qc

    blocks = cv_qc.dz.html_blocks(_fiction_cv_html())
    server = cv_qc._years_breakdown_check(
        blocks, cv_qc.cv_roles(blocks, []), FIXED_TODAY
    )
    ours = cv.years_breakdown_check()
    for key in ("key", "label", "severity", "status", "summary"):
        assert ours[key] == server[key], key
    assert ours["items"][0] == {**server["items"][0], **ours["items"][0]}
    assert server["items"][0]["tenure"] == ours["items"][0]["tenure"]
    assert server["items"][0]["proposal"] == cv.TENURE_PROPOSAL


def test_cv_cwiczebne_we_froncie_ma_punkt_1_i_role_z_generatora():
    source = CV_FICTION.read_text()
    assert cv.POINT_ONE in source
    for title, dates, _, _ in cv.ROLES:
        assert f"<strong>{title}</strong> {dates}" in source


def test_zestaw_w_repo_jest_aktualny():
    data = json.loads(DATASET.read_text())
    meta, stored = data["meta"], data["responses"]
    responses, fiction = cv.cv_practice(stored)
    assert set(fiction) <= set(meta["fiction_responses"])
    assert meta["ready_cv_candidate_id"] == cv.READY_CV_PERSON["candidate_id"]
    for key, body in responses.items():
        assert stored[key] == body, (
            f"przebuduj: python3 scripts/build_poligon_dataset.py --practice-only ({key})"
        )


def test_gotowe_cv_z_innej_rekrutacji_u_klienta_ze_zgoda():
    stored = json.loads(DATASET.read_text())["responses"]
    entry = cv.READY_CV_PERSON["entry_id"]
    assert stored[cv.RULE_KEY]["requires_rodo_consent_block"] is True
    assert stored[f"GET /api/candidates/stages/{entry}/cv/branded"]["status"] == "none"
    (source,) = stored[f"GET /api/candidates/stages/{entry}/cv/branded/sources"][
        "items"
    ]
    assert source["job_id"] != cv.POLIGON_JOB and source["job_id"] >= 990_000
    assert source["consent_carried"] is False


def test_wpisy_nowosci_prowadza_na_rekrutacje_cwiczebna():
    items = {n["id"]: n for n in json.loads(NOVELTIES.read_text())}
    expected = {
        "lata-w-punkcie-1-i-daty-stanowisk": cv.TEMPLATE_CANDIDATE,
        "gotowe-cv-z-nowa-zgoda": cv.READY_CV_PERSON["candidate_id"],
    }
    for nid, candidate in expected.items():
        href = items[nid].get("practice_href") or ""
        assert href.startswith(f"/jobs/{cv.POLIGON_JOB}?"), nid
        assert f"candidate={candidate}" in href, nid
