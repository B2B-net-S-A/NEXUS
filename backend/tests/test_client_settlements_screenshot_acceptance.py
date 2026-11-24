"""Akceptacja klienta ze zrzutu ekranu (OCR), decyzja Artura z 24.11.2026.

Konsultant PKO wkleja do maila zrzut odpowiedzi banku z Outlooka zamiast maila.
Na zrzucie nie ma adresu nadawcy, jest imię i nazwisko i podpis. Akceptacja
przechodzi, gdy na zrzucie jest słowo akceptacji, rozliczany miesiąc, liczba
godzin równa Time Sheet i nadawca, który jest koordynatorem z Time Sheet albo
kontaktem klienta. Do paczki dla klienta idzie wtedy obraz.
Bez tesseracta: OCR podmieniony. Osoby, firmy i liczby fikcyjne.
"""

from __future__ import annotations

import asyncio
import io
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D
from types import SimpleNamespace

from PIL import Image, ImageStat

from app.services.client_settlements import (
    mail_text,
    screenshot_ocr,
    service,
    timesheet_pko,
)

PEOPLE = frozenset({"Kierownik Anna"})

#: Tekst, jaki OCR daje ze zrzutu Outlooka w ciemnym motywie (śmieci na
#: początku linii nagłówka, adresaci bez dwukropka, data z paska zadań).
SCREEN = """Wewnętrzne
RE: Odbiór usług za wrzesień: Jan Nowak
4zP Kierownik Anna
fiw: Do © Nowak Jan (EXT)
m DW © Zastępca Ewa
Cześć Jan, potwierdzam odbiór usług za październik 2026 (176h).
Z pozdrowieniami
Anna Kierownik
Bank Przykład
t: 22 000 00 00
11:54
2026-10-30
"""


def _judge(text: str, **kw):
    args = {"month": "2026-10", "hours": D("176"), "md": None, "people": PEOPLE}
    args.update(kw)
    return mail_text.judge_screenshot(text, **args)


def test_zrzut_z_koordynatorem_godzinami_i_miesiacem_akceptuje():
    verdict = _judge(SCREEN)
    assert verdict is not None and verdict.ok
    assert verdict.title == "Akceptacja ze zrzutu ekranu: 176 h za październik 2026"


def test_zrzut_bez_ktoregos_warunku_nie_akceptuje():
    # Inny miesiąc w treści (bank pomylił miesiąc, temat też wrzesień).
    assert _judge(SCREEN.replace("październik 2026", "wrzesień 2026")) is None
    # Inna liczba godzin niż w Time Sheet.
    assert _judge(SCREEN, hours=D("168")) is None
    # Bez słowa akceptacji: to prośba konsultanta, nie odpowiedź banku.
    assert _judge(SCREEN.replace("potwierdzam", "proszę o potwierdzenie")) is None
    # Nikt z klienta nie jest znany.
    assert _judge(SCREEN, people=frozenset()) is None
    # Bez liczby: samo „Akceptuję” ze zrzutu nie wystarcza.
    assert _judge(SCREEN.replace(" (176h)", "")) is None


def test_koordynator_tylko_wsrod_adresatow_to_nie_nadawca():
    # Zrzut prośby konsultanta do koordynatora: koordynator jest w „Do”.
    request = """RE: Odbiór usług za październik 2026
Nowak Jan
Do © Kierownik Anna
DW Zastępca Ewa
Potwierdzam przesłanie Time Sheet za październik 2026 (176h).
Jan Nowak
"""
    assert not mail_text.sender_on_screen(request, PEOPLE)
    assert _judge(request) is None
    # Jedno słowo z nazwiska to za mało.
    assert not mail_text.sender_on_screen("Anna\nKierownik zespołu", PEOPLE)


def test_koordynator_i_akceptujacy_z_naglowka_time_sheet():
    rows: list[list[object]] = [
        ["Nazwisko i Imię Kontraktora", "Nowak Jan", "Kowalski Jan"],
        ["Koordynator odbierający usługę (z banku)", "Kierownik Anna", "X"],
        ["Akceptujący timesheet (z banku)", "Zastępca Ewa", "Y"],
        [
            "Lp.",
            "Miesiąc realizacji usług",
            "Numer projektu / formacji",
            "Numer zadania projektowego / Tematu formacji",
            "Rezultat/dostarczona funkcjonalność",
            "Liczba godzin realizacji usług październik 2026",
        ],
        [1, "czerwiec", "J0001", "T-1", "Testy", timedelta(days=7, hours=8)],
    ]
    parsed = timesheet_pko.parse_rows(rows)
    assert parsed is not None
    assert parsed.acceptors == frozenset({"Kierownik Anna", "Zastępca Ewa"})


# ── OCR obrazu ───────────────────────────────────────────────────────────────


def _png(width: int, height: int, color: int) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), (color, color, color)).save(buffer, "PNG")
    return buffer.getvalue()


def _fake_ocr(monkeypatch, seen: list) -> None:
    def image_to_string(image, lang=None, timeout=None):
        seen.append((image, lang, timeout))
        return "potwierdzam"

    monkeypatch.setitem(
        sys.modules, "pytesseract", SimpleNamespace(image_to_string=image_to_string)
    )


def test_ciemny_zrzut_odwrocony_i_powiekszony(monkeypatch):
    seen: list = []
    _fake_ocr(monkeypatch, seen)
    assert screenshot_ocr.text(_png(1000, 900, 40)) == "potwierdzam"
    image, lang, timeout = seen[0]
    assert lang == "pol+eng" and timeout == screenshot_ocr.TIMEOUT_S
    assert image.size == (2000, 1800)
    assert ImageStat.Stat(image).mean[0] > 128  # jasne tło po odwróceniu


def test_logo_i_zly_plik_bez_ocr(monkeypatch):
    seen: list = []
    _fake_ocr(monkeypatch, seen)
    assert screenshot_ocr.text(_png(200, 60, 255)) == ""
    assert screenshot_ocr.text(b"to nie jest obraz") == ""
    assert seen == []


def test_pamiec_ocr_po_skrocie_bez_pustych_wynikow(monkeypatch):
    calls: list[bytes] = []

    def text(content: bytes) -> str:
        calls.append(content)
        return "" if content == b"logo" else "tekst"

    monkeypatch.setattr(screenshot_ocr, "text", text)
    monkeypatch.setattr(screenshot_ocr, "_cache", type(screenshot_ocr._cache)())
    assert screenshot_ocr.cached_text("a" * 64, b"zrzut") == "tekst"
    assert screenshot_ocr.cached_text("a" * 64, b"zrzut") == "tekst"
    assert screenshot_ocr.cached_text("b" * 64, b"logo") == ""
    assert screenshot_ocr.cached_text("b" * 64, b"logo") == ""
    assert calls == [b"zrzut", b"logo", b"logo"]


# ── Rozliczenie ──────────────────────────────────────────────────────────────


def _image(doc_id: int, minutes: int) -> SimpleNamespace:
    return SimpleNamespace(
        id=doc_id,
        mime="image/png",
        file_path=f"consultant_portal/1/{doc_id}.png",
        sha256=f"{doc_id:064d}",
        created_at=datetime(2026, 10, 30, 11, tzinfo=timezone.utc)
        + timedelta(minutes=minutes),
    )


def test_rozliczenie_bierze_najnowszy_zrzut_ktory_przechodzi(monkeypatch, tmp_path):
    texts = {
        "1": SCREEN.replace("październik 2026", "wrzesień 2026"),  # pomyłka banku
        "2": SCREEN,  # poprawka po kilku godzinach
    }
    monkeypatch.setattr(
        service.portal_documents,
        "path_for",
        lambda rel: tmp_path / rel.rsplit("/", 1)[-1],
    )
    for name in ("1.png", "2.png"):
        (tmp_path / name).write_bytes(name.encode())
    monkeypatch.setattr(
        screenshot_ocr,
        "cached_text",
        lambda _key, content: texts[content.decode().split(".")[0]],
    )
    found = asyncio.run(
        service._screenshot_acceptance(
            [_image(1, 0), _image(2, 187)],
            month="2026-10",
            hours=D("176"),
            md=None,
            people=PEOPLE,
        )
    )
    assert found is not None
    verdict, image_id = found
    assert verdict.ok and image_id == 2
    # Bez osób klienta OCR nie rusza.
    assert (
        asyncio.run(
            service._screenshot_acceptance(
                [_image(2, 0)],
                month="2026-10",
                hours=D("176"),
                md=None,
                people=frozenset(),
            )
        )
        is None
    )
