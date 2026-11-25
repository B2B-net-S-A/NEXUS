"""Klient ćwiczebny Poligonu (`scripts/poligon_client_practice.py`, 22.11.2026).

Bez bazy: generator to czyste funkcje. Pilnuje, że dane są wymyślone (repo
jest publiczne), identyfikatory leżą w zakresie poligonu, zestaw w repo jest
aktualny względem generatora, a wpisy Nowości z klienta, kontraktu i Finansów
prowadzą na ekran, który zestaw zna.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from scripts import build_poligon_dataset as build
from scripts import poligon_board_tasks_practice as board_tasks_practice
from scripts import poligon_payments_practice as payments_practice
from scripts import poligon_client_practice as practice
from scripts import poligon_cv_practice as cv_practice
from scripts import poligon_person_texts as person_texts
from scripts import poligon_pre_contract_practice as pre_contract_practice

ROOT = Path(__file__).resolve().parents[2]
DATASET = ROOT / "frontend/src/lib/poligon/dataset.json"
NOVELTIES = ROOT / "backend/app/data/novelties/novelties.json"

PRACTICE_NOVELTIES = {
    "klient-piec-sekcji",
    "klient-konsultanci-os-czasu",
    "klient-konsultanci",
    "klient-profil-w-grupach",
    "klienci-stan-z-faktow",
    "klient-rozliczenie-kroki",
    "raporty-dla-klientow",
    "stawka-z-dokumentu",
    "kontrakt-zamowienie-po-koncu-wspolpracy",
    "kontrakty-jedna-lista",
    "kontrakty-lista-co-dalej",
    "kontrakt-start-i-opieka-nowy-uklad",
    "kontrakt-dokumenty-i-aneksy-nowy-uklad",
    "zamowienia-z-maila-do-sprawdzenia",
    "koszt-zamowienia-w-czesciach",
    "finanse-jeden-modul",
}

# Ekran praktyki → odczyt, bez którego ekran nie wstanie.
SCREEN_READS = {
    "/clients": "GET /api/clients/directory/clients",
    "/clients/990501": "GET /api/clients/990501/profile",
    "/contracts": "GET /api/contracts?",
    "/finance": "GET /api/finance/rate-divergences",
}


@pytest.fixture(scope="module")
def responses() -> dict:
    return practice.client_practice(build.FIRST_CANDIDATE + 4)


def _strings(value, key=""):
    if isinstance(value, str):
        yield key, value
    elif isinstance(value, list):
        for v in value:
            yield from _strings(v, key)
    elif isinstance(value, dict):
        for k, v in value.items():
            yield from _strings(v, k)


def _ints(value, key=""):
    if isinstance(value, bool):
        return
    if isinstance(value, int):
        yield key, value
    elif isinstance(value, list):
        for v in value:
            yield from _ints(v, key)
    elif isinstance(value, dict):
        for k, v in value.items():
            yield from _ints(v, k)


def test_stale_zgodne_z_generatorem_zestawu():
    assert practice.POLIGON_JOB == build.POLIGON_JOB
    assert practice.POLIGON_CLIENT == build.POLIGON_CLIENT
    assert practice.CLIENT_NAME == build.CLIENT_NAME
    assert practice.JOB_TITLE == build.JOB_TITLE
    assert practice.DL == build.TRAINERS["dl"]
    assert practice.REC == build.TRAINERS["rec"]
    names = {f"{a} {b}" for a, b in build.PEOPLE}
    assert practice.ACTIVE["name"] in names and practice.ENDED["name"] in names
    for person in (practice.ACTIVE, practice.ENDED):
        index = [f"{a} {b}" for a, b in build.PEOPLE].index(person["name"])
        assert person["candidate_id"] == build.FIRST_CANDIDATE + index


def test_identyfikatory_w_zakresie_poligonu(responses):
    for key in responses:
        assert all(int(n) >= 990_000 for n in re.findall(r"\b\d{5,}\b", key)), key
    for key, body in responses.items():
        for k, n in _ints(body):
            if (k == "id" or k.endswith("_id")) and n >= 1000:
                assert n >= 990_000, (key, k, n)


def test_bez_kontaktow_adresow_i_prawdziwych_osob(responses):
    people = (
        {f"{a} {b}" for a, b in build.ALL_PEOPLE}
        | {t[1] for t in build.TRAINERS.values()}
        | set(practice.CLIENT_PEOPLE)
    )
    for key, body in responses.items():
        for k, v in _strings(body):
            assert not re.search(r"[\w.+-]+@[\w-]+\.\w+|https?://|\+48", v), (key, k, v)
            if re.search(r"(^|_)(name|person|consultant)$", k) and re.match(
                r"^\w+ \w+$", v
            ):
                assert v in people or v.startswith(practice.CLIENT_NAME), (key, k, v)


def test_kwoty_sa_wymyslone_i_spojne(responses):
    row = responses[f"GET /api/contracts/{practice.ACTIVE['contract_id']}"]
    assert row["rate_candidate"] == build.POLIGON_CANDIDATE_HOURLY
    assert row["margin"] == pytest.approx(row["rate_client"] - row["rate_candidate"])
    profile = responses[f"GET /api/clients/{practice.POLIGON_CLIENT}/profile"]
    # Serwer: `active_mrr` = suma miesięcznych marż w pełnych złotych.
    assert profile["summary"]["active_mrr"] == int(row["monthly_margin"])


def test_zestaw_w_repo_jest_aktualny(responses):
    data = json.loads(DATASET.read_text())
    meta, stored = data["meta"], data["responses"]
    # Poza klientem ćwiczebnym wymyślone są QC edytora z nowości CV, pary
    # „stop do podpisu przedwstępnej” (`poligon_pre_contract_practice.py`)
    # teksty osoby-szablonu (`poligon_person_texts.py`) i „Czeka na Ciebie”
    # (`poligon_board_tasks_practice.py`).
    _, cv_fiction = cv_practice.cv_practice(stored)
    _, board_fiction = board_tasks_practice.board_tasks_practice(stored)
    _, payments_fiction = payments_practice.payments_practice()
    _, pre_contract_fiction = pre_contract_practice.pre_contract_practice(stored)
    _, texts_fiction = person_texts.person_texts(stored)
    assert set(meta["fiction_responses"]) == (
        set(responses)
        | set(cv_fiction)
        | set(pre_contract_fiction)
        | set(texts_fiction)
        | set(board_fiction)
        | set(payments_fiction)
    )
    assert meta["client_people"] == practice.CLIENT_PEOPLE
    for key, body in responses.items():
        assert stored[key] == body, (
            f"przebuduj: python3 scripts/build_poligon_dataset.py --practice-only ({key})"
        )


def test_wpisy_nowosci_prowadza_na_ekran_klienta_cwiczebnego():
    items = {n["id"]: n for n in json.loads(NOVELTIES.read_text())}
    stored = json.loads(DATASET.read_text())["responses"]
    for nid in PRACTICE_NOVELTIES:
        href = items[nid].get("practice_href")
        assert href, nid
        path = href.split("?")[0]
        read = SCREEN_READS[path]
        assert any(k == read or k.startswith(read) for k in stored), (nid, read)
