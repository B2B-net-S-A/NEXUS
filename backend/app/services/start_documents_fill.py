"""Wzór klienta z danymi z umowy (NDA Nordei, Appendix 3).

Wzór ma tabelę z etykietami („Consultant's name”, „Street, box”, ...). Wartość
trafia do pustego akapitu pod etykietą albo w nowy akapit. Komórka bez znanej
etykiety zostaje bez zmian, więc obcy wzór wychodzi taki, jaki był. PESEL-u tu
nie ma: konsultant wpisuje go sam albo zostawia NIP.
"""

from __future__ import annotations

import io
import logging
import re
from collections.abc import Mapping
from typing import Any, Optional

from docx import Document
from docx.table import _Cell

from app.core.docx_cells import row_cells
from app.core.docx_metadata import clear_author_metadata

logger = logging.getLogger(__name__)

_POSTAL = re.compile(r"(\d{2}-\d{3})\s+(.+)$")


def split_address(address: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    """(ulica, kod i miasto) z adresu firmy w jednym polu."""

    text = " ".join((address or "").split())
    if not text:
        return None, None
    match = _POSTAL.search(text)
    if match is None:
        return text, None
    street = text[: match.start()].rstrip(" ,")
    return street or None, f"{match.group(1)} {match.group(2)}"


def values_from_payload(payload: Optional[Mapping[str, Any]]) -> dict[str, str]:
    """Pola wzoru z ``render_payload`` umowy. Brak wartości = brak klucza."""

    data = payload or {}
    street, city = split_address(data.get("partner_business_address"))
    nip = str(data.get("partner_nip") or "").strip()
    found = {
        "name": str(data.get("partner_name") or "").strip(),
        "number": f"NIP: {nip}" if nip else "",
        "street": street or "",
        "city": city or "",
        "phone": str(data.get("partner_phone") or "").strip(),
    }
    return {key: value for key, value in found.items() if value}


#: Początek etykiety w komórce (małe litery) → pole.
_LABELS: tuple[tuple[str, str], ...] = (
    ("consultant", "name"),
    ("imię i nazwisko", "name"),
    ("company number", "number"),
    ("nip", "number"),
    ("street", "street"),
    ("ulica", "street"),
    ("postal code", "city"),
    ("kod pocztowy", "city"),
    ("telephone", "phone"),
    ("telefon", "phone"),
)


def _fill_cell(cell: _Cell, values: Mapping[str, str]) -> bool:
    label = next(
        (p.text.strip().lower() for p in cell.paragraphs if p.text.strip()), ""
    )
    field = next((name for prefix, name in _LABELS if label.startswith(prefix)), None)
    value = values.get(field) if field else None
    if not value:
        return False
    # Wiersz „Supplier” ma już dane firmy: nie dopisujemy tam nic.
    if sum(1 for p in cell.paragraphs if p.text.strip()) > 1:
        return False
    empty = next((p for p in cell.paragraphs if not p.text.strip()), None)
    (empty or cell.add_paragraph()).add_run(value)
    return True


def fill_template(data: bytes, values: Mapping[str, str]) -> bytes:
    """DOCX z wstawionymi danymi. Nieczytelny plik wraca bez zmian."""

    try:
        document = Document(io.BytesIO(data))
    except Exception:  # noqa: BLE001 — wzór klienta, może nie być DOCX-em
        logger.warning("[start_documents] wzoru nie da się otworzyć jako DOCX")
        return data
    for table in document.tables:
        for row in table.rows:
            for cell in row_cells(row):
                _fill_cell(cell, values)
    clear_author_metadata(document)
    out = io.BytesIO()
    document.save(out)
    return out.getvalue()
