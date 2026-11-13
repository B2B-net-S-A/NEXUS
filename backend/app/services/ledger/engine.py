"""Reguły księgi bez bazy (K1): konta, bilans dekretu, storno, etykiety.

Kwoty w groszach (``int``), jak dekret E2. Strona ``debit`` = Wn, ``credit`` =
Ma. Storno czerwone: te same strony, kwoty z przeciwnym znakiem — obroty kont
nie rosną sztucznie, a suma Wn i Ma dokumentu dalej się zgadza.

Konto pozycji musi być w planie kont, aktywne i bez kont analitycznych pod
sobą. Wyjątek: analityka słownikowa — konto syntetyczne ze słownikiem
(``dictionary``, np. ``201-2`` → kontrahenci) przyjmuje konta ``201-2-NNN``,
których nie trzeba zakładać w planie jedno po drugim (tak prowadzi je Symfonia
i kartoteka kontrahentów z E0).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import date
from typing import Optional

from app.services.finance_ledger.costs import LedgerError
from app.services.finance_ledger.posting import clean_account, money_pl
from app.services.ledger_schema import (
    DESCRIPTION_MAX,
    DOC_TYPES,
    LINE_TEXT_MAX,
    LINES_MAX,
    MPK_MAX,
    NUMBER_MAX,
    SIDES,
)

DOC_TYPE_LABELS: dict[str, str] = {
    "FVS": "Faktura sprzedaży",
    "FVZ": "Faktura zakupu",
    "WB": "Wyciąg bankowy",
    "LP": "Lista płac",
    "AM": "Amortyzacja",
    "RMK": "Rozliczenie RMK",
    "VAT": "Rozliczenie VAT",
    "PK": "Polecenie księgowania",
    "BO": "Bilans otwarcia",
    "ST": "Storno",
}
assert set(DOC_TYPE_LABELS) == set(DOC_TYPES)
#: Typy zakładane ręcznie na ekranie „Dokumenty”; reszta przychodzi ze źródeł.
MANUAL_TYPES: tuple[str, ...] = ("PK", "BO")
SIDE_LABELS: dict[str, str] = {"debit": "Wn", "credit": "Ma"}
YEAR_MODE_LABELS: dict[str, str] = {
    "symfonia": "Symfonia FK — NEXUS przygotowuje paczki",
    "parallel": "Równolegle — paczki do Symfonii i księga NEXUSA",
    "nexus": "NEXUS — księga urzędowa",
}
ACCOUNT_TYPE_LABELS: dict[str, str] = {
    "active": "bilansowe aktywne",
    "passive": "bilansowe pasywne",
    "mixed": "bilansowe aktywno-pasywne",
    "result": "wynikowe",
    "off_balance": "pozabilansowe",
}
DICTIONARY_LABELS: dict[str, str] = {
    "counterparty": "kontrahenci",
    "mpk": "MPK",
    "tax_office": "urzędy",
    "bank": "rachunki bankowe",
}
MONTHS_PL: tuple[str, ...] = (
    "styczeń",
    "luty",
    "marzec",
    "kwiecień",
    "maj",
    "czerwiec",
    "lipiec",
    "sierpień",
    "wrzesień",
    "październik",
    "listopad",
    "grudzień",
)


@dataclass(frozen=True)
class PlanAccount:
    number: str
    name: str
    kind: str
    active: bool
    dictionary: Optional[str] = None
    has_children: bool = False


@dataclass(frozen=True)
class LineIn:
    side: str
    account: str
    amount: int
    description: str = ""
    counterparty_id: Optional[int] = None
    mpk: Optional[str] = None
    currency: str = "PLN"
    amount_cur: Optional[int] = None


@dataclass(frozen=True)
class Resolved:
    """Konto pozycji po rozpoznaniu: konto z planu i czy to analityka słownika."""

    plan: PlanAccount
    analytic: bool


@dataclass
class Totals:
    debit: int = 0
    credit: int = 0
    issues: list[str] = field(default_factory=list)

    @property
    def balanced(self) -> bool:
        return self.debit == self.credit


def plan_from_rows(
    rows: Iterable[tuple[str, str, str, bool, Optional[str]]],
) -> dict[str, PlanAccount]:
    """``(numer, nazwa, rodzaj, aktywne, słownik)`` → plan z flagą „ma analitykę”.

    Konto ma analitykę, gdy w planie jest konto o numerze zaczynającym się od
    jego numeru i myślnika (``402`` → ``402-203``).
    """

    items = list(rows)
    numbers = {row[0] for row in items}
    parents = {
        "-".join(number.split("-")[:cut])
        for number in numbers
        for cut in range(1, len(number.split("-")))
    }
    return {
        number: PlanAccount(
            number=number,
            name=name,
            kind=kind,
            active=bool(active),
            dictionary=dictionary,
            has_children=number in parents,
        )
        for number, name, kind, active, dictionary in items
    }


def resolve(
    number: str, plan: Mapping[str, PlanAccount]
) -> tuple[Optional[Resolved], Optional[str]]:
    """Konto pozycji → (rozpoznane konto, problem). Dokładnie jedno jest puste."""

    exact = plan.get(number)
    if exact is not None:
        if not exact.active:
            return None, f"Konto {number} jest wyłączone w planie kont."
        if exact.dictionary:
            label = DICTIONARY_LABELS.get(exact.dictionary, exact.dictionary)
            return None, (
                f"Konto {number} prowadzi analitykę ({label}) — księguj na konto "
                f"analityczne, np. {number}-NNN."
            )
        if exact.has_children:
            return None, f"Konto {number} ma konta analityczne — księguj na analitykę."
        return Resolved(exact, analytic=False), None
    parts = number.split("-")
    for cut in range(len(parts) - 1, 0, -1):
        parent = plan.get("-".join(parts[:cut]))
        if parent is None:
            continue
        if parent.dictionary and parent.active:
            return Resolved(parent, analytic=True), None
        if parent.dictionary:
            return None, f"Konto {parent.number} jest wyłączone w planie kont."
        return None, (
            f"Konta {number} nie ma w planie kont — dodaj je albo ustaw słownik "
            f"analityki na koncie {parent.number}."
        )
    return None, f"Konta {number} nie ma w planie kont."


def synthetic_of(number: str, plan: Mapping[str, PlanAccount]) -> str:
    """Konto, pod którym pozycja idzie w zestawieniu syntetycznym."""

    resolved, _ = resolve(number, plan)
    if resolved is not None and resolved.analytic:
        return resolved.plan.number
    return number


def totals(lines: Iterable[LineIn]) -> tuple[int, int]:
    debit = credit = 0
    for line in lines:
        if line.side == "debit":
            debit += line.amount
        else:
            credit += line.amount
    return debit, credit


def check(lines: Sequence[LineIn], plan: Mapping[str, PlanAccount]) -> Totals:
    """Problemy dekretu w kolejności pozycji; pusta lista = można zapisać."""

    result = Totals()
    if len(lines) < 2:
        result.issues.append("Dokument potrzebuje co najmniej dwóch pozycji.")
    if len(lines) > LINES_MAX:
        result.issues.append(f"Dokument ma najwyżej {LINES_MAX} pozycji.")
    for index, line in enumerate(lines, start=1):
        if line.side not in SIDES:
            result.issues.append(f"Pozycja {index}: wybierz stronę Wn albo Ma.")
            continue
        if line.amount == 0:
            result.issues.append(f"Pozycja {index}: kwota nie może być zerem.")
        _, problem = resolve(line.account, plan)
        if problem:
            result.issues.append(f"Pozycja {index}: {problem}")
    result.debit, result.credit = totals(line for line in lines if line.side in SIDES)
    if not result.balanced:
        result.issues.append(
            f"Suma Wn ({money_pl(result.debit)}) różni się od sumy Ma "
            f"({money_pl(result.credit)})."
        )
    return result


def ensure_valid(lines: Sequence[LineIn], plan: Mapping[str, PlanAccount]) -> Totals:
    result = check(lines, plan)
    if result.issues:
        raise LedgerError(result.issues[0], status=422)
    return result


def reversal(lines: Iterable[LineIn]) -> list[LineIn]:
    """Storno czerwone: te same konta i strony, kwoty ze zmienionym znakiem."""

    return [
        replace(
            line,
            amount=-line.amount,
            amount_cur=-line.amount_cur if line.amount_cur is not None else None,
        )
        for line in lines
    ]


def clean_line(raw: Mapping[str, object], index: int) -> LineIn:
    """Pozycja z żądania → ``LineIn`` (konto, strona, grosze, opis, MPK)."""

    side = raw.get("side")
    if side not in SIDES:
        raise LedgerError(f"Pozycja {index}: wybierz stronę Wn albo Ma.", status=422)
    account = clean_account(str(raw.get("account") or ""), f"Pozycja {index}")
    amount = raw.get("amount")
    if not isinstance(amount, int) or isinstance(amount, bool):
        raise LedgerError(f"Pozycja {index}: niepoprawna kwota.", status=422)
    description = " ".join(str(raw.get("description") or "").split())[:LINE_TEXT_MAX]
    mpk_raw = raw.get("mpk")
    mpk = clean_account(str(mpk_raw), f"Pozycja {index} — MPK") if mpk_raw else None
    if mpk is not None and len(mpk) > MPK_MAX:
        raise LedgerError(
            f"Pozycja {index}: MPK ma najwyżej {MPK_MAX} znaków.", status=422
        )
    counterparty = raw.get("counterparty_id")
    if counterparty is not None and (
        not isinstance(counterparty, int) or isinstance(counterparty, bool)
    ):
        raise LedgerError(f"Pozycja {index}: niepoprawny kontrahent.", status=422)
    return LineIn(
        side=str(side),
        account=account,
        amount=amount,
        description=description,
        counterparty_id=counterparty,
        mpk=mpk,
    )


def clean_text(raw: Optional[str], limit: int) -> str:
    return " ".join((raw or "").split())[:limit]


def clean_number(raw: Optional[str]) -> Optional[str]:
    value = clean_text(raw, NUMBER_MAX)
    return value or None


def clean_description(raw: Optional[str]) -> str:
    return clean_text(raw, DESCRIPTION_MAX)


def auto_number_suffix(day: date) -> str:
    return f"/{day.month:02d}/{day.year}"


def auto_number(doc_type: str, seq: int, day: date) -> str:
    """Numer dokumentu bez numeru ze źródła: ``PK 3/10/2026``."""

    return f"{doc_type} {seq}{auto_number_suffix(day)}"


def auto_number_seq(number: str, doc_type: str, day: date) -> Optional[int]:
    """``PK 3/10/2026`` → 3 dla typu PK i października 2026; inny numer → None."""

    prefix, suffix = f"{doc_type} ", auto_number_suffix(day)
    if not (number.startswith(prefix) and number.endswith(suffix)):
        return None
    middle = number[len(prefix) : len(number) - len(suffix)]
    return int(middle) if middle.isdigit() else None


def period_label(year: int, month: int) -> str:
    return f"{MONTHS_PL[month - 1]} {year}"
