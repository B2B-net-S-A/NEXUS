"""Ciągłość wyciągów rachunku firmy — łańcuch sald (19.11.2026).

„Po terminie” faktury do klienta wymaga dowodu, że NEXUS zna każdą wpłatę na
rachunek odbioru od dnia wystawienia do dnia po terminie
(``client_invoicing/payment_proof.py``). Dni operacji tego nie dowodzą:
rachunek EUR ma operacje rzadko, a Santander (eBI24) daje wyciąg tylko w dni
z operacjami (12.11.2026 wyciąg EUR miał numer 156 w roku). Dowodem jest
łańcuch sald:

* **plik** ma saldo otwarcia i zamknięcia z datami (``file_span``) tylko wtedy,
  gdy każda jego część ma oba salda z datami, suma operacji pliku równa się
  sumie zmian sald, a kolejne części łączą się tak jak kolejne pliki (niżej);
* **plik B następuje po A** (``follows``), gdy saldo otwarcia B = saldo
  zamknięcia A, B nie otwiera się przed dniem zamknięcia A, a między nimi nie
  ma dnia bez wyciągu (otwarcie B najpóźniej dzień po zamknięciu A — Santander
  datuje saldo otwarcia dniem samego wyciągu, standard SWIFT dniem
  poprzedniego) albo numery wyciągów banku idą po kolei (``:28C:`` 26156 →
  26157; w nowym roku numer kończy się na 001). Równe saldo nad luką bez
  numerów nie wystarcza: brakujący wyciąg mógł mieć wpływ i wypływ tej samej
  kwoty (wpłata w EUR i jej wymiana na PLN tego samego dnia);
* **ostatni dzień ciągłości** (``covered_until``) liczy się od wyciągu
  otwartego przed danym dniem: przy dacie SWIFT wyciąg z otwarciem w dniu X
  nie obejmuje operacji z dnia X.

Funkcje są czyste (testy bez bazy: ``tests/test_ledger_bank_continuity.py``).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Optional

from app.services.hr.bank.parsed import BalanceCheck, ParsedStatement


@dataclass(frozen=True)
class Span:
    """Saldo otwarcia i zamknięcia wyciągu (pliku albo jego części), grosze ze znakiem."""

    opening_balance: int
    opening_day: date
    closing_balance: int
    closing_day: date
    #: Numer wyciągu banku pierwszej i ostatniej części (``None`` = brak).
    first_number: Optional[int] = None
    last_number: Optional[int] = None


def _grosze(amount: Decimal) -> int:
    return int((Decimal(amount) * 100).to_integral_value())


def numbers_follow(
    previous: Optional[int],
    following: Optional[int],
    previous_day: date,
    following_day: date,
) -> bool:
    """Numer wyciągu ``following`` jest następnym po ``previous`` (także przez Nowy Rok)."""

    if previous is None or following is None:
        return False
    if following == previous + 1:
        return True
    return following_day.year == previous_day.year + 1 and following % 1000 == 1


def follows(previous: Span, following: Span) -> bool:
    """Wyciąg ``following`` zaczyna się dokładnie tam, gdzie skończył się ``previous``."""

    if following.opening_balance != previous.closing_balance:
        return False
    if following.opening_day < previous.closing_day:
        return False
    if following.opening_day <= previous.closing_day + timedelta(days=1):
        return True
    return numbers_follow(
        previous.last_number,
        following.first_number,
        previous.closing_day,
        following.opening_day,
    )


def _part(balance: BalanceCheck) -> Optional[Span]:
    if balance.opening_day is None or balance.closing_day is None:
        return None
    if balance.closing_day < balance.opening_day or not balance.ok:
        return None
    return Span(
        _grosze(balance.opening),
        balance.opening_day,
        _grosze(balance.closing),
        balance.closing_day,
        balance.number,
        balance.number,
    )


def file_span(parsed: ParsedStatement) -> Optional[Span]:
    """Salda całego pliku, gdy plik sam jest ciągły; inaczej ``None``.

    ``None`` nie odrzuca pliku — taki wyciąg po prostu nie dowodzi ciągłości
    (np. część bez salda końcowego, którą Księga przepuszcza bez kontroli).
    """

    if not parsed.balances or len(parsed.balances) != len(parsed.accounts):
        return None
    parts = [_part(balance) for balance in parsed.balances]
    if any(part is None for part in parts):
        return None
    net = sum(
        (
            line.amount if line.direction == "credit" else -line.amount
            for line in parsed.lines
        ),
        Decimal("0"),
    )
    # Operacja poza częścią z saldami (np. bez :60F:) zostałaby bez dowodu.
    if sum((balance.movement for balance in parsed.balances), Decimal("0")) != net:
        return None
    chain = [part for part in parts if part is not None]
    if not all(follows(a, b) for a, b in zip(chain, chain[1:])):
        return None
    return Span(
        chain[0].opening_balance,
        chain[0].opening_day,
        chain[-1].closing_balance,
        chain[-1].closing_day,
        chain[0].first_number,
        chain[-1].last_number,
    )


def reach(spans: Sequence[Span]) -> list[tuple[date, date]]:
    """(dzień otwarcia, ostatni dzień ciągłości łańcucha od tego wyciągu) dla każdego.

    Kolejność wejścia (np. po id wyciągu) rozstrzyga remis dat; krawędzie idą
    tylko do wyciągów dalej w kolejności dat, więc łańcuch nie ma pętli.
    """

    ordered = [
        span
        for _, span in sorted(
            enumerate(spans),
            key=lambda item: (item[1].opening_day, item[1].closing_day, item[0]),
        )
    ]
    ends = [span.closing_day for span in ordered]
    for i in range(len(ordered) - 1, -1, -1):
        for j in range(i + 1, len(ordered)):
            if ends[j] > ends[i] and follows(ordered[i], ordered[j]):
                ends[i] = ends[j]
    return [(span.opening_day, end) for span, end in zip(ordered, ends)]


def covered_until(spans: Sequence[Span], start_before: date) -> Optional[date]:
    """Ostatni dzień ciągłości łańcucha otwartego przed ``start_before`` (``None`` = brak)."""

    return last_day_from(reach(spans), start_before)


def last_day_from(
    reached: Sequence[tuple[date, date]], start_before: date
) -> Optional[date]:
    return max(
        (end for opening, end in reached if opening < start_before), default=None
    )


__all__ = [
    "Span",
    "covered_until",
    "file_span",
    "follows",
    "last_day_from",
    "numbers_follow",
    "reach",
]
