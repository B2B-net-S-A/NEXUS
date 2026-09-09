"""Zrzut zgody kandydata na końcu CV (wymóg PKO BP).

Bank wymaga, żeby pod treścią CV był widoczny zrzut maila, w którym kandydat
zgadza się na przetwarzanie danych. Do 09.2026 generator tylko OSTRZEGAŁ
rekrutera, żeby wkleił go ręcznie przed wysyłką — nie miał skąd wziąć obrazu.

Testy pilnują trzech rzeczy, z których każda po cichu zabrałaby zrzut z pliku:

1. **Obraz przeżywa PONOWNY render.** DOCX powstaje z `render_payload` przy
   KAŻDYM pobraniu, więc zrzut dołożony tylko raz zniknąłby z drugiego pliku.
2. **Awaria nie kasuje CV.** Nieczytelny obraz albo niedostępny magazyn dają
   dokument bez zrzutu (stan sprzed tej funkcji), a nie wywaloną generację —
   za którą właśnie zapłaciliśmy wywołaniem modelu.
3. **Klient z wymogiem nie dostaje CV bez zrzutu.** Odmowa jest twarda i pada
   PRZED naliczeniem kwoty AI.
"""

from __future__ import annotations

import io
from types import SimpleNamespace

import pytest
from docx import Document
from fastapi import HTTPException

from app.api.cv_generator_b2b import _require_consent_screenshot
from app.services.cv_generator_b2b.docx_renderer import add_consent_screenshot
from app.services.cv_generator_b2b.standalone_service import (
    hydrate_consent_screenshot,
)

# Najmniejszy poprawny PNG (1×1, przezroczysty) — python-docx czyta nagłówek,
# więc atrapa musi być prawdziwym obrazem, nie dowolnymi bajtami.
TINY_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000a4944415478da6360000000020001e221bc330000000049454e44ae426082"
)


def _picture_count(doc: Document) -> int:
    """Ile obrazów faktycznie siedzi w dokumencie (nie: ile akapitów dodano)."""
    return len(doc.element.body.findall(".//{*}blip"))


def test_screenshot_is_embedded_at_the_end() -> None:
    doc = Document()
    doc.add_paragraph("DOŚWIADCZENIE")
    assert add_consent_screenshot(doc, TINY_PNG, "Zgoda kandydata") is True
    assert _picture_count(doc) == 1
    assert any("Zgoda kandydata" in p.text for p in doc.paragraphs)


@pytest.mark.parametrize(
    "payload",
    [b"", b"to nie jest obraz", b"\x89PNG-ale-uciety"],
    ids=["pusty", "nie-obraz", "uszkodzony-png"],
)
def test_broken_image_never_breaks_generation(payload: bytes) -> None:
    """Zwraca False i zostawia dokument nietknięty — nie rzuca.

    Wyjątek tutaj wywróciłby CAŁĄ generację, łącznie z wywołaniem modelu, za
    które już zapłacono. CV bez zrzutu jest do ręcznego uzupełnienia; CV, które
    nie powstało, nie jest do niczego.
    """
    doc = Document()
    assert add_consent_screenshot(doc, payload, "Zgoda") is False
    assert _picture_count(doc) == 0


def test_hydration_reads_bytes_from_storage(monkeypatch: pytest.MonkeyPatch) -> None:
    """`render_payload` trzyma sam klucz — bajty doczytuje hydracja.

    Obraz w JSONB puchłby przy każdym odczycie wiersza, a odczytów jest znacznie
    więcej niż generacji.
    """
    import app.services.object_storage as storage

    monkeypatch.setattr(storage, "download_cv", lambda key: TINY_PNG)
    out = hydrate_consent_screenshot(
        {"name": "X", "consent_screenshot": {"storage_key": "zgody/abc.png"}}
    )
    assert out["consent_screenshot"]["_bytes"] == TINY_PNG


def test_hydration_survives_storage_outage(monkeypatch: pytest.MonkeyPatch) -> None:
    """Padnięty magazyn = CV bez zrzutu, nie zerwane pobranie."""
    import app.services.object_storage as storage

    def _boom(key: str) -> bytes:
        raise RuntimeError("magazyn niedostępny")

    monkeypatch.setattr(storage, "download_cv", _boom)
    out = hydrate_consent_screenshot(
        {"consent_screenshot": {"storage_key": "zgody/abc.png"}}
    )
    assert "_bytes" not in out["consent_screenshot"]


def test_hydration_is_a_noop_without_a_key() -> None:
    """Brak sekcji albo pusty klucz nie wołają magazynu ani nie wybuchają."""
    assert hydrate_consent_screenshot({"name": "X"}) == {"name": "X"}
    assert hydrate_consent_screenshot({"consent_screenshot": {}}) == {
        "consent_screenshot": {}
    }
    assert hydrate_consent_screenshot({"consent_screenshot": "śmieci"}) == {
        "consent_screenshot": "śmieci"
    }


def test_rendered_docx_carries_the_screenshot(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pełna ścieżka pobrania: payload z kluczem → DOCX z obrazem.

    I DRUGI raz — bo dokument jest re-renderowany przy każdym pobraniu, a
    hydracja mutuje kopię, nie zapisany payload.
    """
    import app.services.object_storage as storage
    from app.services.cv_generator_b2b import standalone_service as svc

    monkeypatch.setattr(storage, "download_cv", lambda key: TINY_PNG)

    captured: list[dict] = []

    def _fake_render(payload: dict, template_path: str) -> bytes:
        captured.append(payload)
        return b"docx"

    monkeypatch.setattr(svc, "render_cv_to_bytes", _fake_render)

    stored = {"name": "Jan", "consent_screenshot": {"storage_key": "zgody/a.png"}}
    svc.rerender_docx_from_payload(stored)
    svc.rerender_docx_from_payload(stored)

    assert len(captured) == 2
    for payload in captured:
        assert payload["consent_screenshot"]["_bytes"] == TINY_PNG
    # Zapisany payload NIE spuchł o bajty obrazu — hydracja pracuje na kopii.
    assert "_bytes" not in stored["consent_screenshot"]


def test_client_requiring_consent_is_refused_without_a_screenshot() -> None:
    rule = SimpleNamespace(requires_rodo_consent_block=True)
    with pytest.raises(HTTPException) as err:
        _require_consent_screenshot(rule, "")
    assert err.value.status_code == 422
    assert "zrzut" in err.value.detail.lower()


@pytest.mark.parametrize(
    ("rule", "key"),
    [
        (SimpleNamespace(requires_rodo_consent_block=True), "zgody/a.png"),
        (SimpleNamespace(requires_rodo_consent_block=False), ""),
        (None, ""),
    ],
    ids=["wymóg-spełniony", "klient-bez-wymogu", "klient-bez-reguł"],
)
def test_generation_passes_when_consent_is_not_owed(rule, key: str) -> None:
    _require_consent_screenshot(rule, key)


def test_refusal_happens_before_the_ai_quota_is_charged() -> None:
    """Odmowa musi poprzedzać naliczenie kwoty.

    Odwrotna kolejność brałaby rekruterowi limit za żądanie, które i tak nie
    wygenerowało pliku. Sprawdzane na ŹRÓDLE, bo obie ścieżki to osobne
    handlery i regres w jednej z nich jest niewidoczny w drugiej.
    """
    import pathlib
    import re

    src = (
        pathlib.Path(__file__).resolve().parents[1]
        / "app"
        / "api"
        / "cv_generator_b2b.py"
    ).read_text(encoding="utf-8")

    # Tylko WYWOŁANIA (`await ...`), nie definicje: `async def` stoi wyżej niż
    # jakikolwiek strażnik i sam z siebie fałszywie alarmował.
    guards = [
        m.start() for m in re.finditer(r"^\s+consent = _verified_consent\(", src, re.M)
    ]
    charges = [
        m.start() for m in re.finditer(r"await _charge_cv_generation_quota\(", src)
    ]
    # Po jednym strażniku na ścieżkę (`/generate`, `/generate-upload`) plus
    # definicja funkcji; każde naliczenie kwoty ma strażnika przed sobą.
    assert len(guards) >= 2, "brakuje strażnika w jednej ze ścieżek generacji"
    for charge in charges:
        assert any(g < charge for g in guards), (
            "kwota AI naliczana przed sprawdzeniem zrzutu zgody"
        )


def test_consent_heading_exists_in_both_languages() -> None:
    """Nagłówek sekcji ma wersję PL i EN — CV bywa generowane po angielsku."""
    from app.services.cv_generator_b2b.docx_renderer import TRANSLATIONS

    for lang in ("pl", "en"):
        assert TRANSLATIONS[lang]["consent_heading"].strip()


# ── skalowanie obrazu (uwagi z review PR #1335) ────────────────────────────


def _png(width: int, height: int) -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (width, height), "white").save(buf, "PNG")
    return buf.getvalue()


EMU_PER_INCH = 914400


@pytest.mark.parametrize(
    ("size", "opis"),
    [
        ((300, 900), "wąski-długi-z-telefonu"),
        ((2400, 800), "szeroki"),
        ((400, 200), "mały"),
    ],
)
def test_screenshot_always_fits_the_page(size: tuple[int, int], opis: str) -> None:
    """Zrzut mieści się w kolumnie tekstu I na stronie, z proporcjami.

    Dwie pułapki, które wyszły dopiero na review:

    * Podanie `width=` przy wstawianiu rozciąga TAKŻE obrazy węższe niż kolumna
      — zrzut z telefonu rozdmuchany do 6,3" jest rozmyty, czyli bezużyteczny
      jako dowód zgody.
    * Samo skalowanie po szerokości nie łapie obrazu wąskiego i DŁUGIEGO: 300×900
      zostaje w swojej szerokości i wychodzi na 12 cali wysokości, poza stronę,
      gdzie Word przycina go w połowie.
    """
    doc = Document()
    assert add_consent_screenshot(doc, _png(*size), "Zgoda") is True

    pic = doc.inline_shapes[0]
    assert pic.width <= 6.3 * EMU_PER_INCH + 1
    assert pic.height <= 8.5 * EMU_PER_INCH + 1
    # Proporcje nietknięte — skalowanie osobno po każdej osi zniekształciłoby zrzut.
    assert pic.width / pic.height == pytest.approx(size[0] / size[1], rel=0.01)


def test_small_screenshot_is_not_upscaled() -> None:
    """Mały zrzut zostaje mały — skalujemy WYŁĄCZNIE w dół."""
    doc = Document()
    add_consent_screenshot(doc, _png(400, 200), "Zgoda")
    pic = doc.inline_shapes[0]
    assert pic.width < 6.3 * EMU_PER_INCH


# ── walidacja formatu (uwaga z review PR #1335) ────────────────────────────


def test_image_type_is_sniffed_from_bytes_not_from_the_client_header() -> None:
    """Format rozpoznajemy z SYGNATURY, bo nagłówek żądania pisze klient.

    `Content-Type: image/png` na SVG z JavaScriptem albo na HTML-u przechodziłby
    kontrolę opartą o nagłówek, a plik lądowałby w magazynie dokumentów
    kandydatów bez sprawdzenia zawartości.
    """
    from app.api.cv_generator_b2b import _sniff_image_type

    assert _sniff_image_type(TINY_PNG) == "image/png"
    assert _sniff_image_type(b"\xff\xd8\xff\xe0garbage") == "image/jpeg"
    assert _sniff_image_type(b"RIFF????WEBPVP8 ") == "image/webp"

    for hostile in (
        b"<svg xmlns='http://www.w3.org/2000/svg'><script>alert(1)</script></svg>",
        b"<!DOCTYPE html><html><body>nie obraz</body></html>",
        b"%PDF-1.7",
        b"",
    ):
        assert _sniff_image_type(hostile) is None


def test_payload_has_verified_subject_without_a_reusable_token() -> None:
    from app.api.cv_generator_b2b import _verified_consent
    from app.services.cv_generator_b2b import consent_binding

    context = consent_binding.subject(candidate_id=1, stage_id=2, client_id=3)
    token = consent_binding.issue("cv/2026/09/abc-zgoda.png", 4, context)
    payload = _verified_consent(None, token, "", 4, context)
    assert payload["storage_key"] == "cv/2026/09/abc-zgoda.png"
    assert payload["binding"]["subject"] == context
    assert "token" not in payload
