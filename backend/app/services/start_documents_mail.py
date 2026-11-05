"""Mail „Lista dokumentów” do konsultanta: jeden mail zamiast kilku próśb.

Idzie ze skrzynki osoby, która go wysyła (M365), bez podpisu w treści, bo
Outlook dokleja stopkę nadawcy. Tekst dla konsultanta bez myślników (wzór
maili podpisu umów, ``services/b2b_esign/mail.py``). PESEL nigdy mailem.
"""

from __future__ import annotations

import html
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Optional

from app.models.start_document import ClientStartDocument
from app.services.b2b_esign.mail import _p
from app.services.m365.sender import FileAttachment
from app.services.start_documents import (
    KIND_AGREEMENT,
    KIND_PESEL,
    ItemState,
    PairState,
)

SUBJECT = "Dokumenty przed startem u klienta {client}"


@dataclass(frozen=True)
class ListLine:
    text: str
    link: Optional[str] = None


def _until(item: ItemState) -> str:
    return f" (do {item.deadline:%d.%m})" if item.deadline else ""


def lines_for(items: Iterable[ItemState]) -> list[ListLine]:
    """Pozycje do zrobienia przez konsultanta (bez umowy, bez tego, co już jest)."""

    lines: list[ListLine] = []
    for item in items:
        document = item.document
        if document.kind == KIND_AGREEMENT or item.done:
            continue
        if document.kind == KIND_PESEL:
            lines.append(
                ListLine(
                    f"PESEL: proszę podać telefonicznie, nie mailem{_until(item)}."
                )
            )
            continue
        suffix = "" if document.required else " (opcjonalnie)"
        note = f": {document.note}" if document.note else ""
        lines.append(
            ListLine(f"{document.name}{suffix}{_until(item)}{note}", document.link_url)
        )
    return lines


def render(pair: PairState, attachments: Sequence[str]) -> tuple[str, str, str]:
    """(temat, treść HTML, treść jako tekst do skopiowania)."""

    client = pair.client_name or "z tej rekrutacji"
    subject = SUBJECT.format(client=client)
    lines = lines_for(pair.items)
    start = f" {pair.start_date:%d.%m}" if pair.start_date else ""
    intro = f"przed startem u klienta {client}{start} potrzebujemy kilku dokumentów:"
    items_html = "".join(
        '<li style="margin-bottom: 6px">'
        + html.escape(line.text)
        + (
            f' <a href="{html.escape(line.link, quote=True)}">'
            f"{html.escape(line.link)}</a>"
            if line.link
            else ""
        )
        + "</li>"
        for line in lines
    )
    parts = [_p("Dzień dobry,"), _p(html.escape(intro)), f"<ol>{items_html}</ol>"]
    if attachments:
        parts.append(_p("Wzory są w załączniku."))
    text_lines = [
        "Dzień dobry,",
        "",
        intro,
        *[
            f"{index}. {line.text}" + (f" {line.link}" if line.link else "")
            for index, line in enumerate(lines, start=1)
        ],
    ]
    if attachments:
        text_lines += ["", "Wzory są w załączniku."]
    return subject, "".join(parts), "\n".join(text_lines)


def attachment_name(document: ClientStartDocument, pair: PairState) -> str:
    """Nazwa pliku u konsultanta: wzór wypełniony nosi jego nazwisko."""

    name = document.template_name or f"{document.name}.docx"
    if not document.fill_from_agreement:
        return name
    stem, _, extension = name.rpartition(".")
    return f"{stem or name} {pair.candidate_name}.{extension or 'docx'}"


__all__ = ["FileAttachment", "ListLine", "attachment_name", "lines_for", "render"]
