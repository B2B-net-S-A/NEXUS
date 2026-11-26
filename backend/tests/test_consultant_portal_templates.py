"""Wzór dokumentu, który sam wskazuje klienta (``consultant_portal/templates``).

Bez bazy. Układy jak w prawdziwych plikach z poczty rozliczeń, dane fikcyjne.
"""

from __future__ import annotations

import io
from datetime import datetime
from decimal import Decimal

import openpyxl
import pytest

from app.services.client_settlements import kcp, kesu
from app.services.consultant_portal import templates
from tests.test_client_settlements_kcp import _card_rows, _workbook
from tests.test_client_settlements_kesu import NO_COSTS
from tests.test_consultant_portal_kind_from_content import pdf_with_text

# Karta Banku Pocztowego bez polskich znaków: czytnik porównuje tekst po ich
# usunięciu.
BANK_CARD_LINES = [
    "KARTA EWIDENCJI SWIADCZENIA USLUG",
    "Imie i Nazwisko: Testowy Jan",
    "Miesiac: Lipiec",
    "Rok: 2026",
    "1 Zadanie 1: analiza 8",
    "Suma dni przepracowanych 1,0",
    "Liczba godzin czas podstawowy 8",
]
# Karty innego klienta pod tym samym tytułem: miesiąc liczbą i bez wiersza godzin
# czasu podstawowego, choć wydruk z NEXUS-a ma „Suma dni przepracowanych”.
OTHER_CARD_HEAD = [
    "KARTA EWIDENCJI SWIADCZENIA USLUG",
    "Imie i nazwisko: Testowy Jan",
    "Stanowisko: Analityk",
    "Miesiac: 5 Rok: 2026",
    "1 Analiza wymagan 8",
]
OTHER_CARD_SUMS = ["Suma godzin przepracowanych 8", "Suma dni przepracowanych 1,00"]


def test_karta_banku_pocztowego_w_pdf() -> None:
    found = templates.recognize(pdf_with_text(BANK_CARD_LINES), "timelogLip.pdf")

    assert found == templates.Template("bank_pocztowy", "Testowy Jan", (2026, 7))


def test_karta_banku_pocztowego_w_arkuszu() -> None:
    content = _workbook({"KARTA": _card_rows()})

    found = templates.recognize(content, "Karta pracy.xlsm")

    assert found == templates.Template("bank_pocztowy", "Testowy Jan", (2026, 10))


@pytest.mark.parametrize("lines", [OTHER_CARD_HEAD, OTHER_CARD_HEAD + OTHER_CARD_SUMS])
def test_karta_innego_klienta_z_tym_samym_tytulem_to_nie_wzor_banku(lines) -> None:
    content = pdf_with_text(lines)
    assert kcp.parse(content, kcp.PDF) is not None

    assert templates.recognize(content, "karta.pdf") is None


def test_wydruk_karty_alior_z_nexusa_to_nie_wzor_banku() -> None:
    """Paczka KEŚU wraca podpisana mailem: nie może zmienić kontraktu na bank."""

    try:
        import weasyprint  # noqa: F401
    except (ImportError, OSError):
        pytest.skip("WeasyPrint bez bibliotek systemowych (pango)")
    html = kesu.render_html(
        kesu.parse(NO_COSTS),
        rate_md=Decimal("1145.68"),
        md_hours=Decimal("8"),
        month="2026-10",
    )
    content = kesu.render_pdf(html)
    card = kcp.parse(content, kcp.PDF)
    assert card is not None and card.declared_days is not None

    assert templates.recognize(content, "KESU 10.2026.pdf") is None


@pytest.mark.parametrize(
    "project, header",
    [
        # Sama nazwa banku w projekcie.
        ("VeloBank", ["Date", "Project", "Description", "Total Hours"]),
        ("Prace w projekcie Velo Bank", ["Date", "Project", "Total Hours"]),
        # Projekt bez nazwy banku, ale z kolumną strumienia.
        ("Prace programistyczne", ["Date", "Strumień", "Project", "Total Hours"]),
        ("Prace programistyczne", ["Date", "Total Hours", "Nr strumienia"]),
    ],
)
def test_time_sheet_velobanku(project: str, header: list[str]) -> None:
    content = _time_sheet(project, header)

    found = templates.recognize(content, "Testowy Jan_TS - lipiec 2026.xlsx")

    assert found == templates.Template("velobank", "Jan Testowy", (2026, 7))


@pytest.mark.parametrize("project", ["ALFA", "Development", "Evelop Labs"])
def test_time_sheet_innego_klienta_nie_wskazuje_nikogo(project: str) -> None:
    content = _time_sheet(project, ["Date", "Project", "Description", "Total Hours"])

    assert templates.recognize(content, "TS 07.2026.xlsx") is None


@pytest.mark.parametrize(
    "content, name",
    [
        (pdf_with_text(["Faktura VAT nr 1/07/2026", "Razem 1 230,00"]), "fv.pdf"),
        (b"%PDF-1.4 uszkodzony", "x.pdf"),
        (b"PK\x03\x04 nie arkusz", "x.xlsx"),
        (b"<xml/>", "faktura.xml"),
    ],
)
def test_inne_pliki_nie_maja_wzoru(content: bytes, name: str) -> None:
    assert templates.recognize(content, name) is None


def _time_sheet(project: str, header: list[str]) -> bytes:
    """Arkusz „GridTable” (ogólny eksport, ma go kilku klientów)."""

    book = openpyxl.Workbook()
    grid = book.active
    grid.title = "GridTable"
    values = {
        "Date": datetime(2026, 7, 1),
        "Project": project,
        "Description": "Prace",
        "Strumień": 10144,
        "Nr strumienia": 31951,
        "Total Hours": 8,
    }
    for row in (
        [None, "Time Sheet"],
        [None, "Project Name", None, project],
        [None, "Consultant(s)", None, "Jan Testowy"],
        [None, "Date from", None, datetime(2026, 7, 1)],
        [None, "Date to", None, datetime(2026, 7, 31)],
        [None, *header],
        [None, *(values[label] for label in header)],
        [None, "Total Hours", None, None, 8],
    ):
        grid.append(row)
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()
