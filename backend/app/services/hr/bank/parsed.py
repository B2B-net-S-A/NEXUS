"""Wspólny kształt wyciągu po parsowaniu (MT940 i CAMT.053)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Literal, Optional

Direction = Literal["debit", "credit"]


class StatementError(ValueError):
    """Plik nie jest wyciągiem, który umiemy przeczytać — komunikat po polsku."""


@dataclass(frozen=True)
class StatementLine:
    #: Numer pozycji w pliku (od 1) — z nim ``statement_line_ref`` jest unikalny.
    index: int
    booked_on: date
    #: Zawsze dodatnia; kierunek mówi ``direction`` (obciążenie = nasz przelew).
    amount: Decimal
    direction: Direction
    currency: str
    title: str
    counterparty_name: str = ""
    #: 26 cyfr NRB albo ``None`` (rachunek zagraniczny / brak w wyciągu).
    counterparty_account: Optional[str] = None
    #: Referencja banku (MT940 ``//…``, CAMT ``AcctSvcrRef``/``EndToEndId``).
    bank_ref: str = ""

    @property
    def line_ref(self) -> str:
        ref = f"{self.index}:{self.bank_ref}" if self.bank_ref else str(self.index)
        return ref[:64]


@dataclass(frozen=True)
class ParsedStatement:
    format: Literal["mt940", "camt053"]
    account: Optional[str]
    currency: Optional[str]
    lines: tuple[StatementLine, ...] = field(default_factory=tuple)


__all__ = ["Direction", "ParsedStatement", "StatementError", "StatementLine"]
