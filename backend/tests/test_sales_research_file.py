"""Lista osób z researchu z pliku: odczyt CSV i Excela, walidacja na granicy (bez bazy).

Dane są fikcyjne.
"""

from __future__ import annotations

import io
import zipfile
from typing import Optional

import pytest
from openpyxl import Workbook

from app.services.sales import research_file as files
from app.services.sales.research_file import (
    CONFIRMED,
    TO_VERIFY,
    ResearchFileError,
    ResearchRow,
    SkippedRow,
    parse_research_file,
)


def _xlsx(rows: list[list[object]]) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    for row in rows:
        sheet.append(row)
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def _csv(header: str, *rows: str) -> bytes:
    return "\n".join((header, *rows)).encode("utf-8")


def test_csv_with_polish_headers_reads_every_field() -> None:
    payload = (
        "Firma;Imię i nazwisko;Stanowisko;E-mail;Telefon;LinkedIn;Źródło;Strona www;"
        "Pewność;Poziom;Notatka\n"
        "Żuraw Sp. z o.o.;Anna Przykładowa;Head of Data;Anna@Zuraw-Test.example;"
        "+48 600 100 200;linkedin.com/in/anna-przykladowa;"
        "https://zuraw-test.example/zespol;https://www.zuraw-test.example/o-nas;"
        "Pewne;;buduje zespół danych\n"
    ).encode("utf-8-sig")

    listing = parse_research_file("lista.CSV", payload)

    assert listing.skipped == []
    assert listing.rows == [
        ResearchRow(
            line=2,
            company="Żuraw Sp. z o.o.",
            name="Anna Przykładowa",
            title="Head of Data",
            email="anna@zuraw-test.example",
            phone="+48 600 100 200",
            linkedin_url="https://linkedin.com/in/anna-przykladowa",
            source_url="https://zuraw-test.example/zespol",
            domain="zuraw-test.example",
            confidence=CONFIRMED,
            decision_level=2,
            note="buduje zespół danych",
        )
    ]


def test_csv_saved_by_excel_in_cp1250_with_separate_name_columns() -> None:
    payload = (
        "Nazwa firmy,Imię,Nazwisko,Rola\nŁabędź S.A.,Józef,Żółty,Kierownik\n".encode(
            "cp1250"
        )
    )
    [row] = parse_research_file("lista.csv", payload).rows
    assert (row.company, row.name, row.title) == (
        "Łabędź S.A.",
        "Józef Żółty",
        "Kierownik",
    )
    # Bez kolumny pewności i poziomu: do weryfikacji, poziom z nazwy stanowiska.
    assert (row.confidence, row.decision_level) == (TO_VERIFY, 3)


def test_bad_rows_are_skipped_with_a_reason_and_do_not_fail_the_file() -> None:
    payload = _csv(
        "Firma;Osoba;Stanowisko",
        "Czapla Test;Jan Fikcyjny;Manager",
        ";Bez Firmy;Manager",
        "Czapla Test;;Manager",
        ";;",
        "Bocian Test;Ewa Zmyślona;Director",
    )

    listing = parse_research_file("lista.csv", payload)

    assert [row.name for row in listing.rows] == ["Jan Fikcyjny", "Ewa Zmyślona"]
    assert listing.skipped == [
        SkippedRow(line=3, reason=files.NO_COMPANY_REASON),
        SkippedRow(line=4, reason=files.NO_PERSON_REASON),
    ]


def test_invalid_optional_values_are_dropped_with_a_warning() -> None:
    payload = _csv(
        "Firma;Osoba;E-mail;Telefon;LinkedIn;Źródło",
        "Czapla Test;Jan Fikcyjny;jan@;12;javascript:alert(1);ftp://czapla.example/x",
    )

    [row] = parse_research_file("lista.csv", payload).rows

    assert (row.email, row.phone, row.linkedin_url, row.source_url) == (
        None,
        None,
        None,
        None,
    )
    assert len(row.warnings) == 4
    assert row.domain is None


def test_control_characters_are_cut_and_cells_trimmed_to_limits() -> None:
    long_note = "n" * 5000
    payload = _csv(
        "Firma;Osoba;Stanowisko;Notatka",
        f"Czapla\x00‮ Test;Jan​ Fikcyjny\x07;Lead\x1b[31m;{long_note}",
    )
    # Bajt zerowy w CSV to plik binarny, nie lista.
    with pytest.raises(ResearchFileError):
        parse_research_file("lista.csv", payload)

    [row] = parse_research_file("lista.csv", payload.replace(b"\x00", b"")).rows
    assert row.company == "Czapla Test"
    assert row.name == "Jan Fikcyjny"
    assert row.title == "Lead [31m"
    assert row.note is not None and len(row.note) == 2000


@pytest.mark.parametrize(
    ("title", "level"),
    [
        ("Chief Data Officer", 1),
        ("CDO", 1),
        ("VP of Engineering", 1),
        ("Vice President, Data & AI", 1),
        ("Członek Zarządu ds. IT", 1),
        ("Wiceprezes", 1),
        ("Head of Data Platform", 2),
        ("Director, AI & Analytics", 2),
        ("Dyrektorka Departamentu Danych", 2),
        ("Associate Director of Analytics", 2),
        ("Data Engineering Manager", 3),
        ("AI Team Lead", 3),
        ("Kierownik Zespołu Analiz", 3),
        # Słowo w środku innego słowa nie jest tytułem.
        ("Headcount Analyst", 3),
        ("", 3),
        (None, 3),
    ],
)
def test_level_comes_from_the_job_title(title: Optional[str], level: int) -> None:
    assert files.level_from_title(title) == level


def test_level_column_wins_over_the_title() -> None:
    payload = _csv(
        "Firma;Osoba;Stanowisko;Poziom",
        "Czapla Test;Jan Fikcyjny;Head of Data;3",
        "Czapla Test;Ewa Zmyślona;Analityk;1 · Zarząd",
        "Czapla Test;Adam Wymyślony;Director;17",
    )
    rows = parse_research_file("lista.csv", payload).rows
    # Wartość spoza 1–4 to brak poziomu w pliku: decyduje stanowisko.
    assert [row.decision_level for row in rows] == [3, 1, 2]


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("Pewne", CONFIRMED),
        ("potwierdzone", CONFIRMED),
        ("TAK", CONFIRMED),
        ("Do weryfikacji", TO_VERIFY),
        ("niepewne", TO_VERIFY),
        ("", TO_VERIFY),
        (None, TO_VERIFY),
    ],
)
def test_only_a_clear_confirmation_is_confirmed(
    value: Optional[str], expected: str
) -> None:
    assert files.confidence_of(value) == expected


def test_domain_comes_from_the_site_or_a_company_mailbox() -> None:
    assert files.company_domain("https://www.czapla.example/x", None) == (
        "czapla.example"
    )
    assert files.company_domain(None, "jan@czapla.example") == "czapla.example"
    # Poczta publiczna nie jest domeną firmy.
    assert files.company_domain(None, "jan@gmail.com") is None
    assert files.company_domain("to nie adres", None) is None


def test_a_profile_given_as_the_source_is_also_the_linkedin_channel() -> None:
    payload = _csv(
        "Firma;Osoba;Źródło",
        "Czapla Test;Jan Fikcyjny;https://www.linkedin.com/in/jan-fikcyjny",
    )
    [row] = parse_research_file("lista.csv", payload).rows
    assert (
        row.linkedin_url
        == row.source_url
        == ("https://www.linkedin.com/in/jan-fikcyjny")
    )


def test_xlsx_is_read_and_numbers_stay_text() -> None:
    payload = _xlsx(
        [
            [None, None, None],
            ["Firma", "Osoba", "Telefon", "Poziom"],
            ["Czapla Test", "Jan Fikcyjny", 600100200.0, 2.0],
        ]
    )
    [row] = parse_research_file("lista.xlsx", payload).rows
    assert (row.phone, row.decision_level, row.line) == ("600100200", 2, 3)


@pytest.mark.parametrize(
    ("filename", "payload", "detail"),
    [
        ("lista.pdf", b"%PDF", files.BAD_TYPE_DETAIL),
        ("lista.csv", b"  \n ", files.EMPTY_DETAIL),
        ("lista.csv", "Firma;Osoba\n".encode(), files.EMPTY_DETAIL),
        (
            "lista.csv",
            "Osoba;Stanowisko\nJan;Lead\n".encode(),
            files.NO_COMPANY_COLUMN_DETAIL,
        ),
        (
            "lista.csv",
            "Firma;Stanowisko\nCzapla;Lead\n".encode(),
            files.NO_PERSON_COLUMN_DETAIL,
        ),
        ("lista.xlsx", b"to nie jest arkusz", files.UNREADABLE_DETAIL),
    ],
)
def test_a_file_that_cannot_be_a_list_is_refused(
    filename: str, payload: bytes, detail: str
) -> None:
    with pytest.raises(ResearchFileError) as error:
        parse_research_file(filename, payload)
    assert error.value.detail == detail


def test_row_and_size_limits() -> None:
    rows = [f"Czapla Test;Osoba {index}" for index in range(files.MAX_ROWS + 1)]
    with pytest.raises(ResearchFileError) as error:
        parse_research_file("lista.csv", _csv("Firma;Osoba", *rows))
    assert error.value.detail == files.TOO_MANY_ROWS_DETAIL

    exactly = parse_research_file("lista.csv", _csv("Firma;Osoba", *rows[:-1]))
    assert len(exactly.rows) == files.MAX_ROWS

    with pytest.raises(ResearchFileError) as error:
        parse_research_file("lista.csv", b"x" * (files.MAX_FILE_BYTES + 1))
    assert error.value.too_large is True


def test_xlsx_that_unpacks_to_a_huge_sheet_is_refused_before_reading() -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "xl/worksheets/sheet1.xml", b"0" * (files.MAX_UNZIPPED_BYTES + 1)
        )
    with pytest.raises(ResearchFileError) as error:
        parse_research_file("lista.xlsx", buffer.getvalue())
    assert error.value.too_large is True


def _with_sheet(payload: bytes, rewrite) -> bytes:
    """Ten sam arkusz z podmienioną treścią pierwszego skoroszytu."""

    source = zipfile.ZipFile(io.BytesIO(payload))
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as target:
        for member in source.infolist():
            data = source.read(member.filename)
            if member.filename == "xl/worksheets/sheet1.xml":
                data = rewrite(data)
            target.writestr(member.filename, data)
    return buffer.getvalue()


def test_xlsx_with_blank_stretches_keeps_the_rows_below_them() -> None:
    """Puste wiersze nie zjadają limitu: dane pod nimi też są listą."""

    rows: list[list[object]] = [["Firma", "Osoba"]]
    rows += [["Czapla Test", f"Osoba {index}"] for index in range(300)]
    rows += [[None, None] for _ in range(300)]
    rows += [["Bocian Test", f"Dalsza {index}"] for index in range(100)]

    listing = parse_research_file("lista.xlsx", _xlsx(rows))

    assert len(listing.rows) == 400
    assert listing.rows[-1].name == "Dalsza 99"

    too_many = rows + [["Bocian Test", f"Nadmiar {index}"] for index in range(101)]
    with pytest.raises(ResearchFileError) as error:
        parse_research_file("lista.xlsx", _xlsx(too_many))
    assert error.value.detail == files.TOO_MANY_ROWS_DETAIL


def test_xlsx_with_broken_sheet_xml_is_a_bad_file_not_a_crash() -> None:
    payload = _xlsx([["Firma", "Osoba"], ["Czapla Test", "Jan Fikcyjny"]])
    broken = _with_sheet(payload, lambda data: data[: len(data) // 2])
    with pytest.raises(ResearchFileError) as error:
        parse_research_file("lista.xlsx", broken)
    assert error.value.detail == files.UNREADABLE_DETAIL


def test_xlsx_with_an_entity_bomb_is_refused() -> None:
    """Encje rozwijają się w pamięci, nie w archiwum: rozmiar pliku ich nie zdradza."""

    # 50 znaków × 10^6 = 50 MB po rozwinięciu z arkusza, który waży kilobajt.
    entities = f'<!ENTITY a0 "{"a" * 50}">' + "".join(
        f'<!ENTITY a{level} "{f"&a{level - 1};" * 10}">' for level in range(1, 7)
    )

    def bomb(data: bytes) -> bytes:
        sheet = data.decode("utf-8").replace("Jan Fikcyjny", "&a6;")
        return f"<!DOCTYPE worksheet [{entities}]>{sheet}".encode()

    payload = _xlsx([["Firma", "Osoba"], ["Czapla Test", "Jan Fikcyjny"]])
    workbook = _with_sheet(payload, bomb)
    sheet = zipfile.ZipFile(io.BytesIO(workbook)).read("xl/worksheets/sheet1.xml")
    assert b"&a6;" in sheet and len(workbook) < 20_000

    with pytest.raises(ResearchFileError) as error:
        parse_research_file("lista.xlsx", workbook)
    assert error.value.detail == files.UNREADABLE_DETAIL


def test_tens_of_thousands_of_blank_lines_are_not_a_list() -> None:
    payload = (
        "Firma;Osoba\n" + "\n" * files.MAX_SCANNED_LINES + "Czapla;Jan\n"
    ).encode()
    with pytest.raises(ResearchFileError) as error:
        parse_research_file("lista.csv", payload)
    assert error.value.detail == files.TOO_MANY_ROWS_DETAIL


def test_same_person_key_ignores_word_order_case_and_diacritics() -> None:
    assert files.person_key("Żółty Józef") == files.person_key("józef  ZOLTY")
    assert files.person_key("  ") is None
