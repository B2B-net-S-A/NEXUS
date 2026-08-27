"""Jawny typ zamówienia używany przez nowe formularze.

Historyczne rekordy nie mają tej informacji i pozostają z ``NULL`` w nowych
kolumnach. Ich typ nadal rozpoznają dotychczasowe flagi i matchery klientowe.
"""

from __future__ import annotations

import enum


class OrderType(str, enum.Enum):
    periodic = "periodic"
    cost = "cost"
    md = "md"


ORDER_TYPES: tuple[str, ...] = tuple(item.value for item in OrderType)
