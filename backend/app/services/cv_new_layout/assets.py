"""Pliki marki z repo: kroje (Poppins, Source Sans 3; SIL OFL) i znak B2B Network.

Ścieżki liczone od pakietu, więc działają lokalnie, w CI i w obrazie Dockera
(`COPY . .` w `backend/Dockerfile` zabiera `app/assets`). Żadnych zasobów
z sieci: PDF musi wyglądać tak samo bez internetu.

Kroje w `assets/fonts/cv-new` to pliki z `frontend/src/app/fonts` (latin +
latin-ext, opis w tamtejszym README) zapisane jako TTF: Poppins z woff2,
Source Sans 3 400/600 bez zmian, 700 = instancja `wght=700` ze zmiennych
woff2 latin i latin-ext złączonych `fontTools.merge`. Licencje OFL leżą obok.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

ASSETS_DIR = (Path(__file__).resolve().parents[2] / "assets").resolve()
FONTS_DIR = ASSETS_DIR / "fonts" / "cv-new"
LOGO_PATH = ASSETS_DIR / "brand" / "b2bnetwork.svg"
LOGO_RATIO = 721 / 331  # viewBox znaku: szerokość / wysokość

FONT_FILES = (
    ("Poppins", 400, "Poppins-400.ttf"),
    ("Poppins", 500, "Poppins-500.ttf"),
    ("Poppins", 600, "Poppins-600.ttf"),
    ("Poppins", 700, "Poppins-700.ttf"),
    ("Poppins", 800, "Poppins-800.ttf"),
    ("Source Sans 3", 400, "SourceSans3-400.ttf"),
    ("Source Sans 3", 600, "SourceSans3-600.ttf"),
    ("Source Sans 3", 700, "SourceSans3-700.ttf"),
)


def font_face_css() -> str:
    return "".join(
        f"@font-face{{font-family:'{family}';font-weight:{weight};font-style:normal;"
        f"src:url('{(FONTS_DIR / name).as_uri()}') format('truetype')}}"
        for family, weight, name in FONT_FILES
    )


def is_local_asset(url: str) -> bool:
    """Czy `file://` wskazuje plik z `app/assets` (fetcher PDF wpuszcza tylko te)."""
    if not url.startswith("file://"):
        return False
    from urllib.parse import unquote, urlparse

    try:
        path = Path(unquote(urlparse(url).path)).resolve()
    except (OSError, ValueError):
        return False
    return path.is_file() and ASSETS_DIR in path.parents


@lru_cache(maxsize=4)
def _advances(file_name: str) -> tuple[dict[int, float], float]:
    from fontTools.ttLib import TTFont

    font = TTFont(FONTS_DIR / file_name, lazy=True)
    upm = font["head"].unitsPerEm
    hmtx = font["hmtx"]
    widths = {code: hmtx[glyph][0] / upm for code, glyph in font.getBestCmap().items()}
    return widths, widths.get(ord("n"), 0.6)


def text_width(text: str, size: float, file_name: str = "Poppins-700.ttf") -> float:
    """Szerokość napisu w jednostkach `size` (bez kerningu) — z metryk pliku kroju,
    żeby podpisy osi nie wychodziły za krawędź (zgadywanie długości tego nie dawało)."""
    widths, fallback = _advances(file_name)
    return sum(widths.get(ord(ch), fallback) for ch in text) * size
