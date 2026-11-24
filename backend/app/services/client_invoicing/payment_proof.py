"""„Po terminie” z wyciągów: zaległość tylko wtedy, gdy NEXUS może ją udowodnić.

19.11.2026 „po terminie” brało każdą fakturę z terminem za sobą, a wyciągi
w Księgowość → Bank były z jednego dnia (2 741 fałszywych zaległości, PR #3620).
Faktura z terminem za sobą i czymś do zapłaty jest „po terminie” dopiero, gdy:

1. **nie jest rozliczana kompensatą** — seria „Benefit” (``COMPENSATION_SERIES``,
   numer według wzoru serii z ustawień albo domyślnego ``…/Benefit``),
2. **ma rachunek odbioru** — nadpisanie przy kliencie dla waluty, a bez niego
   domyślny rachunek waluty (``issue_settings.account_for``), w postaci 26 cyfr
   NRB — i ten rachunek jest w Księgowość → Ustawienia → Rachunki w tej walucie,
3. **wyciągi tego rachunku są ciągłe** od dnia przed wystawieniem do dnia po
   terminie (łańcuch sald, ``ledger/bank_continuity.py``), przy czym liczą się
   tylko wyciągi, których uznania przeszły przez E8 (``credits_matched``)
   i które wgrano, gdy cały łańcuch faktury był już w NEXUSIE — E8 dopasowuje
   uznania tylko do istniejących faktur,
4. **żadna wpłata, której E8 nie przypisało, nie może być jej zapłatą**:
   wpłata do sprawdzenia (E8 ``unmatched``) i duplikat E8, którego oryginał
   zniknął z „Usuń wyciąg”, z numerem faktury albo KSeF w tytule albo w tej
   samej walucie z kwotą równą temu, co zostało do zapłaty; operacja Księgi
   bez konta albo przypisana ręcznie (E8 jej nie zapisało, np. kwota pasowała
   do kilku faktur) w tej samej walucie i kwocie, w dniach od wystawienia do
   końca ciągłości. Same tytuły operacji Księgi się nie liczą: nogi VAT zapłat
   dla dostawców niosą numery cudzych faktur, takie jak nasze (12.11.2026).

Inaczej faktura ma „brak danych o zapłacie” z powodem (``REASONS``). Liczba dni
po terminie liczy się do ostatniego dnia ciągłości (nie do dziś): po nim NEXUS
o wpłatach nie wie. Reguła: ``docs/claude/zamowienia/faktury-do-klientow-z-ksef.md``.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Collection, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import and_, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.models.client_sales_invoice import ClientSalesInvoicePayment
from app.models.ledger import LedgerBankLine, LedgerBankStatement
from app.services.client_invoicing import issue_settings, payments
from app.services.client_invoicing.billing import money
from app.services.client_invoicing.ledger import Chain
from app.services.hr.bank.titles import ksef_numbers_in, number_in_title
from app.services.ledger import settings as ledger_settings
from app.services.ledger.bank_continuity import Span, last_day_from, reach

REASONS: dict[str, str] = {
    "compensation": "rozliczana kompensatą",
    "no_account": "brak rachunku odbioru w ustawieniach wystawiania",
    "account_outside_ledger": "rachunku odbioru nie ma w Księgowość → Ustawienia",
    "statements": "brak ciągłych wyciągów rachunku od wystawienia do dnia po terminie",
    "credit_pending": "wpłata z wyciągu nieprzypisana do faktury może być jej zapłatą",
}

_PATTERN_TOKENS = {
    "{n}": r"\d+",
    "{mm}": r"\d{2}",
    "{m}": r"\d{1,2}",
    "{yyyy}": r"\d{4}",
}
_TOKEN = re.compile("|".join(re.escape(token) for token in _PATTERN_TOKENS))


@dataclass(frozen=True)
class Verdict:
    """Stan „po terminie” jednej faktury (łańcucha)."""

    #: Dni po terminie do ostatniego dnia ciągłości wyciągów (0 = nie po terminie).
    overdue_days: int = 0
    #: Termin minął, jest coś do zapłaty, a zaległości nie da się udowodnić.
    unknown: bool = False
    reason: Optional[str] = None
    #: Cztery ostatnie cyfry rachunku odbioru.
    account: Optional[str] = None
    #: Ostatni dzień ciągłości wyciągów rachunku od wystawienia faktury.
    until: Optional[date] = None


@dataclass(frozen=True)
class KnownStatement:
    id: int
    account: str
    span: Span
    created_at: datetime
    credits_matched: bool


@dataclass(frozen=True)
class PendingCredit:
    """Wpłata z wyciągu, którą E8 zostawiło do sprawdzenia (``unmatched``)."""

    title: str
    amount: Decimal
    currency: str
    booked_on: Optional[date]
    ksef_numbers: frozenset[str] = frozenset()


def compensation_patterns(issue: dict[str, Any]) -> tuple[re.Pattern[str], ...]:
    """Wzory numerów serii kompensat: z ustawień i domyślne (stare faktury z eBI24)."""

    patterns = {
        issue_settings.DEFAULT_SERIES[code]
        for code in issue_settings.COMPENSATION_SERIES
    } | {
        (issue.get("series") or {}).get(code) or ""
        for code in issue_settings.COMPENSATION_SERIES
    }
    out = []
    for pattern in sorted(p for p in patterns if p):
        parts = _TOKEN.split(pattern)
        tokens = _TOKEN.findall(pattern)
        body = re.escape(parts[0]) + "".join(
            _PATTERN_TOKENS[token] + re.escape(part)
            for token, part in zip(tokens, parts[1:])
        )
        out.append(re.compile(rf"\s*{body}\s*", re.IGNORECASE))
    return tuple(out)


def is_compensation(number: Optional[str], patterns: Sequence[re.Pattern[str]]) -> bool:
    text = " ".join((number or "").split())
    return any(pattern.fullmatch(text) for pattern in patterns)


def receiving_account(
    issue: dict[str, Any], client_id: Optional[int], currency: str
) -> Optional[str]:
    """Numer rachunku odbioru z ustawień wystawiania (surowy) albo ``None``."""

    account = issue_settings.account_for(issue, client_id, currency, "PL")
    return account["number"] if account else None


def chain_created_at(chain: Chain) -> Optional[datetime]:
    """Kiedy cały łańcuch (faktura i korekty) był już w NEXUSIE."""

    stamps = [invoice.created_at for invoice in chain.invoices if invoice.created_at]
    return max(stamps) if stamps else None


def pending_for(
    chain: Chain,
    pending: Iterable[PendingCredit],
    *,
    currency: Optional[str] = None,
    amount: Optional[Decimal] = None,
) -> bool:
    """Wpłata do sprawdzenia, która może być zapłatą tej faktury.

    ``currency`` i ``amount`` — zapłata w innej walucie niż faktura (VAT faktury
    walutowej płacony w PLN); bez kwoty porównujemy tylko numery z tytułu.
    """

    head = chain.head
    ksef = {i.ksef_number for i in chain.invoices if i.ksef_number}
    numbers = [i.invoice_number for i in chain.invoices if i.invoice_number]
    wanted = currency or head.currency
    to_pay = chain.own_to_pay if currency is None else amount
    for credit in pending:
        if ksef & credit.ksef_numbers:
            return True
        if any(number_in_title(number, credit.title) for number in numbers):
            return True
        if (
            to_pay is not None
            and credit.currency == wanted
            and money(credit.amount) == to_pay
            and (credit.booked_on is None or credit.booked_on >= head.issue_date)
        ):
            return True
    return False


@dataclass
class Proof:
    """Wszystko, czego trzeba do werdyktu „po terminie” — ładowane raz na żądanie."""

    issue: dict[str, Any]
    #: NRB rachunku z Księgowość → Ustawienia → waluta rachunku.
    ledger_accounts: dict[str, str]
    #: NRB → wyciągi z saldami (po id, czyli w kolejności wgrania).
    statements: dict[str, tuple[KnownStatement, ...]]
    pending: tuple[PendingCredit, ...] = ()
    #: Operacje Księgi bez konta albo przypisane ręcznie: (waluta, grosze) → dni.
    unassigned: dict[tuple[str, int], tuple[date, ...]] = field(default_factory=dict)
    compensation: tuple[re.Pattern[str], ...] = ()
    _reach: dict[tuple[str, tuple[int, ...]], list[tuple[date, date]]] = field(
        default_factory=dict, repr=False
    )

    def __post_init__(self) -> None:
        if not self.compensation:
            self.compensation = compensation_patterns(self.issue)

    def until(
        self, account: str, created_at: Optional[datetime], issued: date
    ) -> Optional[date]:
        """Ostatni dzień ciągłości wyciągów rachunku od dnia przed ``issued``."""

        eligible = tuple(
            statement
            for statement in self.statements.get(account, ())
            if statement.credits_matched
            and created_at is not None
            and statement.created_at > created_at
        )
        key = (account, tuple(statement.id for statement in eligible))
        if key not in self._reach:
            self._reach[key] = reach([statement.span for statement in eligible])
        return last_day_from(self._reach[key], issued)

    def _unassigned_for(
        self, chain: Chain, until: date, currency: str, amount: Optional[Decimal]
    ) -> bool:
        """Operacja Księgi, której E8 nie przypisało, w kwocie tego, co zostało."""

        if amount is None:
            return False
        head = chain.head
        key = (currency, int(money(amount) * 100))
        return any(
            head.issue_date <= day <= until for day in self.unassigned.get(key, ())
        )

    def verdict(
        self,
        chain: Chain,
        today: date,
        *,
        currency: Optional[str] = None,
        amount: Optional[Decimal] = None,
    ) -> Verdict:
        """Werdykt łańcucha; ``currency``/``amount`` — reszta płacona w innej walucie.

        VAT faktury w EUR klient płaci w PLN (``receivables.vat_gap``): wtedy liczą
        się wyciągi rachunku PLN i wpłaty w PLN, a ``amount`` to VAT w PLN
        (``None`` = kursu nie ma, porównujemy tylko numery z tytułów).
        """

        if chain.overdue_days(today) <= 0:
            return Verdict()
        head = chain.head
        wanted = currency or head.currency
        if is_compensation(head.invoice_number, self.compensation):
            return Verdict(unknown=True, reason="compensation")
        raw = receiving_account(self.issue, head.client_id, wanted)
        if raw is None:
            return Verdict(unknown=True, reason="no_account")
        number = ledger_settings.nrb(raw)
        last4 = "".join(ch for ch in raw if ch.isdigit())[-4:] or None
        if not number or self.ledger_accounts.get(number) != wanted:
            return Verdict(unknown=True, reason="account_outside_ledger", account=last4)
        until = self.until(number, chain_created_at(chain), head.issue_date)
        due = head.due_date
        if until is None or due is None or until <= due:
            return Verdict(
                unknown=True, reason="statements", account=last4, until=until
            )
        rest = chain.own_to_pay if currency is None else amount
        if pending_for(
            chain, self.pending, currency=currency, amount=amount
        ) or self._unassigned_for(chain, until, wanted, rest):
            return Verdict(
                unknown=True, reason="credit_pending", account=last4, until=until
            )
        days = (min(until, today) - due).days
        return Verdict(overdue_days=days, account=last4, until=until)


async def load(db: AsyncSession) -> Proof:
    """Ustawienia, rachunki Księgi, wyciągi z saldami i wpłaty do sprawdzenia."""

    issue = await issue_settings.load(db)
    bank = (await ledger_settings.load(db)).bank
    statements: dict[str, list[KnownStatement]] = defaultdict(list)
    rows = await db.execute(
        select(
            LedgerBankStatement.id,
            LedgerBankStatement.bank_account,
            LedgerBankStatement.opening_balance,
            LedgerBankStatement.opening_day,
            LedgerBankStatement.closing_balance,
            LedgerBankStatement.closing_day,
            LedgerBankStatement.first_number,
            LedgerBankStatement.last_number,
            LedgerBankStatement.created_at,
            LedgerBankStatement.credits_matched,
        )
        .where(LedgerBankStatement.closing_balance.is_not(None))
        .order_by(LedgerBankStatement.id)
    )
    for row in rows:
        statements[row.bank_account].append(
            KnownStatement(
                id=row.id,
                account=row.bank_account,
                span=Span(
                    int(row.opening_balance),
                    row.opening_day,
                    int(row.closing_balance),
                    row.closing_day,
                    row.first_number,
                    row.last_number,
                ),
                created_at=row.created_at,
                credits_matched=bool(row.credits_matched),
            )
        )
    pending = tuple(
        PendingCredit(
            title=payment.title or "",
            amount=Decimal(payment.amount),
            currency=payment.currency,
            booked_on=payment.booked_on,
            ksef_numbers=frozenset(ksef_numbers_in(payment.title or "")),
        )
        for payment in await db.scalars(_pending_query())
    )
    unassigned: dict[tuple[str, int], list[date]] = defaultdict(list)
    for currency, amount, booked_on in await db.execute(
        select(
            LedgerBankLine.currency, LedgerBankLine.amount, LedgerBankLine.booked_on
        ).where(
            LedgerBankLine.direction == "credit",
            LedgerBankLine.kind.in_(UNASSIGNED_KINDS),
        )
    ):
        unassigned[(currency, int(amount))].append(booked_on)
    return Proof(
        issue=issue,
        ledger_accounts={account.number: account.currency for account in bank.accounts},
        statements={key: tuple(value) for key, value in statements.items()},
        pending=pending,
        unassigned={key: tuple(days) for key, days in unassigned.items()},
    )


#: Operacje Księgi, których E8 nie przypisało do faktury sprzedaży.
UNASSIGNED_KINDS = ("unmatched", "manual")


def _ref_tail(column: Any) -> Any:
    """Referencja banku z ``statement_line_ref`` („3:ABC” → „ABC”)."""

    return func.substr(column, func.strpos(column, ":") + 1)


def _pending_query() -> Any:
    """Wpłaty do sprawdzenia i duplikaty E8 bez oryginału.

    Duplikat (ta sama operacja na drugim pliku) E8 zapisuje jako ``ignored``.
    Gdy „Usuń wyciąg” skasuje plik z oryginałem, zapłata faktury znika, a duplikat
    zostaje — to wpłata, której NEXUS już nie przypisuje (przegląd 19.11.2026).
    """

    payment = ClientSalesInvoicePayment
    original = aliased(ClientSalesInvoicePayment)
    duplicate = and_(
        payment.match_status == "ignored",
        payment.reason == payments.DUPLICATE_REASON,
    )
    has_original = exists().where(
        original.kind == "statement_line",
        original.statement_sha256 != payment.statement_sha256,
        original.booked_on == payment.booked_on,
        original.amount == payment.amount,
        _ref_tail(original.statement_line_ref) == _ref_tail(payment.statement_line_ref),
        or_(
            original.match_status != "ignored",
            original.reason.is_(None),
            original.reason != payments.DUPLICATE_REASON,
        ),
    )
    return select(payment).where(
        payment.kind == "statement_line",
        or_(payment.match_status == "unmatched", and_(duplicate, ~has_original)),
    )


def reasons_summary(verdicts: Collection[Verdict]) -> list[dict[str, Any]]:
    """Faktury „brak danych o zapłacie” per powód i rachunek (najliczniejsze najpierw)."""

    counts: dict[tuple[str, Optional[str]], int] = defaultdict(int)
    for verdict in verdicts:
        if verdict.unknown:
            counts[(verdict.reason or "statements", verdict.account)] += 1
    return [
        {"reason": reason, "label": REASONS[reason], "account": account, "count": n}
        for (reason, account), n in sorted(
            counts.items(), key=lambda item: (-item[1], item[0][0], item[0][1] or "")
        )
    ]


__all__ = [
    "REASONS",
    "KnownStatement",
    "PendingCredit",
    "Proof",
    "Verdict",
    "chain_created_at",
    "compensation_patterns",
    "is_compensation",
    "load",
    "pending_for",
    "reasons_summary",
    "receiving_account",
]
