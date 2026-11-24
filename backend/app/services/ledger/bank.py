"""Wyciąg bankowy w księdze (K4a, zakładka „Bank”) — jeden import wyciągu.

Decyzja Artura z 14.11.2026: wyciąg wgrywa się raz, w Księdze. Plik czytają
istniejące ścieżki, bez zmian w ich kodzie, każda w swoim zakresie
i idempotentnie po skrócie pliku:

* E3 (``finance_ledger.payments.import_debits``) — obciążenia → zapłaty
  faktur kosztowych,
* R9 (``hr.bank.statements.import_statement``) — obciążenia → wypłaty dla
  osób z zespołu; tylko gdy importuje osoba z Płacami (D2), i od razu
  uznania → zapłaty faktur do klientów (E8); bez Płac uznania czyta E8
  (``client_invoicing.payments.import_credits``) wprost.

Wynik każdej pozycji Księga odczytuje z tabel tych ścieżek (skrót pliku +
``line_ref``) i zapisuje w ``ledger_bank_lines`` z kontem przeciwstawnym:
faktura kosztowa → konto rozrachunkowe dostawcy z kartoteki, faktura
sprzedaży → konto odbiorcy (jak FVS w K2), wypłata UoP/zlecenia → rozrachunki
z tytułu wynagrodzeń; reszta regułą: rachunek ZUS (bank 60000002) → konto
ZUS, mikrorachunek podatkowy (10100071 222…) → VAT/PIT/CIT według symbolu
formularza ``/SFP/`` z tytułu, opłata banku (bez rachunku kontrahenta,
„opłata/prowizja” w tytule) → konto opłat. Czego nie rozpoznano, czeka na
przypisanie konta. Ta sama operacja z innego wyciągu (dzienny i miesięczny)
= duplikat, nie wchodzi do WB.

„Zaksięguj wyciąg” robi dokument WB w buforze (Wn/Ma rachunek firmy po każdej
operacji), osobno WB płacowy z wypłatami dla zespołu (D2: robi i widzi go
osoba z Płacami). Źródło ``bank_statement`` / ``<id>`` (``<id>-payroll``),
odcisk jak w K2: zmieniony szkic się przebudowuje, zatwierdzony = storno.
K4c-1: rachunek firmy ma walutę (PLN, EUR, USD); plik musi być w walucie
rachunku. Operacja walutowa dostaje kwotę w PLN po średnim kursie NBP
z ostatniego dnia roboczego przed operacją (art. 30 ust. 2 pkt 2 ustawy
o rachunkowości) — kurs dokładnie z tego dnia, jak w K2 i E2; brak kursu
= odmowa importu, nie cichy starszy kurs. WB z rachunku walutowego jest
dokumentem w PLN z pozycjami walutowymi (kwota w walucie i kurs pozycji).
Rozrachunki z rozliczaniem pozycji — K4b (``settlements``), wycena walut na
koniec okresu — K4c-2.
"""

from __future__ import annotations

import asyncio
import calendar
import hashlib
import re
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import and_, delete, func, select, text, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.client_sales_invoice import (
    ClientSalesInvoice,
    ClientSalesInvoicePayment,
)
from app.models.finance_ledger import FinanceCostEntry, FinanceCounterparty
from app.models.finance_payments import (
    FinanceCostPaymentRecord,
    FinancePaymentBatchItem,
)
from app.models.fx_rate import FxRate
from app.models.hr_settlement import PayrollPayment, PayrollSettlement
from app.models.ledger import LedgerBankLine, LedgerBankStatement, LedgerDocument
from app.services.client_invoicing import ledger as client_ledger
from app.services.client_invoicing import payments as client_payments
from app.services.finance_ledger import identifiers
from app.services.finance_ledger import payments as cost_payments
from app.services.finance_ledger import posting
from app.services.finance_ledger.costs import LedgerError
from app.services.hr.bank import statements as hr_statements
from app.services.hr.bank.parsed import ParsedStatement, StatementError, StatementLine
from app.services.hr.bank.titles import ksef_numbers_in
from app.services.ledger import bank_continuity, documents, engine, sources
from app.services.ledger.documents import DocumentSpec, Viewer
from app.services.ledger.engine import LineIn
from app.services.ledger.settings import (
    BANK_CURRENCIES,
    BankSettings,
    LedgerSettings,
    nrb,
)
from app.services.ledger_bank_schema import NAME_MAX, NOTE_MAX, TITLE_MAX

SOURCE_TYPE = "bank_statement"
ZUS_ROUTING = "60000002"
TAX_ROUTING = "10100071"
TAX_PREFIX = "222"
FEE_WORDS = ("oplata", "oplaty", "prowizja", "prowizje", "abonament")
MATCHED = "matched"
KIND_LABELS: dict[str, str] = {
    "cost_invoice": "Faktura kosztowa",
    "team": "Wypłata dla osoby z zespołu",
    "sales_invoice": "Faktura sprzedaży",
    "zus": "ZUS",
    "tax": "Urząd skarbowy",
    "fee": "Opłata banku",
    "manual": "Przypisana ręcznie",
    "unmatched": "Do wyjaśnienia",
    "duplicate": "Duplikat z innego wyciągu",
}
NO_STATEMENT = "Nie ma takiego wyciągu."
UNREADABLE_TEAM = (
    "Nie da się teraz odczytać rachunków osób z zespołu — import wstrzymany, żeby "
    "wypłaty nie trafiły do osób bez Płacami. Zgłoś to administratorowi."
)
OVERVIEW_MAX = 100
APPROVED_WB = (
    "WB tego wyciągu jest już zatwierdzony (pozycja {journal_no}) — zmiana wymaga "
    "storna dokumentu."
)
_SFP = re.compile(r"/SFP/([A-Z0-9-]+)")
UNDO_WB = (
    "Wyciąg ma dokument WB ({number}) — najpierw usuń szkic albo zrób storno, potem "
    "usuń wyciąg."
)
UNDO_PAYROLL = (
    "Z tego pliku są wypłaty dla zespołu (Płace) — tego importu Księga nie cofa."
)
UNDO_BATCH = (
    "Faktura opłacona tym wyciągiem ma zamkniętą pozycję paczki przelewów — "
    "cofnięcie wymaga decyzji Finansów, nie usunięcia wyciągu."
)
UNDO_EBI24 = (
    "Zapłata z tego wyciągu zastąpiła zapłatę z eBI24 — cofnięcie wymaga decyzji "
    "Finansów, nie usunięcia wyciągu."
)
UNDO_DUPLICATES = (
    "Operacje z tego wyciągu są też w {other} jako duplikaty — po usunięciu tego "
    "pliku zapłaty faktur by zniknęły (koszt wróciłby na „Do zapłaty”). Najpierw "
    "usuń tamten wyciąg, potem ten, i wgraj oba od nowa."
)


def routing(number: str) -> str:
    """Numer rozliczeniowy banku z NRB (cyfry 3–10)."""

    return number[2:10] if len(number) == 26 else ""


def tax_form(title: str) -> str:
    """Symbol formularza z tytułu przelewu podatkowego (``/SFP/VAT-7M``)."""

    match = _SFP.search((title or "").upper())
    return match.group(1) if match else ""


def rule_for(
    direction: str, counterparty_account: str, title: str, bank: BankSettings
) -> tuple[str, Optional[str], str]:
    """Rodzaj, konto przeciwstawne i uwaga dla operacji spoza E3/R9/E8."""

    if direction == "debit" and counterparty_account:
        if routing(counterparty_account) == ZUS_ROUTING:
            return (
                "zus",
                bank.zus_account or None,
                "" if bank.zus_account else "Ustaw konto ZUS w Ustawieniach.",
            )
        if (
            routing(counterparty_account) == TAX_ROUTING
            and counterparty_account[10:13] == TAX_PREFIX
        ):
            form = tax_form(title)
            for prefix, field in (
                ("VAT", "vat_account"),
                ("PIT", "pit_account"),
                ("CIT", "cit_account"),
            ):
                if form.startswith(prefix):
                    account = getattr(bank, field)
                    note = "" if account else f"{form}: ustaw konto w Ustawieniach."
                    return ("tax", account or None, note)
            return (
                "tax",
                None,
                "Przelew do urzędu skarbowego bez znanego symbolu formularza "
                "(/SFP/) — przypisz konto.",
            )
    folded = identifiers.fold(title)
    if not counterparty_account and any(word in folded for word in FEE_WORDS):
        return (
            "fee",
            bank.fees_account or None,
            "" if bank.fees_account else "Ustaw konto opłat bankowych w Ustawieniach.",
        )
    return ("unmatched", None, "")


def grosze(amount: Decimal) -> int:
    return int((Decimal(amount) * 100).to_integral_value())


# ── Import ───────────────────────────────────────────────────────────────────


async def _records(db: AsyncSession, model: Any, sha: str) -> dict[str, Any]:
    rows = await db.scalars(
        select(model).where(
            model.kind == "statement_line", model.statement_sha256 == sha
        )
    )
    return {row.statement_line_ref: row for row in rows if row.statement_line_ref}


async def _cost_accounts(
    db: AsyncSession, entry_ids: set[int]
) -> dict[int, FinanceCounterparty]:
    if not entry_ids:
        return {}
    rows = await db.execute(
        select(FinanceCostEntry.id, FinanceCounterparty)
        .join(
            FinanceCounterparty,
            FinanceCounterparty.id == FinanceCostEntry.counterparty_id,
        )
        .where(FinanceCostEntry.id.in_(entry_ids))
    )
    return {entry_id: party for entry_id, party in rows.all()}


async def _sales_accounts(
    db: AsyncSession, invoice_ids: set[int], default: str
) -> dict[int, tuple[Optional[int], Optional[str]]]:
    """Faktura sprzedaży → (kontrahent, konto rozrachunkowe odbiorcy) jak FVS w K2."""

    if not invoice_ids:
        return {}
    invoices = list(
        await db.scalars(
            select(ClientSalesInvoice).where(ClientSalesInvoice.id.in_(invoice_ids))
        )
    )
    keys = {key for invoice in invoices for key in sources.buyer_keys(invoice)}
    parties: dict[tuple[str, str], FinanceCounterparty] = {}
    if keys:
        # Jedno zapytanie zamiast jednego na fakturę i klucz (import 18.11.2026).
        for party in await db.scalars(
            select(FinanceCounterparty)
            .where(
                tuple_(FinanceCounterparty.id_type, FinanceCounterparty.id_value).in_(
                    keys
                )
            )
            .order_by(FinanceCounterparty.id)
        ):
            parties.setdefault((party.id_type, party.id_value), party)
    out: dict[int, tuple[Optional[int], Optional[str]]] = {}
    for invoice in invoices:
        party = next(
            (parties[key] for key in sources.buyer_keys(invoice) if key in parties),
            None,
        )
        if party is None:
            out[invoice.id] = (None, None)
            continue
        out[invoice.id] = (party.id, sources.receivable_account(party, default))
    return out


async def _team_accounts(
    db: AsyncSession, settlement_ids: set[int], settings: LedgerSettings
) -> dict[int, Optional[str]]:
    """Wypłata UoP/zlecenia zdejmuje netto z rozrachunków z tytułu wynagrodzeń."""

    if not settlement_ids:
        return {}
    rows = await db.execute(
        select(PayrollSettlement.id, PayrollSettlement.employment_type).where(
            PayrollSettlement.id.in_(settlement_ids)
        )
    )
    account = settings.payroll.settlement_account or None
    return {
        settlement_id: account if kind in ("uop", "zlecenie") else None
        for settlement_id, kind in rows.all()
    }


async def _duplicates(
    db: AsyncSession, bank_account: str, lines: tuple[StatementLine, ...]
) -> dict[str, bool]:
    """Operacje, które ten rachunek ma już w innym wyciągu (ta sama referencja banku).

    Wartość = czy oryginał był wypłatą dla zespołu: duplikat dziedziczy D2,
    inaczej ta sama wypłata z wyciągu miesięcznego pokazałaby się osobie bez
    Płac z nazwiskiem i kwotą (przegląd bezpieczeństwa K4a 14.11.2026).
    """

    refs = {line.bank_ref[:48] for line in lines if line.bank_ref}
    if not refs:
        return {}
    rows = await db.execute(
        select(
            LedgerBankLine.bank_ref,
            LedgerBankLine.booked_on,
            LedgerBankLine.amount,
            LedgerBankLine.payroll,
        )
        .join(
            LedgerBankStatement, LedgerBankStatement.id == LedgerBankLine.statement_id
        )
        .where(
            LedgerBankStatement.bank_account == bank_account,
            LedgerBankLine.bank_ref.in_(refs),
        )
    )
    seen: dict[tuple[str, Any, int], bool] = {}
    for ref, day, amount, payroll in rows.all():
        key = (ref, day, amount)
        seen[key] = seen.get(key, False) or bool(payroll)
    out: dict[str, bool] = {}
    for line in lines:
        key = (line.bank_ref[:48], line.booked_on, grosze(line.amount))
        if line.bank_ref and key in seen:
            out[line.line_ref] = seen[key]
    return out


@dataclass(frozen=True)
class Classified:
    kind: str
    counter_account: Optional[str]
    counterparty_id: Optional[int]
    ref_id: Optional[int]
    payroll: bool
    note: str


async def _classify(
    db: AsyncSession,
    lines: tuple[StatementLine, ...],
    sha: str,
    *,
    bank_account: str,
    settings: LedgerSettings,
    owners: dict[str, set[int]],
    candidates: list[Any],
) -> dict[str, Classified]:
    costs = await _records(db, FinanceCostPaymentRecord, sha)
    team = await _records(db, PayrollPayment, sha)
    sales = await _records(db, ClientSalesInvoicePayment, sha)
    duplicates = await _duplicates(db, bank_account, lines)
    cost_parties = await _cost_accounts(
        db,
        {
            row.entry_id
            for row in costs.values()
            if row.match_status == MATCHED and row.entry_id
        },
    )
    team_accounts = await _team_accounts(
        db,
        {
            row.settlement_id
            for row in team.values()
            if row.match_status == MATCHED and row.settlement_id
        },
        settings,
    )
    sales_parties = await _sales_accounts(
        db,
        {
            row.invoice_id
            for row in sales.values()
            if row.match_status == MATCHED and row.invoice_id
        },
        settings.sales.receivable_account,
    )

    team_ksef = {number for item in candidates for number in item.ksef_numbers}

    def team_related(line: StatementLine, account: str) -> bool:
        # Tak jak E3: każdy wiersz R9 (też „unmatched” i „ignored”) albo decyzja
        # R9 „dotyczy zespołu” (numer KSeF lub faktury, rachunek osoby). Uznanie
        # z rachunku osoby z zespołu albo z numerem KSeF jej faktury (zwrot
        # wypłaty, np. z zamkniętego rachunku) też jest płacowe (D2). Samego
        # numeru faktury przy uznaniach nie bierzemy — łapałby wpłaty klientów.
        if line.direction == "credit":
            return (bool(account) and account in owners) or bool(
                team_ksef & set(ksef_numbers_in(line.title or ""))
            )
        return (
            line.line_ref in team
            or hr_statements.decide(line, candidates, owners).related
        )

    out: dict[str, Classified] = {}
    for line in lines:
        ref = line.line_ref
        account = nrb(line.counterparty_account)
        related = team_related(line, account)
        if ref in duplicates:
            out[ref] = Classified(
                "duplicate", None, None, None, duplicates[ref] or related, ""
            )
            continue
        if related:
            paid = team.get(ref)
            settlement = (
                paid.settlement_id
                if paid is not None and paid.match_status == MATCHED
                else None
            )
            counter = team_accounts.get(settlement) if settlement else None
            out[ref] = Classified(
                "team",
                counter,
                None,
                settlement,
                True,
                ""
                if counter
                else "Konto przypisuje osoba z Płacami (wypłata B2B, zwrot albo bez "
                "rozliczenia).",
            )
            continue
        if line.direction == "debit":
            cost = costs.get(ref)
            if cost is not None and cost.match_status == MATCHED and cost.entry_id:
                party = cost_parties.get(cost.entry_id)
                counter = party.cost_account if party else None
                out[ref] = Classified(
                    "cost_invoice",
                    counter,
                    party.id if party else None,
                    cost.entry_id,
                    False,
                    ""
                    if counter
                    else "Dostawca bez konta rozrachunkowego w kartotece.",
                )
                continue
        else:
            sale = sales.get(ref)
            if sale is not None and sale.match_status == MATCHED and sale.invoice_id:
                party_id, counter = sales_parties.get(sale.invoice_id, (None, None))
                out[ref] = Classified(
                    "sales_invoice",
                    counter,
                    party_id,
                    sale.invoice_id,
                    False,
                    "" if counter else "Odbiorca spoza kartoteki kontrahentów.",
                )
                continue
        kind, counter, note = rule_for(
            line.direction, account, line.title, settings.bank
        )
        out[ref] = Classified(kind, counter, None, None, False, note)
    return out


def file_currency(parsed: ParsedStatement, lines: tuple[StatementLine, ...]) -> str:
    """Waluta pliku: jedna dla nagłówka i każdej operacji, z listy rachunków firmy."""

    found = {line.currency for line in lines} | {parsed.currency or "PLN"}
    if len(found) > 1:
        raise LedgerError(
            f"Plik ma operacje w kilku walutach ({', '.join(sorted(found))}) — "
            "wgraj każdy rachunek osobnym plikiem.",
            status=422,
        )
    currency = found.pop()
    if currency not in BANK_CURRENCIES:
        raise LedgerError(
            f"Wyciąg w {currency} — rachunki firmy są w {', '.join(BANK_CURRENCIES)}.",
            status=422,
        )
    return currency


async def nbp_rates(
    db: AsyncSession, currency: str, days: set[date]
) -> dict[date, Decimal]:
    """Kurs średni NBP (tabela A) dokładnie z ``rate_day`` każdego dnia operacji.

    Brak kursu = odmowa (jak w K2 i E2), nie starszy kurs po cichu: luka
    w pobieraniu kursów zmieniłaby kwoty w PLN bez śladu.
    """

    wanted = {day: posting.rate_day(day) for day in days}
    rows = await db.execute(
        select(FxRate.effective_date, FxRate.rate_to_pln).where(
            FxRate.currency == currency,
            FxRate.source == "NBP",
            FxRate.effective_date.in_(set(wanted.values()) or {date.min}),
        )
    )
    found = dict(rows.all())
    missing = sorted({rate for rate in wanted.values() if rate not in found})
    if missing:
        raise LedgerError(
            f"Brak kursu NBP {currency} z dnia {missing[0]:%d.%m.%Y} — pobierz kursy "
            "(Finanse → Kursy walut) i wczytaj wyciąg ponownie.",
            status=422,
        )
    return {day: Decimal(found[rate]) for day, rate in wanted.items()}


def _money(amount: Decimal) -> str:
    """Kwota do komunikatu: ``-1 234,50``."""

    return f"{amount:,.2f}".replace(",", " ").replace(".", ",")


def _check_file(parsed: ParsedStatement, lines: tuple[StatementLine, ...]) -> None:
    """Plik musi dać się zaksięgować jednym WB: jeden rachunek, saldo zgodne
    z operacjami, jedna waluta, jeden miesiąc."""

    if not lines:
        raise LedgerError("Wyciąg nie ma żadnej operacji.", status=422)
    if len({item for item in parsed.accounts if item}) > 1:
        raise LedgerError(
            "Plik ma wyciągi kilku rachunków — wgraj każdy rachunek osobnym plikiem "
            "(WB księguje jeden rachunek).",
            status=422,
        )
    gap = next((item for item in parsed.balances if not item.ok), None)
    if gap is not None:
        # Ucięty albo uszkodzony plik wszedłby po cichu z częścią operacji.
        part = f" (wyciąg {gap.statement} w pliku)" if len(parsed.balances) > 1 else ""
        raise LedgerError(
            f"Saldo wyciągu się nie zgadza{part}: otwarcie {_money(gap.opening)} "
            f"i operacje {_money(gap.movement)} dają {_money(gap.expected)}, a bank "
            f"podaje saldo końcowe {_money(gap.closing)}. Plik jest niepełny albo "
            "uszkodzony — pobierz go z banku jeszcze raz.",
            status=422,
        )
    file_currency(parsed, lines)
    months = sorted({(line.booked_on.year, line.booked_on.month) for line in lines})
    if len(months) > 1:
        first, last = months[0], months[-1]
        raise LedgerError(
            f"Wyciąg ma operacje z różnych miesięcy ({first[1]:02d}.{first[0]}–"
            f"{last[1]:02d}.{last[0]}) — WB księguje się w jednym okresie. Wgraj "
            "wyciąg miesięczny albo dzienny.",
            status=422,
        )


async def import_file(
    db: AsyncSession,
    raw: bytes,
    *,
    viewer: Viewer,
    settings: LedgerSettings,
    now: datetime,
) -> tuple[LedgerBankStatement, bool]:
    """Jeden import wyciągu (bez commita): E3, R9/E8, potem linie księgi.

    Zwraca wyciąg i ``True``, gdy plik wszedł teraz (``False`` = ten sam plik
    był już wczytany — bez drugiego importu).
    """

    try:
        # Parsowanie MT940/CAMT to czysty CPU — poza pętlą zdarzeń jedynego
        # procesu web; ten sam wynik dostają E3, R9 i E8.
        parsed = await asyncio.to_thread(hr_statements.parse_file, raw)
    except StatementError as exc:
        raise LedgerError(str(exc), status=422) from exc
    # Pozycja 0,00 (np. kapitalizacja bez odsetek) nie zmienia salda ani WB.
    lines = tuple(line for line in parsed.lines if grosze(line.amount) > 0)
    _check_file(parsed, lines)
    company = settings.bank.by_number(parsed.account)
    if company is None:
        tail = nrb(parsed.account)[-4:] or "?"
        raise LedgerError(
            f"Rachunku z wyciągu (…{tail}) nie ma na liście rachunków firmy — "
            "dodaje go administrator w Ustawieniach Księgowości.",
            status=422,
        )
    currency = file_currency(parsed, lines)
    if currency != company.currency:
        raise LedgerError(
            f"Rachunek …{company.number[-4:]} jest w {company.currency}, a wyciąg "
            f"w {currency} — popraw walutę rachunku w Ustawieniach albo wgraj "
            "właściwy plik.",
            status=422,
        )
    rates: dict[date, Decimal] = {}
    if currency != "PLN":
        rates = await nbp_rates(db, currency, {line.booked_on for line in lines})
    span = bank_continuity.file_span(parsed)
    sha = hashlib.sha256(raw).hexdigest()
    existing = await db.scalar(
        select(LedgerBankStatement).where(LedgerBankStatement.sha256 == sha)
    )
    if existing is not None:
        # Plik wgrany przed zapisem sald (0742): ponowne wgranie je uzupełnia,
        # bez drugiego importu operacji (E3/R9/E8 i linie zostają, jakie były).
        if existing.closing_balance is None and span is not None:
            for key, value in _span_fields(span).items():
                setattr(existing, key, value)
            await db.flush()
        return existing, False
    # D2 zamyka się po bezpiecznej stronie: bez rachunków zespołu wypłaty
    # wyglądałyby jak zwykłe przelewy i trafiłyby do osób bez Płac.
    owners, unreadable = await hr_statements.account_owners(db)
    if unreadable:
        raise LedgerError(UNREADABLE_TEAM, status=503)
    candidates = await hr_statements.load_candidates(db)
    # Te same blokady co E3/R9/E8: ten sam plik nie wchodzi naraz dwiema drogami.
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:key))"),
        {"key": f"hr-statement:{sha}"},
    )
    team = (owners, candidates)
    await cost_payments.import_debits(
        db, raw, actor_id=viewer.user_id, parsed=parsed, team=team
    )
    if viewer.payroll:
        payroll_import = await hr_statements.import_statement(
            db,
            raw,
            actor_id=viewer.user_id,
            match_credits=True,
            parsed=parsed,
            team=team,
        )
        credits = payroll_import.credits or {"error": True}
    else:
        credits = (
            await client_payments.import_credits(
                db, parsed, sha=sha, actor_id=viewer.user_id
            )
        ).as_dict()
    classified = await _classify(
        db,
        lines,
        sha,
        bank_account=company.number,
        settings=settings,
        owners=owners,
        candidates=candidates,
    )
    statement = LedgerBankStatement(
        sha256=sha,
        format=parsed.format,
        bank_account=company.number,
        ledger_account=company.account,
        currency=currency,
        first_day=min(line.booked_on for line in lines),
        last_day=max(line.booked_on for line in lines),
        line_count=len(lines),
        debit_total=sum(
            grosze(line.amount) for line in lines if line.direction == "debit"
        ),
        credit_total=sum(
            grosze(line.amount) for line in lines if line.direction == "credit"
        ),
        **_span_fields(span),
        # Uznań, których E8 nie sprawdziło (moduł wyłączony, błąd w ścieżce
        # Płac), wyciąg nie dowodzi — „po terminie” go wtedy nie liczy.
        credits_matched=credits_matched(credits),
        created_by=viewer.user_id,
        created_at=now,
    )
    db.add(statement)
    await db.flush()
    for position, line in enumerate(lines, start=1):
        item = classified[line.line_ref]
        account = nrb(line.counterparty_account)
        db.add(
            LedgerBankLine(
                statement_id=statement.id,
                line_ref=line.line_ref,
                position=position,
                bank_ref=line.bank_ref[:48],
                booked_on=line.booked_on,
                direction=line.direction,
                amount=grosze(line.amount),
                **_pln_fields(line, currency, rates),
                title=" ".join((line.title or "").split())[:TITLE_MAX],
                counterparty_name=" ".join((line.counterparty_name or "").split())[
                    :NAME_MAX
                ],
                counterparty_last4=account[-4:] if account else None,
                kind=item.kind,
                ref_id=item.ref_id,
                counter_account=item.counter_account or None,
                counterparty_id=item.counterparty_id,
                payroll=item.payroll,
                note=item.note[:NOTE_MAX],
            )
        )
    await db.flush()
    return statement, True


def _span_fields(span: Optional[bank_continuity.Span]) -> dict[str, Any]:
    """Salda i numery pliku do ``ledger_bank_statements`` (``None`` = puste)."""

    if span is None:
        return {}
    return {
        "opening_balance": span.opening_balance,
        "opening_day": span.opening_day,
        "closing_balance": span.closing_balance,
        "closing_day": span.closing_day,
        "first_number": span.first_number,
        "last_number": span.last_number,
    }


def credits_matched(result: dict[str, Any]) -> bool:
    """Wynik E8 importu (``CreditResult.as_dict``): uznania przeszły dopasowanie."""

    return not (
        result.get("disabled") or result.get("error") or result.get("restricted")
    )


# ── Odczyt ───────────────────────────────────────────────────────────────────


def _pln_fields(
    line: StatementLine, currency: str, rates: dict[date, Decimal]
) -> dict[str, Any]:
    """Waluta operacji i jej równowartość w PLN (operacja w PLN: ta sama kwota)."""

    if currency == "PLN":
        return {"currency": "PLN", "amount_pln": grosze(line.amount)}
    rate = rates[line.booked_on]
    return {
        "currency": currency,
        "amount_pln": posting.grosze(Decimal(line.amount) * rate),
        "fx_rate": rate,
        "fx_date": posting.rate_day(line.booked_on),
    }


def pln(line: LedgerBankLine) -> int:
    """Kwota operacji w PLN (wiersze sprzed K4c-1 mają ją w ``amount``)."""

    return line.amount_pln if line.amount_pln is not None else line.amount


def bank_open(settings: LedgerSettings, viewer: Viewer) -> bool:
    """Moduł „Bank” otwarty dla osoby (wyłączony widzi tylko administrator)."""

    return settings.modules.get("bank", False) or viewer.admin


def _visible(line: LedgerBankLine, viewer: Viewer) -> bool:
    return viewer.payroll or not line.payroll


def _resolved(line: LedgerBankLine) -> bool:
    return line.kind == "duplicate" or bool(line.counter_account)


def _line_payload(line: LedgerBankLine, position: int) -> dict[str, Any]:
    return {
        "id": line.id,
        "position": position,
        "booked_on": line.booked_on.isoformat(),
        "direction": line.direction,
        "amount": line.amount,
        "currency": line.currency,
        "amount_pln": pln(line),
        "fx_rate": str(line.fx_rate) if line.fx_rate is not None else None,
        "fx_date": line.fx_date.isoformat() if line.fx_date else None,
        "title": line.title,
        "counterparty_name": line.counterparty_name,
        "counterparty_last4": line.counterparty_last4,
        "kind": line.kind,
        "kind_label": KIND_LABELS[line.kind],
        "counter_account": line.counter_account,
        "payroll": line.payroll,
        "note": line.note,
        "resolved": _resolved(line),
    }


async def _lines(db: AsyncSession, statement_id: int) -> list[LedgerBankLine]:
    return list(
        await db.scalars(
            select(LedgerBankLine)
            .where(LedgerBankLine.statement_id == statement_id)
            .order_by(LedgerBankLine.position)
        )
    )


def _source_id(statement_id: int, payroll: bool) -> str:
    return f"{statement_id}-payroll" if payroll else str(statement_id)


async def _documents(db: AsyncSession, statement_id: int) -> list[LedgerDocument]:
    return list(
        await db.scalars(
            select(LedgerDocument).where(
                LedgerDocument.source_type == SOURCE_TYPE,
                LedgerDocument.source_id.in_(
                    [_source_id(statement_id, False), _source_id(statement_id, True)]
                ),
                LedgerDocument.reversed_by_id.is_(None),
            )
        )
    )


def _account_name(statement: LedgerBankStatement, bank_settings: BankSettings) -> str:
    company = bank_settings.by_number(statement.bank_account)
    return company.name if company else ""


async def statement_payload(
    db: AsyncSession,
    statement: LedgerBankStatement,
    viewer: Viewer,
    bank_settings: BankSettings,
) -> dict[str, Any]:
    """Wyciąg z liniami w zasięgu osoby (D2: wypłaty dla zespołu tylko z Płacami)."""

    lines = await _lines(db, statement.id)
    visible = [line for line in lines if _visible(line, viewer)]
    counts = Counter(line.kind for line in visible)
    docs = [
        doc
        for doc in await _documents(db, statement.id)
        if doc.sensitivity is None or viewer.payroll
    ]
    return {
        "id": statement.id,
        "format": statement.format,
        "bank_account_last4": statement.bank_account[-4:],
        "account_name": _account_name(statement, bank_settings),
        "ledger_account": statement.ledger_account,
        "currency": statement.currency,
        "first_day": statement.first_day.isoformat(),
        "last_day": statement.last_day.isoformat(),
        "debit_total": sum(
            line.amount for line in visible if line.direction == "debit"
        ),
        "credit_total": sum(
            line.amount for line in visible if line.direction == "credit"
        ),
        # Numer pozycji w zasięgu osoby: luka w numeracji zdradzałaby liczbę
        # ukrytych wypłat, a D2 trzyma liczniki płacowe przy Płacach.
        "lines": [
            _line_payload(line, position)
            for position, line in enumerate(visible, start=1)
        ],
        "payroll_hidden": len(visible) < len(lines),
        "counts": dict(counts),
        "unresolved": sum(1 for line in visible if not _resolved(line)),
        "documents": [
            {
                "id": doc.id,
                "number": doc.number,
                "status": doc.status,
                "payroll": doc.sensitivity is not None,
            }
            for doc in docs
        ],
    }


async def overview(
    db: AsyncSession,
    viewer: Viewer,
    bank_settings: BankSettings,
    *,
    year: Optional[int] = None,
    month: Optional[int] = None,
) -> dict[str, Any]:
    """Wyciągi z operacjami w miesiącu (bez miesiąca: ostatnie), liczniki w zasięgu osoby."""

    query = select(LedgerBankStatement)
    if year is not None and month is not None:
        first = date(year, month, 1)
        last = date(year, month, calendar.monthrange(year, month)[1])
        query = query.where(
            LedgerBankStatement.first_day <= last,
            LedgerBankStatement.last_day >= first,
        )
    statements = list(
        await db.scalars(
            query.order_by(
                LedgerBankStatement.last_day.desc(), LedgerBankStatement.id.desc()
            ).limit(OVERVIEW_MAX)
        )
    )
    ids = [statement.id for statement in statements]
    stats: dict[int, list[int]] = {}
    bookable: dict[int, set[bool]] = {}
    posted: dict[int, set[bool]] = {}
    states: dict[int, list[str]] = {}
    if ids:
        where = [LedgerBankLine.statement_id.in_(ids)]
        if not viewer.payroll:
            where.append(LedgerBankLine.payroll.is_(False))
        open_line = and_(
            LedgerBankLine.kind != "duplicate",
            func.coalesce(LedgerBankLine.counter_account, "") == "",
        )
        rows = await db.execute(
            select(
                LedgerBankLine.statement_id,
                LedgerBankLine.payroll,
                func.count(),
                func.count().filter(LedgerBankLine.kind != "duplicate"),
                func.count().filter(open_line),
                func.coalesce(
                    func.sum(LedgerBankLine.amount).filter(
                        LedgerBankLine.direction == "debit"
                    ),
                    0,
                ),
                func.coalesce(
                    func.sum(LedgerBankLine.amount).filter(
                        LedgerBankLine.direction == "credit"
                    ),
                    0,
                ),
            )
            .where(*where)
            .group_by(LedgerBankLine.statement_id, LedgerBankLine.payroll)
        )
        for (
            statement_id,
            payroll,
            total,
            booked,
            unresolved,
            debit,
            credit,
        ) in rows.all():
            row = stats.setdefault(statement_id, [0, 0, 0, 0])
            row[0] += int(total)
            row[1] += int(unresolved)
            row[2] += int(debit)
            row[3] += int(credit)
            if booked:
                bookable.setdefault(statement_id, set()).add(bool(payroll))
        docs = await db.execute(
            select(
                LedgerDocument.source_id,
                LedgerDocument.status,
                LedgerDocument.sensitivity,
            ).where(
                LedgerDocument.source_type == SOURCE_TYPE,
                LedgerDocument.source_id.in_(
                    [
                        _source_id(item, payroll)
                        for item in ids
                        for payroll in (False, True)
                    ]
                ),
                LedgerDocument.reversed_by_id.is_(None),
            )
        )
        for source_id, doc_status, sensitivity in docs.all():
            if sensitivity is not None and not viewer.payroll:
                continue
            statement_id = int(source_id.split("-")[0])
            posted.setdefault(statement_id, set()).add(source_id.endswith("-payroll"))
            states.setdefault(statement_id, []).append(doc_status)
    items = []
    for statement in statements:
        total, unresolved, debit, credit = stats.get(statement.id, [0, 0, 0, 0])
        doc_states = states.get(statement.id, [])
        items.append(
            {
                "id": statement.id,
                "bank_account_last4": statement.bank_account[-4:],
                "account_name": _account_name(statement, bank_settings),
                "ledger_account": statement.ledger_account,
                "currency": statement.currency,
                "first_day": statement.first_day.isoformat(),
                "last_day": statement.last_day.isoformat(),
                "operations": total,
                "unresolved": unresolved,
                "debit_total": debit,
                "credit_total": credit,
                "wb": None
                if not doc_states
                else (
                    "approved"
                    if all(item == "approved" for item in doc_states)
                    else "draft"
                ),
                # Grupa (zwykła albo płacowa) z operacjami do WB, a bez WB.
                "to_post": bool(
                    bookable.get(statement.id, set()) - posted.get(statement.id, set())
                ),
            }
        )
    return {"statements": items}


async def get_statement(
    db: AsyncSession, statement_id: int, viewer: Viewer, bank_settings: BankSettings
) -> dict[str, Any]:
    statement = await db.get(LedgerBankStatement, statement_id)
    if statement is None:
        raise LedgerError(NO_STATEMENT, status=404)
    return await statement_payload(db, statement, viewer, bank_settings)


# ── Cofnięcie importu ────────────────────────────────────────────────────────


def _statement_label(statement: LedgerBankStatement) -> str:
    return (
        f"wyciągu {statement.first_day:%d.%m}–{statement.last_day:%d.%m.%Y}"
        f" (nr {statement.id})"
    )


def _op_ref(line_ref: Optional[str]) -> str:
    """Referencja banku z ``statement_line_ref`` E3/E8 (``pozycja:referencja``)."""

    return (line_ref or "").split(":", 1)[-1]


async def _duplicates_elsewhere(
    db: AsyncSession,
    statement: LedgerBankStatement,
    costs: list[FinanceCostPaymentRecord],
    sales: list[ClientSalesInvoicePayment],
) -> Optional[str]:
    """Inny plik, który ma operacje tego wyciągu jako duplikaty (audyt 24.11.2026).

    Duplikat (linia ``duplicate`` w innym wyciągu tego rachunku albo E3/E8
    ``DUPLICATE_REASON`` pod innym skrótem) wskazuje na oryginał z tego pliku;
    po jego usunięciu operacja wypadłaby z WB, a faktura straciłaby zapłatę —
    ponowne wgranie tego pliku dałoby już tylko duplikat. ``None`` = nikt.
    """

    original = LedgerBankLine.__table__.alias("original")
    copy = LedgerBankLine.__table__.alias("copy")
    other = LedgerBankStatement.__table__.alias("other")
    found = await db.scalar(
        select(other.c.id)
        .select_from(original)
        .join(
            copy,
            and_(
                copy.c.bank_ref == original.c.bank_ref,
                copy.c.booked_on == original.c.booked_on,
                copy.c.amount == original.c.amount,
                copy.c.statement_id != original.c.statement_id,
                copy.c.kind == "duplicate",
            ),
        )
        .join(other, other.c.id == copy.c.statement_id)
        .where(
            original.c.statement_id == statement.id,
            original.c.kind != "duplicate",
            original.c.bank_ref != "",
            other.c.bank_account == statement.bank_account,
        )
        .order_by(other.c.id)
        .limit(1)
    )
    if found is not None:
        held = await db.get(LedgerBankStatement, found)
        return _statement_label(held) if held else "innym wyciągu"
    for model, rows, reason in (
        (FinanceCostPaymentRecord, costs, cost_payments.DUPLICATE_REASON),
        (ClientSalesInvoicePayment, sales, client_payments.DUPLICATE_REASON),
    ):
        mine = {
            (row.booked_on, Decimal(row.amount), _op_ref(row.statement_line_ref))
            for row in rows
            if row.reason != reason and _op_ref(row.statement_line_ref)
        }
        if not mine:
            continue
        copies = await db.execute(
            select(
                model.statement_sha256,
                model.booked_on,
                model.amount,
                model.statement_line_ref,
            )
            .where(
                model.kind == "statement_line",
                model.statement_sha256 != statement.sha256,
                model.reason == reason,
                model.booked_on.in_({day for day, _, _ in mine}),
                model.amount.in_({amount for _, amount, _ in mine}),
            )
            .order_by(model.id)
        )
        for sha, day, amount, line_ref in copies.all():
            if (day, Decimal(amount), _op_ref(line_ref)) in mine:
                held = await db.scalar(
                    select(LedgerBankStatement)
                    .where(LedgerBankStatement.sha256 == sha)
                    .order_by(LedgerBankStatement.id)
                    .limit(1)
                )
                return _statement_label(held) if held else "innym wgranym pliku wyciągu"
    return None


async def delete_statement(
    db: AsyncSession, statement_id: int, *, viewer: Viewer
) -> dict[str, int]:
    """Usuń wyciąg z liniami i zapłatami E3/E8 z tego pliku (bez commita).

    Na wypadek złego dopasowania (17.11.2026: E8 wziął nogi VAT MPP za wpłaty
    klientów) — po poprawce kodu plik wczytuje się od nowa. Tylko przed WB
    i tylko gdy import nie zostawił skutków poza swoimi wierszami: wypłaty
    R9, zamknięta pozycja paczki albo zastąpiona zapłata z eBI24 = odmowa,
    bo ich stanu sprzed importu nie odtworzymy. Stan zapłaty faktur
    kosztowych liczy się od nowa (``refresh`` E3).
    """

    statement = await db.get(LedgerBankStatement, statement_id, with_for_update=True)
    if statement is None:
        raise LedgerError(NO_STATEMENT, status=404)
    sha = statement.sha256
    # Ta sama blokada co import E3/R9/E8 — plik nie wchodzi w trakcie cofania.
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:key))"),
        {"key": f"hr-statement:{sha}"},
    )
    doc = await db.scalar(
        select(LedgerDocument)
        .where(
            LedgerDocument.source_type == SOURCE_TYPE,
            LedgerDocument.source_id.in_(
                [_source_id(statement.id, False), _source_id(statement.id, True)]
            ),
        )
        .limit(1)
    )
    if doc is not None:
        raise LedgerError(UNDO_WB.format(number=doc.number or doc.id), status=409)
    team = await db.scalar(
        select(func.count())
        .select_from(PayrollPayment)
        .where(PayrollPayment.statement_sha256 == sha)
    )
    if team:
        raise LedgerError(UNDO_PAYROLL, status=409)
    costs = list(
        await db.scalars(
            select(FinanceCostPaymentRecord).where(
                FinanceCostPaymentRecord.kind == "statement_line",
                FinanceCostPaymentRecord.statement_sha256 == sha,
            )
        )
    )
    entry_ids = sorted(
        {row.entry_id for row in costs if row.match_status == MATCHED and row.entry_id}
    )
    if entry_ids and await db.scalar(
        select(func.count())
        .select_from(FinancePaymentBatchItem)
        .where(
            FinancePaymentBatchItem.entry_id.in_(entry_ids),
            FinancePaymentBatchItem.status == "done",
        )
    ):
        raise LedgerError(UNDO_BATCH, status=409)
    sales = list(
        await db.scalars(
            select(ClientSalesInvoicePayment).where(
                ClientSalesInvoicePayment.kind == "statement_line",
                ClientSalesInvoicePayment.statement_sha256 == sha,
            )
        )
    )
    invoice_ids = {
        row.invoice_id
        for row in sales
        if row.match_status == MATCHED and row.invoice_id
    }
    if invoice_ids:
        heads = list(
            await db.scalars(
                select(ClientSalesInvoice).where(ClientSalesInvoice.id.in_(invoice_ids))
            )
        )
        chained = {
            invoice.id
            for chain in await client_ledger.build_chains(db, heads)
            for invoice in chain.invoices
        } | invoice_ids
        if await db.scalar(
            select(func.count())
            .select_from(ClientSalesInvoicePayment)
            .where(
                ClientSalesInvoicePayment.invoice_id.in_(chained),
                ClientSalesInvoicePayment.kind == "ebi24",
                ClientSalesInvoicePayment.reason == client_payments.EBI24_SUPERSEDED,
            )
        ):
            raise LedgerError(UNDO_EBI24, status=409)
    other = await _duplicates_elsewhere(db, statement, costs, sales)
    if other is not None:
        raise LedgerError(UNDO_DUPLICATES.format(other=other), status=409)
    lines = await db.scalar(
        select(func.count())
        .select_from(LedgerBankLine)
        .where(LedgerBankLine.statement_id == statement.id)
    )
    result = {
        "lines": int(lines or 0),
        "cost_records": len(costs),
        "cost_matched": sum(1 for row in costs if row.match_status == MATCHED),
        "sales_records": len(sales),
        "sales_matched": sum(1 for row in sales if row.match_status == MATCHED),
    }
    if costs:
        await db.execute(
            delete(FinanceCostPaymentRecord).where(
                FinanceCostPaymentRecord.id.in_([row.id for row in costs])
            )
        )
    if sales:
        await db.execute(
            delete(ClientSalesInvoicePayment).where(
                ClientSalesInvoicePayment.id.in_([row.id for row in sales])
            )
        )
    await db.execute(
        delete(LedgerBankLine).where(LedgerBankLine.statement_id == statement.id)
    )
    await db.execute(
        delete(LedgerBankStatement).where(LedgerBankStatement.id == statement.id)
    )
    await db.flush()
    await cost_payments.refresh(db, entry_ids, actor_id=viewer.user_id)
    return result


# ── Przypisanie i WB ─────────────────────────────────────────────────────────


async def assign(
    db: AsyncSession,
    line_id: int,
    account: str,
    *,
    viewer: Viewer,
    now: datetime,
) -> LedgerBankLine:
    """Konto przeciwstawne operacji wpisane ręcznie (bez commita).

    Gdy WB grupy operacji jest już w buforze, przebudowuje się od razu — szkic
    nie zostaje ze starym kontem. Zatwierdzony WB = najpierw storno.
    """

    line = await db.get(LedgerBankLine, line_id)
    if line is None or not _visible(line, viewer):
        raise LedgerError("Nie ma takiej operacji.", status=404)
    # Przypisanie i księgowanie wyciągu idą po kolei (blokada wyciągu).
    statement = await db.get(
        LedgerBankStatement, line.statement_id, with_for_update=True
    )
    await db.refresh(line)
    if line.kind == "duplicate":
        raise LedgerError(
            "To duplikat operacji z innego wyciągu — nie wchodzi do WB.", status=409
        )
    docs = {doc.source_id: doc for doc in await _documents(db, line.statement_id)}
    doc = docs.get(_source_id(line.statement_id, line.payroll))
    if doc is not None and doc.status != "draft":
        raise LedgerError(APPROVED_WB.format(journal_no=doc.journal_no), status=409)
    plan = await documents.load_plan(db)
    number = engine.clean_line(
        {"side": "debit", "account": account, "amount": 1}, 1
    ).account
    resolved, problem = engine.resolve(number, plan)
    if resolved is None:
        raise LedgerError(f"Konto {number}: {problem}", status=422)
    line.counter_account = number
    if line.kind == "unmatched":
        line.kind = "manual"
    line.note = ""
    line.assigned_by = viewer.user_id
    line.assigned_at = now
    await db.flush()
    if doc is not None and statement is not None:
        chosen = _group(await _lines(db, statement.id), line.payroll)
        await _write_wb(
            db,
            statement,
            chosen,
            payroll=line.payroll,
            viewer=viewer,
            existing=doc,
            plan=plan,
        )
    return line


def _group(lines: list[LedgerBankLine], payroll: bool) -> list[LedgerBankLine]:
    return [
        line for line in lines if line.payroll == payroll and line.kind != "duplicate"
    ]


def wb_spec(
    statement: LedgerBankStatement,
    lines: list[LedgerBankLine],
    *,
    payroll: bool,
) -> DocumentSpec:
    """WB: każda operacja Wn/Ma rachunek firmy i konto przeciwstawne."""

    entries: list[LineIn] = []
    # Pozycja WB z kontem przeciwstawnym → operacja wyciągu (rozrachunki K4b
    # rozliczają ją z fakturą dopasowaną w E3/E8). Numer pozycji = kolejność
    # w ``entries`` (``documents.create_draft`` numeruje od 1). Poza odciskiem —
    # odciski WB sprzed K4b zostają te same.
    links: dict[str, int] = {}
    for line in lines:
        text_ = f"{line.booked_on:%d.%m} {line.counterparty_name or line.title}"[:200]
        amount = pln(line)
        # Operacja walutowa (K4c-1): kwota w PLN, w walucie i kurs pozycji;
        # operacja w PLN bez tych pól — odcisk WB w PLN się nie zmienia.
        extra: dict[str, Any] = {}
        if line.currency != "PLN":
            extra = {
                "currency": line.currency,
                "amount_cur": line.amount,
                "fx_rate": line.fx_rate,
                "fx_date": line.fx_date,
            }
        if line.direction == "debit":
            links[str(len(entries) + 1)] = line.id
            entries.append(
                LineIn(
                    "debit",
                    str(line.counter_account),
                    amount,
                    text_,
                    counterparty_id=line.counterparty_id,
                    **extra,
                )
            )
            entries.append(
                LineIn("credit", statement.ledger_account, amount, text_, **extra)
            )
        else:
            entries.append(
                LineIn("debit", statement.ledger_account, amount, text_, **extra)
            )
            links[str(len(entries) + 1)] = line.id
            entries.append(
                LineIn(
                    "credit",
                    str(line.counter_account),
                    amount,
                    text_,
                    counterparty_id=line.counterparty_id,
                    **extra,
                )
            )
    suffix = " — wypłaty dla zespołu" if payroll else ""
    return DocumentSpec(
        doc_type="WB",
        op_date=statement.last_day,
        doc_date=statement.last_day,
        lines=entries,
        # Opis bez nazwy rachunku z Ustawień: wchodzi do odcisku, a zmiana nazwy
        # po zatwierdzeniu WB blokowałaby „Zaksięguj” (przegląd K4a 14.11.2026).
        description=(
            f"Wyciąg …{statement.bank_account[-4:]} "
            f"{statement.first_day:%d.%m}–{statement.last_day:%d.%m.%Y}{suffix}"
        ),
        source_type=SOURCE_TYPE,
        source_id=_source_id(statement.id, payroll),
        sensitivity="payroll" if payroll else None,
        meta={"statement": statement.id, "bank_lines": links},
    )


async def _write_wb(
    db: AsyncSession,
    statement: LedgerBankStatement,
    chosen: list[LedgerBankLine],
    *,
    payroll: bool,
    viewer: Viewer,
    existing: Optional[LedgerDocument],
    plan: dict[str, Any],
) -> tuple[str, LedgerDocument]:
    """Szkic WB grupy: ``unchanged`` / ``rebuilt`` / ``created`` (zatwierdzony = 409)."""

    spec = wb_spec(statement, chosen, payroll=payroll)
    check = engine.check(spec.lines, plan, max_lines=engine.lines_max("WB"))
    if check.issues:
        raise LedgerError(
            f"WB nie przechodzi kontroli planu kont: {check.issues[0]}", status=422
        )
    mark = sources.fingerprint(spec)
    spec.meta["fingerprint"] = mark
    outcome = "created"
    if existing is not None:
        if (existing.meta or {}).get("fingerprint") == mark:
            return "unchanged", existing
        if existing.status != "draft":
            raise LedgerError(
                APPROVED_WB.format(journal_no=existing.journal_no), status=409
            )
        await documents.delete_draft(db, existing.id, viewer=viewer)
        outcome = "rebuilt"
    created = await documents.create_draft(db, spec, actor_id=viewer.user_id, plan=plan)
    return outcome, created


async def post(
    db: AsyncSession,
    statement_id: int,
    *,
    viewer: Viewer,
) -> dict[str, Any]:
    """„Zaksięguj wyciąg”: WB (i WB płacowy dla Płac) do bufora, bez commita."""

    statement = await db.get(LedgerBankStatement, statement_id, with_for_update=True)
    if statement is None:
        raise LedgerError(NO_STATEMENT, status=404)
    lines = await _lines(db, statement.id)
    visible = [line for line in lines if _visible(line, viewer)]
    open_lines = [
        (position, line)
        for position, line in enumerate(visible, start=1)
        if not _resolved(line)
    ]
    if open_lines:
        position, first = open_lines[0]
        raise LedgerError(
            f"Wyciąg ma operacje bez konta ({len(open_lines)}) — pierwsza: poz. "
            f"{position}, {KIND_LABELS[first.kind]}. Przypisz konta i księguj "
            "ponownie.",
            status=422,
        )
    result: dict[str, Any] = {
        "created": 0,
        "rebuilt": 0,
        "unchanged": 0,
        "documents": [],
    }
    existing = {doc.source_id: doc for doc in await _documents(db, statement.id)}
    plan = await documents.load_plan(db)
    for payroll in [False, True] if viewer.payroll else [False]:
        chosen = _group(visible, payroll)
        if not chosen:
            continue
        outcome, doc = await _write_wb(
            db,
            statement,
            chosen,
            payroll=payroll,
            viewer=viewer,
            existing=existing.get(_source_id(statement.id, payroll)),
            plan=plan,
        )
        result[outcome] += 1
        result["documents"].append({"id": doc.id, "number": doc.number})
    return result
