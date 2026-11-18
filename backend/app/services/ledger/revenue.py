"""Konto przychodu faktury sprzedaży jak w Symfonii FK (K2, decyzja Artura 17.11.2026).

Przychód w Symfonii to drzewo analityk: ``701-<nr klienta>-<rodzaj>`` (1 T&M,
2 Pozostałe, 3 New Business), ``702-<nr>-…`` Fixed Price, a refaktury idą
m.in. na 760. Numer klienta to osobna numeracja Symfonii (z ID kontrahenta
zgadza się tylko u najstarszych klientów), a rodzaju NEXUS nie zna: faktura
powiązana z zamówieniem jest zawsze T&M, ale niepowiązana bywa każdego rodzaju.
Archiwum eBI24 ma przy każdej fakturze dekret, który poszedł do Symfonii
(``externalData.symfonia.accountNumberNet``), więc konto bierzemy stąd:

0. faktura ma już FVS w księdze (szkic albo zatwierdzoną) — konto przychodu
   z tego dokumentu: poprawka księgowej w szkicu przetrwa przebudowę, a zmiana
   historii nabywcy nie przestawia zatwierdzonej FVS;
1. faktura z archiwum (po numerze KSeF) — dokładnie jej konto z Symfonii;
2. korekta — konto faktury korygowanej (archiwum albo zatwierdzona FVS NEXUSA);
3. inna — konto ostatniej wcześniejszej faktury tego nabywcy, z archiwum albo
   z zatwierdzonej FVS w księdze NEXUSA (pomiar na fakturach 2026: 99,3%
   zgodności dla powiązanych z zamówieniem, 95,3% dla pozostałych; zmianę
   rodzaju księgowa poprawia w szkicu przed zatwierdzeniem);
4. bez historii — konto wskazane dla nabywcy przez księgową na problemie
   w „Źródłach” (``app_settings['ledger'].revenue_accounts``, decyzja Artura
   z 18.11.2026: historia ma pierwszeństwo, więc po pierwszej zatwierdzonej
   FVS regułę przejmuje krok 3);
5. bez historii i bez wskazania — problem „Do sprawdzenia”, bez cichego konta
   zapasowego.

Konto przychodów w Ustawieniach (``sales.revenue_account``) zostaje jako tryb
jednego konta: wpisane — każda FVS idzie na nie; puste — reguła wyżej.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Mapping, Optional

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.finance_archive import FinanceArchiveDocument
from app.models.finance_ledger import FinanceCounterparty
from app.models.ledger import LedgerDocument, LedgerLine

CHOSEN = "chosen"
DOCUMENT = "document"
EBI24 = "ebi24"
ORIGINAL = "original"
PREVIOUS = "previous"
SETTINGS = "settings"
SOURCE_LABELS: dict[str, str] = {
    CHOSEN: "wskazane dla nabywcy bez historii",
    DOCUMENT: "z dokumentu tej faktury w księdze",
    EBI24: "z dekretu tej faktury w Symfonii (archiwum eBI24)",
    ORIGINAL: "z faktury korygowanej",
    PREVIOUS: "z poprzedniej faktury nabywcy",
    SETTINGS: "z Ustawień",
}
SALES_SOURCE = "client_sales_invoice"
NO_HISTORY = (
    "Nabywca nie ma wcześniejszej faktury w Symfonii (archiwum eBI24) ani "
    "zatwierdzonej FVS w księdze, więc konta przychodu (701-<nr klienta>-<rodzaj>) "
    "nie da się dobrać — wskaż konto przychodu dla tego nabywcy."
)
_NOT_ID = re.compile(r"[^A-Z0-9]")


def buyer_id(raw: Optional[str]) -> str:
    """Identyfikator nabywcy do porównań: „PL 526-030-…” → „526030…”."""

    value = _NOT_ID.sub("", (raw or "").upper())
    if value.startswith("PL") and len(value) == 12 and value[2:].isdigit():
        return value[2:]
    return value


@dataclass(frozen=True)
class Posted:
    """Konto przychodu jednej wcześniejszej faktury nabywcy."""

    day: date
    account: str
    #: Id faktury sprzedaży, z której jest FVS w księdze NEXUSA.
    invoice_id: Optional[str] = None
    #: Przy tym samym dniu wygrywa księga NEXUSA (1) przed archiwum (0).
    rank: int = 0
    seq: int = 0


@dataclass(frozen=True)
class RevenueHistory:
    by_ksef: Mapping[str, str] = field(default_factory=dict)
    by_invoice: Mapping[str, str] = field(default_factory=dict)
    by_buyer: Mapping[str, tuple[Posted, ...]] = field(default_factory=dict)
    #: Konto przychodu z żywej FVS (szkic albo zatwierdzona) tej faktury.
    current: Mapping[str, str] = field(default_factory=dict)


def pick(
    invoice: Any,
    history: RevenueHistory,
    buyer: Optional[str],
    chosen: Optional[str] = None,
) -> tuple[Optional[str], str]:
    """(konto, skąd) albo (``None``, problem) — kolejność z opisu modułu.

    ``chosen`` — konto wskazane dla nabywcy; liczy się dopiero bez historii."""

    own = str(invoice.id)
    if own in history.current:
        return history.current[own], DOCUMENT
    if invoice.ksef_number and invoice.ksef_number in history.by_ksef:
        return history.by_ksef[invoice.ksef_number], EBI24
    if invoice.invoice_kind == "correction":
        original = None
        if invoice.corrected_ksef_number:
            original = history.by_ksef.get(invoice.corrected_ksef_number)
        if original is None and invoice.corrects_invoice_id:
            original = history.by_invoice.get(str(invoice.corrects_invoice_id))
        if original:
            return original, ORIGINAL
    posted = history.by_buyer.get(buyer_id(buyer), ()) if buyer else ()
    earlier = [
        item
        for item in posted
        if item.day <= invoice.issue_date and item.invoice_id != own
    ]
    if earlier:
        last = max(earlier, key=lambda item: (item.day, item.rank, item.seq))
        return last.account, PREVIOUS
    if chosen:
        return chosen, CHOSEN
    return None, NO_HISTORY


def _symfonia(column: Any) -> Any:
    return column["externalData"]["symfonia"]["accountNumberNet"].astext


async def load_history(
    db: AsyncSession,
    invoices: list[Any],
    counterparties: Mapping[tuple[str, str], FinanceCounterparty],
    *,
    vat_account: str,
) -> RevenueHistory:
    """Dekrety Symfonii z archiwum eBI24 i zatwierdzone FVS NEXUSA dla faktur."""

    ksefs = {invoice.ksef_number for invoice in invoices if invoice.ksef_number}
    ksefs |= {
        invoice.corrected_ksef_number
        for invoice in invoices
        if invoice.invoice_kind == "correction" and invoice.corrected_ksef_number
    }
    buyers = {buyer_id(id_value) for _, id_value in counterparties}
    buyers.discard("")
    by_ksef: dict[str, str] = {}
    by_buyer: dict[str, list[Posted]] = defaultdict(list)

    net = _symfonia(FinanceArchiveDocument.meta)
    official = func.regexp_replace(
        func.upper(FinanceArchiveDocument.meta["_partner"]["officialId"].astext),
        "[^A-Z0-9]",
        "",
        "g",
    )
    wanted = buyers | {f"PL{value}" for value in buyers if value.isdigit()}
    scope = []
    if ksefs:
        scope.append(FinanceArchiveDocument.ksef_number.in_(ksefs))
    if wanted:
        scope.append(official.in_(wanted))
    if scope:
        rows = await db.execute(
            select(
                FinanceArchiveDocument.id,
                FinanceArchiveDocument.ksef_number,
                FinanceArchiveDocument.issue_date,
                official,
                net,
            ).where(
                FinanceArchiveDocument.kind == "sale",
                net.is_not(None),
                net != "",
                or_(*scope),
            )
        )
        for row_id, ksef, day, partner, account in rows.all():
            if ksef:
                by_ksef[ksef] = account
            key = buyer_id(partner)
            if key in buyers and day is not None:
                by_buyer[key].append(Posted(day, account, rank=0, seq=row_id))

    by_invoice: dict[str, str] = {}
    party_keys = {
        party.id: buyer_id(id_value) for (_, id_value), party in counterparties.items()
    }
    originals = {
        str(invoice.corrects_invoice_id)
        for invoice in invoices
        if invoice.invoice_kind == "correction" and invoice.corrects_invoice_id
    }
    current: dict[str, str] = {}
    batch = [str(invoice.id) for invoice in invoices]
    if batch:
        rows = await db.execute(
            _revenue_lines(vat_account).where(
                LedgerDocument.source_type == SALES_SOURCE,
                LedgerDocument.source_id.in_(batch),
            )
        )
        for row in _largest(rows.all()):
            current[row.source_id] = row.account
    doc_scope = []
    if party_keys:
        doc_scope.append(LedgerDocument.counterparty_id.in_(list(party_keys)))
    if originals:
        doc_scope.append(
            and_(
                LedgerDocument.source_type == SALES_SOURCE,
                LedgerDocument.source_id.in_(originals),
            )
        )
    if doc_scope:
        rows = await db.execute(
            _revenue_lines(vat_account).where(
                LedgerDocument.doc_type == "FVS",
                LedgerDocument.status == "approved",
                or_(*doc_scope),
            )
        )
        for row in _largest(rows.all()):
            own = row.source_id if row.source_type == SALES_SOURCE else None
            if own is not None:
                by_invoice[own] = row.account
            key = party_keys.get(row.counterparty_id)
            if key:
                by_buyer[key].append(
                    Posted(row.doc_date, row.account, own, rank=1, seq=row.id)
                )
    return RevenueHistory(
        by_ksef=by_ksef,
        by_invoice=by_invoice,
        by_buyer={key: tuple(items) for key, items in by_buyer.items()},
        current=current,
    )


def _revenue_lines(vat_account: str) -> Any:
    """Pozycje bez kontrahenta poza VAT-em nieodwróconych dokumentów."""

    return (
        select(
            LedgerDocument.id,
            LedgerDocument.doc_date,
            LedgerDocument.counterparty_id,
            LedgerDocument.source_type,
            LedgerDocument.source_id,
            LedgerLine.account,
            LedgerLine.amount,
        )
        .join(LedgerLine, LedgerLine.document_id == LedgerDocument.id)
        .where(
            LedgerDocument.reverses_id.is_(None),
            LedgerDocument.reversed_by_id.is_(None),
            LedgerLine.counterparty_id.is_(None),
            LedgerLine.account != vat_account,
        )
    )


def _largest(rows: list[Any]) -> list[Any]:
    """Pozycja przychodu dokumentu = jego największa pozycja z ``_revenue_lines``."""

    best: dict[int, Any] = {}
    for row in rows:
        current = best.get(row.id)
        if current is None or row.amount > current.amount:
            best[row.id] = row
    return list(best.values())
