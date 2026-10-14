"""Klauzula zgody RODO na końcu CV firmowego — jedno rozpoznanie dla QC i DOCX.

Generator pisze ją jako ``<p class="rodo">`` bez znacznika sekcji, edytor
dokłada ``data-cv-section="rodo"`` dopiero po zapisie, a starsze zatwierdzone
CV zgubiły oba znaczniki — zostają pierwsze słowa klauzuli z szablonu.

Klauzula jest stała (decyzja Artura 12.10.2026, D3): edytor blokuje ją
w przeglądarce, a ``keep_rodo_clause`` pilnuje tego samego przy zapisie
i zatwierdzeniu — także dla starej karty i wywołania API.
"""

from __future__ import annotations

import copy
import html as html_lib
import logging
from functools import lru_cache
from typing import Optional

from fastapi import HTTPException
from lxml import html as lxml_html

logger = logging.getLogger(__name__)

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


def _leading_text(node) -> str:
    """Początek tekstu węzła — tyle, ile czyta `is_rodo_text`.

    Bez sklejania całego poddrzewa: opakowanie z tysiącami akapitów sprawdzane
    przy każdym z nich dawało koszt kwadratowy (audyt 13.10.2026).
    """
    parts: list[str] = []
    size = 0
    for piece in node.itertext():
        parts.append(piece)
        size += len(piece)
        if size >= _PROBE_CHARS:
            break
    return "".join(parts)


def is_rodo_node(node, seen: Optional[dict] = None) -> bool:
    """Akapit klauzuli: znacznik edytora, klasa generatora albo słowa szablonu.

    ``seen`` — wyniki z tego samego przebiegu: przodek wspólny dla tysięcy
    akapitów jest wtedy sprawdzany raz, nie przy każdym z nich.
    """
    if seen is not None and node in seen:
        return seen[node]
    result = (
        node.get("data-cv-section") == "rodo"
        or "rodo" in node.get("class", "").split()
        or is_rodo_text(_leading_text(node))
    )
    if seen is not None:
        seen[node] = result
    return result


def _wrap_loose_clause_text(root) -> None:
    """Luźny tekst między blokami, który wygląda jak klauzula → własny akapit.

    Generator Worda robi z takiego tekstu akapit i przypina go jak każdą
    klauzulę; bez tego cudza klauzula wpisana przed prawdziwą jako goły tekst
    przechodziła niezauważona.
    """
    from app.services.cv_approved_docx import BLOCKS, _WRAPPERS

    def paragraph(text: str):
        node = lxml_html.Element("p")
        node.text = text
        return node

    def walk(container) -> None:
        if is_rodo_text(container.text or ""):
            container.insert(0, paragraph(container.text))
            container.text = None
        for child in list(container):
            if is_rodo_text(child.tail or ""):
                child.addnext(paragraph(child.tail))
                child.tail = None
            if (
                child.tag in _WRAPPERS
                and any(inner.tag in BLOCKS for inner in child)
                and not child.get("data-cv-section")
                and not (child.text or "").strip()
                and not is_rodo_node(child)
            ):
                walk(child)

    walk(root)


def _clause_like(root, seen: Optional[dict] = None) -> list:
    # Bloki, które generator Worda bierze za akapit: `p` albo `div` bez bloków
    # w środku — gdziekolwiek stoją. Punkt listy cytujący klauzulę to treść CV.
    from app.services.cv_approved_docx import BLOCKS

    return [
        node
        for node in root.iter("p", "div")
        if node is not root
        and not any(child.tag in BLOCKS for child in node)
        and is_rodo_node(node, seen)
        and not any(parent.tag in ("ul", "ol") for parent in node.iterancestors())
    ]


def _pinned_by_word(node, root, seen: Optional[dict] = None) -> bool:
    """Czy generator Worda przypnie ten akapit na dole strony jako klauzulę.

    Lustro `cv_approved_docx.flatten` i `paragraph_block`: akapit musi stać na
    poziomie dokumentu (albo w opakowaniu, które generator rozwija) i nie może
    zawierać obrazka. Klauzula schowana w cytacie albo komórce tabeli nie jest
    przypinana — przypięty zostałby następny akapit, który ją udaje.
    """
    from app.services.cv_approved_docx import _WRAPPERS

    if node.find(".//img") is not None:
        return False
    for parent in node.iterancestors():
        if parent is root:
            return True
        if (
            parent.tag not in _WRAPPERS
            or parent.get("data-cv-section")
            or (parent.text or "").strip()
            or is_rodo_node(parent, seen)
        ):
            return False
    return False


def _parse(content_html: str):
    root = lxml_html.fragment_fromstring(content_html, create_parent="div")
    _wrap_loose_clause_text(root)
    return root


def _same_text(node, other) -> bool:
    return _norm("".join(node.itertext())) == _norm("".join(other.itertext()))


def _unmark(node) -> None:
    node.attrib.pop("data-cv-section", None)
    classes = [name for name in node.get("class", "").split() if name != "rodo"]
    if classes:
        node.set("class", " ".join(classes))
    else:
        node.attrib.pop("class", None)


# Zdjęcie znacznika z opakowania potrafi odsłonić w nim następny akapit, który
# udaje klauzulę, a sanitizer i lxml budują z wrogiego HTML-a różne drzewa —
# stąd naprawa w kilku przebiegach, każdy na świeżo sparsowanej treści.
_MAX_ROUNDS = 4


def _restore(kept, incoming_html: str) -> str:
    """Jeden przebieg naprawy; nietknięta treść wraca TYM SAMYM obiektem."""
    try:
        root = _parse(incoming_html)
    except Exception as error:  # noqa: BLE001
        raise HTTPException(
            422,
            "Nie udało się odczytać treści CV. Usuń nietypowe znaki i zapisz ponownie.",
        ) from error
    # Wyniki `is_rodo_node` w obrębie tego drzewa — wspólne opakowanie
    # sprawdzane raz (koszt liniowy, audyt 13.10.2026).
    seen: dict = {}
    nodes = _clause_like(root, seen)
    keeper = next(
        (
            node
            for node in nodes
            if _pinned_by_word(node, root, seen) and _same_text(node, kept)
        ),
        None,
    )
    if keeper is not None and len(nodes) == 1:
        return incoming_html
    for _ in range(len(nodes) + 1):
        others = [node for node in _clause_like(root) if node is not keeper]
        if not others:
            break
        for node in others:
            if is_rodo_text("".join(node.itertext())):
                node.drop_tree()
            else:
                _unmark(node)
    # `root.text` to już zdekodowany tekst — bez ponownego zakodowania encje
    # sprzed pierwszego bloku wróciłyby jako znaczniki. Treść przeszła przez
    # drugi parser, więc sanitizer ma ostatnie słowo.
    from app.services.html_sanitizer import sanitize_cv_html

    rebuilt = sanitize_cv_html(
        html_lib.escape(root.text or "", quote=False)
        + "".join(lxml_html.tostring(child, encoding="unicode") for child in root)
    )
    if keeper is not None:
        return rebuilt
    # Klauzula jako osobny, domknięty fragment na końcu: doklejona w drzewie
    # potrafiła po sanitizerze wylądować w niedomkniętym `<li>`.
    clause = copy.deepcopy(kept)
    clause.tail = None
    return rebuilt + sanitize_cv_html(lxml_html.tostring(clause, encoding="unicode"))


def keep_rodo_clause(previous_html: Optional[str], incoming_html: str) -> str:
    """Treść z edytora z klauzulą zgody taką jak w zapisanym CV.

    Nietknięta klauzula = ``incoming_html`` wraca bez zmian, bajt w bajt:
    w treści jest dokładnie jeden akapit klauzuli, ten sam co zapisany, i to
    jego generator Worda przypnie na dole. W każdym innym układzie zapisana
    klauzula wraca na koniec dokumentu, zmienione i schowane kopie znikają,
    a inny tekst ze znacznikiem klauzuli zostaje w treści bez znacznika.
    CV zapisane bez klauzuli (albo z taką, której Word nie przypina) przyjmuje
    każdą treść, a pusta treść wraca pusta — odmowę „CV nie może być puste”
    daje wołający.
    """
    if not (previous_html or "").strip() or not (incoming_html or "").strip():
        return incoming_html
    try:
        saved_root = _parse(previous_html)
    except Exception:  # noqa: BLE001 — stara treść nie może zablokować zapisu CV
        logger.warning(
            "[cv_rodo] zapisane CV nie daje się odczytać — klauzula bez ochrony"
        )
        return incoming_html
    seen: dict = {}
    saved = [
        node
        for node in _clause_like(saved_root, seen)
        if _pinned_by_word(node, saved_root, seen)
    ]
    if not saved:
        return incoming_html
    content = incoming_html
    for _ in range(_MAX_ROUNDS):
        restored = _restore(saved[0], content)
        if restored is content:
            return content
        content = restored
    logger.warning(
        "[cv_rodo] treść CV nie ustabilizowała się po %s przebiegach", _MAX_ROUNDS
    )
    return content
