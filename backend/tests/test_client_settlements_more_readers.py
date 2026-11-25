"""Czytniki MD z plików, które po próbie IX–X 2026 zostawały w „Sprawdzaniu”.

Bez bazy. Dane fikcyjne: osoby „Jan Testowy” i „Anna Inna”, projekty ALFA,
stawki i kwoty wymyślone. Każdy wzór: MD = godziny / ``fields.md_hours`` (albo
MD wprost z dokumentu), plik spoza wzoru daje ``None``, a miesiąc spoza okresu
to kontrola ``proof.month`` bez MD.
"""

from __future__ import annotations

import io
from datetime import datetime
from decimal import Decimal
from email.message import EmailMessage

import docx
import openpyxl

from app.models.consultant_portal import CpDocument
from app.services.client_settlements import (
    confirmation_ergo,
    declared,
    mail_nn,
    protocol_orlen,
    rules_catalog,
    service,
    timesheet,
    timesheet_bik,
)

MONTH = "2026-09"
PERSON = "Jan Testowy"
EML = "message/rfc822"


def _rules(md_hours: str = "8", month_level: str = "block") -> dict:
    return rules_catalog.effective(
        {
            "proof.month": {"level": month_level},
            "proof.name_match": {"level": "warn"},
            "proof.excel_with_mail": {"level": "off"},
            "proof.accept_has_hours": {"level": "off"},
            "fields.md_hours": {"level": "block", "params": {"hours": md_hours}},
            "fields.day_limit": {"level": "block", "params": {"hours": "24"}},
            "fields.md_month_limit": {"level": "off"},
        }
    )


def _titles(result) -> dict[str, str]:
    return {c["title"]: c["state"] for g in result.groups for c in g["checks"]}


def _sheet_result(parsed, rules=None, month=MONTH):
    return timesheet.evaluate(
        parsed,
        month=month,
        person_name=PERSON,
        has_mail=False,
        rules=rules or _rules(),
        working_days=22,
    )


def _declared_result(parsed, rules=None, month=MONTH):
    return declared.evaluate(
        parsed,
        month=month,
        person_name=PERSON,
        rules=rules or _rules(),
        working_days=22,
    )


# ── 1. Time Sheet w PDF ───────────────────────────────────────────────────────

TS_PDF = """Time Sheet
Project Name ALFA - Klient Testowy Sp. z o.o.
Consultant(s) Jan Testowy
Date from 2026-09-01
Date to 2026-09-30
Date Project Description Total Hours Billable Non-billable
2026-09-01 ALFA Urlop 0 0 0
2026-09-02 ALFA Testy modułu A 6 6 0
Spotkania zespołu, przegląd zadań, zawinięty opis
2026-09-03 ALFA-1, ALFA-2 8 8 -
2026-09-04 - - -
2026-09-05
2026-09-07 ALFA Testy 2026 wydania 6 6 0
Total Hours (This month) 20
Print Name Jan Testowy Print Name
Date 2026-09-30
"""


def test_time_sheet_pdf_md_z_godzin():
    parsed = timesheet.parse_rows([timesheet.text_rows(TS_PDF)])

    assert parsed is not None
    assert parsed.consultant == PERSON
    assert parsed.month == MONTH
    assert parsed.total_hours == Decimal("20")
    assert parsed.declared_total == Decimal("20")
    result = _sheet_result(parsed)
    assert result.md_regular == Decimal("2.500")
    assert not result.blocking


def test_time_sheet_pdf_md_dzieli_przez_fields_md_hours():
    parsed = timesheet.parse_rows([timesheet.text_rows(TS_PDF)])

    assert _sheet_result(parsed, _rules(md_hours="5")).md_regular == Decimal("4.000")


def test_time_sheet_pdf_dzien_tygodnia_przed_data_z_kropkami():
    text = """Time Sheet
Project Name:
Consultant(s) Jan Testowy
Day Date Project Total Hours Billable
Tuesday 2026.09.01 OPEX 2026 - Automaty 8 8
Wednesday 2026.09.02 OPEX 2026 - Automaty 7.5 7.5
Saturday 2026.09.05
Total Hours (This Week) 15.5
"""
    parsed = timesheet.parse_rows([timesheet.text_rows(text)])

    assert parsed.month == MONTH  # bez „Date from”: z dat wierszy
    assert parsed.total_hours == Decimal("15.5")
    assert _sheet_result(parsed).md_regular == Decimal("1.938")


def test_pdf_okres_od_do_z_jedna_kolumna_godzin():
    text = """Jan Testowy Okres od: 01.09.2026
Projekt: ALFA Okres do: 30.09.2026
Data Dzień Opis Godziny Rozliczalne
2026-09-01 wtorek Testowanie oprogramowania 8 8
2026-09-02 środa Testowanie oprogramowania 9
2026-09-05 sobota Testowanie oprogramowania 0
W sumie 17 17
"""
    parsed = timesheet.parse_rows([timesheet.text_rows(text)])

    assert parsed.consultant == PERSON
    assert parsed.project_name == "ALFA"
    assert parsed.month == MONTH
    assert parsed.total_hours == Decimal("17")
    assert parsed.declared_total == Decimal("17")
    assert _sheet_result(parsed).md_regular == Decimal("2.125")


# Time Sheet Boscha w PDF (próba IX–X 2026): daty „DD-MM-RRRR”, a opis zawinięty
# w komórce rozbija wiersz — data stoi sama, godziny w następnej linii.
TS_PDF_DMY = """Time Sheet
Project Name ALFA
Consultant(s) Jan Testowy
Date from 01.09.2026
Date to 30.09.2026
Date Project Description Total Hours Billable Non-billable
01-09-2026 ALFA Testy regresji 8 8 0
02-09-2026 ALFA 8 8 0
Przegląd zadań po aktualizacji
03-09-2026
ALFA środowiska testowego 8 8 0
04-09-2026 ALFA Testy regresji 7,5 7,5 0
05-09-2026
07-09-2026 ALFA Testy regresji 8 8 0
Total Hours (This Month) 39,5
Print Name Print Name
Signed on behalf of Consultant Signed for on behalf of B2Bnetwork
Date 30.09.2026
"""


def test_time_sheet_pdf_z_datami_dzien_miesiac_rok():
    parsed = timesheet.parse_rows([timesheet.text_rows(TS_PDF_DMY)])

    assert parsed is not None
    assert parsed.consultant == PERSON
    assert parsed.month == MONTH
    assert [e.day.day for e in parsed.entries] == [1, 2, 3, 4, 7]
    assert parsed.total_hours == Decimal("39.5")
    assert parsed.declared_total == Decimal("39.5")
    result = _sheet_result(parsed)
    assert result.md_regular == Decimal("4.938")
    assert _titles(result)["Godziny policzone od nowa"] == "ok"
    assert not result.blocking


def test_time_sheet_pdf_godziny_wiersza_z_opisem_zawinietym_pod_data():
    parsed = timesheet.parse_rows([timesheet.text_rows(TS_PDF_DMY)])

    wrapped = next(e for e in parsed.entries if e.day.day == 3)
    assert wrapped.hours == Decimal("8")
    assert wrapped.description == "ALFA środowiska testowego"


def test_time_sheet_pdf_data_bez_godzin_nie_bierze_godzin_innej_linii():
    text = TS_PDF_DMY.replace(
        "03-09-2026\nALFA środowiska testowego 8 8 0",
        "03-09-2026\nALFA wydanie 2026",
    )
    parsed = timesheet.parse_rows([timesheet.text_rows(text)])

    assert [e.day.day for e in parsed.entries] == [1, 2, 4, 7]
    # Sobota 05-09 bez godzin nie bierze godzin z wiersza 07-09.
    assert all(e.day.day != 5 for e in parsed.entries)


def test_pdf_spoza_wzoru_time_sheet_to_none():
    assert timesheet.text_rows("Faktura nr 1/09/2026\nRazem 1000,00 PLN") is None
    # Wiersze z datami bez nagłówka szablonu to nie Time Sheet.
    assert timesheet.text_rows("Time Sheet\n2026-09-01 ALFA 8 8") is None


def test_time_sheet_pdf_za_inny_miesiac_to_kontrola_bez_md():
    parsed = timesheet.parse_rows([timesheet.text_rows(TS_PDF)])
    result = _sheet_result(parsed, month="2026-10")

    assert result.md_regular is None
    assert result.blocking
    assert _titles(result)["Time Sheet za inny miesiąc"] == "fail"


def test_inny_miesiac_przy_wylaczonej_regule_to_informacja_bez_md():
    parsed = timesheet.parse_rows([timesheet.text_rows(TS_PDF)])
    result = _sheet_result(parsed, _rules(month_level="off"), month="2026-10")

    assert result.md_regular is None
    assert not result.blocking
    assert _titles(result)["Time Sheet za inny miesiąc"] == "none"


# ── 2. Polski wariant XLSX ────────────────────────────────────────────────────


def _polish_sheet(year: int = 2026) -> list[list]:
    return [
        [None, "Time Sheet"],
        [None, "Imię Nazwisko", PERSON],
        [None, "Data", "Opis zadań", "Liczba godzin", "Uwagi"],
        [None, datetime(year, 9, 1), "Testy", 8, None],
        [None, datetime(year, 9, 2), None, 6, None],
        [None, datetime(year, 9, 5), None, None, None],
        [None, "Łączna liczba godzin", None, 14, None],
    ]


def _xlsx(rows: list[list]) -> bytes:
    workbook = openpyxl.Workbook()
    for row in rows:
        workbook.active.append(row)
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def test_polski_time_sheet_xlsx_md_z_godzin():
    parsed = timesheet.parse(_xlsx(_polish_sheet()), timesheet.XLSX)

    assert parsed is not None
    assert parsed.consultant == PERSON
    assert parsed.total_hours == Decimal("14")
    assert parsed.declared_total == Decimal("14")
    assert _sheet_result(parsed).md_regular == Decimal("1.750")


def test_polski_time_sheet_z_rokiem_spoza_okresu_to_kontrola_bez_md():
    parsed = timesheet.parse_rows([_polish_sheet(year=2025)])
    result = _sheet_result(parsed)

    assert parsed.month == "2025-09"
    assert result.md_regular is None
    assert _titles(result)["Time Sheet za inny miesiąc"] == "fail"


def test_tabela_data_liczba_godzin_bez_tytulu_time_sheet_to_none():
    # Ta sama tabela jest w raporcie BIK; bez tytułu „Time Sheet” nie jest naszym wzorem.
    rows = [r for r in _polish_sheet() if r[1] != "Time Sheet"]
    assert timesheet.parse_rows([rows]) is None


# ── 3. Raport BIK w PDF bez tabel ─────────────────────────────────────────────

BIK_SHORT = """Rozliczenie czasu pracy zamówienia numer 1234
Za miesiąc wrzesien 2026
Imię i nazwisko: Jan Testowy..
Zadanie Data Czas (godz.)
BIK 1.09.2026 9
BIK 2.09.2026 8
BIK 3.09.2026 7
Suma 24 h
"""

BIK_LONG = """Rozliczenie czasu pracy
Imię i nazwisko Jan Testowy
Miesiąc 01.09.2026
Numer zamówienia
Nazwa zadania Data Liczba godzin
ALFA-101 Moduł płatności Przygotowanie środowiska 1-09 8
Weekend 5-09 0
Przygotowanie testów
2-09
ALFA-102 Moduł płatności wydajnościowych 8
ALFA-103 3-09
Usuwanie podatności Pół dnia 4
Razem 20
"""


def _bik_result(parsed, rules=None, month=MONTH):
    return timesheet_bik.evaluate(
        parsed,
        month=month,
        person_name=PERSON,
        rules=rules or _rules(),
        working_days=22,
    )


def test_bik_pdf_suma_h_md_z_godzin():
    parsed = timesheet_bik.parse_rows(
        timesheet_bik.text_rows(BIK_SHORT), source="pdf", title=True
    )

    assert parsed.consultant == PERSON
    assert parsed.entries_month() == MONTH
    assert parsed.total_hours == Decimal("24")
    assert parsed.declared_total == Decimal("24")
    assert _bik_result(parsed).md_regular == Decimal("3.000")


def test_bik_pdf_dni_bez_roku_i_zawiniete_opisy():
    parsed = timesheet_bik.parse_rows(
        timesheet_bik.text_rows(BIK_LONG), source="pdf", title=True
    )

    assert parsed.month == MONTH
    assert [e.hours for e in parsed.entries] == [
        Decimal("8"),
        Decimal("8"),
        Decimal("4"),
    ]
    assert parsed.declared_total == Decimal("20")
    result = _bik_result(parsed, _rules(md_hours="4"))
    assert result.md_regular == Decimal("5.000")
    assert not result.blocking


def test_bik_pdf_bez_naglowka_tabeli_to_none():
    text = "Rozliczenie czasu pracy\nImię i nazwisko Jan Testowy\nSuma 24 h"
    assert (
        timesheet_bik.parse_rows(
            timesheet_bik.text_rows(text), source="pdf", title=True
        )
        is None
    )


def test_bik_pdf_za_inny_miesiac_to_kontrola_bez_md():
    parsed = timesheet_bik.parse_rows(
        timesheet_bik.text_rows(BIK_SHORT), source="pdf", title=True
    )
    result = _bik_result(parsed, month="2026-10")

    assert result.md_regular is None
    assert _titles(result)["Raport godzin za inny miesiąc"] == "fail"


# ── 4. Potwierdzenie godzin ERGO ──────────────────────────────────────────────

ERGO = """Monthly confirmation of hours worked by an External Consultant
This document is the basis for approval for payment for work performed
Month (mm/yyyy) External Consultant name
01-09-2026 Jan Testowy
↑select from the list ↑select from the list
No Project name Comments
1 ALFA Websites (ID-0001) Time Tracking 152
2
Total 152.00
I confirm that the number of hours reported is correct
"""


def test_ergo_md_z_total():
    parsed = confirmation_ergo.parse_text(ERGO)

    assert parsed.consultant == PERSON
    assert parsed.month == MONTH
    assert parsed.hours == Decimal("152.00")
    result = _declared_result(parsed)
    assert result.md_regular == Decimal("19.000")
    assert not result.blocking and not result.warn


def test_ergo_nowszy_wzor_miesiac_slowem_i_total_z_pd():
    text = """Monthly confirmation of hours worked by a Consultant
Month (mm/yyyy) Consultant name
September 2026 Testowy Jan
1 ALFA 168 21 Time Tracking
Total 168,00 21,00
"""
    parsed = confirmation_ergo.parse_text(text)

    assert parsed.month == MONTH
    assert parsed.hours == Decimal("168.00")
    assert _declared_result(parsed, _rules(md_hours="7")).md_regular == Decimal(
        "24.000"
    )


def test_ergo_inny_pdf_to_none():
    assert confirmation_ergo.parse_text("Faktura numer 1/2026\nTotal 100") is None


def test_ergo_za_inny_miesiac_to_kontrola_bez_md():
    result = _declared_result(confirmation_ergo.parse_text(ERGO), month="2026-10")

    assert result.md_regular is None
    assert result.blocking
    assert _titles(result)["Potwierdzenie godzin ERGO za inny miesiąc"] == "fail"


# ── 5. Mail rozliczeń NN z „Ilość MD” ─────────────────────────────────────────

NN_BODY = """Dzień dobry,

Poniżej znajdują się szczegóły zaakceptowanego odbioru pracy Państwa pracownika:
Imię i nazwisko: Jan Testowy
Okres pracy: 09-2026
Spółka: Klient Testowy S.A.
Numer zamówienia
Nazwa CK
Opis wykonywanej pracy
Ilość MD
Kwota netto
Kwota brutto
00000001
ALFA - Moduł testowy
Prace dewelopera
22.875
22,875.00 PLN
28,136.25 PLN


Kwota netto do zafakturowania: 22,875.00 PLN
Kwota brutto do zafakturowania: 28,136.25 PLN
"""


def _eml(
    body: str, subject: str = "Rozliczenie pracownika Jan Testowy za okres 09-2026"
) -> bytes:
    message = EmailMessage()
    message["From"] = "Rozliczenia <rozliczenia@klient.example>"
    message["To"] = "opiekun@firma.example"
    message["Subject"] = subject
    message.set_content(body)
    return message.as_bytes()


def test_nn_mail_md_wprost_bez_przeliczania():
    parsed = mail_nn.parse(_eml(NN_BODY), EML)

    assert parsed.consultant == PERSON
    assert parsed.month == MONTH
    assert parsed.md == Decimal("22.875")
    assert parsed.amount == Decimal("22875.00")
    # MD z akceptacji klienta, nie z godzin: ``fields.md_hours`` nic nie zmienia.
    assert _declared_result(parsed, _rules(md_hours="6")).md_regular == Decimal(
        "22.875"
    )


def test_nn_cytowana_ponownie_tabela_nie_podwaja_md():
    quoted = "\n".join(f"> {line}" for line in NN_BODY.splitlines())
    parsed = mail_nn.parse_text(f"FYI\n{NN_BODY}\n{quoted}")

    assert parsed.md == Decimal("22.875")


NN_FORWARDED = """Z pozdrowieniami,
Opiekun Testowy
________________________________
From: Rozliczenia kontraktorów
Sent: Tuesday, May 12, 2026 9:00:26 AM
Subject: Rozliczenie pracownika Jan Testowy za okres 09-2026
Dzień dobry,
Poniżej znajdują się szczegóły zaakceptowanego odbioru pracy Państwa pracownika:
Imię i nazwisko: Jan Testowy
Okres pracy: 09-2026
Numer zamówienia Nazwa CK Opis wykonywanej pracy Ilość MD Kwota netto Kwota brutto
00000001 ALFA - Moduł testowy Prace dewelopera v2 20 19,200.00 PLN 23,616.00 PLN
Kwota netto do zafakturowania: 19,200.00 PLN
Kwota brutto do zafakturowania: 23,616.00 PLN
"""


def test_nn_przekazany_mail_z_wierszem_w_jednej_linii():
    parsed = mail_nn.parse(
        _eml(NN_FORWARDED, subject="Fw: Rozliczenie pracownika"), EML
    )

    assert parsed.consultant == PERSON
    assert parsed.month == MONTH
    assert parsed.md == Decimal("20")
    assert parsed.amount == Decimal("19200.00")


def test_nn_wiersz_w_jednej_linii_z_kwotami_po_polsku():
    text = NN_FORWARDED.replace(
        "19,200.00 PLN 23,616.00 PLN", "19 200,00 PLN 23 616,00 PLN"
    )
    parsed = mail_nn.parse_text(text)

    assert parsed.md == Decimal("20")
    assert parsed.amount == Decimal("19200.00")


def test_inny_mail_to_none():
    assert mail_nn.parse(_eml("Akceptuję godziny za wrzesień."), EML) is None


def test_nn_za_inny_okres_to_kontrola_bez_md():
    result = _declared_result(mail_nn.parse_text(NN_BODY), month="2026-10")

    assert result.md_regular is None
    assert _titles(result)["Akceptacja NN za inny miesiąc"] == "fail"


# ── 6. Protokół Orlenu ────────────────────────────────────────────────────────

ORLEN_HOURS = """PROTOKÓŁ
DOTYCZY ZAMÓWIENIA NR: 1
OKRES ROZLICZENIOWY: WRZESIEŃ 2026
Członkowie Personelu
Jan Testowy (150zł x8h = 1200zł MD)
Faktyczny wymiar Roboczodni, w
jakim dany członek Personelu
22 MD - po 6h
Sugerowane
wynagrodzenie
132 h x 150 PLN = 19 800 PLN
"""

ORLEN_MD = """PROTOKÓŁ
OKRES ROZLICZENIOWY: _WRZESIEŃ 2026
Członkowie Personelu
Jan Testowy (150zł x8h = 1200zł MD)
Faktyczny wymiar Roboczodni
0 MD – on-site
22 MD– off-site
Sugerowane wynagrodzenie
22 x 1200 PLN = 26 400 PLN
"""


def test_orlen_godziny_z_wynagrodzenia_md_z_godzin():
    parsed = protocol_orlen.parse_text(ORLEN_HOURS)

    assert parsed.consultant == PERSON
    assert parsed.month == MONTH
    assert parsed.hours == Decimal("132")
    assert parsed.amount == Decimal("19800")
    # 22 dni po 6 h to 132 h = 16,5 MD, nie 22 MD.
    assert _declared_result(parsed).md_regular == Decimal("16.500")


def test_orlen_wynagrodzenie_od_md_rozpoznane_po_stawce_md():
    parsed = protocol_orlen.parse_text(ORLEN_MD)

    assert parsed.hours is None
    assert parsed.md == Decimal("22")
    assert _declared_result(parsed).md_regular == Decimal("22.000")


def test_orlen_bez_wynagrodzenia_godziny_z_faktycznego_wymiaru():
    text = ORLEN_HOURS.split("Sugerowane")[0] + "1 MD – po 3h\n"
    parsed = protocol_orlen.parse_text(text)

    assert parsed.hours == Decimal("135")


def test_orlen_kilka_osob_z_roznymi_kwotami_bez_md():
    text = (
        ORLEN_HOURS + "Anna Inna (100zł x8h = 800zł MD)\n80 h x 100 PLN = 8 000 PLN\n"
    )
    parsed = protocol_orlen.parse_text(text)

    assert parsed.hours is None and parsed.md is None
    result = _declared_result(parsed)
    assert result.md_regular is None
    assert "Protokół Orlen bez godzin" in _titles(result)


def test_orlen_protokol_docx():
    document = docx.Document()
    document.add_paragraph("PROTOKÓŁ")
    table = document.add_table(rows=3, cols=2)
    cells = [
        ("OKRES ROZLICZENIOWY: WRZESIEŃ 2026", "DOTYCZY ZAMÓWIENIA NR: 1"),
        ("Członkowie Personelu … stawki za Roboczodzień", "Jan Testowy"),
        ("Sugerowane wynagrodzenie", "132 h x 150 PLN = 19 800 PLN"),
    ]
    for row, (left, right) in zip(table.rows, cells):
        row.cells[0].text, row.cells[1].text = left, right
    buffer = io.BytesIO()
    document.save(buffer)

    parsed = protocol_orlen.parse(buffer.getvalue(), declared.DOCX)

    assert parsed.consultant == PERSON
    assert parsed.month == MONTH
    assert parsed.hours == Decimal("132")


def test_inny_dokument_to_nie_protokol_orlenu():
    assert (
        protocol_orlen.parse_text("Faktura VAT\n132 h x 150 PLN = 19 800 PLN") is None
    )


def test_orlen_za_inny_okres_to_kontrola_bez_md():
    result = _declared_result(protocol_orlen.parse_text(ORLEN_HOURS), month="2026-10")

    assert result.md_regular is None
    assert _titles(result)["Protokół Orlen za inny miesiąc"] == "fail"


# ── Dispatch w ``service._proof`` ─────────────────────────────────────────────


def _document(
    tmp_path, doc_id: int, name: str, mime: str, content: bytes
) -> CpDocument:
    folder = tmp_path / "consultant_portal" / "1"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_bytes(content)
    return CpDocument(
        id=doc_id,
        kind="report",
        mime=mime,
        file_path=f"consultant_portal/1/{name}",
    )


async def test_md_z_innego_pliku_miesiaca_gdy_wybrany_nieznany(tmp_path, monkeypatch):
    from app.services import storage_service

    monkeypatch.setattr(storage_service, "STORAGE_ROOT", tmp_path)
    unknown = _document(
        tmp_path, 2, "oferta.xlsx", timesheet.XLSX, _xlsx([["Oferta"], ["Cena", 100]])
    )
    mail = _document(tmp_path, 1, "akceptacja.eml", EML, _eml(NN_BODY))

    result = await service._proof(
        unknown, [unknown, mail], month=MONTH, person_name=PERSON, rules=_rules()
    )

    assert result.md_regular == Decimal("22.875")
    assert result.meta["document_id"] == 1


async def test_mail_nn_jako_jedyny_plik_miesiaca(tmp_path, monkeypatch):
    from app.services import storage_service

    monkeypatch.setattr(storage_service, "STORAGE_ROOT", tmp_path)
    mail = _document(tmp_path, 1, "akceptacja.eml", EML, _eml(NN_BODY))

    result = await service._proof(
        mail, [mail], month=MONTH, person_name=PERSON, rules=_rules()
    )

    assert result.md_regular == Decimal("22.875")


async def test_zaden_plik_nieznany_zostaje_bez_md(tmp_path, monkeypatch):
    from app.services import storage_service

    monkeypatch.setattr(storage_service, "STORAGE_ROOT", tmp_path)
    unknown = _document(
        tmp_path, 2, "oferta.xlsx", timesheet.XLSX, _xlsx([["Oferta"], ["Cena", 100]])
    )
    other = _document(tmp_path, 1, "pytanie.eml", EML, _eml("Proszę o fakturę."))

    result = await service._proof(
        unknown, [unknown, other], month=MONTH, person_name=PERSON, rules=_rules()
    )

    assert result.md_regular is None
    assert "Nie rozpoznano szablonu RCP" in _titles(result)


# ── Przypadki z przeglądu kodu ────────────────────────────────────────────────


def test_ergo_total_godzin_i_pd_bez_przecinka_nie_skleja_sie():
    text = "Monthly confirmation of hours worked\nMonth (mm/yyyy)\n09/2026 Jan Testowy\nTotal 176 22\n"

    assert confirmation_ergo.parse_text(text).hours == Decimal("176")


def test_bik_pdf_godziny_z_kropka_nie_sa_data():
    text = BIK_SHORT.replace("BIK 2.09.2026 8", "BIK 2.09.2026 7.5").replace(
        "Suma 24 h\n", ""
    )
    parsed = timesheet_bik.parse_rows(
        timesheet_bik.text_rows(text), source="pdf", title=True
    )

    assert [e.hours for e in parsed.entries] == [
        Decimal("9"),
        Decimal("7.5"),
        Decimal("7"),
    ]


def test_dlugie_ciagi_cyfr_i_spacji_nie_zawieszaja_czytnikow():
    import time

    junk = "1 " * 15000 + "\n" + "1" + " " * 30000 + "\n"
    started = time.monotonic()
    protocol_orlen.parse_text("OKRES ROZLICZENIOWY: WRZESIEŃ 2026\nroboczod\n" + junk)
    mail_nn.parse_text("zaakceptowanego odbioru pracy\n" + junk + " PLN\n")
    timesheet_bik.text_rows("Zadanie Data Czas (godz.)\n" + junk)
    timesheet.text_rows("Time Sheet\nDate Total Hours Billable\n" + junk)

    assert time.monotonic() - started < 1


def test_nn_przekazany_mail_bez_podsumowania_nie_podwaja_md():
    table = NN_BODY.split("\n\n\nKwota netto do zafakturowania")[0]
    forwarded = (
        f"{table}\n\nFrom: Rozliczenia <rozliczenia@klient.example>\n"
        f"Subject: Rozliczenie pracownika\n{table}"
    )
    quoted = table + "\n" + "\n".join(f"> {line}" for line in table.splitlines())

    assert mail_nn.parse_text(forwarded).md == Decimal("22.875")
    assert mail_nn.parse_text(quoted).md == Decimal("22.875")
