"""Zajęcia wierzytelności kontraktora — reguły bez bazy (23.11.2026).

Komornik albo urząd skarbowy zajmuje wierzytelność kontraktora wobec nas.
Przy paczce przelewów płatność faktury kontraktora dzielimy: należność
zajęcia (koszty + odsetki do dnia przelewu + należność główna, minus to, co
już poszło do organu) idzie na rachunek organu, reszta do kontraktora.

* **Zajęcie działa** od dnia doręczenia do dnia uchylenia (dzień uchylenia
  już bez przelewu do organu).
* **Kilka zajęć naraz**: po kolei od najwcześniej doręczonego; każde bierze
  tyle, ile zostało mu do spłaty, najwyżej resztę płatności.
* **Odsetki**: ``none`` — bez odsetek; ``fixed`` — kwota z pisma organu (nie
  rośnie); ``rate`` — stopa roczna od dnia ``interest_from`` od należności
  głównej, odsetki proste za dni kalendarzowe (rok 365 dni) do dnia przelewu;
  ``unknown`` — nieustalone. Wpłata do organu zalicza się najpierw na koszty,
  potem na odsetki, na końcu na należność główną (art. 451 KC), więc po
  wcześniejszym przelewie odsetki liczą się od mniejszej należności.
* **Kwoty nie da się policzyć** (odsetki nieustalone albo bez stopy lub daty,
  brak albo zły rachunek organu, waluta inna niż złoty, MPP, przelew na konto
  US) = ``GarnishmentError`` — płatność faktury czeka na decyzję księgowej,
  która uzupełnia dane zajęcia albo zmienia tryb przelewu.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional

from app.services.hr.bank.titles import LINE_LENGTH, MAX_LINES, clean

ZERO = Decimal("0.00")
CENT = Decimal("0.01")
DAYS_IN_YEAR = Decimal("365")

AUTHORITY_LABELS: dict[str, str] = {
    "bailiff": "Komornik",
    "tax_office": "Urząd skarbowy",
    "other": "Inny organ",
}
INTEREST_LABELS: dict[str, str] = {
    "none": "Bez odsetek",
    "fixed": "Kwota odsetek z pisma",
    "rate": "Stopa roczna od dnia",
    "unknown": "Nieustalone",
}
#: Dlaczego kwoty zajęcia nie da się policzyć (płatność czeka na księgową).
ERROR_LABELS: dict[str, str] = {
    "interest_unknown": "odsetki nieustalone — wpisz kwotę odsetek albo stopę od dnia",
    "interest_incomplete": "brakuje kwoty odsetek albo stopy i daty, od której "
    "liczyć odsetki",
    "no_account": "brak rachunku organu",
    "bad_account": "rachunek organu ma zły format albo sumę kontrolną",
    "currency": "faktura nie jest w złotych — przelew do organu tylko w PLN",
    "mpp": "przelew w podzielonej płatności (MPP) — oznacz fakturę „NIE MPP” "
    "albo zapłać poza paczką",
    "tax_office_mode": "faktura ma „Zapłata na konto US” — zdejmij flagę albo "
    "zapłać poza paczką",
    "title_too_long": "sygnatura nie mieści się w tytule przelewu (4 × 35 znaków)",
}


class GarnishmentError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(ERROR_LABELS.get(code, code))
        self.code = code


def money(value: Decimal) -> Decimal:
    return Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class Terms:
    """Dane zajęcia potrzebne do policzenia kwoty (kopia wiersza bazy)."""

    id: int
    case_number: str
    authority_name: str
    served_on: date
    principal: Decimal
    costs: Decimal = ZERO
    interest_mode: str = "unknown"
    interest_amount: Optional[Decimal] = None
    interest_rate: Optional[Decimal] = None
    interest_from: Optional[date] = None
    account: Optional[str] = None
    lifted_on: Optional[date] = None

    def active_on(self, day: date) -> bool:
        return self.served_on <= day and (
            self.lifted_on is None or self.lifted_on > day
        )


@dataclass(frozen=True)
class Transfer:
    """Przelew do organu z wcześniejszej paczki (data wykonania, kwota)."""

    on: date
    amount: Decimal


@dataclass(frozen=True)
class Balance:
    """Ile zostało do spłaty zajęcia na dzień przelewu."""

    due: Decimal
    principal: Decimal
    interest: Decimal
    costs: Decimal


def _accrue(principal: Decimal, rate: Decimal, start: date, end: date) -> Decimal:
    days = (end - start).days
    if days <= 0 or principal <= ZERO:
        return Decimal("0")
    return principal * rate / Decimal("100") * Decimal(days) / DAYS_IN_YEAR


def balance_on(terms: Terms, day: date, transfers: Iterable[Transfer]) -> Balance:
    """Należność zajęcia na ``day`` po wcześniejszych przelewach do organu.

    Przelewy z datą po ``day`` (paczka na późniejszy dzień) odejmujemy po
    kwocie, bez odsetek — i tak już wyjdą.
    """

    mode = terms.interest_mode
    if mode == "unknown":
        raise GarnishmentError("interest_unknown")
    if mode == "fixed" and terms.interest_amount is None:
        raise GarnishmentError("interest_incomplete")
    if mode == "rate" and (terms.interest_rate is None or terms.interest_from is None):
        raise GarnishmentError("interest_incomplete")
    principal = Decimal(terms.principal)
    costs = Decimal(terms.costs or 0)
    interest = Decimal(terms.interest_amount or 0) if mode == "fixed" else Decimal("0")
    rate = Decimal(terms.interest_rate or 0)
    last = terms.interest_from
    ordered = sorted(transfers, key=lambda t: t.on)
    later = Decimal("0")
    for transfer in ordered:
        if transfer.on > day:
            later += Decimal(transfer.amount)
            continue
        if mode == "rate" and last is not None:
            interest += _accrue(principal, rate, last, transfer.on)
            last = max(last, transfer.on)
        left = Decimal(transfer.amount)
        for part in ("costs", "interest", "principal"):
            have = {"costs": costs, "interest": interest, "principal": principal}[part]
            take = min(have, left)
            left -= take
            if part == "costs":
                costs -= take
            elif part == "interest":
                interest -= take
            else:
                principal -= take
    if mode == "rate" and last is not None:
        interest += _accrue(principal, rate, last, day)
    due = money(costs) + money(interest) + money(principal) - money(later)
    return Balance(
        due=max(money(due), ZERO),
        principal=money(principal),
        interest=money(interest),
        costs=money(costs),
    )


@dataclass(frozen=True)
class Share:
    terms: Terms
    amount: Decimal
    balance: Balance


def split(
    to_pay: Decimal,
    garnishments: Sequence[tuple[Terms, Balance]],
) -> tuple[list[Share], Decimal]:
    """Płatność → przelewy do organów (od najwcześniej doręczonego) i reszta."""

    rest = money(to_pay)
    shares: list[Share] = []
    for terms, balance in sorted(
        garnishments, key=lambda pair: (pair[0].served_on, pair[0].id)
    ):
        if rest <= ZERO:
            break
        if balance.due <= ZERO:
            continue
        take = min(balance.due, rest)
        shares.append(Share(terms=terms, amount=take, balance=balance))
        rest = money(rest - take)
    return shares, rest


def _wrap(words: Sequence[str]) -> list[str]:
    lines: list[str] = []
    current = ""
    for word in words:
        while len(word) > LINE_LENGTH:
            if current:
                lines.append(current)
                current = ""
            lines.append(word[:LINE_LENGTH])
            word = word[LINE_LENGTH:]
        candidate = f"{current} {word}".strip()
        if len(candidate) <= LINE_LENGTH:
            current = candidate
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def title_lines(
    *,
    case_number: str,
    debtor_nip: Optional[str],
    invoice_number: Optional[str],
) -> list[str]:
    """Tytuł przelewu do organu: sygnatura, dłużnik (NIP) i numer faktury.

    Numer faktury w tytule pozwala dopasować obciążenie z wyciągu do faktury
    (``payment_rules.decide_debit``, rachunek organu jest znany z pozycji paczki).
    """

    case = _wrap(f"Sygn. {clean(case_number)}".split())
    number = clean(invoice_number or "")
    invoice = [f"faktura {number}"] if number else []
    nip = [f"dłużnik NIP {debtor_nip}"] if debtor_nip else []
    label = ["Zajęcie wierzytelności"]
    # Pierwszy układ, który się mieści: sygnatura i numer faktury (dopasowanie
    # wyciągu) zostają zawsze, NIP dłużnika i opis odpadają w tej kolejności.
    for parts in ((label, nip + invoice), (label, invoice), ([], invoice)):
        head, tail = parts
        lines = [*case, *head, *(_wrap(" ".join(tail).split()) if tail else [])]
        if len(lines) <= MAX_LINES:
            return lines
    raise GarnishmentError("title_too_long")


__all__ = [
    "AUTHORITY_LABELS",
    "Balance",
    "ERROR_LABELS",
    "GarnishmentError",
    "INTEREST_LABELS",
    "Share",
    "Terms",
    "Transfer",
    "balance_on",
    "money",
    "split",
    "title_lines",
]
