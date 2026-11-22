"""Pamięć podręczna plików XML faktur z KSeF (podgląd faktury kosztowej).

Plik pobrany raz na żądanie zostaje pod ``storage_service.STORAGE_ROOT``
(wolumen uploadów, jak PDF-y Płac w ``pdf_store``):
``ksef_xml/<sha[:2]>/<sha>.xml``, gdzie ``sha`` to SHA-256 numeru KSeF. Numer
KSeF jest niezmienny i jednoznaczny, a treść faktury w KSeF się nie zmienia,
więc wpis nie wygasa. Nazwa pliku to sam skrót — numer z bazy nie trafia do
ścieżki, więc nie wyjdzie poza katalog niezależnie od formatu.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Optional

from app.services import storage_service

SUBDIR = "ksef_xml"


def _path(ksef_number: str) -> Path:
    digest = hashlib.sha256(ksef_number.encode("utf-8")).hexdigest()
    return Path(storage_service.STORAGE_ROOT) / SUBDIR / digest[:2] / f"{digest}.xml"


def load(ksef_number: str) -> Optional[bytes]:
    try:
        return _path(ksef_number).read_bytes()
    except OSError:
        return None


def save(ksef_number: str, xml: bytes) -> None:
    target = _path(ksef_number)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(f".{os.getpid()}.part")
    temporary.write_bytes(xml)
    os.replace(temporary, target)


__all__ = ["load", "save"]
