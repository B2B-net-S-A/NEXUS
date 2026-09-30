"""Render approved editor content without extracting, rewriting or inferring facts.

The DOCX of a recruitment CV (draft preview, approved version, DL review, Cpro
queue, client link) is built from the EDITOR HTML, so recruiter and QC edits
survive. Until 30.09.2026 that HTML was converted generically — bullets typed
as "• " text, no section rules, no education table — and the file sent to the
client looked nothing like the same CV downloaded from the generator
(`docx_renderer.render_cv_to_bytes`). The layout pass below recognises the CV
sections (``data-cv-section`` markers written by the generator and kept by the
editor; heading titles for older HTML without markers) and lays them out with
the generator's building blocks. Text, its order and inline emphasis still
come from the editor verbatim; only labels ("Company:", "Tasks:") and the
arrangement follow the corporate template. HTML the pass does not recognise
falls back to the generic conversion.
"""

from __future__ import annotations

import base64
import copy
from io import BytesIO
import re
from typing import Any, Optional

from docx import Document
from docx.enum.style import WD_STYLE_TYPE
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor
from lxml import html

from app.services.cv_generator_b2b.docx_renderer import (
    add_bottom_pinned_rodo,
    add_consent_screenshot,
    add_education_table,
    add_horizontal_line,
    normalize_letterhead_layout,
    style_education_row,
    TRANSLATIONS,
)

RENDERER_VERSION = "approved-html-2"
BLOCKS = {
    "p",
    "div",
    "section",
    "article",
    "main",
    "header",
    "footer",
    "blockquote",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "ul",
    "ol",
    "li",
    "table",
    "hr",
    "pre",
}
# Wrappers without their own layout (the generator's `<article class="cv">`,
# `<div class="job">`): their blocks are laid out as if they were top-level.
_WRAPPERS = {"div", "section", "article", "main", "header", "footer"}
_CV_SECTIONS = {
    "why_points",
    "education",
    "skills",
    "certifications",
    "languages",
    "experience",
}
# Numbering definition 1 of the corporate template: red square bullet with a
# hanging indent — the same list the generator uses (`add_bullet_point`).
_BULLET_NUM_ID = "1"
_COLOR_HEADER = RGBColor(225, 79, 79)
# Text after the bold position of a role line is a date range and nothing
# else ("12.2025 - present", "2015 – 2019"). Anything longer is prose that
# merely starts in bold ("**Projekt:** nowy system płatności").
_DATES_ONLY = re.compile(
    r"(?=.*\b(?:19|20)\d{2}\b)[\d\s./()–—\-]*"
    r"(?:\b(?:present|obecnie|currently|now|teraz|nadal|ongoing)\b[\s.)]*)?",
    re.IGNORECASE,
)
_LEADING_SEPARATOR = re.compile(r"^[\s—–\-,:·|]+")


def _norm_title(text: str) -> str:
    return " ".join(text.split()).casefold().rstrip(":?").strip()


def _section_titles() -> dict[str, str]:
    titles = {"summary": "why_points", "podsumowanie": "why_points"}
    for t in TRANSLATIONS.values():
        titles[_norm_title(t["why"])] = "why_points"
        for key in ("education", "skills", "certifications", "languages", "experience"):
            titles[_norm_title(t[key])] = key
    return titles


_SECTION_TITLES = _section_titles()
_DUTIES_LABELS = {_norm_title(t["responsibilities"]) for t in TRANSLATIONS.values()}
_TECH_LABELS = tuple(t["technologies"] for t in TRANSLATIONS.values())
# Older approved HTML lost the consent marker in the editor; the clause is
# still recognisable by its fixed opening words.
_RODO_OPENINGS = tuple(
    _norm_title(" ".join(t["rodo"].split()[:5])) for t in TRANSLATIONS.values()
)


class ApprovedDocxError(ValueError):
    pass


class _HasImage(Exception):
    """Inline content holds an image — use the generic path that embeds it."""


def _image(value: str) -> bytes:
    # Never fetch arbitrary URLs from editable HTML. Tiptap currently emits no
    # remote images; fail explicitly if an API client submits one.
    match = re.fullmatch(r"data:image/(?:png|jpeg);base64,([A-Za-z0-9+/=\s]+)", value)
    if not match or len(match[1]) > 8_000_000:
        raise ApprovedDocxError(
            "Nieobsługiwany obraz w CV. Użyj osadzonego PNG lub JPEG."
        )
    try:
        data = base64.b64decode(match[1], validate=True)
        from PIL import Image

        with Image.open(BytesIO(data)) as im:
            im.verify()
    except Exception as error:
        raise ApprovedDocxError("Nie można odczytać obrazu w CV.") from error
    return data


def _tag(node: Any) -> str:
    return str(node.tag).lower()


def _inline_state(node: Any, state: dict) -> dict:
    state = dict(state)
    tag = _tag(node)
    for tags, key in [
        ({"b", "strong"}, "bold"),
        ({"em", "i"}, "italic"),
        ({"u"}, "underline"),
        ({"s", "del"}, "strike"),
        ({"sub"}, "sub"),
        ({"sup"}, "sup"),
        ({"code"}, "code"),
    ]:
        if tag in tags:
            state[key] = True
    style = node.get("style", "").lower()
    if re.search(r"font-weight\s*:\s*(bold|[7-9]00)", style):
        state["bold"] = True
    if "font-style: italic" in style or "font-style:italic" in style:
        state["italic"] = True
    return state


Segments = list  # [(text, state)]; text "\n" is a line break


def _segments(node: Any, state: Optional[dict] = None) -> Segments:
    """Flat inline runs of ``node`` (its own tail excluded)."""
    out: Segments = []

    def walk(current: Any, current_state: dict) -> None:
        current_state = _inline_state(current, current_state)
        tag = _tag(current)
        if tag == "img":
            raise _HasImage
        if tag == "br":
            out.append(("\n", current_state))
            return
        if current.text:
            out.append((current.text, current_state))
        for child in current:
            walk(child, current_state)
            if child.tail:
                out.append((child.tail, current_state))

    walk(node, state or {})
    return out


def _plain(segments: Segments) -> str:
    return "".join(text for text, _ in segments)


def _trim(segments: Segments) -> Segments:
    """Drop surrounding whitespace across segment boundaries."""
    items = [(text, state) for text, state in segments]
    while items and not items[0][0].strip():
        items.pop(0)
    while items and not items[-1][0].strip():
        items.pop()
    if items:
        items[0] = (items[0][0].lstrip(), items[0][1])
        items[-1] = (items[-1][0].rstrip(), items[-1][1])
    return items


def _split_leading_bold(segments: Segments) -> tuple[Segments, Segments]:
    items = _trim(segments)
    lead: Segments = []
    index = 0
    while index < len(items) and items[index][1].get("bold"):
        lead.append(items[index])
        index += 1
    return lead, items[index:]


def _strip_leading_separator(segments: Segments) -> Segments:
    items = list(segments)
    while items:
        text, state = items[0]
        stripped = _LEADING_SEPARATOR.sub("", text)
        if stripped:
            items[0] = (stripped, state)
            break
        items.pop(0)
    return items


def _formatted(segments: Segments) -> bool:
    return any(text.strip() and any(state.values()) for text, state in segments)


def _has_block_child(node: Any) -> bool:
    return any(_tag(child) in BLOCKS for child in node)


def _template_has_bullets(doc: Any) -> bool:
    try:
        numbering = doc.part.numbering_part.element
    except (KeyError, NotImplementedError, AttributeError):
        return False
    return any(
        num.get(qn("w:numId")) == _BULLET_NUM_ID
        for num in numbering.findall(qn("w:num"))
    )


def render_approved_docx(
    content_html: str,
    template: bytes,
    *,
    consent: bytes | None = None,
    language: str = "pl",
) -> bytes:
    """The HTML is already sanitized. Preserve text, emphasis and order exactly.

    Uses the corporate letterhead but never the original generated narrative.
    Text formatting comes from the editor, not a fresh keyword/model pass.
    """
    doc = Document(BytesIO(template))
    normalize_letterhead_layout(doc)
    for child in list(doc.element.body):
        if not child.tag.endswith("}sectPr"):
            doc.element.body.remove(child)
    t = TRANSLATIONS.get(language, TRANSLATIONS["pl"])
    bullets_available = _template_has_bullets(doc)
    # Use private body styles: changing Normal also changes the letterhead,
    # while template Heading styles may contain all-caps and border residue.
    normal = doc.styles.add_style("Approved CV Body", WD_STYLE_TYPE.PARAGRAPH)
    normal.base_style = doc.styles["Normal"]
    normal.font.name = "Montserrat"
    normal.font.size = Pt(10)
    normal.font.color.rgb = RGBColor.from_string("373535")
    normal.paragraph_format.space_after = Pt(5)
    # Sizes follow the generator: 24 pt document title, 14 pt section titles.
    for level, size in [(1, 24), (2, 14), (3, 11)]:
        heading = doc.styles.add_style(
            f"Approved CV Heading {level}", WD_STYLE_TYPE.PARAGRAPH
        )
        heading.base_style = normal
        heading.font.name = "Montserrat SemiBold"
        heading.font.size = Pt(size)
        heading.font.color.rgb = _COLOR_HEADER
        heading.font.all_caps = False
        heading.paragraph_format.keep_with_next = True
        heading.paragraph_format.space_before = Pt(10)
    root = html.fragment_fromstring(content_html or "", create_parent="div")

    def text_run(paragraph, text, state):
        if not text:
            return
        run = paragraph.add_run(text)
        run.bold = state.get("bold", False)
        run.italic = state.get("italic", False)
        run.underline = state.get("underline", False)
        run.font.strike = state.get("strike", False)
        run.font.subscript = state.get("sub", False)
        run.font.superscript = state.get("sup", False)
        if state.get("code"):
            run.font.name = "Courier New"

    def inline(node, paragraph, state=None):
        state = _inline_state(node, state or {})
        tag = _tag(node)
        if tag == "br":
            paragraph.add_run().add_break()
        elif tag == "img":
            try:
                paragraph.add_run().add_picture(
                    BytesIO(_image(node.get("src", ""))), width=Inches(5.5)
                )
            except ApprovedDocxError:
                raise
            except Exception as error:
                raise ApprovedDocxError("Nie można wstawić obrazu do DOCX.") from error
        else:
            text_run(paragraph, node.text, state)
            for child in node:
                inline(child, paragraph, state)
                text_run(paragraph, child.tail, state)

    def emit(paragraph, segments, force=None):
        for text, state in segments:
            if text == "\n":
                paragraph.add_run().add_break()
            else:
                text_run(paragraph, text, {**state, **(force or {})})

    def paragraph_for(container, tag="p", style="", prefix=""):
        paragraph = container.add_paragraph(style=normal)
        if prefix:
            paragraph.add_run(prefix)
        if tag.startswith("h") and len(tag) == 2 and tag[1].isdigit():
            paragraph.style = "Approved CV Heading " + str(min(int(tag[1]), 3))
        align = re.search(r"text-align\s*:\s*(left|right|center|justify)", style)
        if align:
            paragraph.alignment = {
                "left": WD_ALIGN_PARAGRAPH.LEFT,
                "right": WD_ALIGN_PARAGRAPH.RIGHT,
                "center": WD_ALIGN_PARAGRAPH.CENTER,
                "justify": WD_ALIGN_PARAGRAPH.JUSTIFY,
            }[align[1]]
        return paragraph

    def spaced(paragraph, before, after, line=None):
        paragraph.paragraph_format.space_before = Pt(before)
        paragraph.paragraph_format.space_after = Pt(after)
        if line is not None:
            paragraph.paragraph_format.line_spacing = line
        return paragraph

    def render_table(node, container):
        rows = node.xpath("./tr|./thead/tr|./tbody/tr|./tfoot/tr")
        if not rows:
            return
        # Respect merged cells; reject pathological dimensions before allocating.
        occupied = {}
        cells = []
        max_col = 0
        for row_index, row in enumerate(rows):
            col = 0
            for cell in row.xpath("./td|./th"):
                while (row_index, col) in occupied:
                    col += 1
                try:
                    width = int(cell.get("colspan", "1"))
                    height = int(cell.get("rowspan", "1"))
                except ValueError as error:
                    raise ApprovedDocxError(
                        "Nieprawidłowe scalanie komórek tabeli."
                    ) from error
                if (
                    not (1 <= width <= 20 and 1 <= height <= len(rows) - row_index)
                    or col + width > 20
                ):
                    raise ApprovedDocxError("Nieobsługiwany rozmiar tabeli w CV.")
                for ri in range(row_index, row_index + height):
                    for ci in range(col, col + width):
                        if (ri, ci) in occupied:
                            raise ApprovedDocxError(
                                "Nakładające się komórki tabeli w CV."
                            )
                        occupied[ri, ci] = True
                cells.append((row_index, col, height, width, cell))
                max_col = max(max_col, col + width)
                col += width
        if not max_col or len(rows) > 1000:
            raise ApprovedDocxError("Nieobsługiwany rozmiar tabeli w CV.")
        table = container.add_table(rows=len(rows), cols=max_col)
        for ri, ci, height, width, cell_node in cells:
            target = table.cell(ri, ci)
            if height > 1 or width > 1:
                target = target.merge(table.cell(ri + height - 1, ci + width - 1))
            target.text = ""
            render_container(cell_node, target)
            if (
                target.paragraphs
                and not target.paragraphs[0].text
                and len(target.paragraphs) > 1
            ):
                first = target.paragraphs[0]._element
                first.getparent().remove(first)

    def render_container(node, container, depth=0):
        # Mixed inline/block contents remain in document order. Unknown cosmetic
        # wrappers keep all their text; no source selection occurs in this layer.
        paragraph = None
        if node.text and node.text.strip():
            paragraph = paragraph_for(container)
            text_run(paragraph, node.text, {})
        for child in node:
            tag = _tag(child)
            if tag in {"ul", "ol"}:
                paragraph = None
                render_list(child, container, depth)
            elif tag == "table":
                paragraph = None
                render_table(child, container)
            elif tag == "hr":
                paragraph = None
                if container is doc:
                    add_horizontal_line(doc)
            elif tag in {"p", "pre", "blockquote", "h1", "h2", "h3", "h4", "h5", "h6"}:
                paragraph = None
                p = paragraph_for(container, tag, child.get("style", ""))
                inline(child, p)
            elif tag in BLOCKS:
                paragraph = None
                render_container(child, container, depth)
            else:
                if paragraph is None:
                    paragraph = paragraph_for(container)
                inline(child, paragraph)
            if child.tail and (child.tail.strip() or paragraph is not None):
                if paragraph is None:
                    paragraph = paragraph_for(container)
                text_run(paragraph, child.tail, {})

    # ── Lists: the template's red square bullets (Word numbering) ──────────

    def bullet_paragraph(container, depth, number=None):
        if number is not None or not bullets_available:
            # Ordered lists keep their visible numbers; a template without the
            # bullet definition gets a typed bullet instead of an invisible one.
            prefix = f"{number}. " if number is not None else "• "
            p = paragraph_for(container, prefix=prefix)
            p.paragraph_format.left_indent = Inches(0.15 * (depth + 1))
            return spaced(p, 1, 1, 1.5)
        p = paragraph_for(container)
        num_pr = OxmlElement("w:numPr")
        ilvl = OxmlElement("w:ilvl")
        ilvl.set(qn("w:val"), str(min(depth, 2)))
        num_id = OxmlElement("w:numId")
        num_id.set(qn("w:val"), _BULLET_NUM_ID)
        num_pr.append(ilvl)
        num_pr.append(num_id)
        p._element.get_or_add_pPr().insert(0, num_pr)
        return spaced(p, 1, 1, 1.5)

    def render_list(node, container, depth=0):
        ordered = _tag(node) == "ol"
        for number, li in enumerate(node.xpath("./li"), 1):
            p = bullet_paragraph(container, depth, number if ordered else None)
            started = False  # whether `p` already holds this item's text
            text_run(p, li.text, {})
            started = bool(li.text and li.text.strip())
            for part in list(li):
                part_tag = _tag(part)
                if part_tag in {"ul", "ol"}:
                    render_list(part, container, depth + 1)
                    p = None
                elif part_tag == "p":
                    if p is None:
                        # Text after a nested list continues the item without
                        # a second bullet, aligned with the item's text.
                        p = paragraph_for(container)
                        p.paragraph_format.left_indent = Inches(0.5 * (depth + 1))
                        spaced(p, 1, 1, 1.5)
                    elif started:
                        # Tiptap lists wrap item text in paragraphs.
                        p.add_run().add_break()
                    inline(part, p)
                    started = True
                else:
                    if p is None:
                        p = paragraph_for(container)
                    inline(part, p)
                    started = True
                if part.tail and (part.tail.strip() or p is not None):
                    if p is None:
                        p = paragraph_for(container)
                    text_run(p, part.tail, {})

    # ── Corporate layout ─────────────────────────────────────────────────

    # Role markers decide whether experience relies on markers or on shape;
    # the consent marker alone (older editor HTML) says nothing about roles.
    marked = bool(root.xpath(".//*[@data-cv-section='role']"))
    rodo: dict[str, Segments] = {}
    state = {"section": None, "rule": False, "jobs": 0, "after_role": False}
    education_rows: list[Any] = []

    def section_key(node) -> Optional[str]:
        marker = node.get("data-cv-section")
        if marker in _CV_SECTIONS:
            return marker
        return _SECTION_TITLES.get(_norm_title("".join(node.itertext())))

    def is_rodo(node) -> bool:
        return (
            node.get("data-cv-section") == "rodo"
            or "rodo" in node.get("class", "").split()
            or _norm_title("".join(node.itertext())).startswith(_RODO_OPENINGS)
        )

    def ruled():
        if not state["rule"]:
            add_horizontal_line(doc)
        state["rule"] = True

    def generic(node):
        wrapper = html.Element("div")
        wrapper.append(copy.deepcopy(node))
        wrapper[0].tail = None
        render_container(wrapper, doc)

    def flush_education():
        if not education_rows:
            return
        table = add_education_table(doc, len(education_rows), t)
        for index, segments in enumerate(education_rows, start=1):
            cells = table.rows[index].cells
            lead_plain: Segments = []
            position = 0
            while position < len(segments) and not segments[position][1].get("bold"):
                lead_plain.append(segments[position])
                position += 1
            bold: Segments = []
            while position < len(segments) and segments[position][1].get("bold"):
                bold.append(segments[position])
                position += 1
            rest = _trim(_strip_leading_separator(segments[position:]))
            cells[0].text = ""
            cells[1].text = ""
            if bold:
                emit(cells[0].paragraphs[0], _trim(lead_plain))
                target = cells[1].paragraphs[0]
                emit(target, _trim(bold))
                if rest:
                    target.add_run().add_break()
                    emit(target, rest)
            else:
                # No institution in bold (edited by hand): keep the row whole.
                emit(cells[1].paragraphs[0], _trim(segments))
            style_education_row(cells, index)
        doc.add_paragraph()
        education_rows.clear()

    def labelled_line(label, segments, *, label_bold=False, value_bold=True):
        p = paragraph_for(doc)
        text_run(p, label + " ", {"bold": label_bold})
        emit(p, _trim(segments), {"bold": True} if value_bold else None)
        return spaced(p, 0, 0)

    def role_kind(node) -> Optional[str]:
        marker = node.get("data-cv-section")
        if marker in {"role", "employer", "duties_label", "technologies"}:
            return marker
        if marked:
            return None
        text = "".join(node.itertext())
        if _norm_title(text) in _DUTIES_LABELS:
            return "duties_label"
        if text.strip().startswith(_TECH_LABELS):
            return "technologies"
        try:
            lead, rest = _split_leading_bold(_segments(node))
        except _HasImage:
            return None
        if lead and _DATES_ONLY.fullmatch(_plain(rest).strip()):
            return "role"
        return None

    def render_role(node, employer) -> bool:
        try:
            lead, dates = _split_leading_bold(_segments(node))
        except _HasImage:
            return False
        if not lead or not _plain(lead).strip():
            return False
        if state["jobs"]:
            add_horizontal_line(doc)
        state["jobs"] += 1
        if _plain(dates).strip():
            p = paragraph_for(doc)
            emit(p, _trim(dates), {"bold": True})
            spaced(p, 1, 0)
        if employer is not None:
            render_employer(employer)
        labelled_line(t["position"], lead)
        return True

    def render_employer(node):
        try:
            labelled_line(t["company_name"], _segments(node))
        except _HasImage:
            generic(node)

    def render_technologies(node):
        try:
            segments = _trim(_segments(node))
        except _HasImage:
            generic(node)
            return
        p = paragraph_for(doc)
        plain = _plain(segments)
        label = next((lab for lab in _TECH_LABELS if plain.startswith(lab)), "")
        remaining = len(label)
        for text, seg_state in segments:
            if remaining > 0:
                head, text = text[:remaining], text[remaining:]
                remaining -= len(head)
                text_run(p, head, {**seg_state, "bold": True})
            emit(p, [(text, seg_state)])
        spaced(p, 4, 2)

    def render_skill(node):
        try:
            segments = _trim(_segments(node))
        except _HasImage:
            generic(node)
            return
        emit(bullet_paragraph(doc, 0), segments)

    def render_languages(node):
        try:
            segments = _trim(_segments(node))
        except _HasImage:
            generic(node)
            return
        if not _formatted(segments):
            for item in _plain(segments).split(" · "):
                if item.strip():
                    text_run(bullet_paragraph(doc, 0), item.strip(), {})
        else:
            emit(bullet_paragraph(doc, 0), segments)

    def title(node):
        p = paragraph_for(doc, "h1", node.get("style", ""))
        inline(node, p)
        spaced(p, 2, 6)

    def section_heading(node):
        state["section"] = section_key(node)
        state["jobs"] = 0
        ruled()
        p = paragraph_for(doc, "h2", node.get("style", ""))
        inline(node, p)
        spaced(p, 2, 3)

    def paragraph_block(node, blocks, index) -> int:
        """Lay out one p-like block; returns how many blocks it consumed."""
        section = state["section"]
        after_role, state["after_role"] = state["after_role"], False
        if is_rodo(node) and "clause" not in rodo:
            # One clause, pinned once. Text typed below it in the editor keeps
            # the marker (Enter copies it) and stays in the body instead of a
            # second box stacked on the first.
            try:
                rodo["clause"] = _trim(_segments(node))
                return 1
            except _HasImage:
                pass
        if section == "education":
            try:
                education_rows.append(_segments(node))
                return 1
            except _HasImage:
                pass
        flush_education()
        if section == "skills":
            render_skill(node)
            return 1
        if section == "languages":
            render_languages(node)
            return 1
        if section == "experience":
            kind = role_kind(node)
            if kind == "role":
                nxt = blocks[index + 1] if index + 1 < len(blocks) else None
                employer = (
                    nxt
                    if nxt is not None
                    and _tag(nxt) in {"p", "div"}
                    and not _has_block_child(nxt)
                    and (
                        nxt.get("data-cv-section") == "employer"
                        or (not marked and role_kind(nxt) is None)
                    )
                    else None
                )
                if render_role(node, employer):
                    return 2 if employer is not None else 1
                # Position no longer bold: the line stays as typed, and the
                # employer right below it still gets its label.
                state["after_role"] = True
                p = paragraph_for(doc, _tag(node), node.get("style", ""))
                inline(node, p)
                return 1
            elif kind == "employer" and after_role:
                render_employer(node)
                return 1
            elif (
                kind == "duties_label"
                and _norm_title("".join(node.itertext())) in _DUTIES_LABELS
            ):
                try:
                    segments = _trim(_segments(node))
                except _HasImage:
                    generic(node)
                    return 1
                p = paragraph_for(doc)
                emit(p, segments, {"underline": True})
                spaced(p, 0, 1)
                return 1
            elif kind == "technologies":
                render_technologies(node)
                return 1
        p = paragraph_for(doc, _tag(node), node.get("style", ""))
        inline(node, p)
        return 1

    def flatten(node) -> list[Any]:
        """Top-level blocks; loose text becomes its own paragraph block."""
        out: list[Any] = []

        def loose(text):
            if text and text.strip():
                p = html.Element("p")
                p.text = text
                out.append(p)

        loose(node.text)
        for child in node:
            tag = _tag(child)
            if (
                tag in _WRAPPERS
                and _has_block_child(child)
                and not child.get("data-cv-section")
                and not (child.text and child.text.strip())
                and not is_rodo(child)
            ):
                out.extend(flatten(child))
            else:
                out.append(child)
            loose(child.tail)
        return out

    blocks = flatten(root)
    index = 0
    while index < len(blocks):
        node = blocks[index]
        tag = _tag(node)
        consumed = 1
        if tag != "hr" and not (
            state["section"] == "education"
            and tag in {"p", "div"}
            and not _has_block_child(node)
            and not is_rodo(node)
        ):
            flush_education()
        if tag == "h1":
            title(node)
        elif tag == "hr":
            flush_education()
            ruled()
        elif tag == "h2":
            section_heading(node)
        elif tag in {"ul", "ol"}:
            render_list(node, doc)
        elif tag == "table":
            render_table(node, doc)
        elif tag in {"p", "pre", "blockquote", "div", "h3", "h4", "h5", "h6"}:
            if tag in {"p", "div"} and not _has_block_child(node):
                consumed = paragraph_block(node, blocks, index)
            elif tag == "div":
                generic(node)
            else:
                p = paragraph_for(doc, tag, node.get("style", ""))
                inline(node, p)
        else:
            generic(node)
        if tag != "hr":
            state["rule"] = False
        index += consumed
    flush_education()

    if consent is not None:
        if not add_consent_screenshot(doc, consent, t["consent_heading"]):
            raise ApprovedDocxError(
                "Nie można dołączyć zrzutu zgody. Zatwierdzenie zatrzymane."
            )
    clause = [
        (
            " " if text == "\n" else text,
            bool(st.get("bold")),
            bool(st.get("italic")),
            bool(st.get("underline")),
        )
        for text, st in rodo.get("clause", [])
    ]
    if any(text.strip() for text, *_ in clause):
        # Same bottom-pinned clause as the generator (last page, once), with
        # the editor's emphasis.
        add_bottom_pinned_rodo(doc, "", runs=clause)
    output = BytesIO()
    doc.save(output)
    return output.getvalue()
