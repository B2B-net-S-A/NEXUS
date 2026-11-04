"""Ramka z linkiem do panelu klienta w pobieranym pliku Word CV (02.11.2026).

CV dalej idzie do klienta jako plik. Pod tytułem dostaje ramkę: QR, klikalny
link, krótki adres zwykłym tekstem (do przepisania z wydruku) i datę ważności.
Działa na bajtach przy pobraniu, zapisany dokument zostaje bez zmian. Awaria
to plik bez ramki i wpis w logu, bo klient ma dostać CV niezależnie od panelu.
"""

from __future__ import annotations

import io
import logging
from datetime import datetime
from typing import Any, Optional

import segno
from docx import Document
from docx.opc.constants import RELATIONSHIP_TYPE
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

from app.core.scheduling import business_date

logger = logging.getLogger(__name__)

_QR_WIDTH = Cm(2.4)
_QR_COLUMN = Cm(3)
_TEXT_COLUMN = Cm(13.5)
_FONT = "Montserrat"
_TEXT = {
    "pl": {
        "lead": "Panel tej rekrutacji: dopasowanie, pytania, prośba o rozmowę",
        "valid": "Link ważny do {date}",
    },
    "en": {
        "lead": "Recruitment panel: requirements match, questions, interview request",
        "valid": "Link valid until {date}",
    },
}
_GREY = RGBColor(0x59, 0x59, 0x59)
_LINK = RGBColor(0x05, 0x63, 0xC1)


def _qr_png(url: str) -> io.BytesIO:
    buffer = io.BytesIO()
    segno.make(url, error="m").save(buffer, kind="png", scale=6, border=2)
    buffer.seek(0)
    return buffer


def _borders(table: Any) -> None:
    properties = table._tbl.tblPr
    borders = OxmlElement("w:tblBorders")
    for side in ("top", "left", "bottom", "right"):
        edge = OxmlElement(f"w:{side}")
        edge.set(qn("w:val"), "single")
        edge.set(qn("w:sz"), "6")
        edge.set(qn("w:space"), "0")
        edge.set(qn("w:color"), "BFBFBF")
        borders.append(edge)
    properties.append(borders)


def _hyperlink(paragraph: Any, url: str, label: str) -> None:
    rel_id = paragraph.part.relate_to(
        url, RELATIONSHIP_TYPE.HYPERLINK, is_external=True
    )
    link = OxmlElement("w:hyperlink")
    link.set(qn("r:id"), rel_id)
    run = paragraph.add_run(label)
    run.font.name = _FONT
    run.font.size = Pt(9)
    run.font.color.rgb = _LINK
    run.font.underline = True
    # Run powstał w akapicie; przenosimy go do elementu odnośnika.
    link.append(run._r)
    paragraph._p.append(link)


def _title_paragraph(document: Any) -> Optional[Any]:
    return next((p for p in document.paragraphs if p.text.strip()), None)


def _line(cell: Any, text: str, *, bold: bool = False, first: bool = False) -> Any:
    paragraph = cell.paragraphs[0] if first else cell.add_paragraph()
    paragraph.paragraph_format.space_after = Pt(1)
    if text:
        run = paragraph.add_run(text)
        run.font.name = _FONT
        run.font.size = Pt(9)
        run.font.bold = bold
        if not bold:
            run.font.color.rgb = _GREY
    return paragraph


def _stamped(
    docx_bytes: bytes,
    url: str,
    short_url: str,
    expires_at: Optional[datetime],
    language: str,
) -> bytes:
    document = Document(io.BytesIO(docx_bytes))
    title = _title_paragraph(document)
    if title is None:
        raise ValueError("Plik Word nie ma akapitu z tekstem.")
    text = _TEXT.get(language, _TEXT["pl"])
    table = document.add_table(rows=1, cols=2)
    _borders(table)
    # Szerokości siatki i komórek: LibreOffice czyta pierwsze, Word drugie.
    table.autofit = False
    table.columns[0].width = _QR_COLUMN
    table.columns[1].width = _TEXT_COLUMN
    qr_cell, text_cell = table.cell(0, 0), table.cell(0, 1)
    qr_cell.width = _QR_COLUMN
    text_cell.width = _TEXT_COLUMN
    qr_cell.paragraphs[0].add_run().add_picture(_qr_png(url), width=_QR_WIDTH)
    _line(text_cell, text["lead"], bold=True, first=True)
    _hyperlink(_line(text_cell, ""), url, url)
    _line(text_cell, short_url)
    if expires_at is not None:
        day = business_date(expires_at).strftime("%d.%m.%Y")
        _line(text_cell, text["valid"].format(date=day))
    title._p.addnext(table._tbl)
    # Tabela tuż przed następnym akapitem nie może się z nim skleić w Wordzie.
    spacer = OxmlElement("w:p")
    table._tbl.addnext(spacer)
    out = io.BytesIO()
    document.save(out)
    return out.getvalue()


def stamp_panel_link(
    docx_bytes: bytes,
    url: str,
    short_url: str,
    expires_at: Optional[datetime],
    *,
    language: str = "pl",
) -> bytes:
    """Plik z ramką panelu; przy jakiejkolwiek awarii oryginalne bajty."""
    try:
        return _stamped(docx_bytes, url, short_url, expires_at, language)
    except Exception:  # noqa: BLE001 — python-docx rzuca różnymi typami, plik ma wyjść
        logger.exception("client panel: stamping the DOCX failed")
        return docx_bytes
