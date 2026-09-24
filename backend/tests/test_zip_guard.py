"""Bomba ZIP w DOCX nie dociera do python-docx (audyt bezpieczeństwa 24.09.2026).

Publiczny formularz kariery sprawdza rozmiar pliku SKOMPRESOWANEGO (10 MB);
DOCX 2,97 MB rozwijał się w ``docx.Document()`` do 7,9 GB RAM przy limicie
kontenera 4 GB.
"""

from __future__ import annotations

import io
import zipfile

import pytest

from app.core import zip_guard
from app.core.zip_guard import UnsafeArchive, assert_safe_ooxml


def _docx(document_xml: bytes) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", b"<Types/>")
        archive.writestr("word/document.xml", document_xml)
    return buf.getvalue()


def test_bomb_is_refused_before_parsing() -> None:
    body = b"<w:p/>" * (zip_guard.MAX_XML_PART_UNCOMPRESSED // 6 + 1)
    data = _docx(body)
    assert len(data) < 1024 * 1024  # mały na dysku, ogromny po rozpakowaniu

    with pytest.raises(UnsafeArchive):
        assert_safe_ooxml(data)


def test_real_sized_cv_passes(tmp_path) -> None:
    data = _docx(b"<w:p><w:r><w:t>Java</w:t></w:r></w:p>" * 20_000)
    assert_safe_ooxml(data)
    path = tmp_path / "cv.docx"
    path.write_bytes(data)
    assert_safe_ooxml(str(path))


def test_not_a_zip_is_left_to_the_parser() -> None:
    assert_safe_ooxml(b"%PDF-1.7 not a zip")


def test_every_untrusted_docx_parser_calls_the_guard() -> None:
    from pathlib import Path

    backend = Path(__file__).resolve().parents[1]
    for rel in (
        "app/services/cv_text_extractor.py",
        "app/services/cv_generator_b2b/text_extractor.py",
        "app/services/cv_generator_b2b/legacy_v7/text_extractor.py",
        "app/services/champion_document.py",
        "app/services/dz_review.py",
    ):
        src = (backend / rel).read_text(encoding="utf-8")
        assert src.count("Document(") <= src.count("assert_safe_ooxml("), rel
