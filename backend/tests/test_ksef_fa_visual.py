"""Wizualizacja faktury FA(3) z KSeF (podgląd faktury kosztowej) — bez bazy.

Zmyślona korekta w EUR z trzema stawkami: tytuł, strony, pozycje przed i po
korekcie, podsumowanie stawek z VAT w złotych, adnotacje, płatność, kod QR.
"""

from __future__ import annotations

import pytest

from app.services.hr.ksef import fa, fa_visual
from tests._fa3_samples import correction_eur

KSEF = "1111111111-20261110-0A0B0C0D0E0F-11"


def _html(xml: bytes, ksef: str | None = KSEF) -> str:
    return fa_visual.render_html(xml, ksef_number=ksef, environment="prod").html


def test_korekta_w_euro_z_kilkoma_stawkami() -> None:
    html = _html(correction_eur())

    assert "Faktura korygująca" in html
    assert "nr KOR/7/11/2026" in html
    assert "Data wystawienia: 10.11.2026, Kraków" in html
    assert "Okres: 01.10.2026 – 31.10.2026" in html
    assert "Dostawca Przykładowy sp. z o.o." in html and "NIP 1111111111" in html
    assert "Nabywca Testowy S.A." in html and "NIP 2222222222" in html
    assert "<h3>Faktor</h3>" in html
    # Pozycje: osobno stan przed i po korekcie.
    before, after = html.split("Stan przed korektą")[1].split("Stan po korekcie")
    assert "500,00 EUR" in before and "500,00 EUR" not in after
    assert "400,00 EUR" in after and "zw." in after
    # Podsumowanie stawek: netto i VAT w walucie, VAT w złotych z P_14_*W.
    assert "VAT w zł" in html
    assert "23% (22%)" in html and "-100,00 EUR" in html and "-98,21 zł" in html
    assert "8% (7%)" in html and "17,08 zł" in html
    assert "zwolnione" in html
    assert "Różnica do zapłaty: -59,00 EUR" in html
    assert "Kurs waluty do VAT: 4,27 zł." in html
    # Adnotacje i dane korekty.
    assert "Mechanizm podzielonej płatności." in html
    assert "Zwolnienie z VAT: art. 43 ust. 1 pkt 37 ustawy o VAT." in html
    assert "Odwrotne obciążenie." not in html
    assert "Korygowana faktura: FV/3/11/2026 z 02.11.2026" in html
    assert "Przyczyna korekty: Rabat za październik." in html
    # Płatność, zamówienie, opis, stopka.
    assert "Termin płatności: 24.11.2026." in html
    assert "Forma płatności: przelew." in html
    assert "PL61109010140000071219812874 (Bank Testowy, SWIFT WBKPPLPP)" in html
    assert "Zamówienie: ZAM-42 z 15.09.2026." in html
    assert "Projekt: Alfa" in html
    assert "Dziękujemy za współpracę." in html
    # Kod QR KOD I i numer KSeF.
    assert "data:image/svg+xml" in html and KSEF in html


def test_bez_numeru_ksef_bez_kodu_qr() -> None:
    html = _html(correction_eur(), ksef=None)
    assert "data:image/svg+xml" not in html


def test_tekst_z_pliku_jest_escapowany() -> None:
    html = _html(correction_eur(item_name="&lt;script&gt;alert(1)&lt;/script&gt;"))
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_zly_plik_odrzucony() -> None:
    with pytest.raises(fa.InvoiceParseError) as doctype:
        fa_visual.render_html(
            b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "b">]><Faktura/>',
            ksef_number=None,
            environment="prod",
        )
    assert doctype.value.code == "doctype"
    with pytest.raises(fa.InvoiceParseError):
        fa_visual.render_html(b"<Inne/>", ksef_number=None, environment="prod")


def test_nazwa_pliku_bez_ukosnikow() -> None:
    visual = fa_visual.render_html(
        correction_eur(), ksef_number=None, environment="prod"
    )
    assert fa_visual.filename(visual) == "faktura-KOR-7-11-2026.pdf"


def test_pdf_z_weasyprint() -> None:
    try:
        import weasyprint  # noqa: F401
    except (ImportError, OSError) as exc:  # brak Pango poza obrazem Dockera
        pytest.skip(f"WeasyPrint niedostępny: {exc}")
    visual = fa_visual.render_html(
        correction_eur(), ksef_number=KSEF, environment="prod"
    )
    content = fa_visual.render_pdf(visual)
    assert content.startswith(b"%PDF-")
