"""Pamięć odczytów CV z okna „Dodaj kandydata” (`/cv/preview` → `/from-cv`).

Osobna, OGRANICZONA pamięć procesu — nie `app/core/cache.py`, który nie ma
limitu rozmiaru ani sprzątania wygasłych wpisów (tekst CV to dziesiątki KB).

- klucz: SHA-256 treści pliku,
- najwyżej ``MAX_ENTRIES`` wpisów (najdawniej użyty wypada pierwszy),
- TTL ``TTL_SECONDS``; wygasłe wpisy są zamiatane przy każdym zapisie,
- tekst CV dłuższy niż ``MAX_RAW_TEXT_CHARS`` nie jest trzymany (`None`) —
  `/from-cv` odczyta go wtedy z pliku ponownie (bez modelu, lokalnie).
"""

from __future__ import annotations

import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Callable, Optional

MAX_ENTRIES = 64
TTL_SECONDS = 30 * 60
MAX_RAW_TEXT_CHARS = 200_000


@dataclass(frozen=True)
class CachedCvRead:
    parsed: dict[str, Any]
    raw_text: Optional[str]


class CvPreviewCache:
    def __init__(
        self,
        *,
        max_entries: int = MAX_ENTRIES,
        ttl_seconds: float = TTL_SECONDS,
        max_raw_text_chars: int = MAX_RAW_TEXT_CHARS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.max_entries = max_entries
        self.ttl_seconds = ttl_seconds
        self.max_raw_text_chars = max_raw_text_chars
        self._clock = clock
        self._entries: OrderedDict[str, tuple[float, CachedCvRead]] = OrderedDict()

    def __len__(self) -> int:
        return len(self._entries)

    def __contains__(self, sha256: str) -> bool:
        return sha256 in self._entries

    def _sweep(self, now: float) -> None:
        expired = [key for key, (exp, _) in self._entries.items() if exp <= now]
        for key in expired:
            del self._entries[key]

    def get(self, sha256: str) -> Optional[CachedCvRead]:
        entry = self._entries.get(sha256)
        if entry is None:
            return None
        expires_at, value = entry
        if expires_at <= self._clock():
            del self._entries[sha256]
            return None
        self._entries.move_to_end(sha256)
        return value

    def set(self, sha256: str, *, parsed: dict[str, Any], raw_text: str) -> None:
        if self.ttl_seconds <= 0 or self.max_entries <= 0:
            return
        now = self._clock()
        self._sweep(now)
        kept_text = raw_text if len(raw_text) <= self.max_raw_text_chars else None
        self._entries[sha256] = (
            now + self.ttl_seconds,
            CachedCvRead(parsed=parsed, raw_text=kept_text),
        )
        self._entries.move_to_end(sha256)
        while len(self._entries) > self.max_entries:
            self._entries.popitem(last=False)

    def pop(self, sha256: str) -> None:
        self._entries.pop(sha256, None)

    def clear(self) -> None:
        self._entries.clear()


preview_cache = CvPreviewCache()
