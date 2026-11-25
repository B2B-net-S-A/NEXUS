"""Zestawienie dostawcy BNP Paribas CIB („Vendor's file”, ``vendor_file``). Bez bazy.

Próba IX–X 2026: koordynatorka wysyła klientowi „RRRRMM_<firma>_worksheet.xlsx”,
klient odpisuje „Potwierdzam zestawienie”. Nikt nie czytał pliku, więc rozliczenie
stało w „Czeka na liczbę MD”. Faktury Finansów: IX 11,5 MD, X 21,5 MD. Osoby
i liczby fikcyjne.
"""

from __future__ import annotations

import asyncio
import io
from decimal import Decimal

from app.models.consultant_portal import CpDocument
from app.services.client_settlements import rules_catalog, service, vendor_file

PERSON = "Jan Testowy"
HEADER = [
    "No.",
    "ID",
    "Service",
    "Year",
    "Month",
    "Resource Name (without Polish letters)",
    "Resource Type",
    "Act MD",
    "Act Hours",
]


def _row(person: str = PERSON, month: object = "September", md=11.5, hours=92):
    return [1, "h00001", "Java Developer", 2026, month, person, "Contractor", md, hours]


def _xlsx(*rows: list[object]) -> bytes:
    import openpyxl

    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "Vendor's file"
    sheet.append(HEADER)
    for row in rows:
        sheet.append(row)
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def _declared(*rows: list[object], person: str = PERSON):
    parsed = vendor_file.parse_rows([HEADER, *rows])
    assert parsed is not None
    return vendor_file.declared_for(parsed, person, Decimal("8"))


def test_wiersz_osoby_daje_md_godziny_i_miesiac():
    found = _declared(_row())
    assert found is not None
    assert (found.md, found.hours, found.month) == (
        Decimal("11.5"),
        Decimal("92"),
        "2026-09",
    )
    assert found.consultant == PERSON


def test_md_z_jednostka_w_komorce():
    found = _declared(_row(md="17,5MD", hours=140))
    assert found is not None and found.md == Decimal("17.5")


def test_osoba_bez_polskich_liter_i_miesiac_liczba():
    found = _declared(
        _row(person="Lukasz Zolw", month=10, md=21.5, hours=172), person="Łukasz Żółw"
    )
    assert found is not None and (found.md, found.month) == (Decimal("21.5"), "2026-10")


def test_plik_innej_osoby_nic_nie_daje():
    # U klienta kontrola nazwiska jest wyłączona: MD innej osoby weszłyby bez śladu.
    assert _declared(_row(person="Anna Inna")) is None


def test_kilka_osob_w_pliku_bierze_tylko_swoja():
    found = _declared(_row(person="Anna Inna", md=20, hours=160), _row())
    assert found is not None and found.md == Decimal("11.5")


def test_godziny_niezgodne_z_md_to_brak_liczby():
    found = _declared(_row(md=11.5, hours=100))
    assert found is not None
    assert (found.md, found.hours) == (None, None)


def test_dwa_miesiace_osoby_to_brak_liczby():
    found = _declared(_row(), _row(month="October", md=21.5, hours=172))
    assert found is not None
    assert (found.md, found.month) == (None, None)


def test_arkusz_bez_naglowka_to_nie_zestawienie():
    assert vendor_file.parse_rows([["Date", "Total Hours"], ["2026-09-01", 8]]) is None
    assert vendor_file.parse(b"to nie xlsx", vendor_file.XLSX) is None


def test_plik_xlsx():
    parsed = vendor_file.parse(_xlsx(_row()), vendor_file.XLSX)
    assert parsed is not None and parsed[0].md == Decimal("11.5")


# ── Rozliczenie: odczyt pliku miesiąca ───────────────────────────────────────


def _read(content: bytes, month: str = "2026-09"):
    doc = CpDocument(id=5, mime=vendor_file.XLSX, kind="report", file_path="x.xlsx")
    return asyncio.run(
        service._read_file(
            doc,
            content,
            reports=[doc],
            month=month,
            person_name=PERSON,
            rules=rules_catalog.effective({}),
            other_md=Decimal("0"),
            working_days=22,
        )
    )


def test_rozliczenie_bierze_md_z_zestawienia():
    result = _read(_xlsx(_row()))
    assert result is not None
    assert result.md_regular == Decimal("11.500")
    titles = {c["title"] for g in result.groups for c in g["checks"]}
    assert "Miesiąc z dokumentu: wrzesień 2026" in titles


def test_zestawienie_za_inny_miesiac_bez_md():
    result = _read(_xlsx(_row()), month="2026-10")
    assert result is not None and result.md_regular is None
