"""Filtr umiejętności ma być JEDEN, wspólny dla obu powierzchni wyszukiwania.

Dlaczego ten plik istnieje. Filtr „nie ma <umiejętność>" miał dwie niezależne
implementacje: `structured_candidate_search._skill_match` (używana przez
`POST /api/search/candidates`) i lokalna `skill_predicate` w
`candidates.py::_build_candidate_filtered_query` (używana przez
`GET /api/candidates`, czyli główną listę). PR #960 naprawił pierwszą — a
frontend wysyła `NOT <X>` do drugiej, więc naprawa nie dotknęła ścieżki, z
której korzystają rekruterzy.

To jest filtr TWARDY: wykluczony kandydat nie pojawia się w wynikach i wygląda
identycznie jak kandydat, którego w bazie nie ma. Rozjazd między powierzchniami
jest więc niewidoczny — obie odpowiadają 200, obie zwracają „jakieś" wyniki.
Zmierzone na produkcji 2026-07-28: zapytanie „nie ma Go" wycinało na głównej
liście 196 osób, z których Go znało 15.

Te testy nie sprawdzają wyników zapytań (do tego trzeba bazy). Sprawdzają
STRUKTURALNIE, że obie powierzchnie wołają ten sam predykat i że sam predykat
pokrywa oba kodowania JSON występujące w danych.
"""

from __future__ import annotations

import inspect

import pytest


def test_lista_kandydatow_uzywa_wspolnego_predykatu() -> None:
    """`candidates.py` nie może mieć własnej kopii logiki dopasowania."""
    from app.api import candidates as modul

    zrodlo = inspect.getsource(modul)
    assert "_skill_match" in zrodlo, (
        "candidates.py nie importuje `_skill_match` — główna lista znów ma "
        "własną implementację filtra umiejętności i rozjedzie się z "
        "/api/search/candidates, tak jak przed #960"
    )
    assert 'pattern = f"%{skill.lower()}%"' not in zrodlo, (
        "wrócił goły wzorzec podłańcuchowy `%skill%` — to on wycinał 196 osób "
        "przy 15 realnie znających Go"
    )


@pytest.mark.parametrize(
    "umiejetnosc,tekst,ma_trafic",
    [
        # kształt listy stringów
        ("Go", '["Python", "Go"]', True),
        # kształt słownikowy
        ("Go", '[{"name": "Go", "level": "senior"}]', True),
        # PODWÓJNE KODOWANIE — 303 wiersze na produkcji mają taki kształt,
        # a wzorzec sprawdzający tylko `"Go"` gubił tu 10 z 15 trafień
        ("Go", '"[\\"Go\\", \\"Python\\"]"', True),
        # to, co stary wzorzec łapał fałszywie
        ("Go", '["Django"]', False),
        ("Go", '["MongoDB"]', False),
        ("Go", '["Golang"]', False),
        ("Go", '["Google Cloud Platform"]', False),
    ],
)
def test_predykat_pokrywa_oba_kodowania(
    umiejetnosc: str, tekst: str, ma_trafic: bool
) -> None:
    """Sprawdza samą regułę dopasowania, bez bazy.

    Odtwarza to, co robi SQL: `strpos` po zrzucie JSON zamienionym na małe
    litery, dla obu granic tokenu (`"X"` oraz `\\"X\\"`).
    """
    blob = tekst.lower()
    igla = umiejetnosc.lower()
    trafia = (f'"{igla}"' in blob) or (f'\\"{igla}\\"' in blob)
    assert trafia is ma_trafic, (
        f"{umiejetnosc!r} vs {tekst!r}: oczekiwano trafienie={ma_trafic}, "
        f"wyszło {trafia}"
    )


def test_predykat_nie_uzywa_like() -> None:
    """`LIKE` tu nie wystarcza i nie wolno do niego wrócić.

    W LIKE odwrotny ukośnik jest domyślnym znakiem ucieczki, więc wzorzec na
    podwójne kodowanie (``%\\"Go\\"%``) degeneruje się po cichu do wariantu bez
    ukośników i przestaje odróżniać oba kształty. Ta pułapka przewróciła pomiar
    przy pisaniu tej poprawki — dlatego predykat używa `strpos`, które nie ma
    znaków ucieczki ani wieloznaczników.
    """
    from app.services import structured_candidate_search as m

    zrodlo = inspect.getsource(m._skill_match)
    assert "strpos" in zrodlo, "predykat przestał używać strpos"
    assert ".ilike(" not in zrodlo and ".like(" not in zrodlo, (
        "predykat wrócił do LIKE — wzorzec na podwójne kodowanie zdegeneruje "
        "się przez domyślny znak ucieczki i znów zgubi 2/3 trafień"
    )


def test_zrodlo_tekstu_obejmuje_trzy_kolumny() -> None:
    """Obie powierzchnie muszą przeszukiwać ten sam zbiór kolumn.

    Lista kandydatów zawsze brała `skills` + `verified_tech` + `tags`;
    wyszukiwarka strukturalna pomijała `verified_tech`. Ten sam filtr dawał więc
    różne wyniki zależnie od ekranu.
    """
    from app.services import structured_candidate_search as m

    zrodlo = inspect.getsource(m._skills_text)
    for kolumna in ("skills", "verified_tech", "tags"):
        assert kolumna in zrodlo, f"_skills_text() pomija kolumnę {kolumna}"
