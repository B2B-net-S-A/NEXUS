"""Ile ludzie zmieniają w CV z generatora: linia bazowa i porównanie po sekcjach.

Baza to pierwszy szkic etapu. Od E3 (07.11.2026) jego treść jest zapisana przy
podpięciu (`generated_editor_html`, `services/cv_edit_summary.py`), bo odtwarzanie
z ``render_payload`` zawodzi po zmianie renderera (07.11: 129 z 395 CV). Dla CV
sprzed E3 baza jest odtwarzana tym samym rendererem, który ją zbudował
(`apply_generated_to_stage_cv`), i sprawdzana zapisanym skrótem
(`generated_editor_html_sha256`) co do bajtu (`first_draft_is_reproduced`).

Renderer pogrubia według taksonomii umiejętności, dlatego proces spoza web musi
najpierw wywołać ``refresh_alias_map()``. Inaczej skrót się nie zgadza, choć tekst
jest ten sam (03.11.2026 na kopii produkcji: 300 z 453 bez mapy, 453 z 453 z mapą).

Porównujemy tekst, nie HTML: edytor przepisuje znaczniki bez zmiany treści. Tekst
szablonu (tytuły sekcji, etykiety, klauzula zgody) nie wchodzi do liczb, bo CV
nietknięte ma mieć zero, a mianownik ma liczyć to, co napisał generator.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import hashlib
import re
from typing import Any, Iterator, Optional
import unicodedata

from lxml import html

from app.services.cv_approved_docx import (
    BLOCKS,
    _DUTIES_LABELS,
    _SECTION_TITLES,
    _TECH_LABELS,
    _norm_title,
    _tag,
)
from app.services.cv_generator_b2b.docx_renderer import TRANSLATIONS
from app.services.cv_generator_b2b.html_export import render_interactive_html
from app.services.cv_generator_b2b.public_view import build_public_payload
from app.services.cv_rodo_clause import is_rodo_node
from app.services.html_sanitizer import sanitize_cv_html

SECTIONS = ("summary", "skills", "experience", "education", "other")
TOTAL = "total"

_REPORT_SECTION = {
    "why_points": "summary",
    "skills": "skills",
    "experience": "experience",
    "education": "education",
    "certifications": "other",
    "languages": "other",
}
_BLOCK_TAGS = {*BLOCKS, "thead", "tbody", "tfoot", "tr", "td", "th"}
_LEADING_LABELS = tuple(
    label.casefold()
    for label in (
        *_TECH_LABELS,
        *(t["considered_for"] for t in TRANSLATIONS.values()),
    )
)
# „C++”, „C#”, „Node.js” i „CI/CD” to jedno słowo; przecinek i nawias nie są zmianą.
_WORD = re.compile(r"[^\W_]+(?:[-+#./'’][^\W_]+)*[+#]*")


def generator_first_draft_html(render_payload: dict[str, Any]) -> str:
    """Pierwszy szkic etapu odtworzony z zapisanego wyniku generatora."""
    public = build_public_payload(render_payload)
    return sanitize_cv_html(render_interactive_html(public, [], document_only=True))


def first_draft_is_reproduced(
    render_payload: dict[str, Any], metadata: Optional[dict]
) -> bool:
    """Czy baza jest bajt w bajt szkicem, którego skrót zapisano przy podpięciu."""
    recorded = (metadata or {}).get("generated_editor_html_sha256")
    current = hashlib.sha256(generator_first_draft_html(render_payload).encode())
    return isinstance(recorded, str) and recorded == current.hexdigest()


def words(text: str) -> list[str]:
    return _WORD.findall(text.casefold())


def _clean(text: str) -> str:
    return " ".join(unicodedata.normalize("NFC", text).split())


def _text_blocks(node: Any) -> Iterator[Any]:
    """Bloki bez bloków w środku, w kolejności dokumentu; luźny tekst jako akapit."""

    def loose(text: Optional[str]) -> Iterator[Any]:
        if text and text.strip():
            paragraph = html.Element("p")
            paragraph.text = text
            yield paragraph

    if not any(_tag(child) in _BLOCK_TAGS for child in node):
        yield node
        return
    yield from loose(node.text)
    for child in node:
        yield from _text_blocks(child)
        yield from loose(child.tail)


def _without_label(text: str) -> str:
    folded = text.casefold()
    for label in _LEADING_LABELS:
        if folded.startswith(label):
            return text[len(label) :].strip()
    return text


def section_texts(content_html: Optional[str]) -> dict[str, list[str]]:
    """Tekst CV po sekcjach, bez tekstu szablonu."""
    texts: dict[str, list[str]] = {section: [] for section in SECTIONS}
    root = html.fragment_fromstring(content_html or "", create_parent="div")
    # `text_content` skleja słowa po obu stronach `<br>`.
    for line_break in root.iter("br"):
        line_break.tail = " " + (line_break.tail or "")
    section = "other"
    for node in _text_blocks(root):
        text = _clean(node.text_content())
        marker = node.get("data-cv-section")
        if not text or is_rodo_node(node):
            continue
        if _tag(node) == "h2":
            known = marker if marker in _REPORT_SECTION else None
            known = known or _SECTION_TITLES.get(_norm_title(text))
            if known:
                section = _REPORT_SECTION[known]
                continue
            section = "other"
        elif marker == "duties_label" or _norm_title(text) in _DUTIES_LABELS:
            continue
        text = _without_label(text)
        if text:
            texts[section].append(text)
    return texts


@dataclass(frozen=True)
class SectionEdit:
    """Zmiana jednej sekcji względem bazy; ``changed`` obejmuje też samą kolejność."""

    base_words: int
    added: int
    removed: int
    changed: bool

    @property
    def added_share(self) -> Optional[float]:
        return self.added / self.base_words if self.base_words else None

    @property
    def removed_share(self) -> Optional[float]:
        return self.removed / self.base_words if self.base_words else None


def _edit(base: list[str], final: list[str]) -> SectionEdit:
    base_text, final_text = " ".join(base), " ".join(final)
    base_words = Counter(words(base_text))
    final_words = Counter(words(final_text))
    return SectionEdit(
        base_words=sum(base_words.values()),
        added=sum((final_words - base_words).values()),
        removed=sum((base_words - final_words).values()),
        changed=base_text != final_text,
    )


def compare_cv(baseline_html: str, final_html: str) -> dict[str, SectionEdit]:
    """Zmiana po sekcjach i całości (słowo przeniesione między sekcjami to nie zmiana całości)."""
    base = section_texts(baseline_html)
    final = section_texts(final_html)
    edits = {section: _edit(base[section], final[section]) for section in SECTIONS}
    edits[TOTAL] = _edit(
        [text for section in SECTIONS for text in base[section]],
        [text for section in SECTIONS for text in final[section]],
    )
    return edits
