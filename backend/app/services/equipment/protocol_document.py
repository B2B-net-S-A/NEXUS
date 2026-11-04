"""Plik protokołu: DOCX ze wzoru (docxtpl) i PDF tym samym mechanizmem co CV.

Treść powstaje WYŁĄCZNIE z migawki zapisanej w protokole (nagłówek, pozycje,
wartości) — ponowne pobranie po zmianie cennika daje ten sam dokument.
Kwota słownie: ``pln_words_with_fraction`` z generatora umów (ten sam zapis
„… złote 73/100”, który recepcja wpisywała ręcznie).

PDF: generator dokumentów Akademii oddaje tylko DOCX, więc protokół idzie
przez ``cv_pdf_preview.pdf_from_docx`` (LibreOffice w kontenerze, kolejka,
limit czasu). Brak LibreOffice = ``ProtocolPdfUnavailable`` → trasa 503,
a DOCX dalej da się pobrać.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional, Sequence

import docx
from docx.table import Table
from docx.text.paragraph import Paragraph
from docxtpl import DocxTemplate
from jinja2 import Environment, StrictUndefined

from app.core.docx_cells import grid_rows
from app.services import cv_pdf_preview
from app.services.b2b_contract_generator.number_words import pln_words_with_fraction
from app.services.equipment import identifiers
from app.services.equipment.protocol_template import (
    ISSUE_TEMPLATE,
    RETURN_TEMPLATE,
    TEMPLATE_DIR,
)

DASH = "—"


class ProtocolPdfUnavailable(RuntimeError):
    """PDF nie powstał (brak LibreOffice, kolejka, limit czasu)."""


@dataclass(frozen=True)
class LineView:
    position: int
    name: str
    identifier: Optional[str]
    quantity: int
    unit_value: Optional[Decimal]
    condition: Optional[str] = None
    notes: Optional[str] = None


@dataclass(frozen=True)
class ProtocolView:
    kind: str
    number: str
    protocol_date: date
    holder_name: str
    issuer_name: str
    lines: tuple[LineView, ...]
    #: Dopiski pod podpisami po potwierdzeniu w NEXUSIE (puste przed).
    holder_signature: str = ""
    issuer_signature: str = ""


def _cents(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def amount(value: Optional[Decimal]) -> str:
    """Cena w wierszu jak we wzorze: „2589,00” (bez separatora tysięcy)."""
    if value is None:
        return DASH
    return f"{_cents(value):.2f}".replace(".", ",")


def total_amount(value: Decimal) -> str:
    """Suma jak we wzorze: „3 903,73”."""
    whole, _, fraction = f"{_cents(value):.2f}".partition(".")
    groups = []
    while len(whole) > 3:
        groups.insert(0, whole[-3:])
        whole = whole[:-3]
    groups.insert(0, whole)
    return " ".join(groups) + "," + fraction


def line_total(line: LineView) -> Decimal:
    if line.unit_value is None:
        return Decimal("0")
    return _cents(line.unit_value * line.quantity)


def protocol_total(lines: Sequence[LineView]) -> Decimal:
    return sum((line_total(line) for line in lines), Decimal("0"))


def pl_date(value: date) -> str:
    return f"{value.day:02d}.{value.month:02d}.{value.year}"


def context_for(view: ProtocolView) -> dict:
    total = protocol_total(view.lines)
    lines = [
        {
            "position": line.position,
            "name": line.name,
            "identifier": line.identifier or DASH,
            "quantity": line.quantity,
            "price": amount(line.unit_value),
            "value": DASH if line.unit_value is None else amount(line_total(line)),
            "condition": identifiers.CONDITION_LABELS.get(
                line.condition or "", line.condition or DASH
            ),
            "notes": line.notes or "",
        }
        for line in view.lines
    ]
    return {
        "number": view.number,
        "protocol_date": pl_date(view.protocol_date),
        "holder_name": view.holder_name,
        "issuer_name": view.issuer_name,
        "lines": lines,
        "total": total_amount(total),
        "total_words": pln_words_with_fraction(float(total)),
        "holder_signature": view.holder_signature,
        "issuer_signature": view.issuer_signature,
    }


def _env() -> Environment:
    # StrictUndefined: literówka w szablonie ma paść w teście, a nie wyjść
    # do podpisu jako puste miejsce w protokole.
    return Environment(autoescape=True, undefined=StrictUndefined)


def render_docx(view: ProtocolView) -> bytes:
    name = ISSUE_TEMPLATE if view.kind == "wydanie" else RETURN_TEMPLATE
    template = DocxTemplate(str(TEMPLATE_DIR / name))
    template.render(context_for(view), jinja_env=_env())
    buffer = io.BytesIO()
    template.save(buffer)
    return buffer.getvalue()


async def render_pdf(view: ProtocolView) -> bytes:
    try:
        return await cv_pdf_preview.pdf_from_docx(render_docx(view))
    except cv_pdf_preview.PdfPreviewUnavailable as exc:
        raise ProtocolPdfUnavailable(str(exc)) from exc


def document_blocks(document_bytes: bytes) -> list[dict]:
    """Treść pliku w kolejności: akapity i wiersze tabeli (strona podpisu, testy)."""
    document = docx.Document(io.BytesIO(document_bytes))
    body = document.element.body
    blocks: list[dict] = []
    for child in body.iterchildren():
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "p":
            paragraph = Paragraph(child, document)
            blocks.append({"type": "paragraph", "text": paragraph.text})
        elif tag == "tbl":
            table = Table(child, document)
            blocks.append(
                {
                    "type": "table",
                    "rows": [
                        [cell.text for cell in cells] for cells in grid_rows(table)
                    ],
                }
            )
    return blocks
