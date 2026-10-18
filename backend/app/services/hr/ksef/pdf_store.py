"""Pliki PDF faktur spoza KSeF (dopięte ręcznie przez Płace).

Klucz pliku to skrót treści: ``payroll_invoices/<sha[:2]>/<sha>.pdf`` pod
``storage_service.STORAGE_ROOT`` (wolumen uploadów). Nazwa od użytkownika nie
trafia na dysk ani do logów, a ten sam plik wgrany drugi raz ma ten sam klucz.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

from app.services import storage_service

SUBDIR = "payroll_invoices"
MAX_PDF_BYTES = 10 * 1024 * 1024


class PdfRejected(ValueError):
    pass


def check_pdf(content: bytes) -> str:
    """SHA-256 pliku albo ``PdfRejected`` (pusty, za duży, nie PDF)."""

    if not content:
        raise PdfRejected("Plik jest pusty.")
    if len(content) > MAX_PDF_BYTES:
        raise PdfRejected("PDF faktury może mieć najwyżej 10 MB.")
    if content.lstrip()[:5] != b"%PDF-":
        raise PdfRejected("Plik nie jest PDF-em.")
    return hashlib.sha256(content).hexdigest()


def save_pdf(content: bytes) -> tuple[str, str]:
    """Zapisuje PDF; zwraca (klucz względny, SHA-256)."""

    digest = check_pdf(content)
    root = Path(storage_service.STORAGE_ROOT)
    relative = f"{SUBDIR}/{digest[:2]}/{digest}.pdf"
    target = root / relative
    if not target.is_file():
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(".part")
        temporary.write_bytes(content)
        os.replace(temporary, target)
    return relative, digest


def path_for(relative: str) -> Path:
    """Ścieżka pliku pod korzeniem uploadów (bez wyjścia poza katalog)."""

    root = Path(storage_service.STORAGE_ROOT).resolve()
    path = (root / relative).resolve()
    try:
        path.relative_to(root / SUBDIR)
    except ValueError:
        raise FileNotFoundError("poza katalogiem faktur") from None
    if not path.is_file():
        raise FileNotFoundError("brak pliku faktury")
    return path
