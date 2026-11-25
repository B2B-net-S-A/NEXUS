"""„Nowe CV” jako plik Word (etap 2 formatu pliku klienta, decyzje Artura z 25.11.2026).

Wariant B po makietach: strona 1 to obraz pola treści strony 1 PDF (1:1, bez
edycji — stronę 1 poprawia się w NEXUSIE), od strony 2 stanowiska i pełne listy
jako tekst i tabele Worda, które klient może poprawiać. Strona 1 złożona
z tabel Worda wyglądała wyraźnie gorzej niż PDF (Artur: „okropnie”), a wersja
z obrazami etykiet i tekstem obok nie została wybrana.

Word nie liczy niczego drugi raz: obraz strony 1 pochodzi z tego samego PDF,
który klient dostaje przy formacie PDF, a to, co przechodzi na koniec CV
(pełna lista umiejętności, wszystkie certyfikaty), wynika z `page1()` z tymi
samymi ustawieniami dopasowania (`FitReport`) co PDF. Od strony 2 krój to
Poppins jak w PDF, osadzony w pliku (`docx_fonts`).
"""

from __future__ import annotations

import html
import io
import logging
import re
from datetime import date
from typing import Iterable, Optional

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Mm, Pt, RGBColor

from app.services.cv_new_layout.context import Ctx, DatedRole, build_context
from app.services.cv_new_layout.document import NewCvDocument
from app.services.cv_new_layout.facts import certs_by_year
from app.services.cv_new_layout.labels import consent_heading, default_rodo_clause
from app.services.cv_new_layout.page1 import page1, skill_items
from app.services.cv_new_layout.render import sniff_image_mime
from app.services.cv_new_layout.roles import role_period
from app.services.cv_new_layout.styles import (
    BOTTOM,
    BRAND,
    HEAD_1,
    INK,
    SIDE,
    SOFT,
    SOFT2,
    TOP_1,
)
from app.services.cv_new_layout.text import clean

logger = logging.getLogger(__name__)

FONT = "Poppins"
SIZE = 8.6  # pt — treść od strony 2, jak `body` w arkuszu PDF
CONTENT_W = 210.0 - 2 * SIDE
# Pole treści strony 1 PDF (bez nagłówka i stopki — te ma Word).
PAGE1_TOP = TOP_1 - 1.0
PAGE1_BOTTOM = 297.0 - BOTTOM
WORD_TOP, WORD_BOTTOM = PAGE1_TOP, BOTTOM
# Obraz o włos mniejszy niż pole treści Worda: równy co do ułamka bywa łamany na str. 2.
PAGE1_FIT = 0.985
LOGO_H_1, LOGO_H_N = 7.2, 4.8  # mm — znak w nagłówku strony 1 i dalszych, jak w PDF
GRID = "CCCCCC"
HEAD_FILL = "F1F1F1"


# ---------- pomocnicze ----------

# Kolejność dzieci ze schematu OOXML (Word odrzuca plik z elementami w złej kolejności;
# LibreOffice jest łaskawszy, więc podgląd w nim tego nie pokaże).
_PPR_AFTER_BORDER = (
    "shd",
    "tabs",
    "suppressAutoHyphens",
    "kinsoku",
    "wordWrap",
    "overflowPunct",
    "topLinePunct",
    "autoSpaceDE",
    "autoSpaceDN",
    "bidi",
    "adjustRightInd",
    "snapToGrid",
    "spacing",
    "ind",
    "contextualSpacing",
    "mirrorIndents",
    "suppressOverlap",
    "jc",
    "textDirection",
    "textAlignment",
    "textboxTightWrap",
    "outlineLvl",
    "divId",
    "cnfStyle",
    "rPr",
    "sectPr",
    "pPrChange",
)
_TBLPR_ORDER = (
    "tblStyle",
    "tblpPr",
    "tblOverlap",
    "bidiVisual",
    "tblStyleRowBandSize",
    "tblStyleColBandSize",
    "tblW",
    "jc",
    "tblCellSpacing",
    "tblInd",
    "tblBorders",
    "shd",
    "tblLayout",
    "tblCellMar",
    "tblLook",
    "tblCaption",
    "tblDescription",
)


def _insert_before(parent, child, successors: Iterable[str]) -> None:
    """Wstawia `child` przed pierwszym istniejącym następnikiem ze schematu."""
    tags = {qn(f"w:{name}") for name in successors}
    for i, existing in enumerate(parent):
        if existing.tag in tags:
            parent.insert(i, child)
            return
    parent.append(child)


def _tblpr_set(tblpr, child) -> None:
    name = child.tag.split("}")[1]
    for old in tblpr.findall(child.tag):
        tblpr.remove(old)
    _insert_before(tblpr, child, _TBLPR_ORDER[_TBLPR_ORDER.index(name) + 1 :])


def _hex(value: str) -> str:
    return value.lstrip("#").upper()


def _run(
    paragraph, text: str, *, size: float = SIZE, bold: bool = False, color: str = INK
):
    run = paragraph.add_run(text)
    run.font.name = FONT
    rpr = run._element.get_or_add_rPr()
    fonts = rpr.find(qn("w:rFonts"))
    if fonts is None:
        fonts = OxmlElement("w:rFonts")
        rpr.insert(0, fonts)
    for attr in ("w:ascii", "w:hAnsi", "w:cs", "w:eastAsia"):
        fonts.set(qn(attr), FONT)
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.color.rgb = RGBColor.from_string(_hex(color))
    return run


def _key_runs(paragraph, ctx: Ctx, text: str) -> None:
    """Słowa z rekrutacji pogrubione — te same zakresy co `Keywords.bold` w PDF."""
    pos = 0
    for start, end in ctx.keys.spans(text):
        if start > pos:
            _run(paragraph, text[pos:start])
        _run(paragraph, text[start:end], bold=True)
        pos = end
    if pos < len(text):
        _run(paragraph, text[pos:])


def _spacing(
    paragraph, before: float = 0.0, after: float = 0.0, line_pt: Optional[float] = None
) -> None:
    fmt = paragraph.paragraph_format
    fmt.space_before = Pt(before)
    fmt.space_after = Pt(after)
    if line_pt:
        fmt.line_spacing_rule = WD_LINE_SPACING.EXACTLY
        fmt.line_spacing = Pt(line_pt)


def _border(ppr, side: str, color: str, eighths: int) -> None:
    box = ppr.find(qn("w:pBdr"))
    if box is None:
        box = OxmlElement("w:pBdr")
        _insert_before(ppr, box, _PPR_AFTER_BORDER)
    edge = OxmlElement(f"w:{side}")
    edge.set(qn("w:val"), "single")
    edge.set(qn("w:sz"), str(eighths))
    edge.set(qn("w:space"), "1")
    edge.set(qn("w:color"), _hex(color))
    box.append(edge)


def _shade(cell, color: str) -> None:
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), _hex(color))
    cell._element.get_or_add_tcPr().append(shd)


def _picture(paragraph, png: bytes, width_mm: float) -> None:
    """Obraz w linii bez odstępu od tekstu (LibreOffice bez `dist*` dokłada 3,2 mm)."""
    run = paragraph.add_run()
    run.add_picture(io.BytesIO(png), width=Mm(width_mm))
    inline = run._element.find(".//" + qn("wp:inline"))
    if inline is not None:
        for side in ("distT", "distB", "distL", "distR"):
            inline.set(side, "0")


def _first(cell):
    p = cell.paragraphs[0]
    _spacing(p, line_pt=SIZE * 1.32)
    return p


def _grid_table(document, rows: int, widths: Iterable[float]):
    """Tabela-formularz jak `table.role` w PDF: cienka szara siatka, stałe kolumny."""
    widths = list(widths)
    table = document.add_table(rows=rows, cols=len(widths))
    table.alignment = WD_TABLE_ALIGNMENT.LEFT
    table.autofit = False
    tblpr = table._element.tblPr
    layout = OxmlElement("w:tblLayout")
    layout.set(qn("w:type"), "fixed")
    _tblpr_set(tblpr, layout)
    borders = OxmlElement("w:tblBorders")
    for side in ("top", "left", "bottom", "right", "insideH", "insideV"):
        edge = OxmlElement(f"w:{side}")
        edge.set(qn("w:val"), "single")
        edge.set(qn("w:sz"), "4")
        edge.set(qn("w:color"), GRID)
        borders.append(edge)
    _tblpr_set(tblpr, borders)
    margins = OxmlElement("w:tblCellMar")
    for side, value in (("left", 113), ("right", 113), ("top", 45), ("bottom", 45)):
        edge = OxmlElement(f"w:{side}")
        edge.set(qn("w:w"), str(value))
        edge.set(qn("w:type"), "dxa")
        margins.append(edge)
    _tblpr_set(tblpr, margins)
    for row in table.rows:
        for cell, width in zip(row.cells, widths):
            cell.width = Mm(width)
    for col, width in zip(table._element.tblGrid.findall(qn("w:gridCol")), widths):
        col.set(qn("w:w"), str(int(width / 25.4 * 1440)))
    return table


def _keep_rows_whole(table, head_rows: int = 0) -> None:
    """Wiersz nie łamie się między stronami; nagłówek roli trzyma się następnego wiersza."""
    for i, row in enumerate(table.rows):
        row._tr.get_or_add_trPr().append(OxmlElement("w:cantSplit"))
        if i < head_rows:
            for p in row.cells[1].paragraphs:
                p.paragraph_format.keep_with_next = True


# ---------- strona 1: obraz z PDF ----------


def page1_png(pdf: bytes, dpi: int = 300) -> tuple[bytes, float, float]:
    """Pole treści strony 1 PDF (bez nagłówka i stopki) jako PNG: (bajty, mm, mm)."""
    import pypdfium2

    document = pypdfium2.PdfDocument(pdf)
    try:
        image = document[0].render(scale=dpi / 72).to_pil().convert("RGB")
    finally:
        document.close()
    px = dpi / 25.4
    image = image.crop(
        (
            round(SIDE * px),
            round(PAGE1_TOP * px),
            round((210.0 - SIDE) * px),
            round(PAGE1_BOTTOM * px),
        )
    )
    out = io.BytesIO()
    image.save(out, format="PNG", optimize=True)
    return out.getvalue(), image.width / px, image.height / px


def svg_png(svg: str, width_mm: float, height_mm: float, dpi: int = 300) -> bytes:
    """SVG z repo (znak w nagłówku) jako PNG — WeasyPrint z fetcherem tylko na zasoby repo."""
    import pypdfium2

    from app.services.cv_new_layout.render import html_to_document

    page = (
        "<!doctype html><html><head><meta charset='utf-8'><style>"
        f"@page{{size:{width_mm}mm {height_mm}mm;margin:0}}html,body{{margin:0}}"
        f"svg{{display:block;width:{width_mm}mm;height:{height_mm}mm}}</style></head>"
        f"<body>{svg}</body></html>"
    )
    document = pypdfium2.PdfDocument(html_to_document(page).write_pdf())
    try:
        image = document[0].render(scale=dpi / 72).to_pil()
    finally:
        document.close()
    out = io.BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()


# ---------- od strony 2 ----------


def _heading(document, title: str) -> None:
    """Jak `.rest h2` w PDF: wersaliki w kolorze marki, kreska nad tytułem."""
    p = document.add_paragraph()
    _spacing(p, before=7.4, after=3.1)
    _border(p._p.get_or_add_pPr(), "top", BRAND, 10)
    p.paragraph_format.keep_with_next = True
    run = _run(p, title, size=10.5, bold=True, color=BRAND)
    run.font.all_caps = True


def _role_table(document, ctx: Ctx, r: DatedRole) -> None:
    t, role = ctx.t, r.role
    rows: list[tuple[str, str, object]] = []
    period = role_period(ctx, r)
    if period:
        rows.append((t["period"], "text", period))
    if role.company:
        rows.append((t["company"], "bold", role.company))
    if role.position:
        rows.append((t["position"], "bold", role.position))
    duties = [clean(d) for d in role.responsibilities if clean(d)]
    if duties:  # puste pola znikają, zamiast stać jako pusty wiersz (jak w PDF)
        rows.append((t["tasks"], "list", duties))
    if role.technologies:
        rows.append((t["technologies"], "keys", ", ".join(role.technologies)))
    if not rows:
        return
    table = _grid_table(document, len(rows), (30.0, CONTENT_W - 30.0))
    for i, (label, kind, value) in enumerate(rows):
        head, body = table.rows[i].cells
        _shade(head, HEAD_FILL)
        _run(_first(head), label, bold=True)
        if kind == "text":
            _run(_first(body), value)
        elif kind == "bold":
            _run(_first(body), value, bold=True)
        elif kind == "keys":
            _key_runs(_first(body), ctx, value)
        else:
            for j, duty in enumerate(value):
                p = _first(body) if j == 0 else body.add_paragraph()
                _spacing(p, after=1.7, line_pt=SIZE * 1.32)
                p.paragraph_format.left_indent = Mm(4.0)
                p.paragraph_format.first_line_indent = Mm(-4.0)
                p.paragraph_format.tab_stops.add_tab_stop(Mm(4.0))
                _run(p, "•\t", color=BRAND)
                _key_runs(p, ctx, duty)
    _keep_rows_whole(
        table, head_rows=sum(1 for _, k, _ in rows if k in ("text", "bold"))
    )
    gap = document.add_paragraph()
    _spacing(gap, line_pt=12.8)  # 4,5 mm jak `table.role{margin-bottom}`


def _skills_full(document, ctx: Ctx) -> None:
    rows = [(g.label, skill_items(ctx, g.content)) for g in ctx.doc.skills]
    rows = [(label, items) for label, items in rows if items]
    if not rows:
        return
    table = _grid_table(document, len(rows), (36.0, CONTENT_W - 36.0))
    for i, (label, items) in enumerate(rows):
        head, body = table.rows[i].cells
        _shade(head, HEAD_FILL)
        _run(_first(head), label, bold=True)
        p = _first(body)
        for j, item in enumerate(items):
            if j:
                _run(p, ", ")
            _run(p, item, bold=ctx.keys.is_key(item))
    _keep_rows_whole(table)


def _education_full(document, ctx: Ctx, certs_hidden: int) -> None:
    """Jak `education_full` w PDF: tabela szkół (gdy więcej niż jedna) i — gdy strona 1
    pokazała tylko część — pełna lista certyfikatów."""
    t, schools = ctx.t, ctx.doc.education
    if len(schools) > 1:
        table = _grid_table(document, len(schools) + 1, (36.0, 76.0, CONTENT_W - 112.0))
        for cell, text in zip(
            table.rows[0].cells, (t["dates"], t["school"], t["field_degree"])
        ):
            _shade(cell, "E8E8E8")
            _run(_first(cell), text, size=7.8, bold=True)
        for i, s in enumerate(schools, start=1):
            a, b, c = table.rows[i].cells
            _run(_first(a), s.dates.replace(" - ", " – ") or "—", size=8.3)
            _run(_first(b), s.institution, size=8.3, bold=True)
            _run(_first(c), s.degree, size=8.3)
        _keep_rows_whole(table)
        document.add_paragraph()
    if certs_hidden:
        certs = certs_by_year(ctx.doc.certifications)
        has_year = any(c.year for c in certs)
        widths = (14.0, CONTENT_W - 14.0) if has_year else (CONTENT_W,)
        table = _grid_table(document, len(certs) + 1, widths)
        heads = (t["year"], t["certificate"]) if has_year else (t["certificate"],)
        for cell, text in zip(table.rows[0].cells, heads):
            _run(_first(cell), text, size=7.8, bold=True, color=SOFT)
        for i, c in enumerate(certs, start=1):
            cells = table.rows[i].cells
            if has_year:
                _run(_first(cells[0]), c.year, size=8.3, color=SOFT)
            _run(_first(cells[-1]), c.name, size=8.3)
        _keep_rows_whole(table)


def _consent_and_rodo(document, doc: NewCvDocument) -> None:
    """Zrzut zgody (wymóg PKO BP) i klauzula RODO na końcu, jak w PDF."""
    data = doc.consent_image
    if data and sniff_image_mime(data) in ("image/png", "image/jpeg", "image/gif"):
        h = document.add_paragraph()
        _spacing(h, before=14, after=5.7)
        h.paragraph_format.keep_with_next = True
        _run(h, consent_heading(doc.language), size=8, bold=True, color=SOFT2)
        try:
            _picture(document.add_paragraph(), data, 95.0)
        except Exception:  # noqa: BLE001 — nieczytelny zrzut = CV bez zrzutu (jak w PDF)
            logger.warning("cv_new_docx: zrzut zgody pominięty", exc_info=True)
    clause = doc.rodo_clause_html
    if clause and clause.strip():
        texts = [
            html.unescape(re.sub(r"<[^>]+>", "", part)).strip()
            for part in re.split(r"</p>|<br\s*/?>", clause)
        ]
    else:
        texts = [default_rodo_clause(doc.language)]
    first = True
    for text in texts:
        if not text:
            continue
        p = document.add_paragraph()
        _spacing(p, before=17 if first else 0, after=2.8, line_pt=6.6 * 1.3)
        if first:
            _border(p._p.get_or_add_pPr(), "top", "#D9D4D4", 2)
            first = False
        _run(p, text, size=6.6, color=SOFT2)


# ---------- nagłówek, stopka, całość ----------


def _logo(paragraph, height_mm: float) -> None:
    from app.services.cv_new_layout.assets import LOGO_PATH, LOGO_RATIO

    try:
        width = height_mm * LOGO_RATIO
        png = svg_png(LOGO_PATH.read_text(encoding="utf-8"), width, height_mm)
        _picture(paragraph, png, width)
    except Exception:  # noqa: BLE001 — bez znaku nagłówek jest pusty, CV zostaje
        logger.warning("cv_new_docx: znak w nagłówku pominięty", exc_info=True)


def _footer(paragraph, text: str) -> None:
    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _run(paragraph, text, size=5.6, color=SOFT)


def _page_setup(document, ctx: Ctx) -> None:
    """A4, marginesy z arkusza PDF; na stronie 1 większy znak (inny nagłówek)."""
    section = document.sections[0]
    section.page_width, section.page_height = Mm(210), Mm(297)
    section.left_margin = section.right_margin = Mm(SIDE)
    section.top_margin, section.bottom_margin = Mm(WORD_TOP), Mm(WORD_BOTTOM)
    section.header_distance = Mm(HEAD_1 * 0.28)
    section.footer_distance = Mm(3.0)
    section.different_first_page_header_footer = True
    _logo(section.first_page_header.paragraphs[0], LOGO_H_1)
    _logo(section.header.paragraphs[0], LOGO_H_N)
    _footer(section.first_page_footer.paragraphs[0], ctx.t["footer"])
    _footer(section.footer.paragraphs[0], ctx.t["footer"])


def render_new_cv_docx(
    doc: NewCvDocument,
    pdf: bytes,
    *,
    skill_cap: Optional[int] = None,
    skill_groups: Optional[int] = None,
    today: Optional[date] = None,
) -> bytes:
    """Plik Word „Nowego CV”: strona 1 z PDF `pdf` (ten sam render, co plik PDF),
    od strony 2 tabele. `skill_cap` / `skill_groups` — z `FitReport` tego renderu,
    żeby koniec CV miał dokładnie to, co strona 1 PDF skróciła."""
    from app.services.cv_new_layout.assets import FONTS_DIR
    from app.services.cv_new_layout.docx_fonts import embed_font

    ctx = build_context(doc, today)
    _html, skills_truncated, certs_hidden = page1(ctx, skill_cap, skill_groups)
    document = Document()
    normal = document.styles["Normal"]
    normal.font.name = FONT
    normal.font.size = Pt(SIZE)
    normal.paragraph_format.space_after = Pt(0)
    _page_setup(document, ctx)
    body = document._body._element
    for p in list(body.findall(qn("w:p"))):
        body.remove(p)

    png, width, height = page1_png(pdf)
    room = 297.0 - WORD_TOP - WORD_BOTTOM
    scale = min(1.0, room / height) * PAGE1_FIT
    first = document.add_paragraph()
    _spacing(first)
    _picture(first, png, width * scale)

    t = ctx.t
    rest_start = len(body) - 1  # nowe elementy idą przed sectPr
    if skills_truncated:
        _heading(document, t["skills_full"])
        _skills_full(document, ctx)
    if ctx.roles:
        _heading(document, t["experience"])
        for r in ctx.roles:
            _role_table(document, ctx, r)
    if len(ctx.doc.education) > 1 or certs_hidden:
        _heading(document, t["education_full"])
        _education_full(document, ctx, certs_hidden)
    _consent_and_rodo(document, doc)
    # Reszta zawsze od strony 2 — „podział przed akapitem”, nie pusty akapit z podziałem.
    start = body[rest_start]
    if start.tag == qn("w:p"):
        from docx.text.paragraph import Paragraph

        Paragraph(start, document._body).paragraph_format.page_break_before = True

    embed_font(
        document, FONT, FONTS_DIR / "Poppins-400.ttf", FONTS_DIR / "Poppins-700.ttf"
    )
    props = document.core_properties
    props.title = (
        f"{t['doc_title']} – {doc.position}" if doc.position else t["doc_title"]
    )
    props.author = "B2B.net S.A."
    out = io.BytesIO()
    document.save(out)
    return out.getvalue()
