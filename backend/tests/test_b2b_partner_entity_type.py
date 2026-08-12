"""Klasyfikacja JDG vs spółka + linie kolumny „Partner".

Czysta logika, zero mocków HTTP — dlatego ten plik testuje `entity_type`, a nie
`registry_lookup` (ten drugi ciąga sieć i do dziś nie ma ani jednego testu).

Najgroźniejszy błąd tej heurystyki jest asymetryczny: fałszywe „spółka" dokłada
zbędną drugą linię (brzydkie), a fałszywe „JDG" UKRYWA osobę kontaktową spółki
(utrata informacji). Dlatego lista przypadków „musi dać JDG" jest tu dłuższa
i pilnuje konkretnych pułapek: nagie „SA"/„AS" w środku nazwy, `S.A.M.` jako
inicjały, „Sasin" jako słowo zawierające `sa`, oraz „SPA" jako salon.
"""

from __future__ import annotations

import pytest

from app.services.b2b_contract_generator.entity_type import (
    COMPANY,
    SOLE_TRADER,
    entity_type_from_company_name,
    entity_type_from_registry,
    fold_company_text,
    partner_display_lines,
    resolve_partner_entity_type,
)


# ── fold ─────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "raw,expected",
    [
        # `ł` NIE rozkłada się w NFD — bez jawnej podmiany wyszłoby „spoka".
        ("Spółka", "spolka"),
        (
            "SPÓŁKA Z OGRANICZONĄ ODPOWIEDZIALNOŚCIĄ",
            "spolka z ograniczona odpowiedzialnoscia",
        ),
        ("Sp. z o.o.", "sp z o o"),
        ("Łódź Ćma Żółw", "lodz cma zolw"),
        ("Jan   Kowalski", "jan kowalski"),
        ("", ""),
        (None, ""),
    ],
)
def test_fold_company_text(raw, expected):
    assert fold_company_text(raw) == expected


def test_fold_never_swallows_l_with_stroke():
    """Regresja na konkretny błąd: NFKD + ascii-ignore daje „spoka"."""
    assert "l" in fold_company_text("spółka")
    assert fold_company_text("spółka") == "spolka"


# ── heurystyka po nazwie: MUSI dać JDG (brak drugiej linii) ───────────────────


@pytest.mark.parametrize(
    "name",
    [
        "JK Software Jan Kowalski",
        # Realny przykład z docstringa `registry_lookup`.
        "Management Services - Olaf Moczydłowski",
        "Anna Kowalska Usługi Programistyczne",
        # `s a` nie na końcu — inicjały, nie spółka akcyjna.
        "PHU S.A.M. Jan Kowalski",
        # Nagie `AS` nie na końcu.
        "AS Serwis Jan Kowalski",
        # `sa` jest fragmentem słowa, nie osobnym tokenem.
        "Sasin Consulting",
        # `spa` świadomie poza słownikiem — inaczej salon staje się spółką.
        "Salon Anna Nowak SPA",
        "Kancelaria Radcy Prawnego Adam Nowak",
        "Jan Kowalski",
        "",
    ],
)
def test_company_name_heuristic_says_not_a_company(name):
    assert entity_type_from_company_name(name) != COMPANY


@pytest.mark.parametrize(
    "name",
    [
        # Rodzina sp. z o.o. — cała nieregularna interpunkcja.
        "ZW Software Sp. z o.o.",
        "ZW Software sp.zo.o.",
        "ZW Software SPZOO",
        "ZW Software Spółka z ograniczoną odpowiedzialnością",
        "ZW Software Spółka z o.o.",
        # S.A. kropkowane i nagie (nagie wymaga WIELKICH liter).
        "ACME Bank S.A.",
        "Nordea Bank Abp SA",
        # Forma prawna w ŚRODKU nazwy — ogon oddziału obcięty.
        "Nordea Bank Abp S.A. Oddział w Polsce",
        # Komandytowa, jawna, komandytowo-akcyjna, prosta S.A.
        "Alfa sp.k.",
        "Beta sp. j.",
        "Gamma Spółka Komandytowa",
        "Delta S.K.A.",
        "Epsilon P.S.A.",
        "ABC sp. z o.o. sp. k.",
        # s.c. pisane MAŁYMI literami — celowo bez wymogu wielkich.
        "Jan Kowalski i Anna Nowak s.c.",
        # Formy niegospodarcze i zagraniczne.
        "Fundacja Dobra Wola",
        "Stowarzyszenie Programistów",
        "Spółdzielnia Pracy Kappa",
        "Zeta GmbH",
        "Eta Ltd",
        "Theta Inc.",
        "Iota LLC",
    ],
)
def test_company_name_heuristic_says_company(name):
    assert entity_type_from_company_name(name) == COMPANY


# ── twardy sygnał z rejestru ─────────────────────────────────────────────────


@pytest.mark.parametrize(
    "source,krs,expected",
    [
        ("CEIDG", None, SOLE_TRADER),
        ("KRS", "0000123456", COMPANY),
        # `source` przychodzi w czterech niespójnych formatach — lower też musi
        # działać, bo `lookup_by_krs` zwraca „krs" małymi.
        ("krs", "0000123456", COMPANY),
        ("biala_lista", None, SOLE_TRADER),
        ("biala_lista", "0000123456", COMPANY),
        # Konflikt sygnałów: CEIDG mówi JDG, ale jest numer KRS. Wątpliwość
        # idzie na spółkę — zafiksowane jawnie, żeby nikt tego nie „naprawił".
        ("CEIDG", "0000123456", COMPANY),
        ("biznes", None, None),
        (None, None, None),
        ("", "", None),
        # KRS bez ani jednej cyfry to nie numer KRS.
        (None, "-", None),
    ],
)
def test_entity_type_from_registry(source, krs, expected):
    assert entity_type_from_registry(source, krs) == expected


# ── rozstrzygnięcie: snapshot bije heurystykę ────────────────────────────────


def test_stored_snapshot_wins_over_the_name_heuristic():
    """Ticket wymaga snapshotu „nieprzeliczanego później". Gdyby heurystyka
    wygrywała, rozbudowa słownika form prawnych zmieniałaby wynik dla umów
    podpisanych dawno temu."""
    assert (
        resolve_partner_entity_type(
            stored=SOLE_TRADER, legal_name="Kowalski Consulting Sp. z o.o."
        )
        == SOLE_TRADER
    )


@pytest.mark.parametrize(
    "stored,legal_name,expected",
    [
        (None, "X Sp. z o.o.", COMPANY),
        # Niejednoznaczne → spółka (nadmiarowa linia nie szkodzi, brak szkodzi).
        (None, "JK Software Jan Kowalski", COMPANY),
        (None, None, COMPANY),
        # Śmieć w kolumnie traktowany jak brak sygnału, nie jak wartość.
        ("garbage", "JK Software Jan Kowalski", COMPANY),
        (COMPANY, "JK Software Jan Kowalski", COMPANY),
    ],
)
def test_resolve_partner_entity_type(stored, legal_name, expected):
    assert resolve_partner_entity_type(stored=stored, legal_name=legal_name) == expected


def test_resolve_never_returns_none():
    """Kolumna w bazie jest nullowalna, DTO nie — różnicą jest właśnie ta
    funkcja, więc nie wolno jej zwrócić `None`."""
    for stored in (None, "", "garbage", SOLE_TRADER, COMPANY):
        for legal in (None, "", "Alfa", "Alfa Sp. z o.o."):
            assert resolve_partner_entity_type(stored=stored, legal_name=legal) in (
                SOLE_TRADER,
                COMPANY,
            )


# ── linie kolumny „Partner" ──────────────────────────────────────────────────


def test_company_gets_two_lines():
    assert partner_display_lines(
        legal_name="ZW Software Sp. z o.o.",
        person_name="Zofia Wiśniewska",
        entity_type=COMPANY,
    ) == ("ZW Software Sp. z o.o.", "Zofia Wiśniewska")


def test_sole_trader_gets_one_line():
    assert partner_display_lines(
        legal_name="JK Software Jan Kowalski",
        person_name="Jan Kowalski",
        entity_type=SOLE_TRADER,
    ) == ("JK Software Jan Kowalski", None)


def test_substring_rule_kills_duplication_even_when_classified_as_company():
    """Sedno taniości domyślnego „niejednoznaczne → spółka": nazwa JDG zawiera
    właściciela, więc druga linia znika nawet bez sygnału z rejestru."""
    assert partner_display_lines(
        legal_name="JK Software Jan Kowalski",
        person_name="Jan Kowalski",
        entity_type=COMPANY,
    ) == ("JK Software Jan Kowalski", None)


def test_substring_rule_does_not_hide_a_real_company_contact():
    """„jan kowalski" nie jest podciągiem „kowalski consulting sp z o o", więc
    osoba kontaktowa spółki zostaje."""
    assert partner_display_lines(
        legal_name="Kowalski Consulting Sp. z o.o.",
        person_name="Jan Kowalski",
        entity_type=COMPANY,
    ) == ("Kowalski Consulting Sp. z o.o.", "Jan Kowalski")


def test_substring_rule_does_not_match_a_word_fragment():
    """Porównanie na stringach otoczonych spacjami — „Jan Kowal" nie może
    zniknąć tylko dlatego, że nazwa zawiera „Kowalski"."""
    legal, secondary = partner_display_lines(
        legal_name="Kowalski Systems Sp. z o.o.",
        person_name="Jan Kowal",
        entity_type=COMPANY,
    )
    assert secondary == "Jan Kowal"


def test_historical_row_without_legal_name_falls_back_to_the_person():
    """Wiersz sprzed 0223: `partner_legal_name` NULL, a `partner_name` trzyma
    nazwę firmy (realny fixture w `test_b2b_generated_contract_status`).
    Klasyfikacja jest tu nieistotna — gdyby decydowała, ta sama firma
    wypisałaby się DWA RAZY."""
    assert partner_display_lines(
        legal_name=None,
        person_name="ZW Software Sp. z o.o.",
        entity_type=COMPANY,
    ) == ("ZW Software Sp. z o.o.", None)


def test_diacritics_and_extra_spaces_do_not_defeat_the_substring_rule():
    assert partner_display_lines(
        legal_name="Usługi IT Zofia Wiśniewska",
        person_name="Zofia  Wiśniewska",
        entity_type=COMPANY,
    ) == ("Usługi IT Zofia Wiśniewska", None)


def test_missing_person_yields_a_single_line():
    assert partner_display_lines(
        legal_name="Alfa Sp. z o.o.", person_name=None, entity_type=COMPANY
    ) == ("Alfa Sp. z o.o.", None)


def test_both_missing_yields_nothing_to_render():
    """FE pokazuje wtedy „—"; None jest tu informacją, nie pustym stringiem."""
    assert partner_display_lines(
        legal_name=None, person_name=None, entity_type=COMPANY
    ) == (None, None)
