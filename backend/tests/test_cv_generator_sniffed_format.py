"""Generator CV rozpoznaje format pliku po bajtach, nie po nazwie (runda 6 audytu).

Produkcja 22.09.2026: 3 320 CV z Traffita to PDF-y zapisane pod nazwą
``*.docx``. Generator wybierał parser po rozszerzeniu, więc takie CV kończyło
się „Nie można odczytać dokumentu DOCX.” — w obu przepływach (domyślnym
``legacy_v7`` i przebudowanym) oraz w kontroli uploadu.
"""

from __future__ import annotations


import pytest

from app.services.cv_generator_b2b import text_extractor as current
from app.services.cv_generator_b2b.legacy_v7 import text_extractor as legacy
from app.services.cv_text_extractor import sniff_extension_bytes
from tests.test_cv_upload_preflight import docx, pdf


def _ole() -> bytes:
    return b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 600


def test_sniff_bytes_recognises_the_three_formats():
    assert sniff_extension_bytes(pdf()) == ".pdf"
    assert sniff_extension_bytes(docx()) == ".docx"
    assert sniff_extension_bytes(_ole()) == ".doc"
    assert sniff_extension_bytes(b"not a known format") is None
    assert sniff_extension_bytes(b"") is None


@pytest.mark.parametrize("module", [current, legacy], ids=["v10", "legacy_v7"])
def test_pdf_named_docx_is_read_as_pdf(module, monkeypatch):
    # Bez binarki pdftotext i bez OCR — sam pdfplumber, deterministycznie.
    monkeypatch.setattr(module, "_extract_pdf_pdftotext", lambda data: None)
    monkeypatch.setattr(module, "_extract_pdf_ocr", lambda *a, **k: None)
    if hasattr(module, "_extract_mixed_pdf"):
        monkeypatch.setattr(module, "_extract_mixed_pdf", lambda data: None)

    text = module.extract_text_from_file(pdf(), "Jan_Kowalski_CV.docx")

    assert "Synthetic CV" in text


@pytest.mark.parametrize("module", [current, legacy], ids=["v10", "legacy_v7"])
def test_docx_named_pdf_is_read_as_docx(module):
    text = module.extract_text_from_file(docx("Programista Python"), "cv.pdf")
    assert "Programista Python" in text


@pytest.mark.parametrize("module", [current, legacy], ids=["v10", "legacy_v7"])
def test_legacy_word_gets_a_clear_message(module):
    with pytest.raises(module.CVTextExtractionError, match=r"\.doc"):
        module.extract_text_from_file(_ole(), "cv.docx")


def test_upload_preflight_accepts_pdf_named_docx():
    from app.services.cv_generator_b2b import upload_preflight as preflight
    from app.services.cv_generator_b2b.standalone_service import (
        UploadGenerationInput,
    )

    preflight.validate_upload_inputs(
        UploadGenerationInput(cv_bytes=pdf(), cv_filename="CV.docx")
    )


def test_unknown_bytes_keep_the_declared_extension():
    # Brak sygnatury = zostaje nazwa — zepsuty „DOCX” nadal daje błąd DOCX.
    with pytest.raises(current.CVTextExtractionError, match="DOCX"):
        current.extract_text_from_file(b"not a zip archive", "cv.docx")
