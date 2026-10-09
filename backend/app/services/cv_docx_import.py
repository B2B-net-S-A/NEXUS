"""Plik Word z profilu kandydata → HTML edytora CV firmowego. Bez AI, bez bazy.

Rekruterzy mają gotowe CV dla klientów jako pliki Word „…B2B…” (09.10.2026:
16 008 plików DOCX, 34 z 50 osób w screeningu), a edytor CV etapu przyjmował
wyłącznie CV z generatora. Ta funkcja jest odwrotnością układu szablonu
firmowego (``cv_approved_docx.render_approved_docx``): rozpoznaje jego sekcje,
tabelę edukacji i blok stanowiska („daty / Nazwa firmy: / Stanowisko:”)
i zapisuje je w tym samym kształcie co HTML z generatora, więc zapis z edytora
daje z powrotem ten sam układ. Czego nie rozpozna, zostaje akapitem albo
punktem z zachowanym tekstem i pogrubieniem — tekst źródła nigdy nie znika.
"""

from __future__ import annotations

import html as html_lib
import io
import re
from dataclasses import dataclass
from typing import Any, Iterator, Optional

from app.core.zip_guard import assert_safe_ooxml
from app.services.cv_approved_docx import (
    _DATES_ONLY,
    _DUTIES_LABELS,
    _SECTION_TITLES,
    _TECH_LABELS,
    _norm_title,
)
from app.services.cv_generator_b2b.docx_renderer import TRANSLATIONS
from app.services.cv_rodo_clause import is_rodo_text
from app.services.dz_review import _docx_heading, _run_bold
from app.services.html_sanitizer import sanitize_cv_html

MAX_BYTES = 10 * 1024 * 1024
MIN_TEXT_CHARS = 200

Runs = list[tuple[str, bool]]

_COMPANY_LABELS = tuple(t["company_name"] for t in TRANSLATIONS.values())
_POSITION_LABELS = tuple(t["position"] for t in TRANSLATIONS.values())
_EDUCATION_HEADERS = {
    (_norm_title(t["dates"]), _norm_title(t["education_header"]))
    for t in TRANSLATIONS.values()
}
_TITLES_BY_LANGUAGE = {
    language: {
        _norm_title(t[key])
        for key in (
            "why",
            "education",
            "skills",
            "certifications",
            "languages",
            "experience",
        )
    }
    for language, t in TRANSLATIONS.items()
}
_POLISH_LETTERS = re.compile(r"[ąćęłńóśźż]", re.IGNORECASE)
# Sekcje, w których generator pisze każdą pozycję jako akapit (renderer robi
# z niego punkt) — lista Worda wraca tam do tego samego kształtu.
_PARAGRAPH_ITEM_SECTIONS = {"skills", "languages"}
_ROW_SEPARATOR = " — "
_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


class CvImportError(ValueError):
    """Pliku nie da się wczytać do edytora; komunikat jest dla rekrutera."""


@dataclass(frozen=True)
class ImportedCv:
    html: str
    language: str
    stats: dict[str, int]


@dataclass
class _Line:
    kind: str  # "p" | "li" | "row"
    runs: Runs
    heading: bool = False

    @property
    def text(self) -> str:
        return "".join(text for text, _ in self.runs).strip()


def _merge(runs: Runs) -> Runs:
    out: Runs = []
    for text, bold in runs:
        if not text:
            continue
        if out and out[-1][1] == bold:
            out[-1] = (out[-1][0] + text, bold)
        else:
            out.append((text, bold))
    return out


def _local(element: Any) -> str:
    return str(element.tag).rsplit("}", 1)[-1]


def _in_textbox(element: Any, stop: Any) -> bool:
    parent = element.getparent()
    while parent is not None and parent is not stop:
        if _local(parent) == "txbxContent":
            return True
        parent = parent.getparent()
    return False


def _paragraph_runs(paragraph: Any) -> Runs:
    from docx.text.run import Run

    style = paragraph.style
    para_bold = bool(style is not None and style.font is not None and style.font.bold)
    runs: Runs = []
    # Wszystkie runy akapitu, także w hiperłączu, polu formularza i wstawce
    # śledzenia zmian (`paragraph.runs` widzi tylko bezpośrednie dzieci). Runy
    # pola tekstowego zakotwiczonego w akapicie należą do pola, nie do niego.
    for element in paragraph._p.iter(f"{_W}r"):
        if _in_textbox(element, paragraph._p):
            continue
        run = Run(element, paragraph)
        if run.text:
            runs.append((run.text.replace("\t", " "), _run_bold(run, para_bold)))
    return _merge(runs)


def _paragraph_line(paragraph: Any) -> Optional[_Line]:
    runs = _paragraph_runs(paragraph)
    text = "".join(t for t, _ in runs).strip()
    if not text:
        return None
    style_name = paragraph.style.name if paragraph.style is not None else ""
    properties = paragraph._p.pPr
    numbered = properties is not None and properties.numPr is not None
    is_list = numbered or "list" in style_name.casefold()
    return _Line(
        kind="li" if is_list else "p",
        runs=runs,
        heading=not is_list and _docx_heading(text, style_name),
    )


def _block_elements(container: Any) -> Iterator[Any]:
    """Akapity i tabele kontenera, także owinięte polem formularza Worda."""
    for child in container.iterchildren():
        tag = _local(child)
        if tag in ("p", "tbl"):
            yield child
        elif tag == "sdt":
            content = child.find(f"{_W}sdtContent")
            if content is not None:
                yield from _block_elements(content)
        elif tag in ("ins", "moveTo", "customXml", "smartTag"):
            yield from _block_elements(child)


def _cell_runs(cell: Any) -> Runs:
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    runs: Runs = []
    for element in _block_elements(cell._tc):
        if _local(element) == "tbl":
            parts = [
                _cell_runs(inner)
                for row in Table(element, cell).rows
                for inner in _cells(row)
            ]
        else:
            parts = [_paragraph_runs(Paragraph(element, cell))]
        for part in parts:
            if not "".join(t for t, _ in part).strip():
                continue
            if runs:
                runs.append(("\n", False))
            runs.extend(part)
    return runs


def _cells(row: Any) -> list[Any]:
    seen: set[int] = set()
    cells = []
    for cell in row.cells:  # scalone komórki python-docx oddaje wielokrotnie
        if id(cell._tc) not in seen:
            seen.add(id(cell._tc))
            cells.append(cell)
    return cells


def _row_line(row: Any) -> Optional[_Line]:
    runs: Runs = []
    for cell in _cells(row):
        part = _cell_runs(cell)
        if not "".join(t for t, _ in part).strip():
            continue
        if runs:
            runs.append((" ", False))
        runs.extend(part)
    # Koniec linii w komórce (uczelnia / kierunek) to w edytorze separator —
    # renderer z powrotem robi z niego nową linię w tabeli edukacji.
    flat: Runs = []
    for text, bold in runs:
        pieces = text.split("\n")
        for index, piece in enumerate(pieces):
            if index:
                flat.append((_ROW_SEPARATOR, False))
            flat.append((piece, bold))
    line = _Line(kind="row", runs=_merge(flat))
    return line if line.text else None


def _lines(doc: Any) -> list[_Line]:
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    lines: list[_Line] = []
    for element in _block_elements(doc.element.body):
        if _local(element) == "p":
            line = _paragraph_line(Paragraph(element, doc))
            if line is not None:
                lines.append(line)
        else:
            for row in Table(element, doc).rows:
                line = _row_line(row)
                if line is not None:
                    lines.append(line)
    return lines


def _textbox_texts(doc: Any) -> list[str]:
    """Teksty z pól tekstowych — szablon trzyma tam klauzulę zgody."""
    texts = []
    for element in doc.element.body.iter():
        if str(element.tag).endswith("}txbxContent"):
            text = "".join(
                node.text or ""
                for node in element.iter()
                if str(node.tag).endswith("}t")
            )
            if text.strip():
                texts.append(" ".join(text.split()))
    return texts


def _inline(runs: Runs, *, plain: bool = False) -> str:
    parts = []
    for text, bold in runs:
        escaped = html_lib.escape(text, quote=False).replace("\n", "<br>")
        parts.append(f"<strong>{escaped}</strong>" if bold and not plain else escaped)
    return "".join(parts).strip()


def _cut_prefix(runs: Runs, length: int) -> Runs:
    out: Runs = []
    for text, bold in runs:
        if length >= len(text):
            length -= len(text)
            continue
        out.append((text[length:], bold))
        length = 0
    if out:
        out[0] = (out[0][0].lstrip(), out[0][1])
    return _merge(out)


def _label(text: str, labels: tuple[str, ...]) -> Optional[str]:
    return next((label for label in labels if text.startswith(label)), None)


def _language(lines: list[_Line], rodo_text: Optional[str]) -> str:
    titles = {_norm_title(line.text) for line in lines if line.heading}
    scores = {
        language: len(titles & known) for language, known in _TITLES_BY_LANGUAGE.items()
    }
    if scores["en"] != scores["pl"]:
        return "en" if scores["en"] > scores["pl"] else "pl"
    if rodo_text:
        return "en" if rodo_text.lstrip().lower().startswith("i hereby") else "pl"
    body = " ".join(line.text for line in lines)
    return "pl" if _POLISH_LETTERS.search(body) else "en"


class _Builder:
    def __init__(self) -> None:
        self.parts: list[str] = []
        self.items: list[str] = []
        self.section: Optional[str] = None
        self.pending: list[_Line] = []
        self.dates: Optional[Runs] = None
        self.company: Optional[Runs] = None
        self.rodo: Optional[str] = None
        self.stats = {"sections": 0, "roles": 0, "list_items": 0}

    def _close_list(self) -> None:
        if self.items:
            self.parts.append("<ul>" + "".join(self.items) + "</ul>")
            self.items = []

    def _block(self, fragment: str) -> None:
        self._close_list()
        self.parts.append(fragment)

    def _plain_line(self, line: _Line) -> None:
        if line.kind == "li" and self.section not in _PARAGRAPH_ITEM_SECTIONS:
            self.items.append(f"<li>{_inline(line.runs)}</li>")
            self.stats["list_items"] += 1
            return
        self._block(f"<p>{_inline(line.runs)}</p>")

    def _flush_pending(self) -> None:
        """Daty albo „Nazwa firmy:” bez stanowiska zostają tak, jak były."""
        for line in self.pending:
            self._plain_line(line)
        self.pending, self.dates, self.company = [], None, None

    def _role(self, position: Runs) -> None:
        dates = _inline(self.dates or [], plain=True)
        head = f"<strong>{_inline(position, plain=True)}</strong>"
        self._block(
            f'<p data-cv-section="role">{head}{" " + dates if dates else ""}</p>'
        )
        if self.company:
            self._block(
                f'<p data-cv-section="employer">{_inline(self.company, plain=True)}</p>'
            )
        self.pending, self.dates, self.company = [], None, None
        self.stats["roles"] += 1

    def _experience(self, line: _Line) -> bool:
        text = line.text
        if line.kind == "p":
            if _DATES_ONLY.fullmatch(text):
                self._flush_pending()
                self.pending.append(line)
                self.dates = line.runs
                return True
            company = _label(text, _COMPANY_LABELS)
            if company and self.company is None:
                self.pending.append(line)
                self.company = _cut_prefix(line.runs, len(company))
                return True
            position = _label(text, _POSITION_LABELS)
            if position:
                value = _cut_prefix(line.runs, len(position))
                if "".join(t for t, _ in value).strip():
                    self._role(value)
                    return True
        self._flush_pending()
        if line.kind == "p":
            if _norm_title(text) in _DUTIES_LABELS:
                self._block(
                    f'<p data-cv-section="duties_label">{_inline(line.runs, plain=True)}</p>'
                )
                return True
            technologies = _label(text, _TECH_LABELS)
            if technologies:
                # Etykietę pogrubia renderer; pogrubienia technologii zostają.
                rest = _inline(_cut_prefix(line.runs, len(technologies)))
                self._block(
                    f'<p data-cv-section="technologies">'
                    f"{html_lib.escape(technologies, quote=False)} {rest}</p>"
                )
                return True
        return False

    def add(self, line: _Line) -> None:
        text = line.text
        if self.rodo is None and line.kind != "li" and is_rodo_text(text):
            self._flush_pending()
            self.rodo = text
            return
        if line.heading:
            self._flush_pending()
            key = _SECTION_TITLES.get(_norm_title(text))
            escaped = html_lib.escape(text, quote=False)
            if key:
                self.section = key
                self.stats["sections"] += 1
                self._block(f'<h2 data-cv-section="{key}">{escaped}</h2>')
            else:
                # Nierozpoznany nagłówek nie zamyka sekcji (wielkimi literami
                # bywa pisana nazwa firmy w doświadczeniu).
                self._block(f"<h3>{escaped}</h3>")
            return
        if self.section == "experience" and self._experience(line):
            return
        self._plain_line(line)

    def html(self, title: Optional[_Line], rodo: str) -> str:
        self._flush_pending()
        self._close_list()
        head = f"<h1>{html_lib.escape(title.text, quote=False)}</h1>" if title else ""
        clause = html_lib.escape(rodo, quote=False)
        return (
            f'<article class="cv">{head}{"".join(self.parts)}'
            f'<p class="rodo">{clause}</p></article>'
        )


def docx_to_editor_html(data: bytes) -> ImportedCv:
    """Wczytaj plik Word jako HTML edytora CV. Rzuca :class:`CvImportError`."""
    from docx import Document

    if len(data) > MAX_BYTES:
        raise CvImportError(
            "Plik jest za duży, żeby wczytać go do edytora (limit 10 MB)."
        )
    if not data.startswith(b"PK"):
        raise CvImportError(
            "Do edytora można wczytać tylko plik Word (.docx). Ten plik ma inny format."
        )
    try:
        assert_safe_ooxml(data)
        doc = Document(io.BytesIO(data))
        lines = _lines(doc)
        textboxes = _textbox_texts(doc)
    except Exception as error:  # noqa: BLE001 — uszkodzony albo nietypowy plik
        raise CvImportError(
            "Nie udało się odczytać tego pliku Word. Otwórz go w Wordzie i zapisz ponownie jako .docx."
        ) from error

    chars = sum(len(line.text) for line in lines)
    if chars < MIN_TEXT_CHARS:
        raise CvImportError(
            "W tym pliku nie ma tekstu do wczytania (pusty dokument albo skan)."
        )

    title: Optional[_Line] = None
    body = lines
    if lines[0].kind == "p" and not (
        lines[0].heading and _norm_title(lines[0].text) in _SECTION_TITLES
    ):
        title, body = lines[0], lines[1:]

    builder = _Builder()
    for line in body:
        if (
            line.kind == "row"
            and builder.section == "education"
            and _education_header(line)
        ):
            continue
        builder.add(line)
    rodo_source = builder.rodo or next(
        (text for text in textboxes if is_rodo_text(text)), None
    )
    language = _language(lines, rodo_source)
    rodo = rodo_source or TRANSLATIONS[language]["rodo"]
    html = sanitize_cv_html(builder.html(title, rodo))
    return ImportedCv(
        html=html,
        language=language,
        stats={
            "source_lines": len(lines),
            "chars": chars,
            "textboxes": len(textboxes),
            **builder.stats,
        },
    )


def _education_header(line: _Line) -> bool:
    text = _norm_title(line.text)
    return any(text == f"{dates} {header}" for dates, header in _EDUCATION_HEADERS)
