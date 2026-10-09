"""Plik Word z profilu kandydata → HTML edytora CV firmowego (bez bazy, bez AI).

Screening, 09.10.2026: rekruter wybiera gotowe CV z profilu i edytuje je.
34 z 50 osób w screeningu ma takie CV jako plik Word „…B2B…”, a edytor
przyjmował tylko CV z generatora. Testy pilnują dwóch rzeczy: tekst pliku
nigdy nie ginie, a plik w układzie szablonu firmowego wraca po zapisie
z edytora do tego samego układu.
"""

from __future__ import annotations

import copy
import re
from io import BytesIO

import pytest
from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from lxml import html as lxml_html

from app.services.cv_approved_docx import render_approved_docx
from app.services.cv_document_assets import default_template
from app.services.cv_docx_import import (
    MAX_BYTES,
    CvImportError,
    docx_to_editor_html,
)
from app.services.cv_generator_b2b.docx_renderer import TRANSLATIONS
from app.services.html_sanitizer import sanitize_cv_html

RODO = "Wyrażam zgodę na przetwarzanie moich danych osobowych w tej rekrutacji."

FIRM_HTML = (
    "<h1>Tester QA – Anna Testowa</h1>"
    '<h2 data-cv-section="why_points">DLACZEGO NASZ KANDYDAT?</h2>'
    "<ul><li>5 lat w <strong>Python</strong></li><li>Automatyzacja testów</li></ul>"
    '<h2 data-cv-section="education">EDUKACJA</h2>'
    "<p>2015 - 2019 <strong>Politechnika Testowa</strong> — Informatyka · Wrocław</p>"
    '<h2 data-cv-section="skills">UMIEJĘTNOŚCI</h2>'
    "<p><strong>Języki: </strong>Python, SQL</p>"
    '<h2 data-cv-section="languages">JĘZYKI</h2><p>Polski - C2 · Angielski - B2</p>'
    '<h2 data-cv-section="experience">DOŚWIADCZENIE</h2>'
    '<p data-cv-section="role"><strong>Senior QA Engineer</strong> 12.2025 - obecnie</p>'
    '<p data-cv-section="employer">Acme · Technologie</p>'
    '<p data-cv-section="duties_label">Zakres zadań:</p>'
    "<ul><li>Rozwój testów w <strong>Python</strong></li><li>Utrzymanie CI</li></ul>"
    '<p data-cv-section="technologies">Technologie: <strong>Python</strong>, Jenkins</p>'
    '<p data-cv-section="role"><strong>QA Engineer</strong> 02.2023 - 11.2025</p>'
    '<p data-cv-section="employer">Beta</p>'
    '<p data-cv-section="duties_label">Zakres zadań:</p>'
    "<ul><li>Automatyzacja testów API</li></ul>"
    f'<p class="rodo">{RODO}</p>'
)


def _firm_docx() -> bytes:
    """Plik w układzie szablonu firmowego — taki, jaki dostaje klient."""
    return render_approved_docx(
        sanitize_cv_html(FIRM_HTML), default_template(), consent=None, language="pl"
    )


def _texts(data: bytes) -> list[str]:
    doc = Document(BytesIO(data))
    out = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
    for table in doc.tables:
        for row in table.rows:
            out.append(" | ".join(cell.text.strip() for cell in row.cells))
    return out


def _plain(html: str) -> str:
    return re.sub(r"\s+", " ", lxml_html.fromstring(html).text_content())


def _save(doc) -> bytes:
    out = BytesIO()
    doc.save(out)
    return out.getvalue()


def _hand_made_docx() -> bytes:
    """CV pisane ręcznie w Wordzie: inne etykiety niż szablon, tabela, lista."""
    doc = Document()
    doc.add_paragraph("Jan Fikcyjny")
    doc.add_heading("PROFILE", level=1)
    paragraph = doc.add_paragraph()
    paragraph.add_run("Senior engineer with ")
    paragraph.add_run("Kubernetes").bold = True
    paragraph.add_run(" and <b>cloud</b> background, ten years in delivery teams.")
    doc.add_heading("EXPERIENCE", level=1)
    doc.add_paragraph("ACME BANK")
    doc.add_paragraph("Platform Engineer, 2019 - 2024")
    doc.add_paragraph("Built the deployment platform", style="List Bullet")
    doc.add_paragraph("Ran the on-call rotation", style="List Bullet")
    table = doc.add_table(rows=1, cols=2)
    table.rows[0].cells[0].text = "2010 - 2014"
    table.rows[0].cells[1].text = "Example University"
    doc.add_paragraph(
        "Additional notes: open to hybrid work in Warsaw, available from November, "
        "holds a valid security clearance and a driving licence."
    )
    return _save(doc)


def test_firm_layout_survives_word_to_editor_to_word():
    """Plik z szablonu firmowego po wczytaniu i zapisie ma te same akapity."""
    first = _firm_docx()
    imported = docx_to_editor_html(first)
    second = render_approved_docx(
        imported.html, default_template(), consent=None, language=imported.language
    )
    assert _texts(second) == _texts(first)
    assert imported.language == "pl"


def test_firm_layout_comes_back_in_the_generator_shape():
    imported = docx_to_editor_html(_firm_docx())
    html = imported.html
    assert html.startswith('<article class="cv"><h1>Tester QA – Anna Testowa</h1>')
    for key in ("why_points", "education", "skills", "languages", "experience"):
        assert f'<h2 data-cv-section="{key}">' in html
    assert (
        '<p data-cv-section="role"><strong>Senior QA Engineer</strong> '
        "12.2025 - obecnie</p>"
        '<p data-cv-section="employer">Acme · Technologie</p>'
        '<p data-cv-section="duties_label">Zakres zadań:</p>'
        "<ul><li>Rozwój testów w <strong>Python</strong></li>"
    ) in html
    # Etykiety układu („Nazwa firmy:”, „Stanowisko:”) dokłada renderer — w
    # edytorze ich nie ma, jak w CV z generatora.
    assert "Nazwa firmy" not in html and "Stanowisko:" not in html
    assert (
        '<p data-cv-section="technologies">Technologie: <strong>Python</strong>, '
        "Jenkins</p>"
    ) in html
    assert (
        "<p>2015 - 2019 <strong>Politechnika Testowa</strong> — Informatyka · "
        "Wrocław</p>"
    ) in html
    # Nagłówek tabeli edukacji nie staje się wierszem.
    assert TRANSLATIONS["pl"]["education_header"] not in html
    assert imported.stats["roles"] == 2 and imported.stats["sections"] == 5


def test_consent_clause_is_read_from_the_pinned_text_box_once():
    imported = docx_to_editor_html(_firm_docx())
    assert imported.html.count('class="rodo"') == 1
    assert f'<p class="rodo">{RODO}</p>' in imported.html


def test_hand_made_file_keeps_every_paragraph_in_order():
    imported = docx_to_editor_html(_hand_made_docx())
    text = _plain(imported.html)
    expected = [
        "Jan Fikcyjny",
        "PROFILE",
        "Senior engineer with Kubernetes and <b>cloud</b> background",
        "EXPERIENCE",
        "ACME BANK",
        "Platform Engineer, 2019 - 2024",
        "Built the deployment platform",
        "Ran the on-call rotation",
        "2010 - 2014 Example University",
        "Additional notes: open to hybrid work in Warsaw",
    ]
    positions = [text.find(item) for item in expected]
    assert all(position >= 0 for position in positions), positions
    assert positions == sorted(positions)


def test_hand_made_file_keeps_structure_without_guessing_roles():
    imported = docx_to_editor_html(_hand_made_docx())
    html = imported.html
    assert "<h1>Jan Fikcyjny</h1>" in html
    assert "<strong>Kubernetes</strong>" in html
    # Tekst pliku nie staje się znacznikiem HTML.
    assert "&lt;b&gt;cloud&lt;/b&gt;" in html
    assert '<h2 data-cv-section="experience">EXPERIENCE</h2>' in html
    # Nazwa firmy wielkimi literami nie zamyka sekcji doświadczenia.
    assert "<h3>ACME BANK</h3>" in html
    assert "<h3>PROFILE</h3>" in html
    assert (
        "<ul><li>Built the deployment platform</li>"
        "<li>Ran the on-call rotation</li></ul>"
    ) in html
    assert 'data-cv-section="role"' not in html
    assert imported.stats["roles"] == 0
    assert imported.language == "en"


def test_missing_consent_clause_gets_the_standard_one_in_the_file_language():
    imported = docx_to_editor_html(_hand_made_docx())
    clause = TRANSLATIONS["en"]["rodo"]
    assert imported.html.count('class="rodo"') == 1
    assert clause[:60] in _plain(imported.html)


def test_text_in_links_and_form_fields_is_not_lost():
    doc = Document()
    doc.add_paragraph("Maria Przykładowa")
    linked = doc.add_paragraph("Portfolio: ")
    hyperlink = OxmlElement("w:hyperlink")
    run = OxmlElement("w:r")
    text = OxmlElement("w:t")
    text.text = "projekty na GitHubie"
    run.append(text)
    hyperlink.append(run)
    linked._p.append(hyperlink)
    wrapped = doc.add_paragraph(
        "Akapit w polu formularza Worda — dziesięć lat pracy w zespołach wdrożeniowych, "
        "głównie w bankowości i telekomunikacji, ostatnio jako lider zespołu."
    )
    control = OxmlElement("w:sdt")
    content = OxmlElement("w:sdtContent")
    control.append(content)
    wrapped._p.addprevious(control)
    content.append(wrapped._p)
    doc.add_paragraph("Dodatkowy opis doświadczenia i kompetencji kandydatki. " * 3)
    imported = docx_to_editor_html(_save(doc))
    text_out = _plain(imported.html)
    assert "Portfolio: projekty na GitHubie" in text_out
    assert "Akapit w polu formularza Worda" in text_out


def test_text_box_content_does_not_leak_into_the_paragraph_it_is_anchored_in():
    data = _firm_docx()
    doc = Document(BytesIO(data))
    boxes = [
        element
        for element in doc.element.body.iter()
        if str(element.tag).endswith("}txbxContent")
    ]
    assert boxes, "szablon firmowy trzyma klauzulę zgody w polu tekstowym"
    imported = docx_to_editor_html(data)
    # Klauzula jest raz — jako klauzula, nie jako zwykły akapit treści.
    assert _plain(imported.html).count(RODO) == 1


@pytest.mark.parametrize(
    ("data", "fragment"),
    [
        (b"%PDF-1.7 fake pdf bytes", "tylko plik Word"),
        (b"PK\x03\x04 not really a zip", "Nie udało się odczytać"),
        (b"PK" + b"0" * (MAX_BYTES + 1), "za duży"),
    ],
)
def test_files_that_cannot_be_read_are_refused_in_polish(data, fragment):
    with pytest.raises(CvImportError) as error:
        docx_to_editor_html(data)
    assert fragment in str(error.value)


def test_empty_document_is_refused():
    doc = Document()
    doc.add_paragraph("CV")
    with pytest.raises(CvImportError) as error:
        docx_to_editor_html(_save(doc))
    assert "nie ma tekstu" in str(error.value)


def test_role_block_without_position_stays_as_typed():
    """Daty i „Nazwa firmy:” bez stanowiska nie znikają ani nie udają roli."""
    doc = Document(BytesIO(_firm_docx()))
    body = doc.element.body
    target = next(p for p in doc.paragraphs if p.text.startswith("Stanowisko:"))
    filler = copy.deepcopy(target._p)
    for node in filler.iter(qn("w:t")):
        node.text = ""
    body.replace(target._p, filler)
    imported = docx_to_editor_html(_save(doc))
    text = _plain(imported.html)
    assert "12.2025 - obecnie" in text
    assert "Nazwa firmy: Acme · Technologie" in text
    assert imported.stats["roles"] == 1
