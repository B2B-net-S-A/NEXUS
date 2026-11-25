"""Ostrzeżenie „podwójna zapłata” w planie paczki przelewów (audyt 25.11.2026).

Audyt fakturowania IV–X 2026 znalazł korektę kontraktora na plus równą całej
wcześniejszej fakturze (i podobne u czterech innych dostawców) oraz dwie faktury
jednej osoby na tę samą kwotę w jednym miesiącu. Każdy z tych dokumentów
z osobna wygląda poprawnie, więc paczka zapłaciłaby tę samą usługę dwa razy.

Trzy sytuacje, wszystkie jako ostrzeżenie do odhaczenia (``double_payment``),
nie blokada — bywają uczciwe (dwie osoby jednej firmy z tą samą stawką,
dopłata za cały miesiąc):

* **korekta na plus = cała wcześniejsza faktura** — korekta (``Kor``) z netto
  większym od zera równym netto wcześniejszej faktury VAT tego dostawcy (ta sama
  waluta). Kwota korekty w KSeF to **różnica** („stan po” minus „stan przed”),
  nie stan po korekcie — więc taka korekta dokłada drugą całą fakturę,
* **druga faktura VAT na tę samą kwotę netto za ten sam miesiąc usługi** — tylko
  dziennik „Kontraktorzy” (w zakupach i biurze to zwykłe abonamenty: na kopii
  produkcji 25.11 ok. 190 takich faktur od 10 dostawców, prawie same raty
  i opłaty stałe). Miesiąc usługi znamy dla faktury przypiętej do kontraktu
  (``period_month``); bez niego liczy się wystawienie w odstępie krótszym niż
  ``SAME_MONTH_DAYS`` dni — faktura z 1. dnia miesiąca jest zwykle za poprzedni,
  więc miesiąc kalendarzowy daty wystawienia mylił faktury za kolejne miesiące,
* **ten sam numer faktury dwa razy** od tego samego dostawcy (bez spacji i bez
  wielkości liter). Korekta na zero albo na minus z numerem faktury pierwotnej
  nie dokłada zapłaty i nie ostrzega.

Dokument odrzucony w kolejce albo oznaczony „Duplikat” nie jest „tą drugą”
fakturą: Finanse już go rozstrzygnęły. Ostrzeżenie dostaje wpis, który się
płaci: faktura bez korekt, faktura pierwotna z korektami (sprawdzamy też jej
korekty z łańcucha) i korekta płacona osobno (dokument wydatku).
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Iterable, Optional, Sequence

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.client_settlement import ClientContractorInvoice
from app.models.finance_ledger import FinanceCostEntry
from app.models.hr_approval import ApprovalDocument
from app.services.client_settlements.invoice_chain import CORRECTION_TYPES
from app.services.finance_ledger import journals

ACK = "double_payment"
#: Wystawienie w odstępie krótszym niż tyle dni = ten sam miesiąc usługi
#: (gdy dokument nie zna miesiąca). Kopia produkcji 25.11.2026: pary faktur
#: kontraktorów za kolejne miesiące leżą 27–30 dni od siebie, podejrzane 0–17.
SAME_MONTH_DAYS = 20
ORIGINAL_TYPES = frozenset({"Vat", "VAT"})
_ZERO = Decimal("0")
_SPACES = re.compile(r"\s+")


@dataclass(frozen=True)
class CostDoc:
    """Faktura kosztowa z KSeF (faktura kontraktora albo dokument wydatku)."""

    key: str
    seller_nip: str
    invoice_number: Optional[str]
    kind: Optional[str]
    issue_date: Optional[date]
    currency: str
    net: Optional[Decimal]
    #: Miesiąc usługi ``RRRR-MM`` (faktura przypięta do kontraktu).
    service_month: Optional[str] = None
    entry_id: Optional[int] = None
    #: Odrzucony w kolejce albo „Duplikat” — nie liczy się jako druga faktura.
    settled: bool = False

    @property
    def correction(self) -> bool:
        return self.kind in CORRECTION_TYPES

    @property
    def original(self) -> bool:
        return self.kind in ORIGINAL_TYPES

    @property
    def label(self) -> str:
        number = self.invoice_number or "bez numeru"
        day = self.issue_date.strftime("%d.%m.%Y") if self.issue_date else None
        return f"{number} z {day}" if day else number


def number_key(number: Optional[str]) -> Optional[str]:
    folded = _SPACES.sub("", number or "").lower()
    return folded or None


def _money(value: Decimal) -> str:
    return f"{value:,.2f}".replace(",", " ").replace(".", ",")


def _same_month(a: CostDoc, b: CostDoc) -> bool:
    if a.service_month and b.service_month:
        return a.service_month == b.service_month
    if a.issue_date is None or b.issue_date is None:
        return False
    return abs((a.issue_date - b.issue_date).days) < SAME_MONTH_DAYS


def _adds_payment(doc: CostDoc) -> bool:
    return not doc.correction or (doc.net is not None and doc.net > _ZERO)


def findings(
    doc: CostDoc, others: Iterable[CostDoc], *, contractors: bool
) -> list[str]:
    """Zdania ostrzeżenia dla dokumentu wobec innych dokumentów tego dostawcy."""

    out: list[str] = []
    rest = [
        other
        for other in others
        if other.key != doc.key
        and not other.settled
        and other.seller_nip == doc.seller_nip
    ]
    if doc.correction and doc.net is not None and doc.net > _ZERO:
        for other in rest:
            if (
                other.original
                and other.currency == doc.currency
                and other.net == doc.net
                and (
                    doc.issue_date is None
                    or other.issue_date is None
                    or other.issue_date <= doc.issue_date
                )
            ):
                out.append(
                    f"Korekta {doc.label} dodaje {_money(doc.net)} {doc.currency} "
                    f"netto — tyle, ile cała faktura {other.label}. Kwota korekty "
                    "w KSeF to różnica, więc to druga zapłata za tę samą usługę, "
                    "jeśli dostawca nie skorygował czegoś innego."
                )
                break
    if contractors and doc.original and doc.net is not None and doc.net > _ZERO:
        for other in rest:
            if (
                other.original
                and other.currency == doc.currency
                and other.net == doc.net
                and _same_month(doc, other)
            ):
                out.append(
                    f"Druga faktura od tego dostawcy na {_money(doc.net)} "
                    f"{doc.currency} netto za ten sam miesiąc: {other.label} — "
                    "sprawdź, czy to nie ta sama usługa (dwie osoby jednej firmy "
                    "z tą samą stawką są w porządku)."
                )
                break
    mine = number_key(doc.invoice_number)
    if mine and _adds_payment(doc):
        for other in rest:
            if number_key(other.invoice_number) == mine and _adds_payment(other):
                out.append(
                    f"Ten sam numer faktury co {other.label} od tego samego "
                    "dostawcy — sprawdź, czy to nie ta sama faktura wysłana do "
                    "KSeF dwa razy."
                )
                break
    return out


# ── Odczyt z bazy ────────────────────────────────────────────────────────────


async def _docs(db: AsyncSession, nips: set[str]) -> list[CostDoc]:
    if not nips:
        return []
    entry = FinanceCostEntry
    contractor = await db.execute(
        select(ClientContractorInvoice, entry.id, entry.stage, entry.flags)
        .outerjoin(
            entry,
            and_(
                entry.source_type == "contractor_invoice",
                entry.source_id == ClientContractorInvoice.id,
            ),
        )
        .where(ClientContractorInvoice.seller_nip.in_(nips))
    )
    out: list[CostDoc] = []
    seen: set[str] = set()
    for doc, entry_id, stage, flags in contractor.all():
        seen.add(doc.ksef_number)
        out.append(
            CostDoc(
                key=f"c{doc.id}",
                seller_nip=doc.seller_nip,
                invoice_number=doc.invoice_number,
                kind=doc.invoice_type,
                issue_date=doc.issue_date,
                currency=doc.currency or "PLN",
                net=doc.net_amount,
                service_month=doc.period_month,
                entry_id=entry_id,
                settled=_settled(stage, flags),
            )
        )
    documents = await db.execute(
        select(ApprovalDocument, entry.id, entry.stage, entry.flags)
        .outerjoin(
            entry,
            and_(
                entry.source_type == "approval_document",
                entry.source_id == ApprovalDocument.id,
            ),
        )
        .where(ApprovalDocument.seller_nip.in_(nips))
    )
    for doc, entry_id, stage, flags in documents.all():
        # Ta sama faktura z KSeF w obu tabelach liczy się raz.
        if doc.ksef_number and doc.ksef_number in seen:
            continue
        out.append(
            CostDoc(
                key=f"a{doc.id}",
                seller_nip=doc.seller_nip or "",
                invoice_number=doc.invoice_number,
                kind=doc.ksef_invoice_type,
                issue_date=doc.issue_date,
                currency=doc.currency or "PLN",
                net=doc.net_amount,
                entry_id=entry_id,
                settled=_settled(stage, flags),
            )
        )
    return out


def _settled(stage: Optional[str], flags: Optional[Sequence[str]]) -> bool:
    return stage == "rejected" or "duplicate" in (flags or [])


async def for_entries(
    db: AsyncSession,
    entries: Sequence[FinanceCostEntry],
    *,
    chains: dict[int, tuple[int, ...]],
) -> dict[int, str]:
    """Wpis → zdanie ostrzeżenia (tylko wpisy z ostrzeżeniem).

    ``chains`` — wpisy łańcucha korekt faktury pierwotnej (``Payable.chain``):
    płacąc ją, płacimy też jej korekty, więc sprawdzamy i je.
    """

    wanted = [
        entry
        for entry in entries
        if entry.seller_nip and entry.source_type != "payroll_invoice"
    ]
    docs = await _docs(db, {str(entry.seller_nip) for entry in wanted})
    by_entry = {doc.entry_id: doc for doc in docs if doc.entry_id is not None}
    by_seller: dict[str, list[CostDoc]] = defaultdict(list)
    for doc in docs:
        by_seller[doc.seller_nip].append(doc)
    out: dict[int, str] = {}
    for entry in wanted:
        own = by_entry.get(entry.id)
        if own is None:
            continue
        checked = [own] + [
            by_entry[other]
            for other in chains.get(entry.id, ())
            if other != entry.id and other in by_entry and by_entry[other].correction
        ]
        contractors = journals.journal_of(entry.category) == "contractors"
        sentences: list[str] = []
        for doc in checked:
            for sentence in findings(
                doc, by_seller[doc.seller_nip], contractors=contractors
            ):
                if sentence not in sentences:
                    sentences.append(sentence)
        if sentences:
            out[entry.id] = " ".join(sentences)
    return out


__all__ = ["ACK", "CostDoc", "SAME_MONTH_DAYS", "findings", "for_entries", "number_key"]
