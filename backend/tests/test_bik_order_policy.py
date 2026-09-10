"""Polityka odczytu zamówień BIK — na SYNTETYCZNYCH fixture'ach.

Fixture ``GLUED`` odtwarza układ tekstu, jaki pdfplumber zwraca z realnego
PDF-a BIK z korpusu 09.2026 (SAP gubi spacje: „ProfilUR-JanKowalski",
„4500067890/20260819", adres między etykietą a wartością „Numer/data"). Nazwiska
i kwoty są zmyślone. ``SPACED`` to ten sam dokument ze spacjami — przykład
z ticketu (numer 4500012345 / 03.09.2026, dwie pozycje).

Lata w datach: 2031+ (wolny zakres w bazie testowej, patrz CLAUDE.md).
"""

from decimal import Decimal

import pytest

from app.services.order_pdf_parser import OrderExtraction, ConsultantOrderRow
from app.services.order_policies import (
    PolicyContext,
    active_policies,
    apply_policies,
    apply_rate_kind,
    parse_plan,
    policy_by_key,
)
from app.services.order_policies import bik

GLUED = """ZAMÓWIENIE
B2B.NETS.A
Al.Aleje Jerozolimskie 180
Numer/datazamówienia
02-486 Warszawa
4500067890/20310819
Osobadokontaktów/Telefon/Mail
AndrzejPrzykład
ADRES DOSTAWY Andrzej.Przyklad@bik.pl
BiuroInformacjiKredytowejS.A.
ul.ZygmuntaModzelewskiego77a
02-679Warszawa
ODBIERAJĄCY TOWAR NaszNIP
Marcin Odbiorca PL9511778633
TERMIN DOSTAWY
01.11.2031
Na fakturze proszę powołać się na nr zamówienia : 4500067890
Płatność:Przelew nakontowciągu30dnioddatydostarczeniadoBIKprawidłowowystawionejfaktury
VAT
_______________________________________________________________________
Poz.Przedmiot Ilośćzamów. Jedn. Cenajednostk. Wart.netto
_______________________________________________________________________
10 RozwójProduktówPożyczkowychW.Testowy 64,000 SZT 1.200,00 76.800,00
ProfilUR-WiktorTestowy
Obowiązująca stawkazaosobęwynosi1200,-zł/MD
Wwymiarze64MD(roboczodni).RozliczeniewtrybieT&M.
20 RozwójProduktówPożyczkowychG.Przykładowy 60,000 SZT 1.360,00 81.600,00
ProfilUR-GrzegorzPrzykładowy
Obowiązująca stawkazaosobęwynosi1360,-zł/MD
Wwymiarze60MD(roboczodni).RozliczeniewtrybieT&M.
30 RozwójProduktówPożyczkowychD.Żółtowski 62,000 SZT 1.400,00 86.800,00
ProfilUR-DanielŻółtowski
Obowiązująca stawkazaosobęwynosi1400,-zł/MD
Wwymiarze62MD(roboczodni).RozliczeniewtrybieT&M.
_______________________________________________________________________
Łącz.wart.nettobezVAT 245.200,00 PLN
Zamówienie do umowyramowej
"""

SPACED = """ZAMÓWIENIE
B2B.NET S.A
Al.Aleje Jerozolimskie 180
Numer/data zamówienia
02-486 Warszawa
4500012345 / 20310903
Osoba do kontaktów / Telefon / Mail
Andrzej Przykład
ADRES DOSTAWY Andrzej.Przyklad@bik.pl
Biuro Informacji Kredytowej S.A.
ODBIERAJĄCY TOWAR Nasz NIP
Janusz Odbiorca PL9511778633
TERMIN DOSTAWY
Na fakturze proszę powołać się na nr zamówienia : 4500012345
Płatność: Przelew na konto w ciągu 30 dni od daty dostarczenia do BIK prawidłowo wystawionej faktury VAT
_______________________________________________________________________
Poz. Przedmiot Ilość zamów. Jedn. Cena jednostk. Wart.netto
_______________________________________________________________________
10 Rozwój Strumienia Detalicznego 35,000 SZT 1.080,00 37.800,00
Profil UR - Krystian Sowiński
Obowiązująca stawka za osobę wynosi 1080,- zł/MD
W wymiarze 35 MD (roboczo dni). Rozliczenie w trybie T&M.
20 Rozwój Strumienia Detalicznego 42,000 SZT 1.280,00 53.760,00
Profil UR - Piotr Łęcki
Obowiązująca stawka za osobę wynosi 1280,- zł/MD
W wymiarze 42 MD (roboczo dni). Rozliczenie w trybie T&M.
_______________________________________________________________________
Łącz. wart. netto bez VAT 91.560,00 PLN
W zakresie nieuregulowanym w niniejszym Zamówieniu zastosowanie mają postanowienia umowy ramowej współpracy.
"""


def _run(text: str, *, target: str | None = None, given: str | None = None):
    result = OrderExtraction(
        source="claude",
        # Model zgadywał termin dostawy jako koniec i total jako budżet — polityka
        # musi to zdjąć niezależnie od tego, co przyszło.
        title="4500012345/20310903",
        end_date="2031-11-01",
        total_value=Decimal("91560.00"),
        uncertain=True,
        uncertain_reasons=["Model: nie wiem, która data jest końcem"],
    )
    result, applied = apply_policies(
        result,
        PolicyContext(
            document_text=text, target_consultant=target, target_given_names=given
        ),
        [policy_by_key("bik")],
    )
    assert applied == ["BIK"]
    return result


# ── Pola wspólne zamówienia ─────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("text", "number", "start"),
    [(GLUED, "4500067890", "2031-08-19"), (SPACED, "4500012345", "2031-09-03")],
)
def test_order_number_and_date_come_from_the_number_date_field(text, number, start):
    assert bik.order_number_and_date(text) == (number, start)
    result = _run(text)
    assert result.title == number
    assert result.confidence["title"] == 1.0
    assert result.start_date == start
    assert result.title_needs_review is False


@pytest.mark.parametrize("text", [GLUED, SPACED])
def test_order_is_open_ended_and_delivery_term_is_ignored(text):
    result = _run(text)
    assert result.end_date is None
    assert "end_date" not in result.confidence


@pytest.mark.parametrize("text", [GLUED, SPACED])
def test_order_totals_are_not_carried_into_the_order(text):
    result = _run(text)
    assert result.total_value is None
    # Wiele osób: stawka i limit MD istnieją wyłącznie per pozycja; jednostka
    # (PLN/MD) jest wspólna dla wszystkich pozycji.
    assert (result.rate_client, result.rate_unit, result.md_total) == (None, "day", None)


# ── Pozycje per konsultant ──────────────────────────────────────────────────


def test_ticket_example_two_consultants_each_with_own_limit_and_rate():
    rows = bik.extract_rows(SPACED)
    assert [
        (r.consultant_name, r.md_total, r.rate_client, r.rate_unit) for r in rows
    ] == [
        ("Krystian Sowiński", Decimal("35.000"), Decimal("1080.00"), "day"),
        ("Piotr Łęcki", Decimal("42.000"), Decimal("1280.00"), "day"),
    ]
    assert all(r.start_date == "2031-09-03" and r.end_date is None for r in rows)
    assert all(not r.uncertain for r in rows)


def test_glued_pipeline_layout_splits_names_and_numbers():
    rows = bik.extract_rows(GLUED)
    assert [(r.consultant_name, r.md_total, r.rate_client) for r in rows] == [
        ("Wiktor Testowy", Decimal("64.000"), Decimal("1200.00")),
        ("Grzegorz Przykładowy", Decimal("60.000"), Decimal("1360.00")),
        ("Daniel Żółtowski", Decimal("62.000"), Decimal("1400.00")),
    ]
    assert all(not r.uncertain for r in rows)


def test_policy_replaces_model_rows_and_its_concerns():
    result = _run(SPACED)
    assert [r.consultant_name for r in result.consultant_rows] == [
        "Krystian Sowiński",
        "Piotr Łęcki",
    ]
    assert result.uncertain is False
    assert result.uncertain_reasons == []


@pytest.mark.parametrize(
    "profile_line",
    [
        "Profil UR - Krystian Sowiński",
        "Profil UR Krystian Sowiński",
        "ProfilUR-KrystianSowiński",
        "ProfilURKrystianSowiński",
        "Profil UR – Krystian Sowiński",
    ],
)
def test_name_is_found_with_or_without_the_dash(profile_line):
    text = SPACED.replace("Profil UR - Krystian Sowiński", profile_line)
    assert bik.extract_rows(text)[0].consultant_name == "Krystian Sowiński"


def test_name_anywhere_in_the_position_without_profile_line():
    text = SPACED.replace(
        "10 Rozwój Strumienia Detalicznego 35,000",
        "10 Rozwój Strumienia Detalicznego - Krystian Sowiński 35,000",
    ).replace("Profil UR - Krystian Sowiński\n", "")
    assert bik.extract_rows(text)[0].consultant_name == "Krystian Sowiński"


def test_compound_surname_survives_the_dash_separator():
    text = SPACED.replace("Piotr Łęcki", "Anna Nowak-Kowalska")
    assert bik.extract_rows(text)[1].consultant_name == "Anna Nowak-Kowalska"


def test_unreadable_name_leaves_row_empty_with_a_clear_reason():
    text = SPACED.replace("Profil UR - Piotr Łęcki", "Profil UR - 12345")
    rows = bik.extract_rows(text)
    assert rows[1].consultant_name == ""
    assert rows[1].uncertain is True
    assert rows[1].uncertain_reason.startswith(
        "Pozycja 20: nie udało się jednoznacznie odczytać imienia i nazwiska"
    )
    result = _run(text)
    assert result.uncertain is True
    assert any(r.startswith("Pozycja 20:") for r in result.uncertain_reasons)


def test_two_possible_people_without_profile_anchor_go_to_review():
    text = SPACED.replace(
        "Profil UR - Krystian Sowiński", "Zastępstwo: Jan Nowak, Piotr Zieliński"
    )
    row = bik.extract_rows(text)[0]
    assert row.consultant_name == ""
    assert "kilka możliwych osób" in row.uncertain_reason


def test_initial_in_description_must_match_the_profile_person():
    text = GLUED.replace("ProfilUR-WiktorTestowy", "ProfilUR-JanKowalski")
    row = bik.extract_rows(text)[0]
    assert row.consultant_name == ""
    assert "W. Testowy" in row.uncertain_reason


def test_misread_digits_are_caught_by_the_position_net_value():
    text = SPACED.replace("35,000 SZT 1.080,00", "36,000 SZT 1.080,00")
    row = bik.extract_rows(text)[0]
    assert row.uncertain is True
    assert "nie zgadza się z wartością netto" in row.uncertain_reason
    # Wartość netto nigdy nie nadpisuje odczytu — tylko ostrzega.
    assert row.md_total == Decimal("36.000")


def test_unexpected_unit_is_flagged():
    text = SPACED.replace("35,000 SZT", "35,000 H")
    row = bik.extract_rows(text)[0]
    assert "nieoczekiwana jednostka" in row.uncertain_reason


def test_missing_number_date_field_needs_review():
    text = SPACED.replace("4500012345 / 20310903", "").replace(
        "nr zamówienia : 4500012345", ""
    )
    result = _run(text)
    assert result.title is None
    assert result.title_needs_review is True
    assert result.start_date is None
    assert result.uncertain is True


def test_invoice_number_is_a_fallback_and_a_cross_check():
    text = SPACED.replace("4500012345 / 20310903", "")
    assert _run(text).title == "4500012345"
    conflicting = SPACED.replace("nr zamówienia : 4500012345", "nr zamówienia : 4500099999")
    result = _run(conflicting)
    assert result.title == "4500012345"
    assert any("różni się od numeru" in r for r in result.uncertain_reasons)


# ── Odczyt z karty jednej osoby („Dodaj konsultanta") ───────────────────────


def test_targeted_read_picks_the_row_of_that_person():
    result = _run(SPACED, target="Piotr Łęcki", given="Piotr")
    assert (result.rate_client, result.rate_unit, result.md_total) == (
        Decimal("1280.00"),
        "day",
        Decimal("42.000"),
    )
    assert result.consultant_rate_matched is True
    assert result.consultant_md_matched is True
    assert result.uncertain is False


def test_targeted_read_ignores_concerns_about_other_rows():
    text = SPACED.replace("Profil UR - Krystian Sowiński", "Profil UR - 12345")
    result = _run(text, target="Piotr Łęcki", given="Piotr")
    assert result.md_total == Decimal("42.000")
    assert result.uncertain is False


def test_targeted_read_of_absent_person_keeps_fields_empty():
    result = _run(SPACED, target="Jan Kowalski", given="Jan")
    assert (result.rate_client, result.md_total) == (None, None)
    assert result.uncertain is True


def test_single_position_order_fills_document_fields():
    single = SPACED.split("20 Rozwój")[0] + "Łącz. wart. netto bez VAT 37.800,00 PLN\n"
    result = _run(single)
    assert (result.rate_client, result.rate_unit, result.md_total) == (
        Decimal("1080.00"),
        "day",
        Decimal("35.000"),
    )


# ── Rejestr ─────────────────────────────────────────────────────────────────


def test_bik_policy_is_active_for_the_canonical_client(monkeypatch):
    """Produkcyjne ID 18 działa bez env; conftest odpina je od seriala testów."""
    from dataclasses import replace

    from app.services.order_policies import registry

    assert bik.CANONICAL_CLIENT_IDS == frozenset({18})
    real = replace(policy_by_key("bik"), canonical_client_ids=bik.CANONICAL_CLIENT_IDS)
    monkeypatch.setattr(
        registry,
        "POLICIES",
        tuple(real if p.key == "bik" else p for p in registry.POLICIES),
    )
    monkeypatch.setitem(registry._BY_KEY, "bik", real)
    monkeypatch.delenv("BIK_ORDER_CLIENT_IDS", raising=False)
    assert [p.key for p in active_policies(18)] == ["bik"]
    assert registry.closes_on_md_exhaustion(18) is True
    assert active_policies(4242) == []
    monkeypatch.setenv("BIK_ORDER_CLIENT_IDS", "4242")
    assert [p.key for p in active_policies(4242)] == ["bik"]


def test_registry_declares_the_canonical_bik_id():
    """Źródło rejestru (nie stan po fixturze) wiąże politykę z ID 18."""
    import inspect

    from app.services.order_policies import registry

    source = inspect.getsource(registry)
    assert "canonical_client_ids=bik.CANONICAL_CLIENT_IDS" in source


def test_parse_plan_and_flags():
    policy = policy_by_key("bik")
    assert parse_plan([policy]).rate_unit_default == "day"
    assert policy.open_ended_period is True
    assert policy.closes_on_md_exhaustion is True
    assert policy.exposes_consultant_rows is True


def test_rates_are_net_without_generic_uncertainty():
    result = _run(SPACED)
    result = apply_rate_kind(result, SPACED, [policy_by_key("bik")])
    assert result.uncertain is False
    assert all(r.rate_client_gross is None for r in result.consultant_rows)
    assert [r.rate_client for r in result.consultant_rows] == [
        Decimal("1080.00"),
        Decimal("1280.00"),
    ]


def test_row_type_is_the_shared_consultant_row():
    assert isinstance(bik.extract_rows(SPACED)[0], ConsultantOrderRow)
