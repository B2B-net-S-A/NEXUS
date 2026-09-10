"""Host-native OCR acceptance: image-only PDF with employment after page ten."""

from io import BytesIO
import os
import re
import shutil

import pytest
from PIL import Image, ImageDraw, ImageFont

from app.services.cv_generator_b2b.text_extractor import extract_text_from_file


def test_native_ocr_reads_all_twelve_scanned_pages():
    missing = [
        name for name in ("tesseract", "pdftoppm", "pdfinfo") if not shutil.which(name)
    ]
    if missing:
        message = "Missing native OCR tools: " + ", ".join(missing)
        if os.getenv("REQUIRE_NATIVE_CV_OCR") == "1":
            pytest.fail(message)
        pytest.skip(message)
    font = ImageFont.load_default(size=42)
    pages = []
    try:
        for number in range(1, 13):
            page = Image.new("RGB", (1240, 1754), "white")
            draw = ImageDraw.Draw(page)
            draw.text(
                (100, 150), f"Employment record {number:02d}", font=font, fill="black"
            )
            draw.text(
                (100, 250), f"Employer Company{number:02d}", font=font, fill="black"
            )
            draw.text((100, 350), "Software Engineer", font=font, fill="black")
            pages.append(page)
        output = BytesIO()
        pages[0].save(
            output, format="PDF", save_all=True, append_images=pages[1:], resolution=150
        )
        result = extract_text_from_file(output.getvalue(), "synthetic-scanned-cv.pdf")
        # OCR may insert whitespace at the letter/digit boundary. Require
        # every exact employer number, in order, without accepting substitutions.
        assert re.findall(r"Employer Company\s*(\d{2})\b", result) == [
            f"{number:02d}" for number in range(1, 13)
        ], result
    finally:
        for page in pages:
            page.close()


def _mixed_pdf_fixture():
    """Small PDF fixture: native text page followed by a JPEG-only page."""
    image = Image.new("RGB", (1240, 1754), "white")
    try:
        draw = ImageDraw.Draw(image)
        draw.text(
            (100, 200),
            "Earlier employer ScanCompany",
            fill="black",
            font=ImageFont.load_default(size=42),
        )
        jpeg = BytesIO()
        image.save(jpeg, format="JPEG")
    finally:
        image.close()
    native = b"BT /F1 18 Tf 50 750 Td (NativeCompany exact searchable source employment record) Tj 0 -30 Td (Role: Software Engineer. Dates: January 2018 to December 2020.) Tj ET"
    scanned = b"q 595 0 0 842 0 0 cm /Im1 Do Q"

    def stream(data, metadata=b""):
        return (
            b"<< /Length "
            + str(len(data)).encode()
            + b" "
            + metadata
            + b" >>\nstream\n"
            + data
            + b"\nendstream"
        )

    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R 4 0 R] /Count 2 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 5 0 R >> >> /Contents 6 0 R >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /XObject << /Im1 8 0 R >> >> /Contents 7 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        stream(native),
        stream(scanned),
        stream(
            jpeg.getvalue(),
            b"/Type /XObject /Subtype /Image /Width 1240 /Height 1754 /ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /DCTDecode",
        ),
    ]
    output = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for number, obj in enumerate(objects, 1):
        offsets.append(len(output))
        output.extend(f"{number} 0 obj\n".encode() + obj + b"\nendobj\n")
    xref = len(output)
    output.extend(f"xref\n0 {len(offsets)}\n0000000000 65535 f \n".encode())
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode())
    output.extend(
        f"trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    )
    return bytes(output)


def test_native_ocr_preserves_both_pages_of_mixed_pdf():
    if not all(shutil.which(name) for name in ("tesseract", "pdftoppm", "pdfinfo")):
        if os.getenv("REQUIRE_NATIVE_CV_OCR") == "1":
            pytest.fail("Native OCR tools are required")
        pytest.skip("Native OCR tools unavailable")
    result = extract_text_from_file(_mixed_pdf_fixture(), "mixed.pdf")
    assert "NativeCompany exact searchable source employment record" in result
    assert "ScanCompany" in result
    assert result.index("NativeCompany") < result.index("ScanCompany")


def test_real_mixed_pdf_detects_scanned_page_before_native_only_extraction(monkeypatch):
    from unittest.mock import Mock
    from app.services.cv_generator_b2b import text_extractor

    ocr = Mock(return_value="NativeCompany\nScanCompany")
    monkeypatch.setattr(text_extractor, "_extract_pdf_ocr", ocr)
    raw = _mixed_pdf_fixture()
    result = extract_text_from_file(raw, "mixed.pdf")
    assert result == "NativeCompany\nScanCompany"
    ocr.assert_called_once()
    assert ocr.call_args.args == (raw,)
    native = ocr.call_args.kwargs["native_pages"]
    assert set(native) == {1}
    assert "NativeCompany exact searchable source employment record" in native[1]
