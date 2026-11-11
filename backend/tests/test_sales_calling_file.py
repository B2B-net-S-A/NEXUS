"""Lista do kampanii z pliku: odczyt CSV i Excela oraz walidacja na granicy (bez bazy)."""

from __future__ import annotations

import io
import zipfile

import pytest
from openpyxl import Workbook

from app.services.sales import calling_file as files
from app.services.sales.calling_file import ListFileError, ListRow, parse_list_file


def _xlsx(rows: list[list[object]]) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    for row in rows:
        sheet.append(row)
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def test_csv_with_polish_headers_and_semicolons() -> None:
    payload = (
        "Firma;Imię;Nazwisko;Stanowisko;Telefon;E-mail;Strona www;Branża;Uwagi\n"
        "Żuraw Sp. z o.o.;Anna;Przykładowa;Dyrektor IT;+48 600 100 200;"
        "Anna@Zuraw-Test.example;https://www.zuraw-test.example/kontakt;Logistyka;pilne\n"
        ";;;;;;;;\n"
        ";Bez;Firmy;;600 100 201;;;;\n"
    ).encode("utf-8-sig")
    listing = parse_list_file("lista.CSV", payload)
    assert listing.without_company == 1
    [row] = listing.rows
    assert row == ListRow(
        line=2,
        company="Żuraw Sp. z o.o.",
        person="Anna Przykładowa",
        title="Dyrektor IT",
        phone="+48 600 100 200",
        email="anna@zuraw-test.example",
        website="https://www.zuraw-test.example/kontakt",
        industry="Logistyka",
        note="pilne",
    )
    assert files.row_domain(row) == "zuraw-test.example"


def test_csv_saved_by_excel_in_cp1250_with_commas() -> None:
    payload = "Nazwa firmy,Osoba,Tel\nŁabędź S.A.,Józef Żółty,600100200\n".encode(
        "cp1250"
    )
    [row] = parse_list_file("lista.csv", payload).rows
    assert (row.company, row.person, row.phone) == (
        "Łabędź S.A.",
        "Józef Żółty",
        "600100200",
    )


def test_xlsx_numbers_become_text_and_bad_values_are_dropped() -> None:
    payload = _xlsx(
        [
            [None, None, None, None],
            ["Company", "Phone", "Email", "NIP"],
            ["Czapla Test", 600100200.0, "to nie adres", 1234567890],
            ["Bez numeru", "12", None, None],
        ]
    )
    first, second = parse_list_file("lista.xlsx", payload).rows
    assert (first.line, first.phone, first.email, first.nip) == (
        3,
        "600100200",
        None,
        "1234567890",
    )
    # Dwie cyfry to nie numer: wiersz zostaje, ale bez telefonu.
    assert (second.company, second.phone) == ("Bez numeru", None)


def test_control_characters_and_overlong_cells_are_cleaned() -> None:
    long_name = "A" * 700
    payload = f"firma;telefon\nKruk\x00\x07‮ Test;600 100 200\n{long_name};600 100 201\n"
    with pytest.raises(ListFileError):
        # Bajt zerowy to nie CSV.
        parse_list_file("lista.csv", payload.encode())
    cleaned = payload.replace("\x00", "")
    first, second = parse_list_file("lista.csv", cleaned.encode()).rows
    assert first.company == "Kruk Test"
    assert len(second.company) == 500


@pytest.mark.parametrize(
    ("value", "digits"),
    [
        ("+48 600-100-200", "600100200"),
        ("0048600100200", "600100200"),
        ("(22) 123 45 67", "221234567"),
        ("+44 20 7946 0958", "442079460958"),
        ("12345", None),
        ("brak", None),
        (None, None),
    ],
)
def test_phone_digits(value: object, digits: object) -> None:
    assert files.phone_digits(value) == digits  # type: ignore[arg-type]


def test_domain_comes_from_site_or_business_mail_only() -> None:
    assert (
        files.site_domain("HTTPS://www.Firma-Test.example/o-nas?x=1")
        == "firma-test.example"
    )
    assert files.site_domain("javascript:alert(1)") is None
    assert files.row_domain(ListRow(line=2, company="X", email="jan@gmail.com")) is None
    assert (
        files.row_domain(ListRow(line=2, company="X", email="jan@firma-test.example"))
        == "firma-test.example"
    )


@pytest.mark.parametrize(
    ("filename", "payload", "detail", "too_large"),
    [
        ("lista.xls", b"firma;telefon\nA;600100200\n", files.BAD_TYPE_DETAIL, False),
        ("lista.pdf", b"%PDF-1.7", files.BAD_TYPE_DETAIL, False),
        ("lista", b"firma;telefon\nA;600100200\n", files.BAD_TYPE_DETAIL, False),
        ("lista.csv", b"   \n", files.EMPTY_DETAIL, False),
        ("lista.csv", b"firma;telefon\n", files.EMPTY_DETAIL, False),
        (
            "lista.csv",
            b"osoba;telefon\nJan;600100200\n",
            files.NO_COMPANY_COLUMN_DETAIL,
            False,
        ),
        ("lista.csv", b"firma;osoba\nA;Jan\n", files.NO_PHONE_COLUMN_DETAIL, False),
        ("lista.xlsx", b"firma;telefon\nA;600100200\n", files.UNREADABLE_DETAIL, False),
        ("lista.xlsx", b"PK\x03\x04 to nie archiwum", files.UNREADABLE_DETAIL, False),
        (
            "lista.csv",
            b"firma;telefon\n" + b"x" * files.MAX_FILE_BYTES,
            files.TOO_BIG_DETAIL,
            True,
        ),
    ],
    # Krótkie nazwy przypadków: bez nich `pytest -v` wypisuje w logu CI cały plik
    # 2 MB jako identyfikator testu, a przetwarzanie takiej linii trwało godzinami.
    ids=[
        "xls",
        "pdf",
        "bez-rozszerzenia",
        "pusty",
        "sam-naglowek",
        "bez-firmy",
        "bez-telefonu",
        "xlsx-to-csv",
        "xlsx-zly-zip",
        "za-duzy",
    ],
)
def test_bad_files_are_refused_with_a_message(
    filename: str, payload: bytes, detail: str, too_large: bool
) -> None:
    with pytest.raises(ListFileError) as caught:
        parse_list_file(filename, payload)
    assert caught.value.detail == detail
    assert caught.value.too_large is too_large


def test_row_limit_applies_to_both_formats() -> None:
    lines = [f"Firma {index};600100{index:03d}" for index in range(files.MAX_ROWS + 1)]
    csv_payload = ("firma;telefon\n" + "\n".join(lines)).encode()
    with pytest.raises(ListFileError) as caught:
        parse_list_file("lista.csv", csv_payload)
    assert caught.value.detail == files.TOO_MANY_ROWS_DETAIL
    exact = ("firma;telefon\n" + "\n".join(lines[: files.MAX_ROWS])).encode()
    assert len(parse_list_file("lista.csv", exact).rows) == files.MAX_ROWS
    sheet = [["firma", "telefon"], *[line.split(";") for line in lines]]
    with pytest.raises(ListFileError) as caught:
        parse_list_file("lista.xlsx", _xlsx(sheet))
    assert caught.value.detail == files.TOO_MANY_ROWS_DETAIL


def test_xlsx_that_unpacks_too_big_is_refused_before_reading() -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "xl/worksheets/sheet1.xml", b"0" * (files.MAX_UNZIPPED_BYTES + 1)
        )
    payload = buffer.getvalue()
    assert len(payload) < files.MAX_FILE_BYTES
    with pytest.raises(ListFileError) as caught:
        parse_list_file("lista.xlsx", payload)
    assert (caught.value.detail, caught.value.too_large) == (files.TOO_BIG_DETAIL, True)
