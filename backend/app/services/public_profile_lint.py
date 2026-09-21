"""Deterministyczna kontrola publicznego opisu rekrutacji przed publikacją.

Strona kariery nie pokazuje nazwy klienta ani stawki (decyzja Artura
21.09.2026). Szkic AI dostaje zakaz w prompcie, ale prompt nie jest
gwarancją — a rekruter może dopisać cokolwiek ręcznie. Dlatego zatwierdzenie
przechodzi przez tę funkcję i odmawia przy KAŻDYM znalezisku.

Czysta funkcja (bez bazy): wołający podaje teksty, nazwy klienta z aliasami
i nazwiska osób z rekrutacji. Dzięki temu te same reguły czyta podgląd
(``findings`` w GET) i bramka zatwierdzenia.

Świadomie nadgorliwa: fałszywy alarm kosztuje rekrutera jedno przepisanie
zdania, przeoczenie — nazwę klienta albo stawkę na publicznym LinkedInie.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Iterable

from app.services.client_portfolio_import import (
    loose_client_name,
    normalize_client_name,
)

CODE_CLIENT = "client_name"
CODE_MONEY = "money"
CODE_CONTACT = "contact"
CODE_PERSON = "person_name"

_MIN_NAME_KEY = 3
_EXCERPT_MAX = 120

_CURRENCY = r"(?:zł|zl|pln|eur|euro|€|usd|\$|gbp|£|chf)"
_RATE_UNIT = r"(?:h|godz\.?|godzin[ęy]?|md|mc|mies\.?|miesi[ąa]c|dzie[ńn]|dni[ea]?|day|hour|month)"
_NUMBER = r"\d[\d\s.,]*"

_MONEY_PATTERNS = (
    # „180 zł", „25 000 PLN", „20k PLN", „15 tys. zł"
    re.compile(
        rf"{_NUMBER}\s*(?:k|tys\.?|tysi[ęe]cy)?\s*{_CURRENCY}(?![a-ząćęłńóśźż])",
        re.IGNORECASE,
    ),
    # „PLN 180", „zł 150"
    re.compile(rf"(?<![a-ząćęłńóśźż]){_CURRENCY}\s*{_NUMBER}", re.IGNORECASE),
    # „180/h", „25k/mc", „1200 / MD", „k/h"
    re.compile(rf"(?:{_NUMBER}\s*k?|\bk)\s*/\s*{_RATE_UNIT}\b", re.IGNORECASE),
    # „stawka 180", „budżet do 25 000", „widełki 20-25"
    re.compile(
        r"\b(?:stawk\w*|bud[żz]et\w*|wynagrodzeni\w*|wide[łl]k\w*|rate|salary)"
        r"\W{1,3}(?:\w+\W{1,3}){0,5}\d{2,}",
        re.IGNORECASE,
    ),
)
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", re.IGNORECASE)
_PHONE = re.compile(r"(?<!\d)(?:\+\d{2}[\s-]?)?\d{3}[\s-]?\d{3}[\s-]?\d{3}(?!\d)")
# Zdanie kończy się kropką, po której zaczyna się wielka litera — skróty
# („tys. zł", „godz.") nie tną zdania w pół kwoty.
_SEGMENT_SPLIT = re.compile(r"(?<=[.!?;])\s+(?=[A-ZĄĆĘŁŃÓŚŹŻ0-9])|\n+")


@dataclass(frozen=True)
class Finding:
    code: str
    message: str
    excerpt: str

    def as_dict(self) -> dict:
        return asdict(self)


def _segments(text: str) -> list[str]:
    return [seg.strip() for seg in _SEGMENT_SPLIT.split(text) if seg and seg.strip()]


def _excerpt(segment: str, start: int | None = None, end: int | None = None) -> str:
    seg = segment.strip()
    if len(seg) <= _EXCERPT_MAX:
        return seg
    if start is None or end is None:
        return seg[: _EXCERPT_MAX - 1].rstrip() + "…"
    pad = max(0, (_EXCERPT_MAX - (end - start)) // 2)
    lo = max(0, start - pad)
    hi = min(len(seg), end + pad)
    out = seg[lo:hi].strip()
    return ("…" if lo > 0 else "") + out + ("…" if hi < len(seg) else "")


def _name_keys(names: Iterable[str | None], *, loose: bool) -> list[str]:
    keys: list[str] = []
    for raw in names:
        for key in (
            normalize_client_name(raw),
            loose_client_name(raw) if loose else "",
        ):
            key = key.strip()
            if len(key) >= _MIN_NAME_KEY and key not in keys:
                keys.append(key)
    return keys


def _contains_key(segment: str, key: str) -> bool:
    return f" {key} " in f" {normalize_client_name(segment)} "


def lint_public_texts(
    texts: Iterable[str | None],
    *,
    client_names: Iterable[str | None] = (),
    person_names: Iterable[str | None] = (),
) -> list[Finding]:
    """Znaleziska w tekstach, które trafią na publiczną stronę."""
    findings: list[Finding] = []
    seen: set[tuple[str, str]] = set()

    def add(code: str, message: str, excerpt: str) -> None:
        marker = (code, excerpt)
        if marker in seen:
            return
        seen.add(marker)
        findings.append(Finding(code=code, message=message, excerpt=excerpt))

    client_keys = _name_keys(client_names, loose=True)
    person_keys: list[str] = []
    for raw in person_names:
        full = normalize_client_name(raw)
        if len(full) >= _MIN_NAME_KEY and " " in full and full not in person_keys:
            person_keys.append(full)
        surname = full.split(" ")[-1] if full else ""
        if len(surname) >= 4 and surname not in person_keys:
            person_keys.append(surname)

    for text in texts:
        if not text or not str(text).strip():
            continue
        for segment in _segments(str(text)):
            for key in client_keys:
                if _contains_key(segment, key):
                    excerpt = _excerpt(segment)
                    add(
                        CODE_CLIENT,
                        f"Wykryto nazwę klienta: „{excerpt}” — na stronie kariery "
                        "nie podajemy klienta.",
                        excerpt,
                    )
                    break
            for pattern in _MONEY_PATTERNS:
                match = pattern.search(segment)
                if match:
                    excerpt = _excerpt(segment, match.start(), match.end())
                    add(
                        CODE_MONEY,
                        f"Wykryto kwotę: „{excerpt}” — stawek nie publikujemy.",
                        excerpt,
                    )
                    break
            email = _EMAIL.search(segment)
            phone = _PHONE.search(segment)
            if email or phone:
                match = email or phone
                excerpt = _excerpt(segment, match.start(), match.end())
                add(
                    CODE_CONTACT,
                    f"Wykryto dane kontaktowe: „{excerpt}” — kandydat aplikuje "
                    "przez formularz.",
                    excerpt,
                )
            for key in person_keys:
                if _contains_key(segment, key):
                    excerpt = _excerpt(segment)
                    add(
                        CODE_PERSON,
                        f"Wykryto nazwisko osoby: „{excerpt}” — na stronie podajemy "
                        "wyłącznie imię rekrutera.",
                        excerpt,
                    )
                    break
    return findings
