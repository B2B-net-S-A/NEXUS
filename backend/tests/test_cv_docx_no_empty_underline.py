"""CV z edytora bez jawnego „bez podkreślenia” przy każdym fragmencie tekstu.

Zgłoszenie osoby od Cpro z 10.11.2026: CV pobrane z NEXUSA jest w Wordzie
poprawne, ale w podglądzie Cpro (system klienta) każde zdanie jest
podkreślone. Renderer z edytora ustawiał ``run.underline = False`` przy każdym
fragmencie, a python-docx zapisuje to jako ``<w:u w:val="none"/>``. Word czyta
to jako brak podkreślenia, starsze silniki podglądu (np. mammoth do 1.4.11)
— jako podkreślenie. Plik z generatora tych znaczników nie miał, a kolejka
Cpro bierze CV z edytora od 26.09.2026.
"""

import io
import zipfile

from app.services.cv_approved_docx import render_approved_docx, without_empty_underline
from app.services.cv_document_assets import default_template
from app.services.html_sanitizer import sanitize_cv_html

from tests.test_cv_approved_docx_layout import _editor_html


def _document_xml(docx: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(docx)) as archive:
        return archive.read("word/document.xml").decode("utf-8")


def _render(html_: str) -> bytes:
    return render_approved_docx(sanitize_cv_html(html_), default_template())


def test_editor_cv_has_no_explicit_off_underline_italic_or_strike():
    xml = _document_xml(_render(_editor_html()))
    assert 'w:u w:val="none"' not in xml
    assert '<w:i w:val="0"/>' not in xml
    assert '<w:strike w:val="0"/>' not in xml


def test_intended_underline_and_italic_stay():
    xml = _document_xml(
        _render(
            '<h2 data-cv-section="why_points">DLACZEGO NASZ KANDYDAT?</h2>'
            "<ul><li><p>Zna <u>Kafka</u> i <em>Spark</em></p></li></ul>"
        )
    )
    assert xml.count('<w:u w:val="single"/>') == 1
    assert xml.count("<w:i/>") == 1


def _docx_with(document_xml: str) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("word/document.xml", document_xml)
        archive.writestr("word/header1.xml", '<w:hdr><w:u w:val="none"/></w:hdr>')
    return out.getvalue()


def test_frozen_file_loses_only_the_empty_underline_in_the_body():
    # Zatwierdzone wersje są zamrożonymi bajtami sprzed poprawki; przy wydaniu
    # znika tylko „bez podkreślenia” w treści, reszta archiwum zostaje.
    body = (
        '<w:document><w:r><w:rPr><w:b/><w:u w:val="none"/></w:rPr><w:t>A</w:t></w:r>'
        '<w:r><w:rPr><w:u w:val="single"/></w:rPr><w:t>B</w:t></w:r></w:document>'
    )
    cleaned = without_empty_underline(_docx_with(body))
    xml = _document_xml(cleaned)
    assert 'w:val="none"' not in xml
    assert '<w:u w:val="single"/>' in xml and "<w:b/>" in xml
    with zipfile.ZipFile(io.BytesIO(cleaned)) as archive:
        assert archive.read("word/header1.xml") == b'<w:hdr><w:u w:val="none"/></w:hdr>'


def test_file_without_empty_underline_comes_back_unchanged():
    docx = _render("<p>Tekst</p>")
    assert without_empty_underline(docx) is docx


def test_bytes_that_are_not_a_word_file_come_back_unchanged():
    assert without_empty_underline(b"PK") == b"PK"


def _legacy(docx: bytes) -> bytes:
    """Ten sam plik jak z renderera sprzed approved-html-4: „none” przy tekście."""
    source = zipfile.ZipFile(io.BytesIO(docx))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as target:
        for item in source.infolist():
            data = source.read(item)
            if item.filename == "word/document.xml":
                data = data.replace(
                    b"<w:t", b'<w:rPr><w:u w:val="none"/></w:rPr><w:t', 1
                )
            target.writestr(item, data)
    return out.getvalue()


async def test_approved_version_from_before_the_fix_downloads_without_it(monkeypatch):
    from unittest.mock import AsyncMock

    from app.api import candidate_stage_cv as api
    from app.models.cv_document_version import CvDocumentVersion
    from app.schemas.candidate_stage_cv import CVBrandedFinalize
    from app.services import cv_approval_review
    from tests.test_cv_document_versions_unit import context

    monkeypatch.setattr(
        cv_approval_review,
        "review_for_approval",
        AsyncMock(return_value={"status": "verified"}),
    )
    csv, db, user, _, _ = context(monkeypatch)
    await api.finalize_branded_cv(
        2,
        CVBrandedFinalize(expected_revision=5, content_html="<p>Python</p>"),
        user,
        db,
    )
    version = next(
        c.args[0]
        for c in db.add.call_args_list
        if isinstance(c.args[0], CvDocumentVersion)
    )
    frozen = _legacy(version.docx_content)
    assert 'w:u w:val="none"' in _document_xml(frozen)
    version.docx_content = frozen
    db.scalar.return_value = version

    response = await api.download_approved_docx(2, 1, user, db)

    assert 'w:u w:val="none"' not in _document_xml(response.body)
    assert "etag" not in response.headers
    assert version.docx_content is frozen
