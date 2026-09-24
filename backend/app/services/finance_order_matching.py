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
from dataclasses import dataclass, field


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
# wprost w wierszu jest teraz wiążący: wiersz trafia wyłącznie na zamówienie
# o tym numerze albo nigdzie.
#
# Wiązanie jest liczone WYŁĄCZNIE względem klientów, u których ta osoba ma
# linie — „Uwagi" niosą też inne liczby („w tym delegacja 318", rok, NIP,
# numer faktury), a numer zamówienia jednego klienta („445") nie może blokować
# dopasowania po nazwisku u innego. Wiąże:
#
# * numer ZNANY jako numer zamówienia tego klienta (dosłownie; Polkomtel także
#   bez prefiksu ``SAP``),
# * u klienta z numerami zamówień z samych cyfr (BIK, Polkomtel) — także
#   nieznany ciąg ≥ 7 cyfr: literówka albo niezarejestrowane zamówienie nie
#   może zamienić się w ciche przypisanie do innego zamówienia tej osoby.
#   Klienci z numerami w innym kształcie (BNP ``87_2026``, CeZ ``CeZ/45/2026``)
#   tej reguły nie dostają — tam długi ciąg cyfr w „Uwagach" nie jest numerem.
EXPLICIT_ORDER_NUMBER_MIN_DIGITS = 7
_DIGITS_ONLY_RE = re.compile(r"^\d+$")


@dataclass(frozen=True)
class OrderNumberIndex:
    """Numery zamówień per klient — do rozpoznania numeru w „Uwagach"."""

    by_client: dict[int, frozenset[str]] = field(default_factory=dict)
    #: Klienci z numerami zamówień z samych cyfr (co najmniej jeden ≥ 7 cyfr).
    numeric_clients: frozenset[int] = frozenset()

    def known(self, client_ids: Iterable[int]) -> frozenset[str]:
        keys: set[str] = set()
        for client_id in client_ids:
            keys |= self.by_client.get(client_id, frozenset())
        return frozenset(keys)


def build_order_number_index(
    groups: Iterable[tuple[int | None, str | None]],
) -> OrderNumberIndex:
    """``groups`` to pary ``(client_id, order_number)`` wszystkich zamówień."""

    by_client: dict[int, set[str]] = {}
    numeric: set[int] = set()
    for client_id, order_number in groups:
        if client_id is None or order_number is None:
            continue
        stored = str(order_number).strip()
        if not stored:
            continue
        keys = by_client.setdefault(client_id, set())
        keys.add(stored)
        digits = polkomtel_numeric_order_number(client_id, stored)
        if digits is not None:
            keys.add(digits)
        else:
            digits = stored if _DIGITS_ONLY_RE.match(stored) else None
        if digits is not None and len(digits) >= EXPLICIT_ORDER_NUMBER_MIN_DIGITS:
            numeric.add(client_id)
    return OrderNumberIndex(
        by_client={k: frozenset(v) for k, v in by_client.items()},
        numeric_clients=frozenset(numeric),
    )


def explicit_order_hints(
    hints: Iterable[str],
    index: OrderNumberIndex | None,
    client_ids: Iterable[int],
) -> list[str]:
    """Ciągi cyfr z „Uwag", które wskazują zamówienie tych klientów wprost."""

    if index is None:
        return []
    clients = frozenset(client_ids)
    known = index.known(clients)
    long_binds = bool(clients & index.numeric_clients)
    explicit: list[str] = []
    for hint in hints:
        value = str(hint).strip()
        if not value:
            continue
        if value in known or (
            long_binds and len(value) >= EXPLICIT_ORDER_NUMBER_MIN_DIGITS
        ):
            explicit.append(value)
    return explicit
