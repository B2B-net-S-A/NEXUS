"""Unit tests for CV text extractor.

Verifies dispatch by file extension, graceful handling of unsupported formats,
and whitespace normalization. Heavy-lift libraries (pdfminer, python-docx) are
mocked — we test our dispatch logic, not third-party correctness.
"""

from __future__ import annotations

import os
import tempfile

import pytest


def test_extract_text_dispatches_to_pdfminer_for_pdf(monkeypatch):
    from app.services import cv_text_extractor as cte

    called_with: dict[str, str] = {}

    def _fake_pdf_extract(path: str) -> str:
        called_with["path"] = path
        return "Senior Python Developer\n\nExperience: 10 years."

    monkeypatch.setattr(cte, "_extract_pdf", _fake_pdf_extract)
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        path = f.name
    try:
        out = cte.extract_text(path, "resume.pdf")
        assert "Senior Python Developer" in out
        assert "10 years" in out
        assert called_with["path"] == path
    finally:
        os.unlink(path)


def test_extract_text_dispatches_to_docx_for_docx(monkeypatch):
    from app.services import cv_text_extractor as cte

    monkeypatch.setattr(cte, "_extract_docx", lambda _p: "Jan Kowalski\nLead Engineer")
    with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as f:
        path = f.name
    try:
        out = cte.extract_text(path, "cv.docx")
        assert "Jan Kowalski" in out
        assert "Lead Engineer" in out
    finally:
        os.unlink(path)


def test_extract_text_dispatches_to_docx_for_doc(monkeypatch):
    """Legacy .doc uses same python-docx path (best-effort)."""
    from app.services import cv_text_extractor as cte

    monkeypatch.setattr(cte, "_extract_docx", lambda _p: "content")
    with tempfile.NamedTemporaryFile(suffix=".doc", delete=False) as f:
        path = f.name
    try:
        out = cte.extract_text(path, "cv.doc")
        assert out == "content"
    finally:
        os.unlink(path)


def test_extract_text_txt_reads_raw_content():
    from app.services import cv_text_extractor as cte

    content = "Marek Nowak\n\nSenior Backend Developer\n\n5 years Python."
    with tempfile.NamedTemporaryFile(
        suffix=".txt", delete=False, mode="w", encoding="utf-8"
    ) as f:
        f.write(content)
        path = f.name
    try:
        out = cte.extract_text(path, "cv.txt")
        assert "Marek Nowak" in out
        assert "5 years Python" in out
    finally:
        os.unlink(path)


def test_extract_text_unsupported_extension_raises():
    from app.services import cv_text_extractor as cte

    with tempfile.NamedTemporaryFile(suffix=".rtf", delete=False) as f:
        path = f.name
    try:
        with pytest.raises(cte.UnsupportedCvFormat):
            cte.extract_text(path, "cv.rtf")
    finally:
        os.unlink(path)


def test_extract_text_case_insensitive_extension(monkeypatch):
    """Real-world uploads often have .PDF or .DOCX uppercase."""
    from app.services import cv_text_extractor as cte

    monkeypatch.setattr(cte, "_extract_pdf", lambda _p: "pdf content")
    with tempfile.NamedTemporaryFile(suffix=".PDF", delete=False) as f:
        path = f.name
    try:
        out = cte.extract_text(path, "CV.PDF")
        assert out == "pdf content"
    finally:
        os.unlink(path)


def test_extract_text_normalizes_whitespace(monkeypatch):
    from app.services import cv_text_extractor as cte

    noisy = "   \n\n\n  Hello   world  \n\n\n  Second   line \t\t end  \n\n"
    monkeypatch.setattr(cte, "_extract_pdf", lambda _p: noisy)
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        path = f.name
    try:
        out = cte.extract_text(path, "cv.pdf")
        # no leading/trailing whitespace
        assert out == out.strip()
        # single-newline runs preserved, not triple-blank runs
        assert "\n\n\n" not in out
        # collapsed horizontal whitespace
        assert "Hello world" in out
        assert "Second line end" in out
    finally:
        os.unlink(path)


def test_extract_text_extractor_returning_none_yields_empty(monkeypatch):
    """If pdfminer returns None (corrupt PDF edge case), graceful empty string."""
    from app.services import cv_text_extractor as cte

    monkeypatch.setattr(cte, "_extract_pdf", lambda _p: None)
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        path = f.name
    try:
        out = cte.extract_text(path, "cv.pdf")
        assert out == ""
    finally:
        os.unlink(path)


def test_extract_text_filename_dispatch_fallback(monkeypatch):
    """When file has no extension on disk, fall back to filename extension."""
    from app.services import cv_text_extractor as cte

    monkeypatch.setattr(cte, "_extract_pdf", lambda _p: "ok")
    with tempfile.NamedTemporaryFile(delete=False) as f:
        path = f.name  # no suffix
    try:
        out = cte.extract_text(path, "resume.pdf")
        assert out == "ok"
    finally:
        os.unlink(path)


def test_normalize_drops_nul_bytes():
    """Postgres odrzuca 0x00 w tekście; ekstraktor ma go wyciąć zanim trafi do DB."""
    from app.services.cv_text_extractor import _normalize

    assert _normalize("Jan\x00 Kowalski\x00\n\x00Python") == "Jan Kowalski\nPython"


# ── Format from the bytes, not the name (2026-09-22) ─────────────────────────


def _write(suffix: str, data: bytes) -> str:
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
        f.write(data)
        return f.name


def test_pdf_saved_as_docx_is_read_as_pdf(monkeypatch):
    from app.services import cv_text_extractor as cte

    monkeypatch.setattr(cte, "_extract_pdf", lambda _p: "PDF text")
    monkeypatch.setattr(cte, "_extract_docx", lambda _p: "docx text")
    path = _write(".docx", b"%PDF-1.7\n...")
    try:
        assert cte.extract_text(path, "CV Jan.docx") == "PDF text"
    finally:
        os.unlink(path)


def test_pdf_saved_as_odt_is_read_instead_of_rejected(monkeypatch):
    from app.services import cv_text_extractor as cte

    monkeypatch.setattr(cte, "_extract_pdf", lambda _p: "PDF text")
    path = _write(".odt", b"%PDF-1.4\n...")
    try:
        assert cte.extract_text(path, "cv.odt") == "PDF text"
    finally:
        os.unlink(path)


def test_real_docx_and_unknown_bytes_keep_the_declared_format(monkeypatch):
    import io
    import zipfile

    from app.services import cv_text_extractor as cte

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("word/document.xml", "<w:document/>")
    docx = _write(".docx", buf.getvalue())
    txt = _write(".txt", b"plain text CV")
    try:
        assert cte.sniff_extension(docx) == ".docx"
        assert cte.sniff_extension(txt) is None
        assert cte.extract_text(txt, "cv.txt") == "plain text CV"
    finally:
        os.unlink(docx)
        os.unlink(txt)


def test_zip_that_is_not_word_is_not_called_docx():
    import io
    import zipfile

    from app.services import cv_text_extractor as cte

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("content.xml", "<office/>")
    path = _write(".odt", buf.getvalue())
    try:
        assert cte.sniff_extension(path) is None
    finally:
        os.unlink(path)


# ── ODT ───────────────────────────────────────────────────────────────────────

_ODT_MIME = "application/vnd.oasis.opendocument.text"
_ODT_NS = (
    'xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
    'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" '
    'xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0" '
    'xmlns:draw="urn:oasis:names:tc:opendocument:xmlns:drawing:1.0" '
    'xmlns:svg="urn:oasis:names:tc:opendocument:xmlns:svg-compatible:1.0"'
)


def _odt_bytes(body: str, *, mime: str = _ODT_MIME, prolog: str = "") -> bytes:
    import io
    import zipfile

    content = (
        f"{prolog}<office:document-content {_ODT_NS}><office:body><office:text>"
        f"{body}</office:text></office:body></office:document-content>"
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("mimetype", mime)
        zf.writestr("content.xml", content)
    return buf.getvalue()


def _read_odt(data: bytes, name: str = "cv.odt", suffix: str = ".odt") -> str:
    from app.services import cv_text_extractor as cte

    path = _write(suffix, data)
    try:
        return cte.extract_text(path, name)
    finally:
        os.unlink(path)


def test_odt_text_comes_from_content_xml():
    text = _read_odt(
        _odt_bytes(
            "<text:h>Jan Testowy</text:h>"
            "<text:p>Programista<text:s/>"
            "<text:span>Python</text:span><text:tab/>Łódź<text:line-break/>"
            "od 2020</text:p>"
            "<text:list><text:list-item><text:p>Kubernetes</text:p>"
            "</text:list-item></text:list>"
            "<table:table><table:table-row><table:table-cell>"
            "<text:p>Firma Przykładowa</text:p>"
            "</table:table-cell></table:table-row></table:table>"
        )
    )
    assert text.splitlines() == [
        "Jan Testowy",
        "Programista Python Łódź",
        "od 2020",
        "Kubernetes",
        "Firma Przykładowa",
    ]


def test_odt_reads_text_boxes_and_keeps_words_apart():
    text = _read_odt(
        _odt_bytes(
            "<text:p>przed<draw:frame><svg:title>opis obrazka</svg:title>"
            "<draw:text-box><text:p>w ramce</text:p></draw:text-box></draw:frame>"
            "po</text:p>"
        )
    )
    assert text.splitlines() == ["przed", "w ramce", "po"]


def test_odt_skips_what_is_not_visible_in_the_document():
    """Usunięty tekst ze śledzenia zmian i komentarze nie są treścią CV."""
    text = _read_odt(
        _odt_bytes(
            "<text:tracked-changes><text:changed-region><text:deletion>"
            "<text:p>usunięte</text:p></text:deletion></text:changed-region>"
            "</text:tracked-changes>"
            "<text:p>widoczne<office:annotation><text:p>komentarz</text:p>"
            "</office:annotation> dalej</text:p>"
        )
    )
    assert text == "widoczne dalej"


def test_odt_without_mimetype_is_read_by_its_name():
    import io
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(
            "content.xml",
            f"<office:document-content {_ODT_NS}><office:body><office:text>"
            "<text:p>Tekst CV</text:p></office:text></office:body>"
            "</office:document-content>",
        )
    assert _read_odt(buf.getvalue()) == "Tekst CV"


def test_odt_saved_under_another_name_is_read_from_its_bytes():
    from app.services import cv_text_extractor as cte

    data = _odt_bytes("<text:p>Tekst CV</text:p>")
    assert cte.sniff_extension_bytes(data) == ".odt"
    path = _write(".docx", data)
    try:
        assert cte.sniff_extension(path) == ".odt"
        assert cte.extract_text(path, "cv.docx") == "Tekst CV"
    finally:
        os.unlink(path)


def test_other_opendocument_formats_are_not_odt():
    from app.services import cv_text_extractor as cte

    data = _odt_bytes(
        "<text:p>arkusz</text:p>",
        mime="application/vnd.oasis.opendocument.spreadsheet",
    )
    assert cte.sniff_extension_bytes(data) is None


def test_odt_runs_in_the_worker_process(monkeypatch):
    from app.services import cv_text_extractor as cte

    calls: list[str] = []

    def _fake_worker(op, _path, **_kwargs):
        calls.append(op)
        return None

    monkeypatch.setattr(cte, "_run_pdf_worker", _fake_worker)
    assert _read_odt(_odt_bytes("<text:p>Tekst CV</text:p>")) == ""
    assert calls == ["odt"]


def test_odt_over_the_unpacked_limit_is_not_parsed(monkeypatch):
    """Plik ma kilkanaście KB, a `content.xml` rozwija się ponad limit."""
    from app.services import cv_text_extractor as cte
    from app.core.zip_guard import MAX_XML_PART_UNCOMPRESSED

    data = _odt_bytes("<text:p>" + "a" * (MAX_XML_PART_UNCOMPRESSED + 1) + "</text:p>")
    assert len(data) < 100 * 1024
    assert _read_odt(data) == ""

    def _no_parse(*_args, **_kwargs):
        raise AssertionError("content.xml nie powinien dojść do parsera")

    monkeypatch.setattr(cte, "_odf_parse", _no_parse)
    path = _write(".odt", data)
    try:
        assert cte._worker_odt(path) is None
    finally:
        os.unlink(path)


def test_odt_entities_are_not_expanded(tmp_path):
    """Ani „miliard śmiechów”, ani odczyt pliku z dysku przez encję zewnętrzną."""
    secret = tmp_path / "sekret.txt"
    secret.write_text("TAJNE", encoding="utf-8")
    laughs = "".join(f'<!ENTITY lol{i} "{f"&lol{i - 1};" * 10}">' for i in range(1, 10))
    prolog = (
        '<?xml version="1.0"?><!DOCTYPE office:document-content ['
        f'<!ENTITY lol0 "lol">{laughs}'
        f'<!ENTITY plik SYSTEM "file://{secret}">]>'
    )
    text = _read_odt(
        _odt_bytes("<text:p>start&lol9;&plik;koniec</text:p>", prolog=prolog)
    )
    assert "TAJNE" not in text
    assert "lol" not in text


def test_broken_odt_gives_empty_text_not_an_exception():
    assert _read_odt(_odt_bytes("<text:p>bez domknięcia")) == ""
    assert _read_odt(b"PK\x03\x04 to nie jest archiwum") == ""


def test_backfill_keeps_the_odt_suffix_of_the_temp_file():
    from app.services.cv_text_backfill import _extension_of

    assert _extension_of("cv.ODT", "stage-cv/1/abc") == ".odt"


# ── Sklejony tekst (słowa bez przerw) ─────────────────────────────────────────

_GLUED = "ledtheqainitiativeandthedevelopmentofunittestingtoolforcobolprograms " * 8
_SPACED = "led the qa initiative and the development of unit testing tool " * 8


class _FakePage:
    def __init__(self, default):
        self.default = default

    def extract_text(self, **kwargs):
        return _SPACED if kwargs.get("x_tolerance") == 1 else self.default


class _FakePdf:
    def __init__(self, default):
        self.pages = [_FakePage(default)]

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _fake_pdfplumber(monkeypatch, default):
    import sys
    import types

    module = types.ModuleType("pdfplumber")
    module.open = lambda _path: _FakePdf(default)  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "pdfplumber", module)


def test_looks_glued_is_about_word_length_not_text_length():
    from app.services.cv_text_extractor import looks_glued

    assert looks_glued(_GLUED)
    assert not looks_glued(_SPACED)
    assert not looks_glued("krótkiCVbezprzerw"), "krótkich tekstów nie oceniamy"
    assert not looks_glued(None)


def test_glued_pdf_is_read_again_with_tighter_letter_gap(monkeypatch):
    """Produkcja 23.09.2026: 1 581 CV z tekstem bez spacji — domyślny próg
    pdfplumbera (3 pt) nie widział odstępu między słowami w ciasnym kerningu."""
    from app.services import cv_text_extractor as cte

    _fake_pdfplumber(monkeypatch, _GLUED)
    out = cte._extract_pdf_native("/tmp/x.pdf")
    assert "the qa initiative" in out


def test_well_spaced_pdf_keeps_the_default_read(monkeypatch):
    from app.services import cv_text_extractor as cte

    normal = "Senior QA Engineer with Selenium and Python experience. " * 10
    _fake_pdfplumber(monkeypatch, normal)
    assert cte._extract_pdf_native("/tmp/x.pdf") == normal


def _fake_contract_pdf(monkeypatch, page_texts):
    import types

    from app.services import cv_text_extractor as cte

    class _Page:
        def __init__(self, text):
            self._text = text

        def extract_text(self, **_kwargs):
            return self._text

        def close(self):
            pass

    class _Pdf:
        pages = [_Page(text) for text in page_texts]

        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return False

    monkeypatch.setitem(
        __import__("sys").modules,
        "pdfplumber",
        types.SimpleNamespace(open=lambda _path: _Pdf()),
    )
    return cte


def test_all_pages_ocr_reads_only_pages_without_text(monkeypatch):
    """Aneks NBP z paczki: 4 strony tekstu i 9 stron skanu w jednym PDF-ie."""
    long_text = "Paragraf umowy z treścią, która jest prawdziwym tekstem strony PDF."
    cte = _fake_contract_pdf(monkeypatch, [long_text, "", long_text, "12"])
    scanned: list[int] = []

    def _ocr(_path, number):
        scanned.append(number)
        return f"Tekst ze skanu strony numer {number}"

    monkeypatch.setattr(cte, "_ocr_one_page", _ocr)
    result = cte._worker_all_pages("umowa.pdf")

    assert scanned == [2, 4]
    assert result["pages"] == 4 and result["ocr_pages"] == 2
    assert "Tekst ze skanu strony numer 2" in result["text"]
    assert result["text"].count(long_text) == 2


def test_all_pages_ocr_does_not_stop_at_ten_pages(monkeypatch):
    cte = _fake_contract_pdf(monkeypatch, [""] * 23)
    monkeypatch.setattr(
        cte, "_ocr_one_page", lambda _p, n: f"Strona skanu {n} z tekstem"
    )
    result = cte._worker_all_pages("skan.pdf")
    assert result["ocr_pages"] == 23
    assert "Strona skanu 23 z tekstem" in result["text"]


def test_all_pages_failed_ocr_keeps_the_rest_of_the_document(monkeypatch):
    cte = _fake_contract_pdf(
        monkeypatch, ["", "Tekst drugiej strony, całkiem długi zapis."]
    )

    def _ocr(_path, _number):
        raise RuntimeError("tesseract")

    monkeypatch.setattr(cte, "_ocr_one_page", _ocr)
    result = cte._worker_all_pages("umowa.pdf")
    assert result["ocr_pages"] == 0
    assert "Tekst drugiej strony" in result["text"]


def test_all_pages_timeout_grows_with_pages_up_to_a_ceiling():
    from app.services import cv_text_extractor as cte

    assert cte.all_pages_timeout(None) == 150
    assert cte.all_pages_timeout(248) == 150 + 2480
    assert cte.all_pages_timeout(10_000) == 3600


def test_all_pages_sandboxed_returns_none_when_worker_gives_up(monkeypatch):
    from app.services import cv_text_extractor as cte

    monkeypatch.setattr(cte, "_run_pdf_worker", lambda *_a, **_k: None)
    assert cte.extract_pdf_all_pages_sandboxed("umowa.pdf") is None


# ── Word bez tekstu z python-docx (03.11.2026) ───────────────────────────────
#
# Binarny `.doc` python-docx odrzuca zawsze, a tekst w polach tekstowych
# i kontrolkach pomija, więc `/from-cv` odpowiadał 400 i zgłoszenie z portalu
# przepadało. Na kopii produkcji LibreOffice odczytał 65 z 65 takich `.doc`
# i 28 z 28 takich `.docx`.


@pytest.fixture
def word_file(tmp_path):
    path = tmp_path / "cv.doc"
    path.write_bytes(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1 binarny Word")
    return str(path)


@pytest.fixture
def libreoffice(monkeypatch):
    """Proces odczytu udany: zwraca wywołane operacje, tekst podaje test."""
    from app.services import cv_pdf_preview, cv_text_extractor as cte

    calls: list[str] = []

    def _worker(op, _path, **_kwargs):
        calls.append(op)
        return {"text": "Tekst z LibreOffice. " * 10}

    monkeypatch.setattr(cv_pdf_preview, "soffice_path", lambda: "/usr/bin/soffice")
    monkeypatch.setattr(cte, "_run_pdf_worker", _worker)
    return calls


def test_word_python_docx_cannot_read_is_read_through_libreoffice(
    monkeypatch, word_file, libreoffice
):
    from app.services import cv_text_extractor as cte

    monkeypatch.setattr(cte, "_extract_docx", lambda _p: None)
    assert cte.extract_text(word_file, "cv.doc").startswith("Tekst z LibreOffice.")
    assert libreoffice == ["word"]


def test_word_with_empty_body_is_read_through_libreoffice(
    monkeypatch, word_file, libreoffice
):
    """Cała treść w polach tekstowych: python-docx nie zgłasza błędu, tylko pustkę."""
    from app.services import cv_text_extractor as cte

    monkeypatch.setattr(cte, "_extract_docx", lambda _p: "")
    assert cte.extract_text(word_file, "cv.docx").startswith("Tekst z LibreOffice.")


def test_word_with_body_text_does_not_start_libreoffice(
    monkeypatch, word_file, libreoffice
):
    from app.services import cv_text_extractor as cte

    monkeypatch.setattr(cte, "_extract_docx", lambda _p: "Doświadczenie " * 20)
    assert cte.extract_text(word_file, "cv.docx").startswith("Doświadczenie")
    assert libreoffice == []


def test_word_worker_gets_the_memory_libreoffice_needs(monkeypatch, word_file):
    """Przy limicie z PDF-a (1,5 GB) prawdziwe CV wywracało LibreOffice sygnałem 11."""
    from app.services import cv_pdf_preview, cv_text_extractor as cte

    seen: dict[str, int] = {}

    def _worker(_op, _path, *, memory_bytes):
        seen["memory_bytes"] = memory_bytes
        return {"text": "Tekst z LibreOffice"}

    monkeypatch.setattr(cv_pdf_preview, "soffice_path", lambda: "/usr/bin/soffice")
    monkeypatch.setattr(cte, "_extract_docx", lambda _p: None)
    monkeypatch.setattr(cte, "_run_pdf_worker", _worker)
    cte.extract_text(word_file, "cv.doc")
    assert seen["memory_bytes"] == cte.WORD_WORKER_MEMORY_BYTES
    assert cte.WORD_WORKER_MEMORY_BYTES > cte.PDF_WORKER_MEMORY_BYTES


def test_word_short_text_stays_when_libreoffice_gives_less(monkeypatch, word_file):
    from app.services import cv_pdf_preview, cv_text_extractor as cte

    monkeypatch.setattr(cv_pdf_preview, "soffice_path", lambda: "/usr/bin/soffice")
    monkeypatch.setattr(cte, "_extract_docx", lambda _p: "Krótka treść pliku")
    monkeypatch.setattr(cte, "_run_pdf_worker", lambda *_a, **_k: {"text": "x"})
    assert cte.extract_text(word_file, "cv.docx") == "Krótka treść pliku"


def test_word_worker_failure_keeps_empty_text(monkeypatch, word_file):
    """Limit czasu albo pamięci: pusty tekst jak dotąd, bez wyjątku."""
    from app.services import cv_pdf_preview, cv_text_extractor as cte

    monkeypatch.setattr(cv_pdf_preview, "soffice_path", lambda: "/usr/bin/soffice")
    monkeypatch.setattr(cte, "_extract_docx", lambda _p: None)
    monkeypatch.setattr(cte, "_run_pdf_worker", lambda *_a, **_k: None)
    assert cte.extract_text(word_file, "cv.doc") == ""


def test_word_without_libreoffice_does_not_start_the_worker(monkeypatch, word_file):
    """Lokalnie i w CI LibreOffice'a nie ma: wynik jak przed zmianą."""
    from app.services import cv_pdf_preview, cv_text_extractor as cte

    def _no_worker(*_a, **_k):
        raise AssertionError("bez LibreOffice proces odczytu nie ma czego zrobić")

    monkeypatch.setattr(cv_pdf_preview, "soffice_path", lambda: None)
    monkeypatch.setattr(cte, "_extract_docx", lambda _p: None)
    monkeypatch.setattr(cte, "_run_pdf_worker", _no_worker)
    assert cte.extract_text(word_file, "cv.doc") == ""


def test_word_conversions_wait_for_a_free_slot(monkeypatch, word_file):
    """LibreOffice to ciężki proces: gdy miejsce zajęte, pusty tekst zamiast tłoku."""
    from app.services import cv_pdf_preview, cv_text_extractor as cte

    def _no_worker(*_a, **_k):
        raise AssertionError("zajęte miejsce nie uruchamia drugiej zamiany")

    monkeypatch.setattr(cv_pdf_preview, "soffice_path", lambda: "/usr/bin/soffice")
    monkeypatch.setattr(cte, "_extract_docx", lambda _p: None)
    monkeypatch.setattr(cte, "_run_pdf_worker", _no_worker)
    monkeypatch.setattr(cte, "_WORD_SLOT_WAIT_SECONDS", 0.01)
    assert cte._word_slot.acquire(blocking=False)
    try:
        assert cte.extract_text(word_file, "cv.doc") == ""
    finally:
        cte._word_slot.release()


def test_word_zip_bomb_never_reaches_libreoffice(monkeypatch, tmp_path):
    """Strażnik z `_extract_docx` połyka wyjątek, więc proces odczytu sprawdza sam."""
    import zipfile

    from app.core import zip_guard
    from app.services import cv_pdf_preview, cv_text_extractor as cte

    def _no_conversion(*_a, **_k):
        raise AssertionError("bomba ZIP nie może dojść do LibreOffice")

    monkeypatch.setattr(cv_pdf_preview, "docx_to_pdf", _no_conversion)
    monkeypatch.setattr(zip_guard, "MAX_XML_PART_UNCOMPRESSED", 10)
    path = tmp_path / "bomba.docx"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("word/document.xml", "<w:document>" + "x" * 100)
    assert cte._worker_word(str(path)) is None


def test_word_worker_reads_the_converted_pdf(monkeypatch, tmp_path):
    """Wynik zamiany idzie zwykłą ścieżką PDF-a, więc skan w Wordzie dostaje OCR."""
    from app.services import cv_pdf_preview, cv_text_extractor as cte

    seen: dict[str, bytes] = {}

    def _read_pdf(path):
        with open(path, "rb") as handle:
            seen["pdf"] = handle.read()
        return "Tekst z PDF-a"

    monkeypatch.setattr(
        cv_pdf_preview, "docx_to_pdf", lambda _data, **_k: b"%PDF-1.7 wynik"
    )
    monkeypatch.setattr(cte, "_extract_pdf_inprocess", _read_pdf)
    path = tmp_path / "cv.doc"
    path.write_bytes(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1")
    assert cte._worker_word(str(path)) == "Tekst z PDF-a"
    assert seen["pdf"] == b"%PDF-1.7 wynik"


@pytest.mark.parametrize(
    "content",
    [
        b"<html><body>CV</body></html>",
        b"{\\rtf1\\ansi CV}",
        b'<?xml version="1.0"?><office:document/>',
    ],
)
def test_word_worker_converts_only_real_word_files(monkeypatch, tmp_path, content):
    """Format wybiera LibreOffice po treści, więc plik pod nazwą `.doc` wybierałby filtr."""
    from app.services import cv_pdf_preview, cv_text_extractor as cte

    def _no_conversion(*_a, **_k):
        raise AssertionError("to nie jest Word")

    monkeypatch.setattr(cv_pdf_preview, "docx_to_pdf", _no_conversion)
    path = tmp_path / "cv.doc"
    path.write_bytes(content)
    assert cte._worker_word(str(path)) is None


def test_word_worker_forces_the_import_filter_from_the_bytes(monkeypatch, tmp_path):
    from app.services import cv_pdf_preview, cv_text_extractor as cte

    seen: dict[str, str] = {}

    def _convert(_data, *, infilter):
        seen["infilter"] = infilter
        return b"%PDF-1.7"

    monkeypatch.setattr(cv_pdf_preview, "docx_to_pdf", _convert)
    monkeypatch.setattr(cte, "_extract_pdf_inprocess", lambda _p: "Tekst")
    path = tmp_path / "cv.docx"
    path.write_bytes(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1")
    assert cte._worker_word(str(path)) == "Tekst"
    assert seen["infilter"] == "MS Word 97"


def test_word_worker_returns_none_when_conversion_fails(monkeypatch, tmp_path):
    from app.services import cv_pdf_preview, cv_text_extractor as cte

    def _unavailable(_data, **_k):
        raise cv_pdf_preview.PdfPreviewUnavailable("exit 1")

    monkeypatch.setattr(cv_pdf_preview, "docx_to_pdf", _unavailable)
    path = tmp_path / "cv.doc"
    path.write_bytes(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1")
    assert cte._worker_word(str(path)) is None


def test_from_cv_logs_the_shape_of_a_file_it_could_not_read(
    monkeypatch, tmp_path, caplog
):
    """Bez nazwy pliku w logu: format i rozmiar wystarczą do następnego dochodzenia."""
    import asyncio
    import logging

    from fastapi import HTTPException

    from app.api import candidates
    from app.services import cv_text_extractor as cte

    monkeypatch.setattr(candidates.settings, "UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr(cte, "extract_text", lambda _path, _name: "")
    content = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1 binarny Word"
    with caplog.at_level(logging.WARNING, logger=candidates.logger.name):
        with pytest.raises(HTTPException) as refused:
            asyncio.run(
                candidates._extract_uploaded_cv_text(
                    content,
                    safe_name="Jan_Kowalski.doc",
                    client_filename="Jan_Kowalski.doc",
                )
            )
    assert refused.value.status_code == 400
    assert f"{len(content)} B" in caplog.text and ".doc" in caplog.text
    assert "Kowalski" not in caplog.text


# ── Nazwisko i kontakt w grafice nagłówka ───────────────────────────────────

_BODY_WITHOUT_CONTACT = (
    "Doświadczenie zawodowe\nProgramista Python w firmie Przykład sp. z o.o.\n"
    "Projektowanie usług i testów automatycznych dla systemu bankowego.\n"
    "Wykształcenie\nInformatyka, Politechnika Przykładowa\n"
)
_HEADER_IN_GRAPHIC = "Anna Testowa\nanna.testowa@example.com\n+48 600 100 200\n"


def _pdf_cv(monkeypatch, tmp_path, native: str, ocr):
    """Plik z podpisem PDF, tekst PDF-a i wynik OCR pierwszej strony podstawione."""
    from app.services import cv_text_extractor as cte

    path = tmp_path / "cv.pdf"
    path.write_bytes(b"%PDF-1.7 syntetyczny")
    workers: list[str] = []

    def _worker(op, _path, **_kwargs):
        workers.append(op)
        return {"text": ocr} if op == "first_page_ocr" else None

    monkeypatch.setattr(cte, "_extract_pdf", lambda _p: native)
    monkeypatch.setattr(cte, "_run_pdf_worker", _worker)
    return cte, str(path), workers


def test_cv_with_contact_in_graphic_header_gets_it_from_first_page_ocr(
    monkeypatch, tmp_path
):
    """Profile 18566 i 5842: tekst bez nazwiska i kontaktu, a na obrazie strony są."""
    from app.services.cv_parser import (
        _extract_email_from_text,
        _extract_phone_from_text,
    )

    cte, path, workers = _pdf_cv(
        monkeypatch, tmp_path, _BODY_WITHOUT_CONTACT, _HEADER_IN_GRAPHIC
    )

    text = cte.extract_cv_text(path, "cv.pdf")

    assert workers == ["first_page_ocr"]
    assert text.startswith("Anna Testowa\n")
    assert _extract_phone_from_text(text) == "+48 600 100 200"
    assert text.endswith(cte._normalize(_BODY_WITHOUT_CONTACT))
    # Adres z OCR bywa błędny, a wiadomość poszłaby do obcej osoby.
    assert _extract_email_from_text(text) is None
    assert "example.com" not in text


@pytest.mark.parametrize(
    "contact", ["kontakt: anna@example.com", "tel. 600 100 200", "+48600100200"]
)
def test_cv_with_contact_in_text_skips_ocr(monkeypatch, tmp_path, contact):
    native = _BODY_WITHOUT_CONTACT + contact
    cte, path, workers = _pdf_cv(monkeypatch, tmp_path, native, _HEADER_IN_GRAPHIC)

    assert cte.extract_cv_text(path, "cv.pdf") == cte._normalize(native)
    assert workers == []


def test_cv_short_text_already_went_through_full_ocr(monkeypatch, tmp_path):
    cte, path, workers = _pdf_cv(monkeypatch, tmp_path, "Krótki tekst", "Anna Testowa")

    assert cte.extract_cv_text(path, "cv.pdf") == "Krótki tekst"
    assert workers == []


def test_cv_header_ocr_is_only_for_pdf(monkeypatch, tmp_path):
    from app.services import cv_text_extractor as cte

    path = tmp_path / "cv.txt"
    path.write_text(_BODY_WITHOUT_CONTACT, encoding="utf-8")
    monkeypatch.setattr(
        cte,
        "_run_pdf_worker",
        lambda *_a, **_k: pytest.fail("OCR tylko dla PDF-a"),
    )

    assert cte.extract_cv_text(str(path), "cv.txt") == cte._normalize(
        _BODY_WITHOUT_CONTACT
    )


@pytest.mark.parametrize("ocr", [None, "", 7])
def test_cv_failed_header_ocr_keeps_pdf_text(monkeypatch, tmp_path, ocr):
    cte, path, _ = _pdf_cv(monkeypatch, tmp_path, _BODY_WITHOUT_CONTACT, ocr)

    assert cte.extract_cv_text(path, "cv.pdf") == cte._normalize(_BODY_WITHOUT_CONTACT)


def test_worker_failed_first_page_ocr_returns_nothing(monkeypatch):
    from app.services import cv_text_extractor as cte

    def _broken(_path, _number):
        raise RuntimeError("tesseract")

    monkeypatch.setattr(cte, "_ocr_one_page", _broken)

    assert cte._worker_first_page_ocr("cv.pdf") is None


def test_orders_and_other_documents_do_not_get_header_ocr(monkeypatch, tmp_path):
    """`extract_text` czytają też zamówienia: ich tekst nie może się zmienić."""
    cte, path, workers = _pdf_cv(
        monkeypatch, tmp_path, _BODY_WITHOUT_CONTACT, _HEADER_IN_GRAPHIC
    )

    assert cte.extract_text(path, "zamowienie.pdf") == cte._normalize(
        _BODY_WITHOUT_CONTACT
    )
    assert workers == []


def test_header_ocr_adds_only_lines_missing_from_pdf_text():
    from app.services.cv_text_extractor import _ocr_lines_missing_from_text

    ocr = (
        "Anna Testowa\n"
        "Doświadczenie zawodowe\n"  # jest w tekście PDF-a
        "© — |\n"  # ikony, które OCR czyta jako znaki
        "Programista Pythen w firmie Przykład\n"  # literówka OCR w linii z tekstu
        "anna@example.com\n"
    )

    assert _ocr_lines_missing_from_text(_BODY_WITHOUT_CONTACT, ocr) == ["Anna Testowa"]


@pytest.mark.parametrize(
    ("line", "kept"),
    [
        (
            "Anna Testowa | anna@example.com | +48 600 100 200",
            "Anna Testowa | | +48 600 100 200",
        ),
        ("annaGexample.com", None),  # `@` odczytana jako litera
        ("anna@example.pl", None),
        ("linkedin.com/in/anna-testowa", None),
    ],
)
def test_header_ocr_never_adds_an_address(line, kept):
    from app.services.cv_text_extractor import _ocr_lines_missing_from_text

    assert _ocr_lines_missing_from_text("", line) == ([kept] if kept else [])


def test_header_ocr_keeps_phone_line_even_when_rest_of_it_is_in_pdf_text():
    from app.services.cv_text_extractor import _ocr_lines_missing_from_text

    assert _ocr_lines_missing_from_text(
        "Anna Testowa programista", "Anna Testowa programista 600 100 200"
    ) == ["Anna Testowa programista 600 100 200"]


def test_header_ocr_keeps_phone_line_behind_the_cap():
    from app.services.cv_text_extractor import (
        _OCR_HEADER_MAX_LINES,
        _ocr_lines_missing_from_text,
    )

    filler = [f"Inny{number} wiersz{number}" for number in range(40)]
    lines = _ocr_lines_missing_from_text("", "\n".join(filler + ["tel. 600 100 200"]))

    assert lines == filler[:_OCR_HEADER_MAX_LINES] + ["tel. 600 100 200"]


def test_header_ocr_block_is_capped():
    from app.services.cv_text_extractor import (
        _OCR_HEADER_MAX_LINES,
        _ocr_lines_missing_from_text,
    )

    ocr = "\n".join(f"Inny{number} wiersz{number}" for number in range(100))

    assert len(_ocr_lines_missing_from_text("", ocr)) == _OCR_HEADER_MAX_LINES


def test_name_from_graphic_header_stays_behind_the_identity_rules(
    monkeypatch, tmp_path
):
    """Nazwa z OCR to zwykły nagłówek: #3057 i #3062 działają na niej tak samo."""
    from app.services.candidate_identity_quarantine import evaluate_identity_match
    from app.services.cv_parser import _apply_contact_fallbacks

    cte, path, _ = _pdf_cv(
        monkeypatch,
        tmp_path,
        _BODY_WITHOUT_CONTACT,
        "Project Manager\n" + _HEADER_IN_GRAPHIC,
    )

    parsed = _apply_contact_fallbacks({}, cte.extract_cv_text(path, "cv.pdf"))

    assert (parsed["first_name"], parsed["last_name"]) == ("Anna", "Testowa")
    assert parsed["_name_from_header"] == ["first_name", "last_name"]
    # Inna nazwa w profilu: bramka widzi rozbieżność, a to wołający decyduje
    # (`observed_name_from_header`), że nagłówek nie daje kwarantanny.
    result = evaluate_identity_match(
        candidate_first_name="Ewa",
        candidate_last_name="Przykładowa",
        observed_first_name=parsed["first_name"],
        observed_last_name=parsed["last_name"],
    )
    assert result.decision == "confirmed_mismatch"
