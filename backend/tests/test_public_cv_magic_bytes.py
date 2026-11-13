"""Publiczny formularz CV sprawdza zawartość pliku, nie tylko nazwę i MIME.

Pentest 13.11.2026: ``_validate_cv_file`` przyjmował plik, gdy pasowało
rozszerzenie ALBO zadeklarowany MIME — obie wartości ustawia wysyłający, więc
``cv.pdf`` z dowolną treścią trafiał na dysk i do ekstraktora. Teraz pierwsze
bajty muszą być PDF-em, DOCX-em albo DOC-iem (``sniff_extension_bytes``).
"""

from __future__ import annotations

import io
import zipfile

import pytest
from fastapi import HTTPException
from starlette.datastructures import Headers, UploadFile

from app.api import public_share


def _upload(filename: str, content_type: str) -> UploadFile:
    return UploadFile(
        io.BytesIO(b""),
        filename=filename,
        headers=Headers({"content-type": content_type}),
    )


def _docx_bytes() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("[Content_Types].xml", "<Types/>")
        zf.writestr("word/document.xml", "<w:document/>")
    return buf.getvalue()


def _xlsx_bytes() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("[Content_Types].xml", "<Types/>")
        zf.writestr("xl/workbook.xml", "<workbook/>")
    return buf.getvalue()


_OLE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 512


@pytest.mark.parametrize(
    ("filename", "mime", "content"),
    [
        ("cv.pdf", "application/pdf", b"%PDF-1.7\n1 0 obj"),
        (
            "cv.docx",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            _docx_bytes(),
        ),
        ("cv.doc", "application/msword", _OLE),
        # Przeglądarka bywa skąpa w MIME — liczy się treść.
        ("cv.pdf", "application/octet-stream", b"%PDF-1.4 body"),
    ],
    ids=["pdf", "docx", "doc", "pdf-octet-stream"],
)
def test_real_cv_formats_pass(filename: str, mime: str, content: bytes) -> None:
    public_share._validate_cv_file(_upload(filename, mime), content)


@pytest.mark.parametrize(
    ("filename", "mime", "content"),
    [
        # Nazwa i MIME kłamią: HTML udający PDF.
        ("cv.pdf", "application/pdf", b"<html><script>alert(1)</script></html>"),
        # Plik wykonywalny z nazwą .docx.
        ("cv.docx", "application/msword", b"MZ\x90\x00\x03\x00\x00\x00"),
        # ZIP, ale arkusz, nie dokument Worda.
        ("cv.docx", "application/octet-stream", _xlsx_bytes()),
        # RTF z MIME Worda (dawniej przechodził po samym MIME).
        ("cv.rtf", "application/msword", b"{\\rtf1 test}"),
        # Zgodna treść, ale ani rozszerzenie, ani MIME nie są CV.
        ("cv.exe", "application/x-msdownload", b"%PDF-1.4 body"),
    ],
    ids=["html-as-pdf", "exe-as-docx", "xlsx-as-docx", "rtf-as-doc", "pdf-as-exe"],
)
def test_content_that_is_not_a_cv_is_rejected(
    filename: str, mime: str, content: bytes
) -> None:
    with pytest.raises(HTTPException) as exc:
        public_share._validate_cv_file(_upload(filename, mime), content)
    assert exc.value.status_code == 415
