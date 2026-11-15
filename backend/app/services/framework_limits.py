"""Limit stawki z umowy ramowej: kategoria × poziom z cennika i dopłata technologiczna.

Umowa ramowa klienta (np. Appendix „Charges” Nordei) podaje maksymalną stawkę
godzinową per kategoria kompetencji i poziom, a dla części kategorii dopłatę
za technologię premium (+10% / +20%). Limit konsultanta to
``maksimum z cennika × (1 + dopłata)``. Dopłata NIE zmienia zamówienia (COA)
ani stawki przychodowej — podnosi tylko limit, do którego porównujemy stawkę
(decyzja Artura z 15.11.2026). Cennik i dopłaty są danymi klienta
(``rate_cards``, ``rate_card_adders``), nigdy kodem: repo jest publiczne.

Tu tylko czyste funkcje; zapis kroku limitu robi ``framework_category``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Iterable, Optional, Sequence

LEVELS = ("Junior", "Senior", "Expert")
_LEVEL_RE = re.compile(r"\s+[-–—]\s*(Junior|Senior|Expert)\b", re.IGNORECASE)
# Kolumna kraju w wierszu COA Nordei („IT Operations - Senior Poland - 1 728 Hours”).
_COUNTRY_TAIL_RE = re.compile(
    r"\s+(?:Poland|Sweden|Finland|Denmark|Norway|Estonia|Latvia|Lithuania)\b.*$",
    re.IGNORECASE,
)
_CENT = Decimal("0.01")


@dataclass(frozen=True)
class CardView:
    id: int
    role: str
    seniority: Optional[str]
    rate_client_max: Optional[int | Decimal]
    valid_from: Optional[date] = None
    valid_to: Optional[date] = None

    @classmethod
    def of(cls, row: Any) -> "CardView":
        return cls(
            id=row.id,
            role=row.role,
            seniority=row.seniority,
            rate_client_max=row.rate_client_max,
            valid_from=row.valid_from,
            valid_to=row.valid_to,
        )


@dataclass(frozen=True)
class AdderView:
    id: int
    technology: str
    percent: Decimal
    eligible: tuple[dict, ...]
    valid_from: Optional[date] = None
    valid_to: Optional[date] = None

    @classmethod
    def of(cls, row: Any) -> "AdderView":
        return cls(
            id=row.id,
            technology=row.technology,
            percent=Decimal(str(row.percent)),
            eligible=tuple(row.eligible or ()),
            valid_from=row.valid_from,
            valid_to=row.valid_to,
        )


def _norm(text: Optional[str]) -> str:
    return (
        re.sub(r"\s+", " ", (text or "").replace("–", "-").replace("—", "-"))
        .strip()
        .casefold()
    )


def _level(value: Optional[str]) -> Optional[str]:
    if not value or not value.strip():
        return None
    for level in LEVELS:
        if value.strip().casefold() == level.casefold():
            return level
    return value.strip()


def parse_category_label(label: Optional[str]) -> Optional[tuple[str, Optional[str]]]:
    """„IT Developer - Senior” → (``IT Developer``, ``Senior``); poziom Regular → ``None``.

    Przyjmuje też ogon wiersza COA z krajem. Kategoria bez poziomu, która sama
    ma myślnik („I&O - Oracle DBA”), zostaje w całości jako rola.
    """
    text = re.sub(
        r"\s+", " ", (label or "").replace("–", "-").replace("—", "-")
    ).strip()
    text = _COUNTRY_TAIL_RE.sub("", text).strip(" -")
    if not text:
        return None
    match = _LEVEL_RE.search(text)
    if match:
        role = text[: match.start()].strip(" -")
        return (role, _level(match.group(1))) if role else None
    return (text, None)


def category_label(role: str, seniority: Optional[str]) -> str:
    return f"{role} - {seniority}" if seniority else role


def _valid(item: CardView | AdderView, on: date) -> bool:
    return (item.valid_from is None or item.valid_from <= on) and (
        item.valid_to is None or item.valid_to >= on
    )


def match_card(
    cards: Iterable[CardView], label: Optional[str], *, on: date
) -> Optional[CardView]:
    """Pozycja cennika dla etykiety kategorii, ważna w dniu ``on``."""
    parsed = parse_category_label(label)
    if parsed is None:
        return None
    role, seniority = parsed
    hits = [
        c
        for c in cards
        if _norm(c.role) == _norm(role)
        and _norm(c.seniority) == _norm(seniority)
        and _valid(c, on)
    ]
    # Kilka ważnych pozycji naraz = nowsza wygrywa (aneks do cennika).
    hits.sort(key=lambda c: (c.valid_from or date.min, c.id))
    return hits[-1] if hits else None


def _eligible(adder: AdderView, card: CardView) -> bool:
    return any(
        _norm(pair.get("role")) == _norm(card.role)
        and _norm(pair.get("seniority")) == _norm(card.seniority)
        for pair in adder.eligible
    )


def addon_choices(
    adders: Sequence[AdderView], card: CardView, *, on: date
) -> list[AdderView]:
    """Dopłaty, które umowa dopuszcza dla tej kategorii i poziomu w dniu ``on``."""
    return sorted(
        (a for a in adders if _valid(a, on) and _eligible(a, card)),
        key=lambda a: (-a.percent, _norm(a.technology)),
    )


def framework_limit(
    card: CardView, addon_percent: Optional[Decimal]
) -> Optional[Decimal]:
    """Maksimum z cennika × (1 + dopłata), do grosza; brak maksimum = brak limitu."""
    if card.rate_client_max is None:
        return None
    base = Decimal(str(card.rate_client_max))
    factor = Decimal(1) + (
        Decimal(str(addon_percent)) / 100 if addon_percent else Decimal(0)
    )
    return (base * factor).quantize(_CENT, rounding=ROUND_HALF_UP)


def percent_text(value: Decimal) -> str:
    """``Decimal("20.00")`` → ``"20"``, ``Decimal("12.50")`` → ``"12.5"`` (bez notacji 2E+1)."""
    return format(Decimal(str(value)).normalize(), "f")
