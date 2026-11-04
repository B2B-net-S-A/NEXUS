"""Paczka eksportu z Compassa (format ``compass-bundle``, wersja 1).

Paczka to jeden plik JSON::

    {
      "format": "compass-bundle",
      "version": 1,
      "exported_at": "2026-11-13T18:05:00+01:00",
      "tables": {"profiles": [{...}, ...], "leave_requests": [...], ...}
    }

Eksport robi strona Compassa (same SELECT-y, bez zapisu). Paczka niesie dane
osobowe — leży tylko w pamięci procesu albo w katalogu z ograniczonym dostępem,
nigdy w repozytorium ani w logach (logi niosą liczby i identyfikatory).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Mapping

BUNDLE_FORMAT = "compass-bundle"
BUNDLE_VERSION = 1
#: Bezpiecznik rozmiaru: cała baza Compassa to kilka MB.
MAX_BUNDLE_BYTES = 64 * 1024 * 1024


class BundleError(ValueError):
    """Paczka nie nadaje się do importu (format, wersja, kształt tabel)."""


@dataclass(frozen=True)
class Bundle:
    sha256: str
    version: int
    exported_at: str | None
    tables: Mapping[str, tuple[Mapping[str, Any], ...]]

    def rows(self, table: str) -> tuple[Mapping[str, Any], ...]:
        return self.tables.get(table, ())


def parse_bundle(raw: bytes) -> Bundle:
    if len(raw) > MAX_BUNDLE_BYTES:
        raise BundleError("Paczka jest większa niż 64 MB.")
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BundleError("Paczka nie jest poprawnym plikiem JSON.") from exc
    if not isinstance(data, dict) or data.get("format") != BUNDLE_FORMAT:
        raise BundleError("To nie jest paczka eksportu Compassa.")
    if data.get("version") != BUNDLE_VERSION:
        raise BundleError(
            f"Nieobsługiwana wersja paczki: {data.get('version')!r} "
            f"(obsługiwana: {BUNDLE_VERSION})."
        )
    tables = data.get("tables")
    if not isinstance(tables, dict):
        raise BundleError("Paczka nie ma sekcji „tables”.")
    parsed: dict[str, tuple[Mapping[str, Any], ...]] = {}
    for name, rows in tables.items():
        if not isinstance(name, str) or not isinstance(rows, list):
            raise BundleError(f"Tabela {name!r} nie jest listą wierszy.")
        if not all(isinstance(row, dict) for row in rows):
            raise BundleError(f"Tabela {name!r} ma wiersz, który nie jest obiektem.")
        parsed[name] = tuple(rows)
    exported_at = data.get("exported_at")
    return Bundle(
        sha256=hashlib.sha256(raw).hexdigest(),
        version=BUNDLE_VERSION,
        exported_at=exported_at if isinstance(exported_at, str) else None,
        tables=parsed,
    )
