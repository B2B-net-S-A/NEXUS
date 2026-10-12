"""Klauzula zgody RODO na końcu CV firmowego — jedno rozpoznanie dla QC i DOCX.

Generator pisze ją jako ``<p class="rodo">`` bez znacznika sekcji, edytor
dokłada ``data-cv-section="rodo"`` dopiero po zapisie, a starsze zatwierdzone
CV zgubiły oba znaczniki — zostają pierwsze słowa klauzuli z szablonu.

Klauzula jest stała (decyzja Artura 12.10.2026, D3): edytor blokuje ją
w przeglądarce, a ``keep_rodo_clause`` pilnuje tego samego przy zapisie
i zatwierdzeniu — także dla starej karty i wywołania API.
"""

from __future__ import annotations

import html as html_lib
from functools import lru_cache
from typing import Optional

from lxml import html as lxml_html

OPENING_WORDS = 5
# Klauzula zaczyna się od stałych słów; dalsza część akapitu nie jest potrzebna.
_PROBE_CHARS = 200


def _norm(text: str) -> str:
    return " ".join((text or "").split()).casefold()


@lru_cache(maxsize=1)
def rodo_openings() -> tuple[str, ...]:
    # Leniwie: `docx_renderer` ciągnie python-docx, a szablon jest stały.
    from app.services.cv_generator_b2b.docx_renderer import TRANSLATIONS

    return tuple(
        _norm(" ".join(t["rodo"].split()[:OPENING_WORDS]))
        for t in TRANSLATIONS.values()
    )


def is_rodo_text(text: str) -> bool:
    """Czy akapit zaczyna się jak klauzula zgody z szablonu (PL albo EN)."""
    return _norm((text or "")[:_PROBE_CHARS]).startswith(rodo_openings())


def is_rodo_node(node) -> bool:
    """Akapit klauzuli: znacznik edytora, klasa generatora albo słowa szablonu."""
    return (
        node.get("data-cv-section") == "rodo"
        or "rodo" in node.get("class", "").split()
        or is_rodo_text("".join(node.itertext()))
    )


def _clause_like(root) -> list:
    # Te same bloki, które generator Worda bierze za akapit: `p` albo `div` bez
    # bloków w środku. Punkt listy cytujący klauzulę to treść CV, nie klauzula.
    from app.services.cv_approved_docx import BLOCKS

    return [
        node
        for node in root.iter("p", "div")
        if node is not root
        and not any(child.tag in BLOCKS for child in node)
        and is_rodo_node(node)
        and not any(parent.tag in ("ul", "ol") for parent in node.iterancestors())
    ]


def _same_text(node, other) -> bool:
    return _norm("".join(node.itertext())) == _norm("".join(other.itertext()))


def _unmark(node) -> None:
    node.attrib.pop("data-cv-section", None)
    classes = [name for name in node.get("class", "").split() if name != "rodo"]
    if classes:
        node.set("class", " ".join(classes))
    else:
        node.attrib.pop("class", None)


def keep_rodo_clause(previous_html: Optional[str], incoming_html: str) -> str:
    """Treść z edytora z klauzulą zgody taką jak w zapisanym CV.

    Nietknięta klauzula = ``incoming_html`` wraca bez zmian, bajt w bajt.
    Usunięta albo zmieniona wraca z ``previous_html`` na koniec dokumentu;
    inny tekst, na który przeszedł jej znacznik, zostaje w treści bez znacznika
    (Word przypina na dole pierwszy oznaczony akapit). CV zapisane bez
    klauzuli przyjmuje każdą treść, a pusta treść wraca pusta — odmowę
    „CV nie może być puste” daje wołający.
    """
    if not (previous_html or "").strip() or not (incoming_html or "").strip():
        return incoming_html
    saved = _clause_like(
        lxml_html.fragment_fromstring(previous_html, create_parent="div")
    )
    if not saved:
        return incoming_html
    kept = saved[0]
    root = lxml_html.fragment_fromstring(incoming_html, create_parent="div")
    nodes = _clause_like(root)
    if nodes and _same_text(nodes[0], kept):
        return incoming_html
    found = False
    for node in nodes:
        if not found and _same_text(node, kept):
            found = True
        elif is_rodo_text("".join(node.itertext())):
            node.drop_tree()
        else:
            _unmark(node)
    if not found:
        kept.tail = None
        root.append(kept)
    # `root.text` to już zdekodowany tekst — bez ponownego zakodowania encje
    # sprzed pierwszego bloku wróciłyby jako znaczniki.
    rebuilt = html_lib.escape(root.text or "", quote=False) + "".join(
        lxml_html.tostring(child, encoding="unicode") for child in root
    )
    # Treść przeszła przez drugi parser — sanitizer ma ostatnie słowo.
    from app.services.html_sanitizer import sanitize_cv_html

    return sanitize_cv_html(rebuilt)
