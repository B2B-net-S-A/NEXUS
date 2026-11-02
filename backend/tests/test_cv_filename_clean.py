"""Nazwa pliku CV wpisana przez człowieka (02.11.2026)."""

import pytest

from app.api.candidate_stage_cv import clean_cv_filename


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Bank_Pocztowy_Kierownik", "Bank_Pocztowy_Kierownik.docx"),
        ("Bank Pocztowy.DOCX", "Bank Pocztowy.docx"),
        ("  Żółć  (2026) ", "Żółć (2026).docx"),
        ("../../etc/passwd", "etcpasswd.docx"),
        ('a\\b/c:d*e?f"g<h>i|j', "abcdefghij.docx"),
        ("nazwa\r\nX-Injected: 1", "nazwaX-Injected 1.docx"),
        ("kropka.", "kropka.docx"),
    ],
)
def test_clean_cv_filename(raw, expected):
    assert clean_cv_filename(raw) == expected


@pytest.mark.parametrize("raw", ["", "   ", "***", ".docx", "...", "/\\"])
def test_clean_cv_filename_without_name(raw):
    assert clean_cv_filename(raw) is None
