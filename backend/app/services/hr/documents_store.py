"""Pliki dokumentów osoby (e-teczka) w magazynie uploadów aplikacji.

Ten sam wolumen co dokumenty kontraktów i faktury z PDF-u
(``storage_service.STORAGE_ROOT``), podkatalog ``hr_documents/<osoba>/``.
Nazwa pliku na dysku to skrót treści (``<sha256>.<rozszerzenie>``): nazwa od
człowieka nie trafia na dysk ani do logów, a ponowny zapis tego samego pliku
(np. generator ponawia zapis po podpisie) nadpisuje ten sam plik zamiast
zostawiać osierocony.

Typ pliku rozpoznajemy po treści, nie po nazwie ani nagłówku przeglądarki:
PDF, DOCX (bez makr), JPG, PNG. Treści nie parsujemy — NEXUS tylko przechowuje.
"""

from __future__ import annotations

import hashlib
import io
import os
import zipfile
from pathlib import Path
from typing import Optional

from app.services import storage_service
from app.services.hr_documents_schema import MAX_FILE_BYTES

SUBDIR = "hr_documents"
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
EXTENSIONS: dict[str, str] = {
    "application/pdf": "pdf",
    DOCX_MIME: "docx",
    "image/jpeg": "jpg",
    "image/png": "png",
}


class FileRejected(ValueError):
    """Plik, którego nie przyjmujemy (komunikat po polsku dla użytkownika)."""


def _is_docx(content: bytes) -> bool:
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            names = {entry.filename for entry in archive.infolist()}
    except (zipfile.BadZipFile, OSError):
        return False
    if any(name.lower().endswith("vbaproject.bin") for name in names):
        # Plik z makrami (DOCM przemianowany na DOCX) — nie przechowujemy.
        raise FileRejected(
            "Plik Word z makrami nie jest przyjmowany — zapisz go jako zwykły "
            "DOCX albo PDF."
        )
    return "[Content_Types].xml" in names and "word/document.xml" in names


def sniff_mime(content: bytes) -> Optional[str]:
    """Typ pliku z treści albo ``None`` (nieobsługiwany)."""

    head = content[:16]
    if content[:1024].lstrip().startswith(b"%PDF-"):
        return "application/pdf"
    if head.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if head.startswith(b"PK\x03\x04") and _is_docx(content):
        return DOCX_MIME
    return None


def check(content: bytes) -> tuple[str, str]:
    """(typ, SHA-256) pliku albo ``FileRejected`` (pusty, za duży, zły typ)."""

    if not content:
        raise FileRejected("Plik jest pusty.")
    if len(content) > MAX_FILE_BYTES:
        raise FileRejected("Dokument może mieć najwyżej 20 MB.")
    mime = sniff_mime(content)
    if mime is None:
        raise FileRejected("Wgraj PDF, plik Word (DOCX) albo zdjęcie (JPG, PNG).")
    return mime, hashlib.sha256(content).hexdigest()


def relative_path(user_id: int, digest: str, mime: str) -> str:
    return f"{SUBDIR}/{int(user_id)}/{digest}.{EXTENSIONS[mime]}"


def save(user_id: int, content: bytes, *, mime: str, digest: str) -> str:
    """Zapisuje plik (atomowo: plik tymczasowy + ``os.replace``); zwraca ścieżkę względną."""

    relative = relative_path(user_id, digest, mime)
    target = Path(storage_service.STORAGE_ROOT) / relative
    if not target.is_file():
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(f"{target.name}.part")
        temporary.write_bytes(content)
        os.replace(temporary, target)
    return relative


def path_for(relative: str) -> Path:
    """Ścieżka pliku pod katalogiem e-teczek (bez wyjścia poza niego)."""

    root = Path(storage_service.STORAGE_ROOT).resolve()
    path = (root / relative).resolve()
    try:
        path.relative_to(root / SUBDIR)
    except ValueError:
        raise FileNotFoundError("poza katalogiem dokumentów") from None
    if not path.is_file():
        raise FileNotFoundError("brak pliku dokumentu")
    return path


def delete(relative: str) -> None:
    """Kasuje plik; brak pliku nie jest błędem (nic do usunięcia)."""

    try:
        path = path_for(relative)
    except FileNotFoundError:
        return
    path.unlink(missing_ok=True)
