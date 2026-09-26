"""Bezpieczne do logu reprezentacje nazw plików i kluczy magazynu (runda 6 audytu).

Klucz CV w magazynie ma kształt ``cv/RRRR/MM/<uuid>-<oryginalna_nazwa_pliku>``,
a nazwa pliku CV to zwykle „Jan_Kowalski_CV.pdf”, czyli imię i nazwisko
kandydata. Logi backendu idą do Loki/Coolify, więc do logu trafia tylko to, co
identyfikuje obiekt (prefiks + uuid albo skrót), a z nazwy pliku — rozszerzenie
i długość. Centralna redakcja w ``logging_config`` tego nie złapie, bo nazwisko
w nazwie pliku nie ma rozpoznawalnego kształtu.
"""

from __future__ import annotations

import hashlib
import os
import re

# `<32 hex uuid>-<nazwa>` — kształt z `object_storage.new_cv_storage_key`
# i `upload_briefing_audio`.
_UUID_PREFIXED = re.compile(r"^([0-9a-fA-F]{32})-")
# Segment bez nazwy pliku: sam skrót/uuid/liczba (np. `stage-cv/<id>/<sha256>`,
# `purged/<id>`) — nic osobowego, zostaje dosłownie.
_OPAQUE_SEGMENT = re.compile(r"^[0-9A-Za-z]{1,128}$")


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", "replace")).hexdigest()[:12]


def safe_storage_key(key: str | None) -> str:
    """Klucz magazynu bez części z nazwą pliku: prefiks + uuid albo skrót."""
    if not key:
        return "-"
    prefix, _, last = key.rpartition("/")
    head = f"{prefix}/" if prefix else ""
    match = _UUID_PREFIXED.match(last)
    if match:
        return f"{head}{match.group(1)}-…"
    if _OPAQUE_SEGMENT.match(last):
        return key
    return f"{head}#{_digest(last)}"


def safe_filename(filename: str | None) -> str:
    """Nazwa pliku sprowadzona do rozszerzenia i długości („<plik .pdf, 19 zn.>”)."""
    if not filename:
        return "-"
    ext = os.path.splitext(filename)[1].lower()[:10] or "bez rozszerzenia"
    return f"<plik {ext}, {len(filename)} zn.>"
