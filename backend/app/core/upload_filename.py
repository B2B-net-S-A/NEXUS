"""Nazwa pliku z przeglądarki przycięta do kolumny ``filename`` (runda 9).

Kolumny ``filename`` dokumentów (kontrakty, zamówienia, dokumenty wymagane,
importy Finansów) mają ``VARCHAR(255)``, a nazwa szła do bazy surowa. Polska
nazwa PDF-a banku bez trudu przekracza 255 znaków: ``DataError`` przy zapisie
to 500 bez nagłówków CORS („Network Error”) i plik osierocony na dysku.
Ta sama reguła co ``client_orders._fit_filename_column``: rozszerzenie zostaje
na końcu (po nim front rozpoznaje typ pliku), ucinany jest środek nazwy.
"""

from __future__ import annotations

FILENAME_COLUMN_LIMIT = 255


def fit_filename_column(filename: str, limit: int = FILENAME_COLUMN_LIMIT) -> str:
    """Nazwa pliku nie dłuższa niż ``limit`` znaków, z zachowanym rozszerzeniem."""
    if len(filename) <= limit:
        return filename
    stem, dot, ext = filename.rpartition(".")
    if not dot or len(ext) > 16:
        return filename[:limit]
    keep = limit - len(ext) - 1
    return f"{stem[:keep]}.{ext}"
