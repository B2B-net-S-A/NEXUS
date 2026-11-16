"""Próbka materiałów w zgłoszeniu trenera: jeden mały plik (PDF, PPTX, DOCX) na zgłoszenie.

Nagranie próbne jest za duże na panel, dlatego wideo konsultant podaje jako link
(pole ``materials``). Plik leży pod ``STORAGE_ROOT/trainer_samples/<id zgłoszenia>/``,
klucz bez nazwy pliku, bo nazwa przychodzi od osoby spoza firmy.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

from app.services import storage_service
from app.services.trainings.errors import TrainingError

SUBDIR = "trainer_samples"
MAX_BYTES = 20 * 1024 * 1024
EXTENSIONS: dict[str, bytes] = {
    "pdf": b"%PDF",
    "pptx": b"PK\x03\x04",
    "docx": b"PK\x03\x04",
}
REJECTED = (
    "Próbkę wgraj jako PDF, PPTX albo DOCX do 20 MB. Nagranie podaj jako link w polu "
    "„Link do nagrania albo programu”."
)


def extension_of(file_name: str) -> str:
    return Path(file_name).suffix.lower().lstrip(".")


def check(file_name: str, content: bytes) -> str:
    """Rozszerzenie pliku po sprawdzeniu nazwy, rozmiaru i pierwszych bajtów."""

    extension = extension_of(file_name)
    magic = EXTENSIONS.get(extension)
    if magic is None or not content or len(content) > MAX_BYTES:
        raise TrainingError(422, REJECTED, "sample_rejected")
    if not content.startswith(magic):
        raise TrainingError(422, REJECTED, "sample_rejected")
    return extension


def save(application_id: int, file_name: str, content: bytes) -> str:
    extension = check(file_name, content)
    digest = hashlib.sha256(content).hexdigest()
    relative = f"{SUBDIR}/{application_id}/{digest}.{extension}"
    target = Path(storage_service.STORAGE_ROOT) / relative
    if not target.is_file():
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(f"{target.name}.part")
        temporary.write_bytes(content)
        os.replace(temporary, target)
    return relative


def path_for(relative: str) -> Path:
    """Ścieżka próbki pod jej katalogiem, bez wyjścia poza niego."""

    root = Path(storage_service.STORAGE_ROOT).resolve()
    path = (root / relative).resolve()
    try:
        path.relative_to(root / SUBDIR)
    except ValueError:
        raise FileNotFoundError("poza katalogiem próbek") from None
    if not path.is_file():
        raise FileNotFoundError("brak pliku")
    return path
