"""Pliki dokumentów wydatków (faktura albo paragon do zgody, 0485).

Ten sam wolumen uploadów co e-teczki (``storage_service.STORAGE_ROOT``),
własny podkatalog ``approval_documents/<zgoda>/``: dokument wydatku to papier
firmy, nie osoby, więc nie trafia do e-teczki autora (inny krąg — Finanse,
nie Kadry). Nazwa na dysku to skrót treści; nazwa od człowieka zostaje tylko
w bazie. Typ z treści: PDF, JPG, PNG do 10 MB.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

from app.services import storage_service
from app.services.hr.documents_store import FileRejected, sniff_mime
from app.services.hr_approval_settlement_schema import MAX_FILE_BYTES

SUBDIR = "approval_documents"
EXTENSIONS: dict[str, str] = {
    "application/pdf": "pdf",
    "image/jpeg": "jpg",
    "image/png": "png",
}

__all__ = ["FileRejected", "check", "delete", "path_for", "save"]


def check(content: bytes) -> tuple[str, str]:
    """(typ, SHA-256) albo ``FileRejected`` z komunikatem dla osoby."""

    if not content:
        raise FileRejected("Plik jest pusty.")
    if len(content) > MAX_FILE_BYTES:
        raise FileRejected("Faktura albo paragon może mieć najwyżej 10 MB.")
    mime = sniff_mime(content)
    if mime not in EXTENSIONS:
        raise FileRejected("Wgraj PDF albo zdjęcie (JPG, PNG).")
    return mime, hashlib.sha256(content).hexdigest()


def save(request_id: int, content: bytes, *, mime: str, digest: str) -> str:
    """Zapis atomowy (plik tymczasowy + ``os.replace``); zwraca ścieżkę względną."""

    relative = f"{SUBDIR}/{int(request_id)}/{digest}.{EXTENSIONS[mime]}"
    target = Path(storage_service.STORAGE_ROOT) / relative
    if not target.is_file():
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(f"{target.name}.part")
        temporary.write_bytes(content)
        os.replace(temporary, target)
    return relative


def path_for(relative: str) -> Path:
    """Ścieżka pliku pod katalogiem dokumentów wydatków (bez wyjścia poza niego)."""

    root = Path(storage_service.STORAGE_ROOT).resolve()
    path = (root / relative).resolve()
    try:
        path.relative_to(root / SUBDIR)
    except ValueError:
        raise FileNotFoundError("poza katalogiem dokumentów wydatków") from None
    if not path.is_file():
        raise FileNotFoundError("brak pliku dokumentu wydatku")
    return path


def delete(relative: str) -> None:
    try:
        path = path_for(relative)
    except FileNotFoundError:
        return
    path.unlink(missing_ok=True)
