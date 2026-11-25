"""Word „Nowego CV” (wariant B, decyzja Artura z 25.11.2026): strona 1 to obraz
strony 1 PDF, od strony 2 tabele z osadzonym Poppinsem, ramka panelu na końcu.

Render potrzebuje WeasyPrint (strona 1 z PDF) — bez bibliotek natywnych plik
jest pomijany, jak `test_cv_new_layout_pdf.py`.
"""

from __future__ import annotations

import io

import pytest

try:
    import weasyprint  # noqa: F401
except (ImportError, OSError) as exc:  # brak libpango kończy import OSError
    pytest.skip(f"WeasyPrint niedostępny: {exc}", allow_module_level=True)

from docx import Document
from docx.oxml.ns import qn

from app.services.cv_new_layout import NewCvDocument, render_new_cv_pdf_with_report
from app.services.cv_new_layout.docx_fonts import OBFUSCATED_FONT, obfuscate
from app.services.cv_new_layout.docx_render import (
    PAGE1_BOTTOM,
    PAGE1_TOP,
    page1_png,
    render_new_cv_docx,
)
from app.services.cv_new_layout.labels import LABELS
from tests._cv_new_layout_fixtures import TODAY, english, huge_cv, long_cv, tiny_png

# Kolejność dzieci `w:pPr` i `w:tblPr` ze schematu OOXML (Word odrzuca inną).
PPR_ORDER = (
    "pStyle", "keepNext", "keepLines", "pageBreakBefore", "framePr", "widowControl",
    "numPr", "suppressLineNumbers", "pBdr", "shd", "tabs", "suppressAutoHyphens",
    "kinsoku", "wordWrap", "overflowPunct", "topLinePunct", "autoSpaceDE",
    "autoSpaceDN", "bidi", "adjustRightInd", "snapToGrid", "spacing", "ind",
    "contextualSpacing", "mirrorIndents", "suppressOverlap", "jc", "textDirection",
    "textAlignment", "textboxTightWrap", "outlineLvl", "divId", "cnfStyle", "rPr",
    "sectPr", "pPrChange",
)  # fmt: skip
TBLPR_ORDER = (
    "tblStyle", "tblpPr", "tblOverlap", "bidiVisual", "tblStyleRowBandSize",
    "tblStyleColBandSize", "tblW", "jc", "tblCellSpacing", "tblInd", "tblBorders",
    "shd", "tblLayout", "tblCellMar", "tblLook", "tblCaption", "tblDescription",
)  # fmt: skip


def _word(data: dict, **kw) -> tuple[bytes, NewCvDocument, object]:
    doc = NewCvDocument.from_cv_json(data, **kw)
    pdf, report = render_new_cv_pdf_with_report(doc, today=TODAY)
    docx = render_new_cv_docx(
        doc,
        pdf,
        skill_cap=report.skill_cap,
        skill_groups=report.skill_groups,
        today=TODAY,
    )
    return docx, doc, report


@pytest.fixture(scope="module")
def long_word():
    return _word(long_cv(), consent_image=tiny_png())


def _local(tag: str) -> str:
    return tag.split("}")[1]


def _text(document) -> str:
    parts = [p.text for p in document.paragraphs]
    for table in document.tables:
        for row in table.rows:
            parts.extend(c.text for c in row.cells)
    return "\n".join(parts)


def test_page_one_is_the_pdf_image_and_the_rest_starts_on_page_two(long_word):
    docx, doc, _report = long_word
    document = Document(io.BytesIO(docx))
    body = list(document.element.body)
    first = body[0]
    assert first.findall(".//" + qn("w:drawing")), "strona 1 to obraz"
    assert not "".join(t.text or "" for t in first.iter(qn("w:t"))).strip()
    nxt = body[1]
    assert nxt.tag == qn("w:p")
    assert nxt.find(qn("w:pPr")).find(qn("w:pageBreakBefore")) is not None
    # Bez pustego akapitu z podziałem: przy dłuższej stronie 1 dałby pustą stronę.
    assert not document.element.body.findall(".//" + qn("w:br"))


def test_roles_are_editable_tables_with_pdf_labels(long_word):
    docx, doc, _report = long_word
    document = Document(io.BytesIO(docx))
    labels = LABELS["pl"]
    role_tables = [
        t for t in document.tables if t.rows[0].cells[0].text == labels["period"]
    ]
    assert len(role_tables) == len(doc.experience)
    text = _text(document)
    assert doc.experience[0].company in text
    assert labels["tasks"] in text and labels["technologies"] in text
    assert labels["experience"].upper() in text.upper()


def test_consent_and_rodo_clause_close_the_file(long_word):
    docx, _doc, _report = long_word
    document = Document(io.BytesIO(docx))
    pictures = document.element.body.findall(".//" + qn("w:drawing"))
    assert len(pictures) == 2  # strona 1 i zrzut zgody
    last = [p.text for p in document.paragraphs if p.text.strip()][-1]
    assert "RODO" in last or "danych osobowych" in last or "personal data" in last


def test_what_page_one_shortened_goes_to_the_end_as_in_pdf():
    docx, _doc, report = _word(huge_cv())
    assert report.skill_cap or report.skill_groups
    text = _text(Document(io.BytesIO(docx)))
    assert LABELS["pl"]["skills_full"].upper() in text.upper()


def test_english_cv_uses_english_labels():
    docx, _doc, _report = _word(english(long_cv()))
    text = _text(Document(io.BytesIO(docx)))
    assert LABELS["en"]["tasks"] in text
    assert LABELS["pl"]["tasks"] not in text


def test_poppins_is_embedded_and_deobfuscates_to_a_truetype_font(long_word):
    docx, _doc, _report = long_word
    document = Document(io.BytesIO(docx))
    fonts = [
        p
        for p in document.part.package.iter_parts()
        if p.content_type == OBFUSCATED_FONT
    ]
    assert len(fonts) == 2
    table = next(
        rel.target_part
        for rel in document.part.rels.values()
        if rel.reltype.endswith("/fontTable")
    )
    from docx.oxml import parse_xml

    xml = parse_xml(table.blob)
    poppins = next(
        f for f in xml.findall(qn("w:font")) if f.get(qn("w:name")) == "Poppins"
    )
    for tag in ("w:embedRegular", "w:embedBold"):
        embed = poppins.find(qn(tag))
        part = table.related_parts[embed.get(qn("r:id"))]
        font = obfuscate(part.blob, embed.get(qn("w:fontKey")))
        assert font[:4] == b"\x00\x01\x00\x00", tag
    settings = [_local(c.tag) for c in document.settings.element]
    assert "embedTrueTypeFonts" in settings
    if "zoom" in settings:
        assert settings.index("zoom") < settings.index("embedTrueTypeFonts")


def test_paragraph_and_table_properties_follow_the_schema_order(long_word):
    docx, _doc, _report = long_word
    document = Document(io.BytesIO(docx))
    for ppr in document.element.body.iter(qn("w:pPr")):
        tags = [_local(c.tag) for c in ppr]
        known = [PPR_ORDER.index(t) for t in tags if t in PPR_ORDER]
        assert known == sorted(known), tags
    for tblpr in document.element.body.iter(qn("w:tblPr")):
        tags = [_local(c.tag) for c in tblpr]
        known = [TBLPR_ORDER.index(t) for t in tags if t in TBLPR_ORDER]
        assert known == sorted(known), tags


def test_page_one_image_is_the_pdf_content_area():
    doc = NewCvDocument.from_cv_json(long_cv())
    pdf, _report = render_new_cv_pdf_with_report(doc, today=TODAY)
    _png, width, height = page1_png(pdf)
    assert width == pytest.approx(180.0, abs=0.2)
    assert height == pytest.approx(PAGE1_BOTTOM - PAGE1_TOP, abs=0.2)


def test_panel_frame_goes_to_the_end_of_the_new_word(long_word):
    from app.services.client_panel_stamp import stamp_panel_link

    docx, _doc, _report = long_word
    url = "https://nexus.example.test/p/abc"
    stamped = Document(
        io.BytesIO(
            stamp_panel_link(docx, url, "nexus.example.test/p/abc", None, at_end=True)
        )
    )
    body = list(stamped.element.body)
    assert body[0].findall(".//" + qn("w:drawing")), "strona 1 bez zmian"
    assert url in stamped.tables[-1].rows[0].cells[1].text
