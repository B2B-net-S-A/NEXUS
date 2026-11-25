"""Otwarcie skoroszytu XLSX dla czytników rozliczeń. Bez bazy.

Próba VI–VIII 2026: arkusz zapisany poza Excelem ma w widoku arkusza atrybut
``showZeroes`` (Excel i openpyxl znają tylko ``showZeros``). openpyxl w trybie
``read_only`` rzuca wtedy ``TypeError`` dopiero przy czytaniu wierszy, poza
``try`` wokół ``load_workbook`` w czytnikach, więc wywracał cały mail z poczty
rozliczeń (5 prób, potem porzucenie). Takie atrybuty usuwamy z XML-a arkuszy
przed otwarciem; reszta pliku zostaje bez zmian, a czytnik dostaje swoje dane.
"""

from __future__ import annotations

import io
import re
import zipfile
from typing import Any

#: Atrybuty spoza schematu, przez które openpyxl nie czyta arkusza.
_UNKNOWN_ATTRS = re.compile(rb'\sshowZeroes="[^"]*"')
_MARK = b"showZeroes"


def clean(content: bytes) -> bytes:
    """Plik bez atrybutów ``_UNKNOWN_ATTRS`` w arkuszach; inny plik bez zmian."""

    try:
        source = zipfile.ZipFile(io.BytesIO(content))
    except (zipfile.BadZipFile, OSError, ValueError):
        return content
    with source:
        fixed: dict[str, bytes] = {}
        for name in source.namelist():
            if not (name.startswith("xl/worksheets/") and name.endswith(".xml")):
                continue
            data = source.read(name)
            if _MARK in data:
                fixed[name] = _UNKNOWN_ATTRS.sub(b"", data)
        if not fixed:
            return content
        out = io.BytesIO()
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as target:
            for item in source.infolist():
                target.writestr(item, fixed.get(item.filename) or source.read(item))
        return out.getvalue()


def load_workbook(content: bytes, **options: Any) -> Any:
    """``openpyxl.load_workbook`` na pliku po ``clean``."""

    import openpyxl

    return openpyxl.load_workbook(io.BytesIO(clean(content)), **options)
