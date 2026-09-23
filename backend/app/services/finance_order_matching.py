"""Client-scoped order-number matching for Finance imports.

Finance worksheets carry the numeric SAP order identifier in ``Uwagi``.
Polkomtel stores the same identifier with the literal ``SAP`` prefix on the
order group.  The generic matcher must stay exact: BIK, BNP and every other
client keep their existing identifiers and must not inherit a broad
"digits-only" normalization.
"""

from __future__ import annotations

import re
from collections.abc import Iterable


# Canonical production client pinned by the order-type policy and the
# Polkomtel import completion report.  Tests move this gate to their freshly
# seeded client; matching by name is deliberately forbidden because Traffit
# can update client names.
POLKOMTEL_CLIENT_ID = 15

# Only the documented Polkomtel representation is normalized.  In particular,
# an arbitrary identifier containing digits (``PO-123`` / ``123/2026``) is not
# collapsed to those digits, which would create cross-client false matches.
_POLKOMTEL_SAP_ORDER_RE = re.compile(r"^SAP[\s:-]*(\d+)$", re.IGNORECASE)


def polkomtel_numeric_order_number(
    client_id: int | None, order_number: str | None
) -> str | None:
    """Return the numeric suffix of a canonical Polkomtel ``SAP`` number.

    ``None`` means "do not normalize".  The full-string regex is intentional:
    partial or compound numbers fail closed instead of being guessed.
    """

    if client_id != POLKOMTEL_CLIENT_ID or order_number is None:
        return None
    match = _POLKOMTEL_SAP_ORDER_RE.fullmatch(str(order_number).strip())
    return match.group(1) if match else None


def finance_order_number_matches(
    *,
    client_id: int | None,
    order_number: str | None,
    numeric_hints: Iterable[str],
) -> bool:
    """Match a stored order number against numeric hints from Finance.

    Existing exact behaviour is preserved first.  The sole extra equivalence
    is ``SAP 1234567`` <-> ``1234567`` for canonical Polkomtel.
    """

    if order_number is None:
        return False
    hints = frozenset(str(hint).strip() for hint in numeric_hints if str(hint).strip())
    stored = str(order_number).strip()
    if stored in hints:
        return True
    numeric = polkomtel_numeric_order_number(client_id, stored)
    return numeric is not None and numeric in hints


# ── Jawny numer zamówienia w wierszu importu MD (ticket 23.09.2026) ─────────
#
# Arkusz Finansów niesie numer zamówienia w „Uwagach". Do 09.2026 import MD per
# konsultant czytał go wyłącznie u Polkomtela — u BIK dwa wiersze tej samej
# osoby z DWOMA różnymi numerami (stare i nowe zamówienie w jednym miesiącu)
# lądowały na jednym zamówieniu albo w „Wymaga przypisania". Numer wskazany
# wprost w wierszu jest teraz wiążący u każdego klienta: wiersz trafia
# wyłącznie na zamówienie o tym numerze albo nigdzie.
#
# „Uwagi" niosą też inne liczby („w tym delegacja 318", rok „2026"), więc
# wiążący jest tylko ciąg cyfr, który ZNAMY jako numer zamówienia, albo ciąg
# na tyle długi, że nie jest ani rokiem, ani kwotą z dopisku (numery SAP mają
# 10 cyfr). Nieznany długi numer też jest wiążący — literówka w numerze nie
# może zamienić się w ciche przypisanie do innego zamówienia tej osoby.
EXPLICIT_ORDER_NUMBER_MIN_DIGITS = 7


def known_order_number_keys(
    groups: Iterable[tuple[int | None, str | None]],
) -> frozenset[str]:
    """Numery zamówień w formie, w jakiej mogą stać w „Uwagach".

    ``groups`` to pary ``(client_id, order_number)``. Polkomtel dostaje obie
    formy (``SAP 4500…`` i sam ciąg cyfr), reszta — numer dosłownie.
    """

    keys: set[str] = set()
    for client_id, order_number in groups:
        if order_number is None:
            continue
        stored = str(order_number).strip()
        if not stored:
            continue
        keys.add(stored)
        numeric = polkomtel_numeric_order_number(client_id, stored)
        if numeric is not None:
            keys.add(numeric)
    return frozenset(keys)


def explicit_order_hints(
    hints: Iterable[str], known_order_numbers: frozenset[str]
) -> list[str]:
    """Ciągi cyfr z „Uwag", które wskazują zamówienie wprost (kolejność zachowana)."""

    explicit: list[str] = []
    for hint in hints:
        value = str(hint).strip()
        if not value:
            continue
        if (
            value in known_order_numbers
            or len(value) >= EXPLICIT_ORDER_NUMBER_MIN_DIGITS
        ):
            explicit.append(value)
    return explicit
