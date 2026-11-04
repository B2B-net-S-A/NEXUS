"""Runda 9 (R9-N7-2): odczyt PDF w procesie z limitem pamięci i czasu.

„Bomba” PDF (strumień, który rozwija się do gigabajtów) wgrana z formularza
kariery albo z poczty zamówień zabijała cały backend — pdfminer dekompresuje
strumienie bez limitu, a pdf2image renderował strony w rozmiarze z MediaBox.
"""

from __future__ import annotations

import http.server
import shutil
import subprocess
import sys
import threading
import time
import zipfile
import zlib
from types import SimpleNamespace

import pytest

from app.services import cv_text_extractor as cte


def _pdf(content: bytes, *, compress: bool = False) -> bytes:
    """Minimalny PDF z jedną stroną i podanym strumieniem treści."""
    stream_dict = b"<< /Length %d >>" % len(content)
    if compress:
        stream_dict = b"<< /Length %d /Filter /FlateDecode >>" % len(content)
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842]"
        b" /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        stream_dict + b"\nstream\n" + content + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % number + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    for offset in offsets:
        out += b"%010d 00000 n \n" % offset
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objects) + 1,
        xref,
    )
    return bytes(out)


def _text_pdf(tmp_path) -> str:
    content = b"".join(
        b"BT /F1 12 Tf 50 %d Td (Senior Python Developer line %d) Tj ET\n"
        % (800 - 20 * i, i)
        for i in range(12)
    )
    path = tmp_path / "abcd1234-Jan_Kowalski_CV.pdf"
    path.write_bytes(_pdf(content))
    return str(path)


def test_pdf_is_read_in_the_worker_process(tmp_path):
    path = _text_pdf(tmp_path)
    out = cte.extract_text(path, "Jan_Kowalski_CV.pdf")
    assert "Senior Python Developer line 3" in out


def test_order_document_helpers_go_through_the_worker(tmp_path):
    from app.services import order_document_text as odt

    assert odt._extract_pdf_native is cte.extract_pdf_native_sandboxed
    path = _text_pdf(tmp_path)
    assert odt._pdf_page_count(path) == 1
    assert "Senior Python Developer" in (odt._pdfminer_text(path) or "")


def test_worker_timeout_returns_nothing_instead_of_hanging(tmp_path, monkeypatch):
    path = _text_pdf(tmp_path)
    monkeypatch.setattr(
        cte,
        "_pdf_worker_command",
        lambda op, p: [sys.executable, "-c", "import time; time.sleep(30)"],
    )
    started = time.monotonic()
    assert cte._run_pdf_worker("pdf", path, timeout=1) is None
    assert time.monotonic() - started < 10


def test_worker_crash_degrades_to_empty_text(tmp_path, monkeypatch):
    path = _text_pdf(tmp_path)
    monkeypatch.setattr(
        cte,
        "_pdf_worker_command",
        lambda op, p: [sys.executable, "-c", "raise MemoryError"],
    )
    assert cte.extract_text(path, "cv.pdf") == ""


@pytest.mark.skipif(
    not sys.platform.startswith("linux"), reason="RLIMIT_AS działa tylko na Linuksie"
)
def test_decompression_bomb_is_stopped_by_the_memory_limit(tmp_path):
    # ~600 MB treści po dekompresji w kilkuset kilobajtach pliku.
    comp = zlib.compressobj(9)
    chunk = b" " * (1 << 20)
    body = bytearray(comp.compress(b"BT /F1 12 Tf 50 800 Td (Senior) Tj ET\n"))
    for _ in range(600):
        body += comp.compress(chunk)
    body += comp.flush()
    path = tmp_path / "bomb.pdf"
    path.write_bytes(_pdf(bytes(body), compress=True))

    started = time.monotonic()
    result = cte._run_pdf_worker(
        "native", str(path), timeout=60, memory_bytes=384 * 1024 * 1024
    )
    # Proces odczytu albo padł na limicie (None), albo oddał pusty wynik bez
    # rozdmuchania pamięci — w obu razach proces web żyje i nic nie wisi.
    assert result is None or not (result or {}).get("text")
    assert time.monotonic() - started < 60


def test_ocr_render_is_bounded_in_size_and_kept_on_disk(monkeypatch, tmp_path):
    seen: dict = {}

    def convert_from_path(path, **kwargs):
        seen.update(kwargs)
        return ["page"]

    monkeypatch.setitem(
        sys.modules, "pdf2image", SimpleNamespace(convert_from_path=convert_from_path)
    )
    monkeypatch.setitem(
        sys.modules,
        "pytesseract",
        SimpleNamespace(image_to_string=lambda img, lang: "tekst ze skanu"),
    )
    assert cte._extract_pdf_ocr(str(tmp_path / "scan.pdf")) == "tekst ze skanu"
    assert seen["size"] == cte._OCR_PAGE_MAX_PX
    assert seen["output_folder"]
    assert seen["last_page"] == 10


def test_worker_output_is_capped(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cte, "_extract_pdf_inprocess", lambda p: "x" * 10)
    monkeypatch.setattr(cte, "_PDF_WORKER_MAX_CHARS", 4)
    monkeypatch.setattr(cte, "_apply_worker_limits", lambda: None)
    assert cte._worker_main(["pdf", str(tmp_path / "a.pdf")]) == 0
    assert '"xxxx"' in capsys.readouterr().out
    assert cte._worker_main(["rm", "-rf"]) == 2


# ── Word przez LibreOffice w procesie odczytu (03.11.2026) ───────────────────
#
# Pełny przebieg z prawdziwym LibreOffice'em: jest w obrazie backendu, a lokalnie
# i w CI bywa go brak, więc testy się wtedy pomijają.

_needs_soffice = pytest.mark.skipif(
    not shutil.which("soffice"), reason="brak LibreOffice"
)
_CV_TEXT = "Doświadczenie zawodowe: analityk biznesowy, SQL, Python, raportowanie. "


def _word_with_body(tmp_path, name: str, body: str, rels: str = "") -> str:
    from docx import Document

    base = tmp_path / f"{name}-base.docx"
    Document().save(base)
    with zipfile.ZipFile(base) as archive:
        parts = {item: archive.read(item) for item in archive.namelist()}
    xml = parts["word/document.xml"].decode()
    start = xml.index("<w:body>") + len("<w:body>")
    parts["word/document.xml"] = (xml[:start] + body + xml[start:]).encode()
    rels_part = "word/_rels/document.xml.rels"
    parts[rels_part] = (
        parts[rels_part]
        .decode()
        .replace("</Relationships>", rels + "</Relationships>")
        .encode()
    )
    path = tmp_path / f"{name}.docx"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for item, data in parts.items():
            archive.writestr(item, data)
    return str(path)


def _textbox_docx(tmp_path) -> str:
    return _word_with_body(
        tmp_path,
        "pole",
        '<w:p><w:r><w:pict xmlns:v="urn:schemas-microsoft-com:vml">'
        '<v:shape style="width:450pt;height:300pt"><v:textbox>'
        "<w:txbxContent><w:p><w:r><w:t>"
        + _CV_TEXT * 6
        + "</w:t></w:r></w:p></w:txbxContent></v:textbox></v:shape></w:pict></w:r></w:p>",
    )


@_needs_soffice
def test_real_docx_with_text_only_in_a_text_box(tmp_path):
    assert "analityk biznesowy" in cte.extract_text(_textbox_docx(tmp_path), "cv.docx")


@_needs_soffice
def test_real_binary_doc(tmp_path):
    """Binarny `.doc` robi sam LibreOffice, bo w repo nie trzymamy pliku z Worda."""
    from docx import Document

    source = tmp_path / "zrodlo.docx"
    document = Document()
    document.add_paragraph(_CV_TEXT * 6)
    document.save(source)
    subprocess.run(
        [
            shutil.which("soffice"),
            f"-env:UserInstallation=file://{tmp_path}/profile",
            "--headless",
            "--convert-to",
            "doc:MS Word 97",
            "--outdir",
            str(tmp_path),
            str(source),
        ],
        check=True,
        capture_output=True,
        timeout=120,
    )
    path = tmp_path / "zrodlo.doc"
    assert path.read_bytes().startswith(b"\xd0\xcf\x11\xe0")
    assert "Doświadczenie zawodowe" in cte.extract_text(str(path), "cv.doc")


@pytest.fixture
def link_server():
    """Serwer na 127.0.0.1 z listą żądań, czyli miernik SSRF."""
    hits: list[str] = []

    class _Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            hits.append(self.path)
            self.send_response(200)
            self.end_headers()

        do_HEAD = do_GET

        def log_message(self, *_args):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}", hits
    server.shutdown()


@_needs_soffice
def test_real_conversion_does_not_fetch_links_from_the_file(tmp_path, link_server):
    """CV z obrazem podlinkowanym pod adres wewnętrzny nie wykonuje żądania (SSRF)."""
    base_url, hits = link_server
    url = f"{base_url}/obraz.png"
    path = _word_with_body(
        tmp_path,
        "link",
        '<w:p><w:r><w:drawing xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"'
        ' xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"'
        ' xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture"'
        ' xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<wp:inline><wp:extent cx="914400" cy="914400"/><wp:docPr id="1" name="p"/><a:graphic>'
        '<a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture"><pic:pic>'
        '<pic:nvPicPr><pic:cNvPr id="1" name="p"/><pic:cNvPicPr/></pic:nvPicPr>'
        '<pic:blipFill><a:blip r:link="rIdLink"/></pic:blipFill><pic:spPr><a:xfrm>'
        '<a:off x="0" y="0"/><a:ext cx="914400" cy="914400"/></a:xfrm>'
        '<a:prstGeom prst="rect"/></pic:spPr></pic:pic></a:graphicData></a:graphic>'
        "</wp:inline></w:drawing></w:r></w:p>",
        '<Relationship Id="rIdLink" Type="http://schemas.openxmlformats.org/'
        'officeDocument/2006/relationships/image" '
        f'Target="{url}" TargetMode="External"/>',
    )
    cte.extract_text(path, "cv.docx")
    assert hits == []


@_needs_soffice
def test_real_html_saved_as_doc_makes_no_request(tmp_path, link_server):
    """HTML pod nazwą `.doc`: blokada obrazów nie obejmuje arkusza stylów."""
    base_url, hits = link_server
    path = tmp_path / "cv.doc"
    path.write_text(
        f'<html><head><link rel="stylesheet" href="{base_url}/css.css"></head>'
        f'<body><img src="{base_url}/img.png"><p>{_CV_TEXT * 6}</p></body></html>',
        encoding="utf-8",
    )
    text = cte.extract_text(str(path), "cv.doc")
    assert hits == []
    assert text == ""
