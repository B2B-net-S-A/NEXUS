"""Reguły rozpoznania gotowego CV do klienta przy wgraniu w rekrutacji (15.10.2026).

Czyste funkcje, bez bazy: po nazwie pliku poznajemy CV do klienta (D1), a po
nagłówku — CV innej osoby, którego nie wolno podpiąć jako CV do klienta.
"""

from __future__ import annotations

import pytest

from app.services.client_cv_upload import (
    cv_header,
    looks_like_client_cv,
    other_person_name,
    pattern_prefix,
)


@pytest.mark.parametrize(
    "filename",
    [
        "B2B_Senior_Software_Developer_Ewa_Fikcyjna.docx",
        "CV_B2B_Ewa_Fikcyjna.docx",
        "b2b ewa fikcyjna.docx",
        "B2B.NET_Analityk_Ewa_Fikcyjna_2026.docx",
        "B2B_PANSA_Analityk_Ewa_Fikcyjna.docx",
    ],
)
def test_b2b_word_file_is_a_client_cv(filename: str) -> None:
    assert looks_like_client_cv(filename) is True


@pytest.mark.parametrize(
    "filename",
    [
        # PDF-a nie da się wczytać do edytora — zostaje CV kandydata.
        "B2B_Senior_Software_Developer_Ewa_Fikcyjna.pdf",
        "B2B_Analityk.doc",
        "Ewa_Fikcyjna_CV.docx",
        # „b2b” w środku słowa to nie znacznik CV do klienta.
        "Ewab2bFikcyjna.docx",
        "",
    ],
)
def test_other_files_stay_candidate_cvs(filename: str) -> None:
    assert looks_like_client_cv(filename) is False


@pytest.mark.parametrize(
    ("pattern", "filename"),
    [
        (
            "ZOB-{PROJEKT}_{STANOWISKO}_{IMIE_NAZWISKO}",
            "ZOB-2962_Analityk_Ewa_Fikcyjna.docx",
        ),
        # Pusty projekt: generator zwija „ZOB-_” do „ZOB_”.
        (
            "ZOB-{PROJEKT}_{STANOWISKO}_{IMIE_NAZWISKO}",
            "ZOB_Analityk_Ewa_Fikcyjna.docx",
        ),
        (
            "ORLEN_{PROJEKT}_{STANOWISKO}_{IMIE_NAZWISKO}",
            "Orlen_P1_Analityk_Ewa_Fikcyjna.docx",
        ),
        (
            "Bank_Pocztowy_{STANOWISKO}_{IMIE_NAZWISKO}",
            "Bank Pocztowy_Analityk_Ewa_Fikcyjna.docx",
        ),
        (
            "ENERGA_{PROJEKT}_{STANOWISKO}_{IMIE_NAZWISKO}",
            "ENERGA-X_Tester_Ewa_Fikcyjna.docx",
        ),
    ],
)
def test_client_filename_pattern_is_a_client_cv(pattern: str, filename: str) -> None:
    assert looks_like_client_cv(filename) is False
    assert looks_like_client_cv(filename, pattern) is True


def test_pattern_prefix_needs_a_literal_start() -> None:
    assert pattern_prefix("ZOB-{PROJEKT}_{STANOWISKO}") == "zob"
    assert pattern_prefix("Bank_Pocztowy_{STANOWISKO}") == "bank_pocztowy"
    # Wzór bez stałego początku albo z bardzo krótkim nie rozpoznaje niczego.
    assert pattern_prefix("{STANOWISKO}_{IMIE_NAZWISKO}") == ""
    assert pattern_prefix("CV_{IMIE_NAZWISKO}") == ""
    assert pattern_prefix(None) == ""
    # „ZOBACZ” nie zaczyna się od „ZOB_”.
    assert looks_like_client_cv("ZOBACZ_CV.docx", "ZOB-{PROJEKT}_{STANOWISKO}") is False


def test_cv_header_reads_first_h1() -> None:
    html = "<h1>Analityk – Ewa Fikcyjna</h1><h2>DOŚWIADCZENIE</h2><p>tekst</p>"
    assert cv_header(html) == "Analityk – Ewa Fikcyjna"
    assert cv_header("<p>bez nagłówka</p>") is None
    assert cv_header("") is None


@pytest.mark.parametrize(
    ("header", "filename", "first", "last"),
    [
        ("Analityk – Ewa Fikcyjna", "B2B_Analityk.docx", "Ewa", "Fikcyjna"),
        # Kolejność, wielkość liter i polskie znaki bez znaczenia.
        ("Analityk – FIKCYJNA Ewa", "B2B_Analityk.docx", "Ewa", "Fikcyjna"),
        ("Analityk – Łucja Źdźbłowa", "B2B.docx", "Lucja", "Zdzblowa"),
        # Nazwisko dwuczłonowe w profilu, jeden człon w CV.
        ("Analityk – Ewa Fikcyjna", "B2B.docx", "Ewa", "Fikcyjna-Wzorcowa"),
        # Nagłówek odwrócony: nazwisko przed łącznikiem.
        ("Ewa Fikcyjna – Senior Java Developer", "B2B.docx", "Ewa", "Fikcyjna"),
        # Nazwisko tylko w nazwie pliku.
        ("Analityk – E. F.", "B2B_Analityk_Ewa_Fikcyjna.docx", "Ewa", "Fikcyjna"),
        # CV blind (sam tytuł) i nagłówek bez łącznika przechodzą.
        ("Analityk", "B2B_Analityk_Kandydat.docx", "Ewa", "Fikcyjna"),
        ("Analityk – Kandydat", "B2B.docx", "Ewa", "Fikcyjna"),
        (None, "B2B.docx", "Ewa", "Fikcyjna"),
        # Bez nazwiska w profilu nie mamy z czym porównać.
        ("Analityk – Jan Przykładowy", "B2B.docx", "Ewa", None),
    ],
)
def test_same_person_or_unknown_passes(header, filename, first, last) -> None:
    assert (
        other_person_name(
            header=header, filename=filename, first_name=first, last_name=last
        )
        is None
    )


def test_other_person_in_header_and_filename_is_refused() -> None:
    observed = other_person_name(
        header="Senior Software Developer – Jan Przykładowy",
        filename="B2B_Senior_Software_Developer_Jan_Przykładowy.docx",
        first_name="Ewa",
        last_name="Fikcyjna",
    )
    assert observed == "Jan Przykładowy"
