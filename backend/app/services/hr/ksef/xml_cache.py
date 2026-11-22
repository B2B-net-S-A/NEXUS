"""Pamięć podręczna plików XML faktur z KSeF (podgląd faktury kosztowej).

Plik pobrany raz na żądanie zostaje pod ``storage_service.STORAGE_ROOT``
(wolumen uploadów, jak PDF-y Płac w ``pdf_store``):
``ksef_xml/<sha[:2]>/<numer KSeF>.xml``, gdzie ``sha`` to skrót numeru. Numer
KSeF jest niezmienny i jednoznaczny, a treść faktury w KSeF się nie zmienia,
więc wpis nie wygasa. Do zapisu trafia tylko numer o poprawnym formacie
(``numbers.is_valid``) — ścieżka nie wychodzi poza katalog.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Optional

from app.services import storage_service
from app.services.hr.ksef import numbers

SUBDIR = "ksef_xml"


def _path(ksef_number: str) -> Path:
    if not numbers.is_valid(ksef_number):
        raise ValueError("zły numer KSeF")
    digest = hashlib.sha256(ksef_number.encode("ascii")).hexdigest()
    return (
        Path(storage_service.STORAGE_ROOT) / SUBDIR / digest[:2] / f"{ksef_number}.xml"
    )


def load(ksef_number: str) -> Optional[bytes]:
    try:
        return _path(ksef_number).read_bytes()
    except (OSError, ValueError):
        return None


def save(ksef_number: str, xml: bytes) -> None:
    target = _path(ksef_number)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(f".{os.getpid()}.part")
    temporary.write_bytes(xml)
    os.replace(temporary, target)


__all__ = ["load", "save"]
