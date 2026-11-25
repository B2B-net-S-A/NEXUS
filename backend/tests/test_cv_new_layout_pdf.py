"""Układ „Nowe CV” jako PDF z WeasyPrint: strona 1 na jednej kartce, polskie znaki
krojami marki, klauzula RODO na końcu, zrzut zgody, blind, fetcher bez sieci.

Bez bibliotek natywnych WeasyPrint (libpango) cały plik jest pomijany — czyste
funkcje i HTML sprawdza `test_cv_new_layout_text.py`.
"""

from __future__ import annotations

import io
import re

import pytest

try:
    import weasyprint  # noqa: F401
except (
    ImportError,
    OSError,
) as exc:  # brak libpango kończy import OSError, nie ImportError
    pytest.skip(f"WeasyPrint niedostępny: {exc}", allow_module_level=True)

import pdfplumber

from app.services.cv_generator_b2b.docx_renderer import TRANSLATIONS
from app.services.cv_new_layout import NewCvDocument, render_new_cv_pdf_with_report
from app.services.cv_new_layout.labels import LABELS
from tests._cv_new_layout_fixtures import (
    PANGRAM,
    PANGRAM_UPPER,
    TODAY,
    blind,
    english,
    huge_cv,
    long_cv,
    short_cv,
    tiny_png,
)

POLISH = "ąćęłńóśźżĄĆĘŁŃÓŚŹŻ„”–·"
BRAND_FONT = re.compile(r"\+(Poppins|Source-?Sans-?3)", re.I)


def _render(data: dict, **kw):
    return render_new_cv_pdf_with_report(
        NewCvDocument.from_cv_json(data, **kw), today=TODAY
    )


def _pages(pdf: bytes) -> list[str]:
    with pdfplumber.open(io.BytesIO(pdf)) as doc:
        return [p.extract_text() or "" for p in doc.pages]


def _flat(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


@pytest.fixture(scope="module")
def long_result():
    return _render(long_cv(), consent_image=tiny_png())


@pytest.fixture(scope="module")
def short_result():
    return _render(short_cv())


def test_long_cv_page1_fits_after_shortening(long_result):
    pdf, report = long_result
    assert pdf.startswith(b"%PDF-")
    assert report.fits, report
    assert report.steps, "długie CV powinno wymagać skróceń"
    assert report.summary.startswith("strona 1 mieści się · pismo ")
    pages = _pages(pdf)
    first = _flat(pages[0])
    for heading in (
        "DLACZEGO NASZ KANDYDAT",
        "PRZEBIEG KARIERY",
        "UMIEJĘTNOŚCI",
        "EDUKACJA",
    ):
        assert heading in first
    assert (
        "DOŚWIADCZENIE" not in first and "Zakres zadań" not in first
    )  # nic ze str. 2 nie weszło na str. 1
    assert _flat(pages[1]).startswith(("UMIEJĘTNOŚCI — PEŁNA LISTA", "DOŚWIADCZENIE"))


def test_huge_skill_list_is_capped_on_page1_and_listed_in_full_later():
    pdf, report = _render(huge_cv())
    assert report.fits and report.skill_cap is not None, report
    assert any("najwyżej" in s for s in report.steps)
    pages = [_flat(p) for p in _pages(pdf)]
    assert "pełna lista na str. 2" in pages[0]
    assert pages[1].startswith("UMIEJĘTNOŚCI — PEŁNA LISTA")
    assert (
        " 11.29" in " ".join(pages[1:]) and " 11.29" not in pages[0]
    )  # ostatnia pozycja ostatniej kategorii


def test_short_cv_fits_without_steps(short_result):
    pdf, report = short_result
    # mało treści = większe pismo i luz w środku sekcji, nie dziury (Artur 25.11.2026)
    assert report.fits and report.steps == () and report.font_pt == 11.0
    assert report.summary == "strona 1 mieści się · pismo 11 pt"
    assert report.free_mm and report.free_mm > 30
    assert report.inner_mm > 0
    assert len(_pages(pdf)) == 2


def test_polish_characters_render_with_brand_fonts(long_result):
    pdf, _ = long_result
    text = "".join(_pages(pdf))
    assert PANGRAM in text and PANGRAM_UPPER in text
    assert "„cytat”" in text and "–" in text and "·" in text
    with pdfplumber.open(io.BytesIO(pdf)) as doc:
        fonts = {
            c["fontname"] for p in doc.pages for c in p.chars if c["text"] in POLISH
        }
        seen = {c["text"] for p in doc.pages for c in p.chars if c["text"] in POLISH}
    assert seen == set(POLISH)
    assert fonts and all(BRAND_FONT.search(f) for f in fonts), fonts


def _last_body_text(pdf: bytes, lang: str) -> str:
    """Tekst ostatniej strony bez stopki z danymi spółki (stoi pod treścią)."""
    return _flat(_pages(pdf)[-1].replace(LABELS[lang]["footer"], ""))


def test_rodo_clause_is_the_last_text(long_result):
    assert _last_body_text(long_result[0], "pl").endswith(
        _flat(TRANSLATIONS["pl"]["rodo"])[-60:]
    )


def test_consent_image_is_embedded_only_when_given(long_result, short_result):
    def images(pdf: bytes) -> int:
        with pdfplumber.open(io.BytesIO(pdf)) as doc:
            return sum(len(p.images) for p in doc.pages)

    assert images(long_result[0]) == 1
    assert images(short_result[0]) == 0
    text = _flat("".join(_pages(long_result[0])))
    assert text.index(TRANSLATIONS["pl"]["consent_heading"]) < text.index(
        _flat(TRANSLATIONS["pl"]["rodo"])[:50]
    )


def test_blind_pdf_has_no_name():
    pdf, _ = _render(blind(short_cv()))
    text = "".join(_pages(pdf))
    assert "Jan Testowy" not in text and "Testowy" not in text
    assert "Firma Kappa" not in text and "Firma z branży IT" in text
    assert "PODSUMOWANIE" in text
    with pdfplumber.open(io.BytesIO(pdf)) as doc:
        assert "Testowy" not in str(doc.metadata)
        assert not doc.metadata.get("Author")


def test_english_pdf_labels():
    pdf, report = _render(english(short_cv()))
    pages = [_flat(p) for p in _pages(pdf)]
    assert (
        "WHY OUR CANDIDATE" in pages[0]
        and "CAREER PATH" in pages[0]
        and "today" in pages[0]
    )
    assert (
        "EXPERIENCE" in pages[1] and "Tasks" in pages[1] and "Technologies" in pages[1]
    )
    assert _last_body_text(pdf, "en").endswith(_flat(TRANSLATIONS["en"]["rodo"])[-60:])
    assert report.fits


def test_external_resources_in_clause_are_not_fetched():
    clause = (
        "<p>Klauzula klienta.</p><img src='file:///etc/hosts'><img src='http://127.0.0.1:9/x.png'>"
        "<p style=\"background:url('http://169.254.169.254/latest')\">x</p>"
    )
    pdf, _ = _render(short_cv(), rodo_clause_html=clause)
    assert "Klauzula klienta." in "".join(_pages(pdf))
    with pdfplumber.open(io.BytesIO(pdf)) as doc:
        assert sum(len(p.images) for p in doc.pages) == 0
