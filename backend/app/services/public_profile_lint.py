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

Te same reguły czyta ogłoszenie na portale (``services/job_ad/lint.py``).
Od 13.10.2026 jedno źródło ma też to, co wcześniej znało tylko ogłoszenie:
kwoty słownie („200 złotych”, „30 tys. netto”, „2 mln PLN”), linki, telefon
stacjonarny i z numerem kierunkowym, e-mail zapisany jako „jan [at] firma”
oraz porównywanie tekstu bez znaków niewidocznych (``for_lint``).
"""

from __future__ import annotations

import re
import unicodedata
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
# Kwantyfikator zaborczy: liczba, `\s*` i `\s*` wokół mnożnika dzieliły te same
# spacje, więc „1” + 800 spacji + litera liczyło się kilkanaście sekund
# (sześciennie). Klasa liczby nie zawiera żadnego znaku, od którego zaczyna
# się dalszy ciąg wzorca, więc dopasowania są te same.
_NUMBER = r"\d[\d\s.,]*+"
_MULTIPLIER = r"(?:k|tys\.?|tysi[ęe]cy|mln|mld)"
_CURRENCY_WORD = r"(?:z[łl]ot\w*|dolar\w*|funt\w*|czk|nok|dkk|huf|uah)"

# Kwota „na pewno”: liczba z walutą albo ze stawką za jednostkę czasu.
# Ogłoszenie na portale (`job_ad.lint`) blokuje kopiowanie tylko przy nich,
# a liczbę przy samym słowie „stawka”/„rate” traktuje jako uwagę.
CERTAIN_MONEY_PATTERNS = (
    # „180 zł", „25 000 PLN", „20k PLN", „15 tys. zł"
    re.compile(
        rf"{_NUMBER}\s*(?:k|tys\.?|tysi[ęe]cy)?\s*{_CURRENCY}(?![a-ząćęłńóśźż])",
        re.IGNORECASE,
    ),
    # „PLN 180", „zł 150"
    re.compile(rf"(?<![a-ząćęłńóśźż]){_CURRENCY}\s*{_NUMBER}", re.IGNORECASE),
    # „180/h", „25k/mc", „1200 / MD", „k/h"
    re.compile(rf"(?:{_NUMBER}\s*k?|\bk)\s*/\s*{_RATE_UNIT}\b", re.IGNORECASE),
    # „200 złotych", „20 tysięcy złotych", „150 dolarów", „3000 CZK"
    re.compile(
        rf"{_NUMBER}\s*{_MULTIPLIER}?\s*{_CURRENCY_WORD}(?![a-ząćęłńóśźż])",
        re.IGNORECASE,
    ),
    # „2 mln PLN"
    re.compile(
        rf"{_NUMBER}\s*(?:mln|mld)\s*{_CURRENCY}(?![a-ząćęłńóśźż])", re.IGNORECASE
    ),
    # „30 tys. netto", „25k brutto", „180 netto/h"
    re.compile(rf"{_NUMBER}\s*{_MULTIPLIER}?\s*(?:netto|brutto)\b", re.IGNORECASE),
)
_MONEY_PATTERNS = (
    *CERTAIN_MONEY_PATTERNS,
    # „stawka 180", „budżet do 25 000", „widełki 20-25"
    re.compile(
        r"\b(?:stawk\w*|bud[żz]et\w*|wynagrodzeni\w*|wide[łl]k\w*|rate|salary)"
        r"\W{1,3}(?:\w+\W{1,3}){0,5}\d{2,}",
        re.IGNORECASE,
    ),
)
# Runda 9 (R9-V3-4): start tylko na początku ciągu znaków adresu i kwantyfikatory
# zaborcze — dawny wzorzec próbował od KAŻDEJ pozycji długiego ciągu liter
# (kwadratowo; 16 KB bez „@" liczyło się sekundy na tekście z formularza).
_EMAIL = re.compile(r"(?<![\w.+-])[\w.+-]++@[\w-]++(?:\.[\w-]++)+", re.IGNORECASE)
_PHONE = re.compile(r"(?<!\d)(?:\+\d{2}[\s-]?)?\d{3}[\s-]?\d{3}[\s-]?\d{3}(?!\d)")
# Kandydat aplikuje przez formularz — link w opisie wysyła go gdzie indziej
# (zwykle na stronę klienta). Adres bez „http” i „www” tu nie wpada: końcówki
# „.net”, „.io”, „.js” to nazwy technologii (ASP.NET, socket.io, Node.js).
_LINK = re.compile(r"\bhttps?://\S+|\bwww\.\S+", re.IGNORECASE)
# „jan [at] firma", „jan(at)firma(dot)pl". Start tylko na początku ciągu
# znaków adresu i kwantyfikator zaborczy — jak w ``_EMAIL``.
_SPELLED_EMAIL = re.compile(
    r"(?<![\w.+-])[\w.+-]++\s*[\[(]\s*(?:at|ma[łl]pa)\s*[\])]\s*[\w-]+",
    re.IGNORECASE,
)
# „+48 22 555 12 34", „+49 170 1234567"
_PHONE_INTL = re.compile(r"\+\d{1,3}[\s-]?\d(?:[\s-]?\d){7,11}(?!\d)")
# „22 555 12 34", „(22) 555-12-34". Nie w środku ciągu z łącznikami: slug linku
# rekrutacji też przechodzi kontrolę, a nietrafiony adres jest wymieniany.
_PHONE_LANDLINE = re.compile(
    r"(?<![\w-])\(?\d{2}\)?[\s-]\d{3}[\s-]\d{2}[\s-]\d{2}(?!\d)"
)
_CONTACT_PATTERNS = (
    _EMAIL,
    _PHONE,
    _LINK,
    _SPELLED_EMAIL,
    _PHONE_INTL,
    _PHONE_LANDLINE,
)
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


def for_lint(text: str) -> str:
    """Tekst do porównań: NFKC i bez znaków formatujących (kategoria Cf).

    Tekst wklejony z Worda albo PDF-a niesie miękkie łączniki (U+00AD)
    i spacje zerowej szerokości (U+200B). Człowiek ich nie widzi, a nazwa
    klienta z takim znakiem w środku nie jest już nazwą klienta, tak samo
    jak „180 zł” nie jest kwotą. NFKC sprowadza też znaki pełnej szerokości
    („ＰＬＮ” → „PLN”, „＠” → „@”).
    """
    return "".join(
        ch
        for ch in unicodedata.normalize("NFKC", text)
        if unicodedata.category(ch) != "Cf"
    )


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
        for segment in _segments(for_lint(str(text))):
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
            match = next(
                (
                    found
                    for found in (p.search(segment) for p in _CONTACT_PATTERNS)
                    if found
                ),
                None,
            )
            if match:
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
