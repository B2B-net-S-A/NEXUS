"""Źródła księgi (K2): faktury kosztowe z dekretem E2 → FVZ, sprzedaż z KSeF → FVS.

Plan „Księgowość w NEXUSIE” (13.11.2026): NEXUS księguje równolegle z Symfonią,
więc dokumenty z faktur muszą dać się porównać z Symfonią miesiąc do miesiąca.

* **Koszty** — dekret liczy E2 (``finance_cost_entries.decree``); K2 go nie
  przelicza, tylko przepisuje pozycje do dokumentu ``FVZ``. Do księgi idą
  faktury „Gotowe do księgowania” i „Zaksięgowane” (w Symfonii). Okres =
  miesiąc wpływu (``received_at`` w czasie firmy), jak paczka E2 do Symfonii.
* **Sprzedaż** — każda faktura z KSeF, gdzie spółka jest sprzedawcą
  (``client_sales_invoices``: wystawione w eBI24 i w NEXUSIE) → ``FVS``:
  Wn rozrachunek z odbiorcą (brutto), Ma przychód (netto), Ma VAT należny.
  Okres = miesiąc daty sprzedaży (P_6), korekta — miesiąc wystawienia.
  Waluta: kurs NBP z ostatniego dnia roboczego przed dniem sprzedaży (jak E4,
  art. 31a ustawy o VAT); faktura z NEXUSA bierze kurs zapisany przy
  wystawieniu, korekta — kurs faktury pierwotnej. Brutto i VAT po kursie,
  netto jako różnica (jak E2). Konto rozrachunkowe: z kartoteki kontrahenta
  („konto przychodowe” z eBI24, odpowiednik „kosztowego” w E2), inaczej konto
  z Ustawień + ID Symfonii kontrahenta. Zaliczka (ZAL) czeka na regułę (K3).
* **Kwoty ujemne** (korekty in minus) zamieniają strony, kwoty zostają
  dodatnie — tak samo jak w dekrecie E2. Zaliczka (ZAL) i jej korekta
  (KOR_ZAL) czekają na regułę zaliczek (K3).
* **Księgowanie miesiąca jest idempotentne**: dokument ma źródło
  (``source_type`` + ``source_id``) i odcisk danych (``meta.fingerprint``).
  Nowe źródło = nowy szkic, zmienione = szkic przebudowany, wycofane = szkic
  usunięty. Zatwierdzonego zapisu NEXUS sam nie odwraca: zmienione albo
  wycofane źródło z zapisem w dzienniku wraca jako problem do storna.
* **Faktury osób zespołu** (``payroll_invoice``) to dokumenty płacowe (D2):
  osoba bez Płac ich nie księguje, nie widzi w licznikach i nie usuwa.
* **Rozliczenie kosztów na „5”** (``allocation.py``) to trzecie źródło miesiąca:
  PK z MPK z zatwierdzonych FVZ, przez tę samą maszynę (odcisk, przebudowa,
  problem do storna).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import and_, func, or_, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scheduling import business_date, local_month_bounds
from app.models.client_issued_invoice import ClientIssuedInvoice
from app.models.client_sales_invoice import ClientSalesInvoice
from app.models.finance_ledger import FinanceCostEntry, FinanceCounterparty
from app.models.fx_rate import FxRate
from app.models.ledger import LedgerDocument, LedgerPeriod, LedgerYear
from app.services.finance_ledger import costs, identifiers, posting
from app.services.finance_ledger.costs import LedgerError
from app.services.ledger import allocation, documents, engine
from app.services.ledger.documents import DocumentSpec, Viewer
from app.services.ledger.engine import LineIn
from app.services.ledger.settings import SALES_ACCOUNT_FIELDS, LedgerSettings
from app.services.ledger_schema import DESCRIPTION_MAX, NUMBER_MAX

COSTS = "costs"
SALES = "sales"
ALLOCATION = "allocation"
KIND_LABELS: dict[str, str] = {
    COSTS: "Faktury kosztowe (Koszty, dekret E2)",
    SALES: "Faktury sprzedaży (KSeF)",
    ALLOCATION: "Rozliczenie kosztów na „5” (MPK)",
}
SOURCE_TYPES: dict[str, str] = {
    COSTS: "finance_cost_entry",
    SALES: "client_sales_invoice",
    ALLOCATION: allocation.SOURCE_TYPE,
}
#: Etapy kolejki kosztów, z których faktura idzie do księgi.
COST_STAGES = ("ready", "booked")
PROBLEMS_MAX = 200

NO_BUYER = (
    "Nabywcy nie ma w kartotece kontrahentów — zaimportuj kartotekę z eBI24 "
    "(Finanse → Kontrahenci)."
)
NO_RECEIVABLE = (
    "Kontrahent nie ma konta rozrachunkowego sprzedaży („konto przychodowe”) ani "
    "ID Symfonii — uzupełnij je w Finanse → Kontrahenci."
)
NO_REVENUE_ACCOUNT = (
    "Ustaw konto przychodów ze sprzedaży w Ustawieniach Księgowości (administrator)."
)
#: Zaliczka i jej korekta (KSeF: ``KOR_ZAL``) czekają razem na regułę zaliczek —
#: korekta zaliczki jako FVS zmniejszyłaby przychód, którego nie było.
ADVANCE_TYPES = frozenset({"ZAL", "KOR_ZAL"})
NO_ALLOCATION_ACCOUNTS = (
    "Ustaw konta rozliczenia kosztów na „5” w Ustawieniach Księgowości (administrator)."
)
DETAILS_MAX = 200
ADVANCE = (
    "Faktura zaliczkowa — dekret zaliczki wejdzie z regułą rozliczeń (K3); do tego "
    "czasu zaksięguj ją poleceniem księgowania."
)


@dataclass
class Candidate:
    """Źródło miesiąca: gotowy dokument albo powód, dla którego go nie ma."""

    source_id: str
    label: str
    payroll: bool = False
    spec: Optional[DocumentSpec] = None
    problems: list[str] = field(default_factory=list)
    #: Źródło bez kwot do zaksięgowania (np. korekta samego opisu) — nie problem.
    skipped: bool = False
    #: Rozliczenie kosztów: kwoty MPK do podglądu (kod, nazwa, grosze).
    details: list[dict[str, Any]] = field(default_factory=list)


def fingerprint(spec: DocumentSpec) -> str:
    """Odcisk danych dokumentu ze źródła: zmiana = szkic do przebudowy."""

    payload = {
        "type": spec.doc_type,
        "number": spec.number,
        "op_date": spec.op_date.isoformat(),
        "doc_date": spec.doc_date.isoformat(),
        "description": spec.description,
        "counterparty": spec.counterparty_id,
        "currency": spec.currency,
        "fx_rate": str(spec.fx_rate) if spec.fx_rate is not None else None,
        "fx_date": spec.fx_date.isoformat() if spec.fx_date else None,
        "sensitivity": spec.sensitivity,
        "lines": [
            [
                line.side,
                line.account,
                line.amount,
                line.counterparty_id,
                line.mpk,
                line.currency,
                line.amount_cur,
            ]
            for line in spec.lines
        ],
    }
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def _month_start(year: int, month: int) -> date:
    if not 1 <= month <= 12:
        raise LedgerError("Niepoprawny miesiąc.", status=422)
    return date(year, month, 1)


def _next_month(day: date) -> date:
    return (
        date(day.year + 1, 1, 1)
        if day.month == 12
        else date(day.year, day.month + 1, 1)
    )


def _clip(text: str, limit: int) -> str:
    return " ".join(text.split())[:limit]


# ── Koszty (dekret E2) ──────────────────────────────────────────────────────


def cost_spec(
    entry: FinanceCostEntry,
    *,
    number: str,
    seller: str,
    issue_date: Optional[date],
    ksef_number: Optional[str],
    gross: Optional[Decimal],
    currency: Optional[str],
) -> DocumentSpec | str:
    """Dokument FVZ z gotowego dekretu E2 albo powód (zdanie po polsku)."""

    decree = entry.decree or {}
    positions = decree.get("positions") or []
    if not positions:
        return "Faktura nie ma dekretu — przelicz go w Kosztach."
    doc_currency = str(decree.get("currency") or currency or "PLN").upper()
    fx_rate: Optional[Decimal] = None
    fx_date: Optional[date] = None
    if doc_currency != "PLN":
        if not decree.get("fx_rate") or not decree.get("fx_date"):
            return (
                f"Dekret faktury w {doc_currency} nie ma kursu NBP — przelicz dekret "
                "w Kosztach."
            )
        try:
            fx_rate = Decimal(str(decree["fx_rate"]))
            fx_date = date.fromisoformat(str(decree["fx_date"]))
        except (ArithmeticError, ValueError):
            # Dekret ręczny z nieczytelnym kursem — problem faktury, nie błąd 500.
            return (
                "Kurs w dekrecie faktury jest nieczytelny — przelicz dekret w Kosztach."
            )
        if not fx_rate.is_finite() or fx_rate <= 0:
            return (
                "Kurs w dekrecie faktury jest nieczytelny — przelicz dekret w Kosztach."
            )
    lines: list[LineIn] = []
    for item in positions:
        is_counterparty = item.get("kind") == "counterparty"
        foreign = doc_currency != "PLN" and is_counterparty and gross is not None
        lines.append(
            LineIn(
                side=str(item.get("side")),
                account=str(item.get("account") or ""),
                amount=int(item.get("amount") or 0),
                counterparty_id=entry.counterparty_id if is_counterparty else None,
                currency=doc_currency if foreign else "PLN",
                amount_cur=posting.grosze(abs(gross)) if foreign and gross else None,
            )
        )
    received = business_date(entry.received_at)
    description = str(decree.get("description") or "") or f"{seller} {number}"
    return DocumentSpec(
        doc_type="FVZ",
        op_date=received,
        doc_date=issue_date or received,
        lines=lines,
        number=_clip(number, NUMBER_MAX),
        description=_clip(description, DESCRIPTION_MAX),
        counterparty_id=entry.counterparty_id,
        currency=doc_currency,
        fx_rate=fx_rate,
        fx_date=fx_date,
        source_type=SOURCE_TYPES[COSTS],
        source_id=str(entry.id),
        sensitivity="payroll" if entry.source_type == "payroll_invoice" else None,
        meta={
            "source": "e2",
            "ksef_number": ksef_number,
            "issue_date": issue_date.isoformat() if issue_date else None,
            "e2_doc_type": decree.get("doc_type") or None,
        },
    )


async def _cost_candidates(
    db: AsyncSession, month: date, *, viewer: Viewer
) -> list[Candidate]:
    bounds = local_month_bounds(month)
    # Źródła faktur (wypłaty osób, faktury kontraktorów, dokumenty akceptacji)
    # czyta ta sama unia co kolejka i paczka E2 — jedno miejsce prawdy o kwotach.
    src = costs._sources()
    rows = (
        await db.execute(
            costs._select(src)
            .where(
                FinanceCostEntry.stage.in_(COST_STAGES),
                FinanceCostEntry.received_at >= bounds.start_utc,
                FinanceCostEntry.received_at < bounds.end_utc,
                *costs._payroll_scope(viewer.payroll),
            )
            .order_by(FinanceCostEntry.received_at, FinanceCostEntry.id)
        )
    ).all()
    e2_plan = await posting.load_plan(db)
    candidates: list[Candidate] = []
    for row in rows:
        entry: FinanceCostEntry = row.FinanceCostEntry
        number = row.invoice_number or row.ksef_number or f"wpis {entry.id}"
        seller = row.seller_name or row.counterparty_name or "—"
        candidate = Candidate(
            source_id=str(entry.id),
            label=f"{number} · {seller}",
            payroll=entry.source_type == "payroll_invoice",
        )
        issues = posting.issues_for(
            entry.decree, e2_plan, row.gross_amount, row.currency
        )
        if issues:
            candidate.problems.extend(issues)
        else:
            spec = cost_spec(
                entry,
                number=number,
                seller=seller,
                issue_date=row.issue_date,
                ksef_number=row.ksef_number,
                gross=row.gross_amount,
                currency=row.currency,
            )
            if isinstance(spec, str):
                candidate.problems.append(spec)
            else:
                candidate.spec = spec
        candidates.append(candidate)
    return candidates


# ── Sprzedaż (KSeF) ─────────────────────────────────────────────────────────


def buyer_key(invoice: ClientSalesInvoice) -> Optional[tuple[str, str]]:
    """Identyfikator nabywcy w kartotece kontrahentów (NIP albo VAT UE)."""

    if invoice.buyer_nip:
        return ("nip", invoice.buyer_nip)
    if invoice.buyer_foreign_id:
        try:
            found = identifiers.normalize(invoice.buyer_foreign_id)
        except identifiers.IdentifierError:
            return None
        if found is not None:
            return (found.type, found.value)
    return None


def receivable_account(
    counterparty: FinanceCounterparty, default_account: str
) -> Optional[str]:
    if counterparty.revenue_account:
        return counterparty.revenue_account
    partner = (counterparty.symfonia_partner_id or "").strip()
    if partner.isdigit():
        return f"{default_account}-{partner}"
    return None


def sales_lines(
    *,
    net: Decimal,
    vat: Decimal,
    gross: Decimal,
    currency: str,
    rate: Decimal,
    receivable: str,
    revenue: str,
    vat_account: str,
    counterparty_id: int,
) -> list[LineIn] | str:
    """Pozycje FVS w groszach PLN; ujemna kwota = strona przeciwna."""

    if currency == "PLN":
        gross_g = posting.grosze(gross)
        vat_g = posting.grosze(vat)
        if posting.grosze(net) + vat_g != gross_g:
            return (
                "Netto i VAT faktury nie sumują się do brutto — sprawdź fakturę w KSeF."
            )
    else:
        gross_g = posting.grosze(gross * rate)
        vat_g = posting.grosze(vat * rate)
    net_g = gross_g - vat_g
    lines: list[LineIn] = []

    def add(account: str, amount: int, debit_side: bool, **extra: Any) -> None:
        if amount == 0:
            return
        positive = "debit" if debit_side else "credit"
        negative = "credit" if debit_side else "debit"
        lines.append(
            LineIn(
                side=positive if amount > 0 else negative,
                account=account,
                amount=abs(amount),
                **extra,
            )
        )

    foreign = currency != "PLN"
    add(
        receivable,
        gross_g,
        True,
        counterparty_id=counterparty_id,
        currency=currency if foreign else "PLN",
        amount_cur=posting.grosze(abs(gross)) if foreign and gross else None,
    )
    add(revenue, net_g, False)
    add(vat_account, vat_g, False)
    return lines


@dataclass(frozen=True)
class _SalesContext:
    counterparties: dict[tuple[str, str], FinanceCounterparty]
    issued_rates: dict[int, tuple[Decimal, date]]
    originals: dict[int, ClientSalesInvoice]
    nbp: dict[tuple[str, date], Decimal]


def _rate_base(invoice: ClientSalesInvoice) -> date:
    return invoice.sale_date or invoice.issue_date


def invoice_rate(
    invoice: ClientSalesInvoice, ctx: _SalesContext
) -> tuple[Optional[Decimal], Optional[date], str]:
    """Kurs faktury: z wystawienia w NEXUSIE, z faktury pierwotnej albo NBP."""

    if invoice.currency == "PLN":
        return Decimal("1"), None, "pln"
    issued = ctx.issued_rates.get(invoice.id)
    if issued is not None:
        return issued[0], issued[1], "e4"
    base = invoice
    source = "nbp"
    if invoice.corrects_invoice_id and invoice.corrects_invoice_id in ctx.originals:
        base = ctx.originals[invoice.corrects_invoice_id]
        source = "original"
        issued = ctx.issued_rates.get(base.id)
        if issued is not None:
            return issued[0], issued[1], source
    day = posting.rate_day(_rate_base(base))
    rate = ctx.nbp.get((invoice.currency, day))
    return rate, day, source


def sales_spec(
    invoice: ClientSalesInvoice, ctx: _SalesContext, settings: LedgerSettings
) -> DocumentSpec | str | None:
    """FVS z faktury KSeF; ``str`` = problem, ``None`` = brak kwot do zapisu."""

    if invoice.invoice_type in ADVANCE_TYPES:
        return ADVANCE
    key = buyer_key(invoice)
    counterparty = ctx.counterparties.get(key) if key else None
    if counterparty is None:
        return NO_BUYER
    receivable = receivable_account(counterparty, settings.sales.receivable_account)
    if receivable is None:
        return NO_RECEIVABLE
    if not settings.sales.revenue_account:
        return NO_REVENUE_ACCOUNT
    rate, fx_date, fx_source = invoice_rate(invoice, ctx)
    if rate is None:
        day = fx_date.strftime("%d.%m.%Y") if fx_date else "—"
        return (
            f"Brak kursu NBP {invoice.currency} z dnia {day} — pobierz kursy "
            "(Finanse → Kursy walut)."
        )
    lines = sales_lines(
        net=Decimal(invoice.net_amount),
        vat=Decimal(invoice.vat_amount or 0),
        gross=Decimal(invoice.gross_amount),
        currency=invoice.currency,
        rate=rate,
        receivable=receivable,
        revenue=settings.sales.revenue_account,
        vat_account=settings.sales.vat_account,
        counterparty_id=counterparty.id,
    )
    if isinstance(lines, str):
        return lines
    if not lines:
        return None
    correction = invoice.invoice_kind == "correction"
    op_date = invoice.issue_date if correction else _rate_base(invoice)
    buyer = invoice.buyer_name or counterparty.name
    if correction:
        description = (
            f"Korekta {invoice.corrected_invoice_number or ''} — {buyer}".strip()
        )
    else:
        description = f"{buyer} — {invoice.invoice_number}"
    return DocumentSpec(
        doc_type="FVS",
        op_date=op_date,
        doc_date=invoice.issue_date,
        lines=lines,
        number=_clip(invoice.invoice_number, NUMBER_MAX),
        description=_clip(description, DESCRIPTION_MAX),
        counterparty_id=counterparty.id,
        currency=invoice.currency,
        fx_rate=None if invoice.currency == "PLN" else rate,
        fx_date=None if invoice.currency == "PLN" else fx_date,
        source_type=SOURCE_TYPES[SALES],
        source_id=str(invoice.id),
        meta={
            "source": "ksef",
            "ksef_number": invoice.ksef_number,
            "fx_source": fx_source,
        },
    )


async def _sales_context(
    db: AsyncSession, invoices: list[ClientSalesInvoice]
) -> _SalesContext:
    keys = {key for key in (buyer_key(invoice) for invoice in invoices) if key}
    counterparties: dict[tuple[str, str], FinanceCounterparty] = {}
    if keys:
        rows = await db.scalars(
            select(FinanceCounterparty).where(
                tuple_(FinanceCounterparty.id_type, FinanceCounterparty.id_value).in_(
                    list(keys)
                )
            )
        )
        counterparties = {(row.id_type, row.id_value): row for row in rows}
    original_ids = {
        invoice.corrects_invoice_id
        for invoice in invoices
        if invoice.corrects_invoice_id and invoice.currency != "PLN"
    }
    originals: dict[int, ClientSalesInvoice] = {}
    if original_ids:
        rows = await db.scalars(
            select(ClientSalesInvoice).where(ClientSalesInvoice.id.in_(original_ids))
        )
        originals = {row.id: row for row in rows}
    foreign_ids = {
        invoice.id for invoice in invoices if invoice.currency != "PLN"
    } | set(originals)
    issued_rates: dict[int, tuple[Decimal, date]] = {}
    if foreign_ids:
        rows = await db.execute(
            select(
                ClientIssuedInvoice.sales_invoice_id,
                ClientIssuedInvoice.fx_rate,
                ClientIssuedInvoice.fx_date,
            ).where(
                ClientIssuedInvoice.sales_invoice_id.in_(foreign_ids),
                ClientIssuedInvoice.fx_rate.is_not(None),
                ClientIssuedInvoice.fx_date.is_not(None),
            )
        )
        issued_rates = {
            int(sales_id): (Decimal(rate), fx_day)
            for sales_id, rate, fx_day in rows.all()
        }
    wanted: set[tuple[str, date]] = set()
    for invoice in invoices:
        if invoice.currency == "PLN":
            continue
        base = originals.get(invoice.corrects_invoice_id or 0, invoice)
        wanted.add((invoice.currency, posting.rate_day(_rate_base(base))))
    nbp: dict[tuple[str, date], Decimal] = {}
    if wanted:
        rows = await db.execute(
            select(FxRate.currency, FxRate.effective_date, FxRate.rate_to_pln).where(
                FxRate.source == "NBP",
                FxRate.currency.in_({currency for currency, _ in wanted}),
                FxRate.effective_date.in_({day for _, day in wanted}),
            )
        )
        nbp = {
            (currency, day): Decimal(rate)
            for currency, day, rate in rows.all()
            if (currency, day) in wanted
        }
    return _SalesContext(counterparties, issued_rates, originals, nbp)


async def _sales_candidates(
    db: AsyncSession, month: date, settings: LedgerSettings
) -> list[Candidate]:
    start, end = month, _next_month(month)
    sale_day = func.coalesce(
        ClientSalesInvoice.sale_date, ClientSalesInvoice.issue_date
    )
    invoices = list(
        (
            await db.scalars(
                select(ClientSalesInvoice)
                .where(
                    or_(
                        and_(
                            ClientSalesInvoice.invoice_kind != "correction",
                            sale_day >= start,
                            sale_day < end,
                        ),
                        and_(
                            ClientSalesInvoice.invoice_kind == "correction",
                            ClientSalesInvoice.issue_date >= start,
                            ClientSalesInvoice.issue_date < end,
                        ),
                    )
                )
                .order_by(ClientSalesInvoice.issue_date, ClientSalesInvoice.id)
            )
        ).all()
    )
    ctx = await _sales_context(db, invoices)
    candidates: list[Candidate] = []
    for invoice in invoices:
        candidate = Candidate(
            source_id=str(invoice.id),
            label=f"{invoice.invoice_number} · {invoice.buyer_name or '—'}",
        )
        spec = sales_spec(invoice, ctx, settings)
        if isinstance(spec, str):
            candidate.problems.append(spec)
        elif spec is None:
            candidate.skipped = True
        else:
            candidate.spec = spec
        candidates.append(candidate)
    return candidates


# ── Rozliczenie kosztów na „5” ──────────────────────────────────────────────


async def _allocation_candidates(
    db: AsyncSession, month: date, *, viewer: Viewer, settings: LedgerSettings
) -> list[Candidate]:
    _, period = await _period(db, month)
    if period is None:
        return []
    plan = await documents.load_plan(db)
    candidates: list[Candidate] = []
    for payroll in (False, True) if viewer.payroll else (False,):
        totals = await allocation.month_totals(db, period.id, plan, payroll=payroll)
        candidate = Candidate(
            source_id=allocation.source_id(month.year, month.month, payroll=payroll),
            label="Rozliczenie kosztów na MPK"
            + (" — faktury osób zespołu" if payroll else ""),
            payroll=payroll,
            details=[
                {
                    "code": mpk.code,
                    "label": mpk.label,
                    "amount": amount,
                    "payroll": payroll,
                }
                for mpk, amount in sorted(
                    totals.items(), key=lambda pair: -abs(pair[1])
                )
                if amount
            ],
        )
        spec = None
        if any(totals.values()):
            if not settings.allocation.complete():
                candidate.problems.append(NO_ALLOCATION_ACCOUNTS)
            else:
                spec = allocation.allocation_spec(
                    month.year,
                    month.month,
                    totals,
                    settings.allocation,
                    payroll=payroll,
                )
        if spec is not None:
            candidate.spec = spec
        elif not candidate.problems:
            candidate.skipped = True
        candidates.append(candidate)
    return candidates


# ── Miesiąc: podgląd i księgowanie ──────────────────────────────────────────


async def _candidates(
    db: AsyncSession,
    kind: str,
    month: date,
    *,
    viewer: Viewer,
    settings: LedgerSettings,
) -> list[Candidate]:
    if kind == COSTS:
        candidates = await _cost_candidates(db, month, viewer=viewer)
    elif kind == SALES:
        candidates = await _sales_candidates(db, month, settings)
    elif kind == ALLOCATION:
        candidates = await _allocation_candidates(
            db, month, viewer=viewer, settings=settings
        )
    else:
        raise LedgerError("Nie ma takiego źródła.", status=404)
    # Ta sama kontrola co przy zapisie (konta z planu, analityka słownika,
    # Wn = Ma) — podgląd miesiąca nie obiecuje dokumentu, którego nie da się zapisać.
    plan = await documents.load_plan(db)
    for candidate in candidates:
        if candidate.spec is None:
            continue
        issues = engine.check(candidate.spec.lines, plan).issues
        if issues:
            candidate.problems.extend(issues)
            candidate.spec = None
    return candidates


async def _period(
    db: AsyncSession, month: date
) -> tuple[Optional[LedgerYear], Optional[LedgerPeriod]]:
    year = await db.scalar(select(LedgerYear).where(LedgerYear.year == month.year))
    if year is None:
        return None, None
    period = await db.scalar(
        select(LedgerPeriod).where(
            LedgerPeriod.year_id == year.id, LedgerPeriod.month == month.month
        )
    )
    return year, period


async def _live_documents(
    db: AsyncSession,
    kind: str,
    source_ids: list[str],
    period_id: Optional[int],
    viewer: Viewer,
) -> dict[str, LedgerDocument]:
    """Nieodwrócone dokumenty źródeł miesiąca (i inne z tego okresu)."""

    scope = [LedgerDocument.source_id.in_(source_ids or ["-"])]
    if period_id is not None:
        scope.append(LedgerDocument.period_id == period_id)
    conditions = [
        LedgerDocument.source_type == SOURCE_TYPES[kind],
        LedgerDocument.reversed_by_id.is_(None),
        or_(*scope),
    ]
    if not viewer.payroll:
        conditions.append(LedgerDocument.sensitivity.is_(None))
    rows = await db.scalars(select(LedgerDocument).where(*conditions))
    return {row.source_id: row for row in rows if row.source_id is not None}


def _problem(
    candidate_label: str, source_id: str, problems: list[str]
) -> dict[str, Any]:
    return {"source_id": source_id, "label": candidate_label, "problems": problems}


def _storno_hint(doc: LedgerDocument, reason: str) -> str:
    return f"{reason} — zrób storno zapisu nr {doc.journal_no} w dzienniku."


async def month_summary(
    db: AsyncSession,
    year: int,
    month: int,
    *,
    viewer: Viewer,
    settings: LedgerSettings,
) -> dict[str, Any]:
    """Stan źródeł miesiąca bez zapisu: co jest w księdze, co czeka, co blokuje."""

    start = _month_start(year, month)
    year_row, period = await _period(db, start)
    items = []
    for kind in (COSTS, SALES, ALLOCATION):
        candidates = await _candidates(
            db, kind, start, viewer=viewer, settings=settings
        )
        existing = await _live_documents(
            db,
            kind,
            [item.source_id for item in candidates],
            period.id if period else None,
            viewer,
        )
        counts = {"draft": 0, "approved": 0, "to_post": 0, "changed": 0, "skipped": 0}
        problems: list[dict[str, Any]] = []
        seen: set[str] = set()
        for candidate in candidates:
            seen.add(candidate.source_id)
            doc = existing.get(candidate.source_id)
            if doc is not None:
                counts[doc.status] = counts.get(doc.status, 0) + 1
            if candidate.spec is None and doc is not None and doc.status == "draft":
                counts["changed"] += 1
            if candidate.skipped:
                counts["skipped"] += 1
                continue
            if candidate.spec is None:
                problems.append(
                    _problem(candidate.label, candidate.source_id, candidate.problems)
                )
                continue
            if doc is None:
                counts["to_post"] += 1
            elif (doc.meta or {}).get("fingerprint") != fingerprint(candidate.spec):
                if doc.status == "draft":
                    counts["changed"] += 1
                else:
                    problems.append(
                        _problem(
                            candidate.label,
                            candidate.source_id,
                            [_storno_hint(doc, "Źródło zmieniło się po zatwierdzeniu")],
                        )
                    )
        for source_id, doc in existing.items():
            if source_id in seen:
                continue
            if doc.status == "draft":
                counts["changed"] += 1
            else:
                problems.append(
                    _problem(
                        f"{doc.doc_type} {doc.number}",
                        source_id,
                        [_storno_hint(doc, "Źródła nie ma już do księgowania")],
                    )
                )
        item: dict[str, Any] = {
            "kind": kind,
            "label": KIND_LABELS[kind],
            "total": len(candidates),
            **counts,
            "problems": problems[:PROBLEMS_MAX],
            "problems_total": len(problems),
            "payroll_hidden": kind in (COSTS, ALLOCATION) and not viewer.payroll,
        }
        if kind == ALLOCATION:
            item["details"] = [
                detail for candidate in candidates for detail in candidate.details
            ][:DETAILS_MAX]
            pending = 0
            if period is not None:
                pending = await allocation.pending_cost_documents(
                    db, period.id, payroll=False
                )
                if viewer.payroll:
                    pending += await allocation.pending_cost_documents(
                        db, period.id, payroll=True
                    )
            item["pending_costs"] = pending
        items.append(item)
    return {
        "year": year,
        "month": month,
        "year_exists": year_row is not None,
        "period_open": bool(
            year_row is not None
            and period is not None
            and year_row.status == "open"
            and period.status == "open"
        ),
        "sales_accounts": {
            key: getattr(settings.sales, key) for key in SALES_ACCOUNT_FIELDS
        },
        "items": items,
    }


async def sync_month(
    db: AsyncSession,
    kind: str,
    year: int,
    month: int,
    *,
    viewer: Viewer,
    settings: LedgerSettings,
) -> dict[str, Any]:
    """„Zaksięguj miesiąc” (bez commita): szkice ze źródeł, bez dubli."""

    start = _month_start(year, month)
    year_row, period = await _period(db, start)
    if year_row is None or period is None:
        raise LedgerError(
            f"Nie ma roku obrotowego {year} — załóż go w Ustawieniach Księgowości.",
            status=409,
        )
    if year_row.status != "open" or period.status != "open":
        raise LedgerError(
            f"Okres {month:02d}.{year} jest zamknięty — źródeł do niego nie księguje się.",
            status=409,
        )
    candidates = await _candidates(db, kind, start, viewer=viewer, settings=settings)
    existing = await _live_documents(
        db, kind, [item.source_id for item in candidates], period.id, viewer
    )
    plan = await documents.load_plan(db)
    result = {"created": 0, "rebuilt": 0, "deleted": 0, "unchanged": 0, "skipped": 0}
    problems: list[dict[str, Any]] = []
    seen: set[str] = set()

    async def drop(doc: LedgerDocument) -> None:
        await documents.delete_draft(db, doc.id, viewer=viewer)

    for candidate in candidates:
        seen.add(candidate.source_id)
        doc = existing.get(candidate.source_id)
        spec = candidate.spec
        if spec is None:
            if doc is not None and doc.status == "draft":
                await drop(doc)
                result["deleted"] += 1
            if candidate.skipped:
                result["skipped"] += 1
            else:
                problems.append(
                    _problem(candidate.label, candidate.source_id, candidate.problems)
                )
            continue
        mark = fingerprint(spec)
        if doc is not None:
            if (doc.meta or {}).get("fingerprint") == mark:
                result["unchanged"] += 1
                continue
            if doc.status != "draft":
                problems.append(
                    _problem(
                        candidate.label,
                        candidate.source_id,
                        [_storno_hint(doc, "Źródło zmieniło się po zatwierdzeniu")],
                    )
                )
                continue
            await drop(doc)
        spec.meta = {**spec.meta, "fingerprint": mark}
        try:
            await documents.create_draft(db, spec, actor_id=viewer.user_id, plan=plan)
        except LedgerError as exc:
            problems.append(
                _problem(candidate.label, candidate.source_id, [exc.message])
            )
            continue
        result["rebuilt" if doc is not None else "created"] += 1
    for source_id, doc in existing.items():
        if source_id in seen:
            continue
        if doc.status == "draft":
            await drop(doc)
            result["deleted"] += 1
        else:
            problems.append(
                _problem(
                    f"{doc.doc_type} {doc.number}",
                    source_id,
                    [_storno_hint(doc, "Źródła nie ma już do księgowania")],
                )
            )
    return {
        "kind": kind,
        **result,
        "problems": problems[:PROBLEMS_MAX],
        "problems_total": len(problems),
    }
