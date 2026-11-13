"""Edukacja bez dat: tabela bez pustej kolumny „Daty”.

Zgłoszenie 13.11.2026: CV osoby, która nie podała dat studiów, miało
w Edukacji kolumnę „Daty” z pustą komórką. Gdy żaden wiersz nie ma dat,
tabela ma jedną kolumnę „Nazwa uczelni/kierunek” na całą szerokość.
"""

from io import BytesIO

from docx import Document

from app.services.cv_approved_docx import render_approved_docx
from app.services.cv_document_assets import default_template
from app.services.cv_docx_import import docx_to_editor_html
from app.services.cv_generator_b2b.docx_renderer import render_cv_to_bytes
from app.services.html_sanitizer import sanitize_cv_html

SCHOOL = "Uniwersytet Testowy"
DEGREE = "Informatyka · Wrocław"


def _payload(education: list[dict]) -> dict:
    return {
        "name": "Jan Testowy",
        "first_name": "Jan",
        "position": "Analityk",
        "language": "pl",
        "why_points": ["Analiza danych"],
        "education": education,
        "experience": [],
    }


def _generator(education: list[dict]) -> Document:
    docx = render_cv_to_bytes(_payload(education), BytesIO(default_template()))
    return Document(BytesIO(docx))


def _editor(rows: str) -> Document:
    content = (
        '<h1>Analityk – Jan Testowy</h1><hr><h2 data-cv-section="education">EDUKACJA</h2>'
        + rows
    )
    return Document(
        BytesIO(render_approved_docx(sanitize_cv_html(content), default_template()))
    )


def _grid(doc: Document) -> list[list[str]]:
    return [[cell.text for cell in row.cells] for row in doc.tables[0].rows]


def test_generator_without_any_dates_drops_the_dates_column():
    doc = _generator([{"dates": "", "institution": SCHOOL, "degree": DEGREE}])
    assert _grid(doc) == [["Nazwa uczelni/kierunek"], [f"{SCHOOL}\n{DEGREE}"]]


def test_generator_keeps_dates_column_when_one_row_has_dates():
    doc = _generator(
        [
            {"dates": "", "institution": SCHOOL, "degree": DEGREE},
            {"dates": "2015 - 2019", "institution": "Politechnika", "degree": "Fizyka"},
        ]
    )
    assert _grid(doc) == [
        ["Daty", "Nazwa uczelni/kierunek"],
        ["", f"{SCHOOL}\n{DEGREE}"],
        ["2015 - 2019", "Politechnika\nFizyka"],
    ]


def test_generator_tolerates_missing_dates_key():
    doc = _generator([{"institution": SCHOOL, "degree": DEGREE}])
    assert _grid(doc) == [["Nazwa uczelni/kierunek"], [f"{SCHOOL}\n{DEGREE}"]]


def test_editor_without_any_dates_drops_the_dates_column():
    doc = _editor(f"<p><strong>{SCHOOL}</strong> — {DEGREE}</p>")
    assert _grid(doc) == [["Nazwa uczelni/kierunek"], [f"{SCHOOL}\n{DEGREE}"]]


def test_editor_keeps_dates_column_when_a_row_has_dates():
    doc = _editor(
        f"<p><strong>{SCHOOL}</strong> — {DEGREE}</p>"
        "<p>2015 - 2019 <strong>Politechnika</strong> — Fizyka</p>"
    )
    assert _grid(doc) == [
        ["Daty", "Nazwa uczelni/kierunek"],
        ["", f"{SCHOOL}\n{DEGREE}"],
        ["2015 - 2019", "Politechnika\nFizyka"],
    ]


def test_single_column_spans_the_full_table_width():
    doc = _generator([{"dates": "", "institution": SCHOOL, "degree": DEGREE}])
    widths = doc.tables[0]._tbl.xpath("./w:tblGrid/w:gridCol/@w:w")
    assert len(widths) == 1
    two = _generator([{"dates": "2015", "institution": SCHOOL, "degree": DEGREE}])
    two_widths = two.tables[0]._tbl.xpath("./w:tblGrid/w:gridCol/@w:w")
    assert int(widths[0]) == sum(int(w) for w in two_widths)


def test_single_column_table_imports_back_into_the_editor():
    """Plik bez kolumny dat poprawiony w Wordzie i wgrany ponownie
    („Użyj innego CV”): nagłówek nie staje się wierszem, uczelnia zostaje."""
    content = (
        "<h1>Analityk – Jan Testowy</h1><hr>"
        '<h2 data-cv-section="why_points">DLACZEGO NASZ KANDYDAT?</h2>'
        "<ul><li><p>5 lat analizy danych w bankowości</p></li></ul>"
        '<h2 data-cv-section="education">EDUKACJA</h2>'
        f"<p><strong>{SCHOOL}</strong> — {DEGREE}</p>"
        '<h2 data-cv-section="experience">DOŚWIADCZENIE</h2>'
        '<p data-cv-section="role"><strong>Analityk</strong> 02.2019 - 03.2025</p>'
        '<p data-cv-section="employer">Acme</p>'
        '<p data-cv-section="duties_label">Zakres zadań:</p>'
        "<ul><li><p>Raporty sprzedaży</p></li></ul>"
    )
    docx = render_approved_docx(sanitize_cv_html(content), default_template())
    assert _grid(Document(BytesIO(docx)))[0] == ["Nazwa uczelni/kierunek"]
    html = docx_to_editor_html(docx).html
    assert "uczelni" not in html and "Daty" not in html
    assert f"<p><strong>{SCHOOL}</strong> — {DEGREE}</p>" in html
