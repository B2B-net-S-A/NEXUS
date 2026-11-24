"""Tekst zrzutu ekranu z maila (OCR), gdy akceptacja klienta przyszła jako obraz.

Decyzja Artura z 24.11.2026 (PKO, próba IX–X 2026): konsultant wkleja do maila
zrzut odpowiedzi banku z Outlooka zamiast samego maila. Tesseract (pol+eng)
jest w obrazie backendu. Czytamy tylko obrazy miesiąca osoby, tylko gdy mail
akceptacji nie przeszedł kontroli, i najwyżej ``MAX_IMAGES`` najnowszych.
Logo ze stopki (mały obraz) pomijamy. Ciemny motyw odwracamy, mały zrzut
powiększamy, bo inaczej OCR myli polskie litery w nazwiskach. Błąd albo
przekroczony czas = pusty tekst, czyli akceptację sprawdza człowiek.
"""

from __future__ import annotations

import io
import logging
from collections import OrderedDict

logger = logging.getLogger(__name__)

IMAGE_MIMES = ("image/png", "image/jpeg")
#: Mniejszy obraz to logo albo ikona, nie zrzut wiadomości.
MIN_WIDTH, MIN_HEIGHT = 500, 300
MAX_PIXELS = 25_000_000
MAX_IMAGES = 3
TIMEOUT_S = 20
#: Powiększamy zrzut węższy niż tyle pikseli (OCR potrzebuje ok. 30 px na literę).
UPSCALE_BELOW = 1600
_CACHE_SIZE = 256
_cache: OrderedDict[str, str] = OrderedDict()


def text(content: bytes) -> str:
    """Tekst obrazu; obraz za mały, uszkodzony albo OCR bez wyniku = ``""``."""

    try:
        import pytesseract  # type: ignore[import-untyped]
        from PIL import Image, ImageOps, ImageStat

        with Image.open(io.BytesIO(content)) as image:
            if (
                image.width < MIN_WIDTH
                or image.height < MIN_HEIGHT
                or image.width * image.height > MAX_PIXELS
            ):
                return ""
            gray = ImageOps.grayscale(image)
        if ImageStat.Stat(gray).mean[0] < 128:
            # Ciemny motyw Outlooka: jasne litery na ciemnym tle.
            gray = ImageOps.invert(gray)
        if gray.width < UPSCALE_BELOW:
            gray = gray.resize((gray.width * 2, gray.height * 2))
        return str(pytesseract.image_to_string(gray, lang="pol+eng", timeout=TIMEOUT_S))
    except Exception as exc:  # noqa: BLE001 — obraz z zewnątrz, OCR best-effort
        logger.info("rozliczenia: OCR zrzutu nie wyszedł (%s)", type(exc).__name__)
        return ""


def cached_text(key: str, content: bytes) -> str:
    """``text`` z pamięcią po skrócie pliku: przeliczenia miesiąca czytają ten sam
    obraz wiele razy, a OCR trwa kilka sekund."""

    if key in _cache:
        _cache.move_to_end(key)
        return _cache[key]
    found = text(content)
    if found:
        # Pusty wynik (logo, błąd, limit czasu) nie zostaje: następne przeliczenie
        # spróbuje jeszcze raz.
        _cache[key] = found
        while len(_cache) > _CACHE_SIZE:
            _cache.popitem(last=False)
    return found
