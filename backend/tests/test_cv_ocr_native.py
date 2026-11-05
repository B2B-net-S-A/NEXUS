"""Host-native OCR acceptance: image-only PDF with employment after page ten."""

from io import BytesIO
import os
import re
import shutil
import zlib

import pytest
from PIL import Image, ImageDraw, ImageFont

from app.services.cv_generator_b2b.text_extractor import extract_text_from_file


def test_native_ocr_reads_benchmark_scan_across_page_breaks(tmp_path):
    from scripts.prepare_cv_document_corpus import write_scanned_pdf

    missing = [
        name for name in ("tesseract", "pdftoppm", "pdfinfo") if not shutil.which(name)
    ]
    if missing:
        message = "Missing native OCR tools: " + ", ".join(missing)
        if os.getenv("REQUIRE_NATIVE_CV_OCR") == "1":
            pytest.fail(message)
        pytest.skip(message)
    font = ImageFont.load_default(size=24)
    path = tmp_path / "benchmark-scan.pdf"
    write_scanned_pdf(
        ["First employer ScanCompanyStart", "2020: Python development"]
        + ["Additional source note about the project."] * 60
        + ["Final employer ScanCompanyFinal", "2023: SQL reporting"],
        path,
        font,
    )
    result = extract_text_from_file(path.read_bytes(), path.name)
    compact = re.sub(r"\s+", "", result).lower()
    assert "scancompanystart" in compact, result
    assert "scancompanyfinal" in compact, result
    assert compact.index("scancompanystart") < compact.index("scancompanyfinal")
    assert "2020" in result and "Python" in result, result
    assert "2023" in result and "SQL" in result, result


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


def _pdf_with_graphic_header(path, header_lines, body_lines):
    """PDF z nagłówkiem w obrazku i tekstem w treści, jak CV z szablonu graficznego."""
    font = ImageFont.load_default(size=40)
    image = Image.new("L", (1650, 400), 255)
    draw = ImageDraw.Draw(image)
    for number, line in enumerate(header_lines):
        draw.text((60, 40 + 70 * number), line, font=font, fill=0)
    pixels = zlib.compress(image.tobytes())
    text = "BT /F1 12 Tf 60 500 Td 16 TL " + " ".join(
        f"({line}) Tj T*" for line in body_lines
    )
    content = f"q 495 0 0 120 50 680 cm /Im1 Do Q {text} ET".encode()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R "
        b"/Resources << /Font << /F1 << /Type /Font /Subtype /Type1 "
        b"/BaseFont /Helvetica >> >> /XObject << /Im1 5 0 R >> >> >>",
        b"<< /Length %d >>\nstream\n%s\nendstream" % (len(content), content),
        b"<< /Type /XObject /Subtype /Image /Width 1650 /Height 400 "
        b"/ColorSpace /DeviceGray /BitsPerComponent 8 /Filter /FlateDecode "
        b"/Length %d >>\nstream\n%s\nendstream" % (len(pixels), pixels),
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n%s\nendobj\n" % (number, body)
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    for offset in offsets:
        out += b"%010d 00000 n \n" % offset
    out += b"trailer << /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objects) + 1,
        xref,
    )
    path.write_bytes(bytes(out))


def test_native_ocr_reads_contact_from_graphic_header(tmp_path):
    """Tekst w treści ma ponad 100 znaków, więc sam próg OCR-a nagłówka nie czyta."""
    from app.services.cv_parser import (
        _extract_email_from_text,
        _extract_phone_from_text,
    )
    from app.services.cv_text_extractor import extract_cv_text, extract_text

    missing = [name for name in ("tesseract", "pdftoppm") if not shutil.which(name)]
    if missing:
        message = "Missing native OCR tools: " + ", ".join(missing)
        if os.getenv("REQUIRE_NATIVE_CV_OCR") == "1":
            pytest.fail(message)
        pytest.skip(message)
    path = tmp_path / "graphic-header.pdf"
    _pdf_with_graphic_header(
        path,
        ["Marta Syntetyczna", "marta.syntetyczna@example.com", "+48 600 100 200"],
        [
            "Professional experience",
            "Software engineer at Example Company building payment services.",
            "Designed automated tests and reporting for a banking system.",
        ],
    )

    native = extract_text(str(path), path.name)
    assert "Professional experience" in native
    assert len(native) >= 100
    assert _extract_email_from_text(native) is None
    assert _extract_phone_from_text(native) is None

    text = extract_cv_text(str(path), path.name)
    assert text.index("Marta Syntetyczna") < text.index("Professional experience")
    assert _extract_phone_from_text(text) == "+48 600 100 200"
    assert _extract_email_from_text(text) is None
    assert "example.com" not in text.split("Professional experience")[0]
