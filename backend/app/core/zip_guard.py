"""Strażnik plików OOXML (DOCX/XLSX) przed „bombą ZIP”.

Limit uploadu (10 MB na publicznym formularzu kariery) sprawdza plik
SKOMPRESOWANY. DOCX to ZIP: 3 MB pliku rozwija się do setek MB XML-a, a
python-docx buduje z niego drzewo lxml — zmierzone 24.09.2026: 2,97 MB →
7,9 GB RAM i 160 s w ``docx.Document()``. Backend ma ``mem_limit: 4g`` i jeden
proces uvicorna, więc kilka takich zgłoszeń z publicznego formularza wyłącza
aplikację wszystkim (audyt bezpieczeństwa 24.09.2026).

Sprawdzamy nagłówki archiwum (``ZipFile.infolist`` nie rozpakowuje treści)
PRZED przekazaniem pliku do parsera. Progi są hojne dla prawdziwych CV:
największy ``word/document.xml`` w bazie CV ma pojedyncze megabajty.
"""

from __future__ import annotations

import io
import zipfile
from os import PathLike
from typing import Union

MAX_TOTAL_UNCOMPRESSED = 100 * 1024 * 1024  # obrazy w CV bywają duże
MAX_XML_PART_UNCOMPRESSED = 10 * 1024 * 1024  # to XML ląduje w lxml
MAX_ENTRIES = 5_000


class UnsafeArchive(ValueError):
    """Archiwum przekracza limity — nie wolno go parsować."""


def assert_safe_ooxml(source: Union[bytes, str, PathLike]) -> None:
    """Rzuca ``UnsafeArchive``, gdy plik rozwinąłby się ponad limity.

    Plik, który w ogóle nie jest ZIP-em, przepuszczamy — o formacie decyduje
    parser, który i tak zgłosi błąd po swojemu.
    """
    handle = io.BytesIO(source) if isinstance(source, (bytes, bytearray)) else source
    try:
        with zipfile.ZipFile(handle) as archive:
            entries = archive.infolist()
    except (zipfile.BadZipFile, OSError):
        return
    if len(entries) > MAX_ENTRIES:
        raise UnsafeArchive(f"too many archive entries: {len(entries)}")
    total = 0
    for entry in entries:
        total += entry.file_size
        if entry.filename.lower().endswith((".xml", ".rels")) and (
            entry.file_size > MAX_XML_PART_UNCOMPRESSED
        ):
            raise UnsafeArchive(
                f"archive part too large: {entry.filename} ({entry.file_size} B)"
            )
    if total > MAX_TOTAL_UNCOMPRESSED:
        raise UnsafeArchive(f"archive expands to {total} B")
