"""Marker blacklisty wklejony w imię kandydata: zdejmowanie i mapowanie na status.

Warianty zapisu NIE są wymyślone — to komplet form zaobserwowanych na produkcji
18.08.2026 (29 osób, wszystkie ze źródła `traffit`, wszystkie ze `status=active`).
Test trzyma je jawnie, żeby zawężenie wzorca zapaliło się tutaj, a nie na
produkcji, gdzie objawem jest zaproponowanie klientowi osoby z blacklisty.
"""

from __future__ import annotations

import pytest

from app.services.traffit.mappers import (
    has_blacklist_marker,
    strip_status_marker,
    traffit_employee_to_candidate,
)

# (surowe imię z Traffita, oczekiwane imię po oczyszczeniu)
BLACKLIST_FORMS = [
    ("[BLACKLIST]Borys", "Borys"),
    ("[blacklist]Robert", "Robert"),
    ("[BLACK LIST] Jan", "Jan"),
    ("[BLACKLIST] Maciej", "Maciej"),
    ("[Blacklist] Piotr", "Piotr"),
    ("(Blacklist) Karolina", "Karolina"),
    ("[Black List] Michał", "Michał"),
    ("[Black list] Piotr", "Piotr"),
    ("[black list] Maciej", "Maciej"),
    ("[ blacklist ] Wiktor", "Wiktor"),
    ("[BLACK LIST]Jaromir", "Jaromir"),
    ("[BLACK LIST]  Agnieszka", "Agnieszka"),
    ("[black list]Piotr", "Piotr"),
]

ACTIVE_FORMS = [
    ("/ ACTIVE] Bartłomiej", "Bartłomiej"),
    ("[active / Bartosz", "Bartosz"),
    ("/active] Bartosz", "Bartosz"),
    ("/Active] Igor", "Igor"),
    ("[ACTIVE] Marcin", "Marcin"),
    ("/ active] Marcin", "Marcin"),
    ("[Active] Marek", "Marek"),
    ("[active] Paweł", "Paweł"),
    ("[active/ Maciej", "Maciej"),
]


@pytest.mark.parametrize("raw,oczekiwane", BLACKLIST_FORMS + ACTIVE_FORMS)
def test_marker_znika_z_imienia(raw: str, oczekiwane: str):
    assert strip_status_marker(raw) == oczekiwane


@pytest.mark.parametrize("raw,_", BLACKLIST_FORMS)
def test_blacklista_jest_rozpoznana(raw: str, _: str):
    assert has_blacklist_marker(raw) is True


@pytest.mark.parametrize("raw,_", ACTIVE_FORMS)
def test_active_to_nie_blacklista(raw: str, _: str):
    """„[ACTIVE]" jest szumem, nie zakazem — nie może wpychać nikogo na blacklistę."""
    assert has_blacklist_marker(raw) is False


@pytest.mark.parametrize(
    "wartosc",
    ["Jan", "Anna-Maria", "Łukasz", "Nowak-Kowalska", "Activision", "Blacklista"],
)
def test_zwykle_imiona_nietkniete(wartosc: str):
    """Bez ogranicznika obok słowa nie ruszamy niczego.

    „Activision" i „Blacklista" to kontrola fałszywych trafień: wzorzec wymaga
    nawiasu albo ukośnika, więc sama obecność liter nie wystarcza — ani do
    zdjęcia tekstu, ani (co ważniejsze) do nadania statusu blacklisted, bo to
    ciche wykluczenie realnej osoby z propozycji.
    """
    assert strip_status_marker(wartosc) == wartosc
    assert has_blacklist_marker(wartosc) is False


def test_akcept_zostaje_nietkniety():
    """Świadome ograniczenie zakresu: nie wiadomo, co znaczy, i nie ma go gdzie przenieść.

    Skasowanie markera bez pola docelowego byłoby utratą jedynego zapisu —
    dokładnie tym błędem, którego ta zmiana ma uniknąć przy blackliście.
    """
    assert strip_status_marker("[akcept]Agnieszka") == "[akcept]Agnieszka"


def test_mapper_ustawia_status_i_czysci_imie():
    wynik = traffit_employee_to_candidate(
        {
            "id": 1,
            "name": "[BLACK LIST] Jaromir",
            "lastname": "Putrycz",
            "status": "active",
        }
    )
    assert wynik["name"] == "Jaromir"
    assert wynik["lastname"] == "Putrycz"
    # Traffit twierdzi „active" — marker w imieniu wygrywa, bo to jedyne miejsce,
    # w którym blacklista w ogóle została zapisana.
    assert wynik["status"] == "blacklisted"


def test_marker_w_nazwisku_tez_liczy():
    wynik = traffit_employee_to_candidate(
        {"id": 2, "name": "Jan", "lastname": "[blacklist] Kowalski", "status": "active"}
    )
    assert wynik["lastname"] == "Kowalski"
    assert wynik["status"] == "blacklisted"


def test_bez_markera_status_z_traffita_zostaje():
    wynik = traffit_employee_to_candidate(
        {"id": 3, "name": "Anna", "lastname": "Nowak", "status": "inactive"}
    )
    assert wynik["status"] == "passive"
    assert wynik["name"] == "Anna"


def test_active_nie_zmienia_statusu():
    wynik = traffit_employee_to_candidate(
        {"id": 4, "name": "[ACTIVE] Marcin", "lastname": "Badtke", "status": "active"}
    )
    assert wynik["name"] == "Marcin"
    assert wynik["status"] == "active"


def test_pole_bedace_samym_markerem_wraca_do_fallbacku():
    wynik = traffit_employee_to_candidate(
        {"id": 5, "name": "[BLACKLIST]", "lastname": "[blacklist]", "status": "active"}
    )
    assert wynik["name"] == "?"
    assert wynik["lastname"] == "?"
    assert wynik["status"] == "blacklisted"


def test_marker_zatrudnienia_dziala_dalej():
    """Regresja: nowy wzorzec nie może wyprzeć starego (`[zatrudniony]`, 0165)."""
    wynik = traffit_employee_to_candidate(
        {"id": 6, "name": "[zatrudniony] Ewa", "lastname": "Zieleń", "status": "active"}
    )
    assert wynik["name"] == "Ewa"
    assert wynik["status"] == "active"


def test_oba_markery_naraz():
    wynik = traffit_employee_to_candidate(
        {"id": 7, "name": "[zatrudniony] [BLACKLIST] Tomasz", "lastname": "Sochacki"}
    )
    assert wynik["name"] == "Tomasz"
    assert wynik["status"] == "blacklisted"
