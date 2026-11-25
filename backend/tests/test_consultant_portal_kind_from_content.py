"""Rodzaj pliku z poczty rozliczeń: „faktura” sprawdzona treścią (próba IX–X 2026).

RCP BNP przysłane z tematem „faktura …”, jako „2026-09.pdf” albo w mailu
„FV i podpisane rozliczenie godzinowe” trafiało do faktur, więc rozliczenie nie
powstawało (9 przypadków). PDF rozpoznany jako RCP to raport; prawdziwa faktura
zostaje fakturą.
"""

from __future__ import annotations

import io

import docx
import openpyxl

from app.services.client_settlements import rcp_bnp, timesheet
from app.services.consultant_portal.mailbox import kind_of_file


def test_pdf_named_as_invoice_but_rcp_inside_is_a_report(monkeypatch) -> None:
    seen = []

    def fake_parse(content: bytes, mime: str):
        seen.append(mime)
        return object()

    monkeypatch.setattr(rcp_bnp, "parse", fake_parse)
    assert kind_of_file("faktura 09/2026", "2026-09.pdf", b"%PDF-1.7 ...") == "report"
    assert seen == ["application/pdf"]


def test_real_invoice_pdf_stays_an_invoice(monkeypatch) -> None:
    monkeypatch.setattr(rcp_bnp, "parse", lambda content, mime: None)
    assert (
        kind_of_file("FV 1/10/2026", "FV_1_10_2026.pdf", b"%PDF-1.4 ...") == "invoice"
    )


def test_report_by_name_is_not_parsed(monkeypatch) -> None:
    def boom(content: bytes, mime: str):
        raise AssertionError("raport z nazwy nie wymaga odczytu treści")

    monkeypatch.setattr(rcp_bnp, "parse", boom)
    assert kind_of_file("TS wrzesień", "Timesheet_09.pdf", b"%PDF-1.7") == "report"


def test_non_pdf_invoice_is_not_parsed(monkeypatch) -> None:
    monkeypatch.setattr(rcp_bnp, "parse", lambda content, mime: object())
    assert kind_of_file("faktura", "faktura.xml", b"<xml/>") == "invoice"


# ── Raporty godzin innych klientów (próba IX–X 2026, po czytnikach z #3774) ────
#
# Potwierdzenie godzin ERGO przysłane jako „<osoba> September 2026.xlsx - Monthly
# Conformation .pdf” nie ma w nazwie słowa-klucza, więc szło do faktur obok
# prawdziwej faktury kontraktora, a rozliczenie nie widziało raportu. Dane fikcyjne.

ERGO_LINES = [
    "Monthly confirmation of hours worked by an External Consultant",
    "Month (mm/yyyy) External Consultant name",
    "01-09-2026 Jan Testowy",
    "1 ALFA Websites (ID-0001) Time Tracking 168",
    "Total 168.00",
    "I confirm that the number of hours reported is correct",
]
INVOICE_LINES = [
    "Faktura VAT nr 17/2026",
    "Sprzedawca: Jan Testowy Uslugi IT",
    "Nabywca: Firma Testowa Sp. z o.o.",
    "Uslugi programistyczne 09/2026 21 x 1000,00",
    "Razem do zaplaty: 25 830,00 PLN",
]


def test_ergo_confirmation_pdf_without_keywords_is_a_report() -> None:
    pdf = pdf_with_text(ERGO_LINES)

    assert (
        kind_of_file(
            "Fwd: wrzesień",
            "Jan Testowy September 2026.xlsx -  Monthly Conformation .pdf",
            pdf,
        )
        == "report"
    )


def test_contractor_invoice_next_to_it_stays_an_invoice() -> None:
    assert (
        kind_of_file(
            "Fwd: wrzesień", "faktura-17-2026.pdf", pdf_with_text(INVOICE_LINES)
        )
        == "invoice"
    )


def test_time_sheet_xlsx_under_invoice_subject_is_a_report() -> None:
    rows = [
        ["Time Sheet"],
        ["Imię i nazwisko", "Jan Testowy"],
        ["Data", "Opis", "Liczba godzin"],
        *[[f"2026-09-{day:02d}", "ALFA", 8] for day in (1, 2, 3, 4, 7)],
        ["Suma", None, 40],
    ]
    content = _xlsx(rows)
    assert timesheet.parse(content, timesheet.XLSX) is not None

    assert (
        kind_of_file("Faktura 09/2026", "czas_pracy_092026.xlsx", content) == "report"
    )


def test_orlen_protocol_docx_without_keywords_is_a_report() -> None:
    document = docx.Document()
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

    assert (
        kind_of_file("Fwd: wrzesień", "Jan Testowy 09.docx", buffer.getvalue())
        == "report"
    )


# Arkusz zbiorczy klienta z drugiego strumienia (próba IX–X 2026): plik „B2B_09_2026.pdf”
# pod tematem „[BL] Rozliczenie 09.2026 …” nie ma w nazwie słowa-klucza, więc szedł
# do faktur i nikt nie czytał podpisu klienta. Wzór klienta: „Nazwisko Imię … MD.”.

CLIENT_SHEET_LINES = [
    "Dostawca B2B",
    "Nazwisko Imie Stanowisko Okres od: Okres do: MD.",
    "TESTOWY JAN INZYNIER TESTOW 2026-09-01 2026-09-30 20,00",
    "Suma koncowa 2026-09-01 2026-09-30 20,00",
]


def test_client_sheet_pdf_without_keywords_is_a_report() -> None:
    pdf = pdf_with_text(CLIENT_SHEET_LINES)

    assert (
        kind_of_file("FW: [BL] Rozliczenie 09.2026 [ABC] [B2B]", "B2B_09_2026.pdf", pdf)
        == "report"
    )


def test_sheet_header_without_rows_stays_an_invoice() -> None:
    """Sam nagłówek wzoru bez wiersza osoby z MD to nie arkusz."""

    pdf = pdf_with_text(CLIENT_SHEET_LINES[:2])

    assert kind_of_file("FW: rozliczenie", "B2B_09_2026.pdf", pdf) == "invoice"


def _xlsx(rows: list[list]) -> bytes:
    book = openpyxl.Workbook()
    sheet = book.active
    for row in rows:
        sheet.append(row)
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()


def pdf_with_text(lines: list[str]) -> bytes:
    """Najprostszy PDF z warstwą tekstu (Helvetica)."""

    def esc(text: str) -> str:
        return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")

    stream = (
        "BT /F1 10 Tf 40 800 Td 14 TL "
        + " ".join(f"({esc(line)}) Tj T*" for line in lines)
        + " ET"
    )
    objects = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
        "/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream",
    ]
    out = b"%PDF-1.4\n"
    offsets = []
    for index, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{index} 0 obj\n{body}\nendobj\n".encode("latin-1")
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref}\n%%EOF\n"
    ).encode()
    return out


def test_karta_kcp_pod_tematem_faktura_to_raport() -> None:
    """Próba VI–VIII 2026: „timelogLip.pdf” (karta KCP) w mailu „Faktura” szedł do faktur."""

    from tests.test_client_settlements_kcp import _card_rows, _workbook

    content = _workbook({"KARTA": _card_rows()})
    assert kind_of_file("Faktura", "timelogLip.xlsx", content) == "report"
