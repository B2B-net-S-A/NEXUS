"""Import wyciągu (MT940 albo CAMT.053) i „opłacono” z banku (R9).

Płace wgrywają wyciąg z rachunku firmy. Dla każdego OBCIĄŻENIA szukamy
rozliczenia osoby z zespołu:

1. **numer KSeF w tytule** — faktura z KSeF przy rozliczeniu; kwota musi być
   równa brutto faktur rozliczenia (pierwotna + korekty), inaczej wiersz
   trafia do „nierozpoznanych” z porównaniem,
2. **rachunek odbiorcy = rachunek osoby** z danych do rozliczeń (pełny numer
   porównujemy w pamięci, po odszyfrowaniu):
   B2B — kwota równa brutto faktur (numer faktury w tytule rozstrzyga remis);
   zlecenie i UoP — kwota dodatnia nie większa niż brutto (na rękę liczy
   Symfonia), miesiąc z tytułu („10/2026”, „październik 2026”) rozstrzyga remis,
3. **numer faktury w tytule** i kwota równa brutto faktur.

Dopasowany wiersz → ``settlements.mark_paid(source='statement')`` (R-A:
idempotentne, opłacone i anulowane bez zmian). Nikt nie oznacza zapłaty
własnego rozliczenia (audyt A2, 19.10.2026): wiersz dopasowany do rozliczenia
importującego zostaje ``unmatched`` z powodem ``own_settlement`` — przypisuje
go ktoś inny z Płac („Przypisz” ma tę samą regułę). Wiersz dotyczący osoby
z zespołu, ale bez pewnego dopasowania, zostaje jako ``unmatched`` do decyzji
Płac („Przypisz” albo „Pomiń”). Obciążenia, które nie dotyczą nikogo z zespołu
(czynsz, ZUS, dostawcy), i uznania nie trafiają do bazy — liczymy je tylko
(„pominięte”), jak faktury od dostawców w KSeF.

Uznania idą osobną ścieżką (``_import_credits``, etap 5 — E8): zapłaty faktur
do klientów (``services/client_invoicing/payments.py``), gdy moduł faktur do
klientów jest włączony, a importujący ma moduł Finanse (``match_credits`` —
trasa sprawdza ``finance_module`` u bieżącego konta). Bez niego uznania są
tylko policzone: same „Płace” nie oznaczają faktury klienta jako zapłaconej
i z wyniku nie wynika, czy numer faktury z tytułu istnieje. Biegną
w SAVEPOINT przed obciążeniami — błąd po tamtej stronie nie zatrzymuje
„opłacono” dla zespołu, a wynik niesie same liczby (Płace nie widzą kwot
klientów). Ponowny import pliku dopisuje tylko uznania, których jeszcze nie
było (np. wyciąg wgrany przed włączeniem modułu albo przez Płace bez Finansów).

Ten sam plik drugi raz nic nie zmienia (skrót SHA-256 pliku + numer pozycji,
indeks unikalny ``uq_payroll_payments_statement_line``); ta sama operacja na
innym pliku (wyciąg dzienny i miesięczny) zostaje jako ``ignored`` z powodem.
Równoległy import tego samego pliku czeka na blokadę doradczą po skrócie.

Rachunki osób i treść wyciągu nie trafiają do logów ani śladu HR — ślad ma
liczby, format i początek skrótu pliku.
"""

from __future__ import annotations

import hashlib
import logging
import re
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field, replace
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.encryption import TokenCipherNotConfigured
from app.models.hr_payroll import PayrollPeriod
from app.models.hr_settlement import (
    EmployeeBillingDetails,
    PayrollPayment,
    PayrollSettlement,
)
from app.models.user import User
from app.services.client_invoicing import payments as client_payments
from app.services.hr import audit, billing_details
from app.services.hr import settlements as settlement_service
from app.services.hr.bank import camt053, mt940
from app.services.hr.bank.finance import PayableInvoice, invoice_gross, matched_invoices
from app.services.hr.bank.parsed import ParsedStatement, StatementError, StatementLine
from app.services.hr.bank.titles import ksef_numbers_in
from app.services.hr.payroll_errors import (
    PayrollConflict,
    PayrollError,
    PayrollForbidden,
    PayrollNotFound,
)
from app.services.hr.payroll_report import money
from app.services.hr_settlement_schema import (
    CURRENCIES,
    REASON_MAX_LENGTH,
    TITLE_MAX_LENGTH,
)

logger = logging.getLogger(__name__)

MAX_STATEMENT_BYTES = 5 * 1024 * 1024
#: Rozliczenia, które wyciąg może opłacić (opłacone — tylko jako dowód duplikatu).
PAYABLE_STATUSES: tuple[str, ...] = ("ready", "approved", "mismatch")
KNOWN_STATUSES: tuple[str, ...] = (*PAYABLE_STATUSES, "paid")
DUPLICATE_REASON = "Ta sama operacja była już na wcześniej wgranym wyciągu."

#: Dopełniacz i mianownik — „za październik 2026”, „października 2026”.
_MONTH_STEMS: tuple[str, ...] = (
    "stycz",
    "lut",
    "mar",
    "kwie",
    "maj",
    "czerw",
    "lip",
    "sierp",
    "wrze",
    "pa[zź]dziern",
    "listopad",
    "grud",
)
_NUMERIC_PERIOD = re.compile(r"(?<!\d)(0?[1-9]|1[0-2])\s*[./-]\s*(20\d{2})(?!\d)")
_NAMED_PERIOD = re.compile(
    r"(?<![a-ząćęłńóśźż])(" + "|".join(_MONTH_STEMS) + r")[a-ząćęłńóśźż]*\s+(20\d{2})",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Candidate:
    """Rozliczenie, które wyciąg może opłacić (dane potrzebne dopasowaniu)."""

    settlement_id: int
    user_id: int
    employment_type: str
    currency: str
    status: str
    year: int
    month: int
    expected_amount: Decimal
    #: Brutto faktur (B2B); ``None`` — zlecenie i UoP albo brak faktury.
    pay_amount: Optional[Decimal]
    ksef_numbers: tuple[str, ...] = ()
    invoice_numbers: tuple[str, ...] = ()


@dataclass(frozen=True)
class Decision:
    settlement_id: Optional[int]
    #: Wiersz dotyczy kogoś z zespołu (zapisujemy go) — także bez dopasowania.
    related: bool
    reason: str
    user_id: Optional[int] = None


@dataclass
class ImportResult:
    format: str
    sha256: str
    already_imported: bool = False
    operations: int = 0
    debits: int = 0
    matched: int = 0
    already_paid: int = 0
    unmatched: int = 0
    duplicates: int = 0
    skipped: int = 0
    accounts_unreadable: bool = False
    paid: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[dict[str, Any]] = field(default_factory=list)
    #: Uznania → zapłaty faktur do klientów (same liczby; ``None`` = nie liczono).
    credits: Optional[dict[str, Any]] = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "format": self.format,
            "statement": self.sha256[:12],
            "already_imported": self.already_imported,
            "operations": self.operations,
            "debits": self.debits,
            "matched": self.matched,
            "already_paid": self.already_paid,
            "unmatched": self.unmatched,
            "duplicates": self.duplicates,
            "skipped": self.skipped,
            "accounts_unreadable": self.accounts_unreadable,
            "paid": self.paid,
            "warnings": self.warnings,
            "credits": self.credits,
        }


# ── Czyste reguły dopasowania ─────────────────────────────────────────────────


def _norm(text_: str) -> str:
    return re.sub(r"\s+", "", (text_ or "").upper())


def periods_in(title: str) -> set[tuple[int, int]]:
    """Miesiące wymienione w tytule: ``10/2026``, ``10.2026``, ``październik 2026``."""

    found = {
        (int(year), int(month)) for month, year in _NUMERIC_PERIOD.findall(title or "")
    }
    for stem, year in _NAMED_PERIOD.findall(title or ""):
        for index, pattern in enumerate(_MONTH_STEMS):
            if re.fullmatch(pattern, stem.lower()):
                found.add((int(year), index + 1))
                break
    return found


def _invoice_in_title(candidate: Candidate, title: str) -> bool:
    flat = _norm(title)
    return any(number and _norm(number) in flat for number in candidate.invoice_numbers)


def _single(
    candidates: Sequence[Candidate], title: str
) -> tuple[Optional[Candidate], str]:
    if len(candidates) == 1:
        return candidates[0], "single"
    if not candidates:
        return None, "none"
    by_invoice = [c for c in candidates if _invoice_in_title(c, title)]
    if len(by_invoice) == 1:
        return by_invoice[0], "invoice_number"
    periods = periods_in(title)
    by_period = [c for c in candidates if (c.year, c.month) in periods]
    if len(by_period) == 1:
        return by_period[0], "period"
    return None, "ambiguous"


def _fits_amount(candidate: Candidate, amount: Decimal) -> bool:
    if candidate.employment_type == "b2b":
        return candidate.pay_amount is not None and candidate.pay_amount == amount
    # Zlecenie i UoP: na rękę ≤ brutto (podatki i składki liczy Symfonia).
    return Decimal("0") < amount <= candidate.expected_amount


def decide(
    line: StatementLine,
    candidates: Sequence[Candidate],
    accounts: dict[str, set[int]],
) -> Decision:
    """Dopasowanie jednego obciążenia (czysta funkcja — testy bez bazy)."""

    amount = money(line.amount)
    same_currency = [c for c in candidates if c.currency == line.currency]

    numbers = set(ksef_numbers_in(line.title))
    if numbers:
        by_ksef = [c for c in same_currency if numbers & set(c.ksef_numbers)]
        if len(by_ksef) == 1:
            found = by_ksef[0]
            if found.status == "paid":
                # Druga zapłata tej samej faktury — do decyzji, nie „już opłacone”.
                return Decision(None, True, "already_paid", found.user_id)
            if found.pay_amount is not None and found.pay_amount == amount:
                return Decision(found.settlement_id, True, "ksef", found.user_id)
            return Decision(None, True, "amount_differs", found.user_id)
        if len(by_ksef) > 1:
            return Decision(None, True, "ambiguous", None)

    people = accounts.get(line.counterparty_account or "", set())
    if people:
        own = [
            c
            for c in same_currency
            if c.user_id in people and c.status in PAYABLE_STATUSES
        ]
        by_amount = [c for c in own if _fits_amount(c, amount)]
        # Zlecenie i UoP: kwota na rękę nie wskazuje rozliczenia (zwrot kosztów
        # też jest „≤ brutto”) — wymagamy miesiąca rozliczenia w tytule.
        periods = periods_in(line.title)
        fitting = [
            c
            for c in by_amount
            if c.employment_type == "b2b" or (c.year, c.month) in periods
        ]
        chosen, how = _single(fitting, line.title)
        user_id = next(iter(people)) if len(people) == 1 else None
        if chosen is not None:
            return Decision(
                chosen.settlement_id, True, f"account_{how}", chosen.user_id
            )
        if not own:
            return Decision(None, True, "no_open_settlement", user_id)
        if by_amount and not fitting:
            return Decision(None, True, "no_period", user_id)
        return Decision(
            None, True, "ambiguous" if fitting else "amount_differs", user_id
        )

    open_b2b = [
        c
        for c in same_currency
        if c.employment_type == "b2b"
        and c.status in PAYABLE_STATUSES
        and _invoice_in_title(c, line.title)
    ]
    if open_b2b:
        fitting = [c for c in open_b2b if _fits_amount(c, amount)]
        if len(fitting) == 1:
            return Decision(
                fitting[0].settlement_id, True, "invoice_number", fitting[0].user_id
            )
        return Decision(
            None,
            True,
            "amount_differs" if not fitting else "ambiguous",
            open_b2b[0].user_id if len({c.user_id for c in open_b2b}) == 1 else None,
        )
    return Decision(None, False, "unrelated")


REASON_LABELS: dict[str, str] = {
    "amount_differs": "Kwota przelewu inna niż do zapłaty.",
    "ambiguous": "Pasuje do kilku rozliczeń — wybierz właściwe.",
    "no_open_settlement": "Osoba nie ma rozliczenia do zapłaty.",
    "no_period": "W tytule nie ma miesiąca rozliczenia — wybierz rozliczenie.",
    "already_paid": "Rozliczenie było już opłacone — sprawdź, czy to nie podwójna zapłata.",
    "own_settlement": "Rozliczenie osoby, która wgrała wyciąg — przypisuje je inna "
    "osoba z Płac.",
}


# ── Odczyt i kontekst z bazy ──────────────────────────────────────────────────


def parse_file(raw: bytes) -> ParsedStatement:
    if not raw:
        raise StatementError("Plik jest pusty.")
    if len(raw) > MAX_STATEMENT_BYTES:
        raise StatementError(
            f"Wyciąg jest większy niż {MAX_STATEMENT_BYTES // (1024 * 1024)} MB."
        )
    if camt053.looks_like(raw):
        return camt053.parse(raw)
    if mt940.looks_like(mt940.decode(raw)):
        return mt940.parse(raw)
    raise StatementError(
        "Nie rozpoznaję formatu — wgraj wyciąg MT940 (.sta, .txt) albo CAMT.053 (.xml)."
    )


async def account_owners(db: AsyncSession) -> tuple[dict[str, set[int]], bool]:
    """Rachunek (26 cyfr) → osoby; ``True`` = nie udało się odszyfrować rachunków."""

    owners: dict[str, set[int]] = defaultdict(set)
    rows = await db.scalars(
        select(EmployeeBillingDetails).where(
            EmployeeBillingDetails.account_encrypted.is_not(None)
        )
    )
    for details in rows:
        try:
            account = billing_details.decrypt_account(details)
        except (TokenCipherNotConfigured, ValueError):
            logger.warning(
                "[payments] nie odszyfrowano rachunków — bez dopasowania po rachunku"
            )
            return {}, True
        if account:
            owners[account].add(details.user_id)
    return dict(owners), False


async def load_candidates(
    db: AsyncSession, statuses: Iterable[str] = KNOWN_STATUSES
) -> list[Candidate]:
    rows = await db.execute(
        select(PayrollSettlement, PayrollPeriod.year, PayrollPeriod.month)
        .join(PayrollPeriod, PayrollPeriod.id == PayrollSettlement.period_id)
        .where(PayrollSettlement.status.in_(tuple(statuses)))
    )
    settlements = rows.all()
    invoices = await matched_invoices(db, [s.id for s, _y, _m in settlements])
    candidates: list[Candidate] = []
    for settlement, year, month in settlements:
        own: list[PayableInvoice] = invoices.get(settlement.id, [])
        candidates.append(
            Candidate(
                settlement_id=settlement.id,
                user_id=settlement.user_id,
                employment_type=settlement.employment_type,
                currency=settlement.currency,
                status=settlement.status,
                year=int(year),
                month=int(month),
                expected_amount=Decimal(settlement.expected_amount),
                pay_amount=invoice_gross(own),
                ksef_numbers=tuple(i.ksef_number for i in own if i.ksef_number),
                invoice_numbers=tuple(i.invoice_number for i in own),
            )
        )
    return candidates


async def _seen_elsewhere(db: AsyncSession, line: StatementLine, sha: str) -> bool:
    if not line.bank_ref:
        return False
    found = await db.scalar(
        select(func.count())
        .select_from(PayrollPayment)
        .where(
            PayrollPayment.kind == "statement_line",
            PayrollPayment.statement_sha256 != sha,
            PayrollPayment.statement_line_ref.endswith(
                f":{line.bank_ref[:48]}", autoescape=True
            ),
            PayrollPayment.amount == money(line.amount),
            PayrollPayment.booked_on == line.booked_on,
        )
    )
    return bool(found)


# ── Import ────────────────────────────────────────────────────────────────────


async def _import_credits(
    db: AsyncSession,
    parsed: ParsedStatement,
    sha: str,
    actor_id: int,
    *,
    match_credits: bool,
) -> dict[str, Any]:
    """Uznania → faktury do klientów; awaria tej ścieżki nie rusza obciążeń."""

    if not match_credits:
        return client_payments.count_credits(parsed).as_dict()
    try:
        async with db.begin_nested():
            outcome = await client_payments.import_credits(
                db, parsed, sha=sha, actor_id=actor_id
            )
    except Exception:  # noqa: BLE001 — wypłaty dla zespołu idą dalej
        logger.exception("[payments] uznania z wyciągu %s pominięte", sha[:12])
        return client_payments.CreditResult(error=True).as_dict()
    return outcome.as_dict()


async def import_statement(
    db: AsyncSession, raw: bytes, *, actor_id: int, match_credits: bool
) -> ImportResult:
    """Wyciąg Płac; ``match_credits`` — importujący ma moduł Finanse (uznania klientów)."""

    parsed = parse_file(raw)
    sha = hashlib.sha256(raw).hexdigest()
    result = ImportResult(format=parsed.format, sha256=sha)
    # Dwa równoległe importy tego samego pliku: drugi czeka i widzi „już był”.
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:key))"),
        {"key": f"hr-statement:{sha}"},
    )
    result.credits = await _import_credits(
        db, parsed, sha, actor_id, match_credits=match_credits
    )
    known = await db.scalar(
        select(func.count())
        .select_from(PayrollPayment)
        .where(
            PayrollPayment.kind == "statement_line",
            PayrollPayment.statement_sha256 == sha,
        )
    )
    result.operations = len(parsed.lines)
    if known:
        result.already_imported = True
        return result

    accounts, unreadable = await account_owners(db)
    result.accounts_unreadable = unreadable
    candidates = await load_candidates(db)
    by_id = {c.settlement_id: c for c in candidates}
    names = {
        int(uid): str(name)
        for uid, name in (
            await db.execute(
                select(User.id, User.name).where(
                    User.id.in_({c.user_id for c in candidates} or {0})
                )
            )
        ).all()
    }
    own_accounts: dict[int, set[str]] = defaultdict(set)
    for account, users in accounts.items():
        for user_id in users:
            own_accounts[user_id].add(account)

    for line in parsed.lines:
        if line.direction != "debit" or line.currency not in CURRENCIES:
            # Uznania i waluty spoza rozliczeń nie dotyczą wypłat dla zespołu.
            result.skipped += 1
            continue
        result.debits += 1
        decision = decide(line, candidates, accounts)
        if not decision.related:
            result.skipped += 1
            continue
        payment = PayrollPayment(
            kind="statement_line",
            amount=money(line.amount),
            currency=line.currency,
            booked_on=line.booked_on,
            title=(line.title or "")[:TITLE_MAX_LENGTH] or None,
            counterparty_last4=(line.counterparty_account or "")[-4:] or None,
            statement_sha256=sha,
            statement_format=parsed.format,
            statement_line_ref=line.line_ref,
            created_by=actor_id,
        )
        if await _seen_elsewhere(db, line, sha):
            payment.match_status = "ignored"
            payment.reason = DUPLICATE_REASON
            db.add(payment)
            result.duplicates += 1
            continue
        if decision.settlement_id is None:
            payment.match_status = "unmatched"
            payment.reason = REASON_LABELS.get(decision.reason)
            db.add(payment)
            result.unmatched += 1
            continue
        candidate = by_id[decision.settlement_id]
        if candidate.user_id == actor_id:
            # Własnego rozliczenia nie oznaczasz jako opłacone — decyzja innej osoby.
            payment.match_status = "unmatched"
            payment.reason = REASON_LABELS["own_settlement"]
            db.add(payment)
            result.unmatched += 1
            continue
        payment.match_status = "matched"
        payment.settlement_id = decision.settlement_id
        db.add(payment)
        await db.flush()
        settlement = await db.get(PayrollSettlement, decision.settlement_id)
        paid = await settlement_service.mark_paid(
            db,
            settlement,
            source="statement",
            amount=money(line.amount),
            paid_on=line.booked_on,
            actor_id=actor_id,
        )
        if paid:
            # Kolejna operacja na to samo rozliczenie w tym pliku = podwójna zapłata.
            candidate = replace(candidate, status="paid")
            by_id[candidate.settlement_id] = candidate
            candidates = [
                candidate if c.settlement_id == candidate.settlement_id else c
                for c in candidates
            ]
            result.matched += 1
            result.paid.append(
                {
                    "settlement_id": candidate.settlement_id,
                    "name": names.get(candidate.user_id, ""),
                    "period": f"{candidate.month:02d}/{candidate.year}",
                    "amount": str(money(line.amount)),
                    "currency": candidate.currency,
                    "booked_on": line.booked_on.isoformat(),
                }
            )
        else:
            result.already_paid += 1
        known_accounts = own_accounts.get(candidate.user_id, set())
        if (
            line.counterparty_account
            and known_accounts
            and line.counterparty_account not in known_accounts
        ):
            result.warnings.append(
                {
                    "code": "other_account",
                    "settlement_id": candidate.settlement_id,
                    "name": names.get(candidate.user_id, ""),
                    "message": (
                        "Przelew poszedł na inny rachunek niż w danych do rozliczeń "
                        f"(•• {line.counterparty_account[-4:]})."
                    ),
                }
            )

    await db.flush()
    audit.record(
        db,
        actor_user_id=actor_id,
        subject_user_id=None,
        entity_type="bank_statement",
        entity_id=sha[:12],
        action="statement_imported",
        sensitivity="payroll",
        details={
            "format": parsed.format,
            "operations": result.operations,
            "matched": result.matched,
            "already_paid": result.already_paid,
            "unmatched": result.unmatched,
            "duplicates": result.duplicates,
            "skipped": result.skipped,
            "accounts_unreadable": unreadable,
        },
    )
    return result


# ── Nierozpoznane: lista, przypisanie, pominięcie ─────────────────────────────


async def _line(db: AsyncSession, payment_id: int) -> PayrollPayment:
    payment = await db.scalar(
        select(PayrollPayment)
        .where(
            PayrollPayment.id == payment_id,
            PayrollPayment.kind == "statement_line",
        )
        .with_for_update()
    )
    if payment is None:
        raise PayrollNotFound("Nie ma takiej operacji z wyciągu.")
    if payment.match_status != "unmatched":
        raise PayrollConflict("Ta operacja jest już rozstrzygnięta.")
    return payment


async def unmatched_lines(db: AsyncSession) -> list[dict[str, Any]]:
    """Nierozpoznane operacje z podpowiedzią: rozliczenia osób o tych 4 cyfrach."""

    lines = list(
        await db.scalars(
            select(PayrollPayment)
            .where(
                PayrollPayment.kind == "statement_line",
                PayrollPayment.match_status == "unmatched",
            )
            .order_by(PayrollPayment.booked_on.desc(), PayrollPayment.id)
        )
    )
    if not lines:
        return []
    owners: dict[str, set[int]] = defaultdict(set)
    for user_id, last4 in (
        await db.execute(
            select(
                EmployeeBillingDetails.user_id, EmployeeBillingDetails.account_last4
            ).where(EmployeeBillingDetails.account_last4.is_not(None))
        )
    ).all():
        owners[str(last4)].add(int(user_id))
    candidates = await load_candidates(db, PAYABLE_STATUSES)
    names = {
        int(uid): str(name)
        for uid, name in (
            await db.execute(
                select(User.id, User.name).where(
                    User.id.in_({c.user_id for c in candidates} or {0})
                )
            )
        ).all()
    }
    out: list[dict[str, Any]] = []
    for line in lines:
        people = owners.get(line.counterparty_last4 or "", set())
        hints = [
            {
                "settlement_id": c.settlement_id,
                "name": names.get(c.user_id, ""),
                "period": f"{c.month:02d}/{c.year}",
                "employment_type": c.employment_type,
                "to_pay": str(c.pay_amount) if c.pay_amount is not None else None,
                "expected_amount": str(c.expected_amount),
                "currency": c.currency,
            }
            for c in candidates
            if c.user_id in people and c.currency == line.currency
        ]
        out.append(
            {
                "id": line.id,
                "booked_on": line.booked_on.isoformat() if line.booked_on else None,
                "amount": str(line.amount),
                "currency": line.currency,
                "title": line.title or "",
                "reason": line.reason,
                "counterparty_last4": line.counterparty_last4,
                "format": line.statement_format,
                "hints": hints,
            }
        )
    return out


async def assign_line(
    db: AsyncSession, payment_id: int, settlement_id: int, *, actor_id: int
) -> dict[str, Any]:
    """„Przypisz” operację z wyciągu — te same strażniki co ręczne „opłacono”.

    Własnego rozliczenia nikt nie oznacza jako opłacone (403), a opłacone
    i anulowane nie przyjmują kolejnej zapłaty (409) — druga zapłata tej
    samej faktury zostaje nierozpoznana, do wyjaśnienia. Rozliczenie bez
    dokumentu albo z nierozwiązaną rozbieżnością — 409, przelew B2B o kwocie
    innej niż brutto faktur — 422 (``ensure_payable_by_hand``, 19.10.2026);
    operacja zostaje wtedy nierozpoznana.
    """

    payment = await _line(db, payment_id)
    settlement = await settlement_service.lock_settlement(db, settlement_id)
    if settlement is None:
        raise PayrollNotFound("Nie ma takiego rozliczenia.")
    if settlement.user_id == actor_id:
        raise PayrollForbidden("Własnego rozliczenia nie oznaczasz jako opłacone.")
    if settlement.status == "cancelled":
        raise PayrollConflict("To rozliczenie jest anulowane.")
    if settlement.status == "paid":
        raise PayrollConflict(
            "To rozliczenie jest już opłacone — sprawdź, czy to nie podwójna zapłata."
        )
    if settlement.currency != payment.currency:
        raise PayrollError("Waluta przelewu jest inna niż waluta rozliczenia.")
    await settlement_service.ensure_payable_by_hand(
        db, settlement, amount=Decimal(payment.amount)
    )
    payment.settlement_id = settlement.id
    payment.match_status = "matched"
    await db.flush()
    paid = await settlement_service.mark_paid(
        db,
        settlement,
        source="statement",
        amount=Decimal(payment.amount),
        paid_on=payment.booked_on,
        actor_id=actor_id,
    )
    audit.record(
        db,
        actor_user_id=actor_id,
        subject_user_id=settlement.user_id,
        entity_type="payroll_payment",
        entity_id=payment.id,
        action="statement_line_assigned",
        sensitivity="payroll",
        details={"settlement_id": settlement.id, "paid": paid},
    )
    return {"id": payment.id, "settlement_id": settlement.id, "paid": paid}


async def ignore_line(
    db: AsyncSession, payment_id: int, *, reason: str, actor_id: int
) -> dict[str, Any]:
    note = (reason or "").strip()
    if len(note) < 3:
        raise PayrollError("Podaj powód pominięcia (co najmniej 3 znaki).")
    payment = await _line(db, payment_id)
    payment.match_status = "ignored"
    payment.reason = note[:REASON_MAX_LENGTH]
    await db.flush()
    audit.record(
        db,
        actor_user_id=actor_id,
        subject_user_id=None,
        entity_type="payroll_payment",
        entity_id=payment.id,
        action="statement_line_ignored",
        sensitivity="payroll",
        details={"reason": payment.reason},
    )
    return {"id": payment.id, "match_status": "ignored"}


async def recent_imports(db: AsyncSession, *, limit: int = 5) -> list[dict[str, Any]]:
    """Ostatnie wgrane wyciągi (zapisane operacje dotyczące zespołu)."""

    rows = await db.execute(
        select(
            PayrollPayment.statement_sha256,
            PayrollPayment.statement_format,
            func.min(PayrollPayment.created_at),
            func.max(PayrollPayment.booked_on),
            func.count(),
            func.count().filter(PayrollPayment.match_status == "matched"),
            func.count().filter(PayrollPayment.match_status == "unmatched"),
        )
        .where(PayrollPayment.kind == "statement_line")
        .group_by(PayrollPayment.statement_sha256, PayrollPayment.statement_format)
        .order_by(func.min(PayrollPayment.created_at).desc())
        .limit(limit)
    )
    return [
        {
            "statement": str(sha)[:12],
            "format": fmt,
            "imported_at": imported.isoformat() if imported else None,
            "last_booked_on": last.isoformat() if last else None,
            "lines": int(total),
            "matched": int(matched),
            "unmatched": int(unmatched),
        }
        for sha, fmt, imported, last, total, matched, unmatched in rows.all()
    ]


__all__ = [
    "Candidate",
    "Decision",
    "ImportResult",
    "MAX_STATEMENT_BYTES",
    "REASON_LABELS",
    "account_owners",
    "assign_line",
    "decide",
    "ignore_line",
    "import_statement",
    "load_candidates",
    "parse_file",
    "periods_in",
    "recent_imports",
    "unmatched_lines",
]
