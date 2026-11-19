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
class BalanceCheck:
    """Saldo jednego wyciągu z pliku: otwarcie + operacje ma dać zamknięcie banku.

    Powstaje tylko, gdy wyciąg ma oba salda (MT940 ``:60F:``/``:60M:`` i
    ``:62F:``/``:62M:``, CAMT.053 ``OPBD``/``PRCD`` i ``CLBD``). Kwoty ze
    znakiem: obciążenie i saldo debetowe są ujemne.

    Daty sald i numer wyciągu banku służą ciągłości wyciągów rachunku
    (``ledger/bank_continuity.py``); ``None`` = bank ich nie podał albo nie
    umiemy ich przeczytać.
    """

    #: Numer wyciągu (części wyciągu) w pliku, od 1.
    statement: int
    opening: Decimal
    movement: Decimal
    closing: Decimal
    #: Data salda otwarcia (MT940 ``:60F:``, CAMT ``Bal/Dt``). Santander
    #: (eBI24) podaje dzień samego wyciągu, standard SWIFT — dzień poprzedniego.
    opening_day: Optional[date] = None
    #: Data salda zamknięcia (MT940 ``:62F:``, CAMT ``CLBD``).
    closing_day: Optional[date] = None
    #: Numer wyciągu banku bez numeru części (MT940 ``:28C:`` „26101/1” → 26101,
    #: CAMT ``LglSeqNb``, a bez niego ``ElctrncSeqNb``).
    number: Optional[int] = None

    @property
    def expected(self) -> Decimal:
        return self.opening + self.movement

    @property
    def ok(self) -> bool:
        return self.expected == self.closing


@dataclass(frozen=True)
class ParsedStatement:
    format: Literal["mt940", "camt053"]
    account: Optional[str]
    currency: Optional[str]
    lines: tuple[StatementLine, ...] = field(default_factory=tuple)
    #: Rachunki wszystkich wyciągów w pliku (``:25:`` / ``Stmt/Acct``), po kolei;
    #: ``account`` to tylko jeden z nich. Księga (K4a) odrzuca plik z kilkoma.
    accounts: tuple[str, ...] = ()
    #: Salda wyciągów, które je mają. Księga (K4a) odrzuca plik, w którym saldo
    #: się nie zgadza (plik ucięty albo uszkodzony).
    balances: tuple[BalanceCheck, ...] = ()


__all__ = [
    "BalanceCheck",
    "Direction",
    "ParsedStatement",
    "StatementError",
    "StatementLine",
]
