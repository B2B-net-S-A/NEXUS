"""Zrzut zgody RODO w PDF „Nowe CV” (audyt 24.11.2026, bez bazy).

Upload zgody przyjmuje PNG, JPEG i WEBP, a „Nowe CV” rozpoznawało tylko PNG
i JPEG: zrzut WEBP wypadał z PDF po cichu, choć bramka pobrania widziała
zapisany obraz i przepuszczała plik do klienta.
"""

from __future__ import annotations

from io import BytesIO

import pytest
from PIL import Image

from app.services import cv_new_layout, cv_new_pdf
from app.services.cv_new_pdf import NewCvPdfError


def _image(fmt: str) -> bytes:
    out = BytesIO()
    Image.new("RGB", (8, 6), (200, 40, 40)).save(out, format=fmt)
    return out.getvalue()


@pytest.fixture
def captured(monkeypatch):
    """Render bez WeasyPrint — zapamiętuje dokument, który dostałby renderer."""
    seen: dict = {}

    def fake_render(document):
        seen["document"] = document
        report = type("Report", (), {"fits": True, "font_pt": 10.0, "steps": ()})
        return b"%PDF-fake", report

    monkeypatch.setattr(cv_new_layout, "render_new_cv_pdf_with_report", fake_render)
    return seen


def _render(consent):
    return cv_new_pdf._render(
        "<p>Treść CV</p>",
        language="pl",
        blind=False,
        fallback=None,
        extras=None,
        consent=consent,
    )


def test_webp_consent_lands_in_the_pdf_as_png(captured):
    _render(_image("WEBP"))
    document = captured["document"]
    assert document.consent_image_mime == "image/png"
    assert document.consent_image.startswith(b"\x89PNG")
    with Image.open(BytesIO(document.consent_image)) as image:
        assert image.size == (8, 6)


@pytest.mark.parametrize(
    ("fmt", "mime"), [("PNG", "image/png"), ("JPEG", "image/jpeg")]
)
def test_png_and_jpeg_consent_pass_unchanged(captured, fmt, mime):
    data = _image(fmt)
    _render(data)
    assert captured["document"].consent_image == data
    assert captured["document"].consent_image_mime == mime


def test_no_consent_renders_without_image(captured):
    _render(None)
    assert captured["document"].consent_image is None


def test_unreadable_consent_refuses_instead_of_pdf_without_consent(captured):
    with pytest.raises(NewCvPdfError) as error:
        _render(b"RIFF\x00\x00\x00\x00WEBPuszkodzony")
    assert str(error.value) == cv_new_pdf.MSG_CONSENT_UNREADABLE
    assert "document" not in captured


async def test_unreadable_consent_keeps_its_message_through_the_public_call(captured):
    with pytest.raises(NewCvPdfError) as error:
        await cv_new_pdf.render_new_cv_pdf(
            "<p>Treść CV</p>",
            language="pl",
            template=None,
            fallback=None,
            extras=None,
            consent=b"to nie jest obraz",
        )
    assert str(error.value) == cv_new_pdf.MSG_CONSENT_UNREADABLE
