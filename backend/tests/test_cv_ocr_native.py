"""Host-native OCR acceptance: image-only PDF with employment after page ten."""

from io import BytesIO
import os
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
    font = ImageFont.truetype("DejaVuSans.ttf", 42)
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
        for number in range(1, 13):
            assert f"Company{number:02d}" in result, result
    finally:
        for page in pages:
            page.close()
