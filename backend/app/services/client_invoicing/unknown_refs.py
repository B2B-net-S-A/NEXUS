"""Faktura nazywa osobę albo zamówienie, których NEXUS nie zna (audyt luk 25.11.2026).

Przegląd faktur KSeF IV–X 2026 pokazał dwie luki, których nie widział żaden alert:

- osoby z faktur Nordei bez żadnego kontraktu u klienta (ponad 20 osób),
  bo ``line_gaps`` bierze tylko osoby z kontraktem, a resztę zostawia Finansom;
- faktury z numerem zamówienia, którego NEXUS nie ma, gdy osoba ma pozycję albo
  pozycja nie nazywa osoby (u jednego klienta prawie 50 faktur bez żadnej karty).

Oba sygnały trafiają do tego samego alertu DL co ``line_gaps``
(``invoice_without_order_line``): faktura nie ma pozycji zamówienia w NEXUSIE,
różni się tylko tym, czego brakuje. Faktura, dla której ``line_gaps`` już
wskazał osobę, nie dostaje drugiej karty o numerze.

Osobę bierzemy tylko z jawnego znacznika („Contractor”, „Konsultant”), bo wolny
tekst pozycji to też nazwy projektów i osoby klienta („Nordea Contact: …”).
Literówka albo skrócone podwójne nazwisko w fakturze („Nowak” przy
„Nowak-Kowalski”) nie jest luką: osoba ma kontrakt, tylko klient pisze inaczej.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from typing import Literal

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.candidate import Candidate
from app.models.client_sales_invoice import ClientSalesInvoice
from app.models.client_time_report import ClientExternalId
from app.models.contract import Contract, ContractStatus
from app.services.client_invoicing import clients, matching
from app.services.client_invoicing.line_gaps import GAP_MONTHS_BACK, _months_back
from app.services.client_settlements.time_reports import person_numbers

PERSON_NO_KIND = "client_person_no"
#: Znacznik osoby w pozycji faktury; po nim imię i nazwisko (2–4 wyrazy).
_MARKER = re.compile(
    r"\b(?:contractor|consultant|konsultant)\b\s*[:;,-]?\s*", re.IGNORECASE
)
#: Osoba klienta w tej samej pozycji („Nordea Contact: …”) — bywa wpisana też jako kontraktor.
_CONTACT = re.compile(r"\bcontact\b\s*:\s*", re.IGNORECASE)
#: Wyraz z literami; apostrof i łącznik w środku („O’Neill”, „Nowak-Kowalski”).
_WORD = re.compile(r"[^\W\d_](?:[^\W\d_]|['’-](?=[^\W\d_]))*")
#: Wyrazy, na których kończy się imię i nazwisko („… ID: M1”, „… Nr zamówienia”).
_STOP = frozenset({"id", "nr", "nids", "numer", "zamowienie", "zamowienia", "order"})
_SAME_SURNAME_EDITS = 2

Kind = Literal["person", "order"]


@dataclass(frozen=True)
class UnknownRef:
    invoice_id: int
    invoice_number: str
    client_id: int
    year: int
    month: int
    kind: Kind
    label: str

    @property
    def entity_key(self) -> str:
        slug = "-".join(_fold_words(self.label)) or "brak"
        return f"invoice:{self.invoice_id}:{self.kind}:{slug}"


def _fold_words(text: str) -> list[str]:
    folded = re.sub(r"['’]", "", matching._fold(text).lower())
    return [w for w in re.split(r"[^a-z0-9]+", folded) if w]


def _names_after(marker: re.Pattern[str], text: str) -> list[str]:
    found: list[str] = []
    for hit in marker.finditer(text):
        rest = text[hit.end() :]
        words: list[str] = []
        position = 0
        for match in _WORD.finditer(rest):
            word = match.group(0)
            if (
                rest[position : match.start()].strip()
                or matching._fold(word).lower() in _STOP
                or not word[0].isupper()
            ):
                break
            words.append(word)
            position = match.end()
            if len(words) == 4:
                break
        if len(words) >= 2:
            found.append(" ".join(words))
    return found


def marked_people(text: str) -> list[str]:
    """Imiona i nazwiska po znaczniku osoby, np. „Contractor Jan Przykładowy ID: M1”.

    Nazwisko, które ta sama pozycja podaje też jako osobę klienta („Contact:”),
    to błąd w treści faktury, nie kontraktor.
    """

    contacts = {matching._fold(name).lower() for name in _names_after(_CONTACT, text)}
    return [
        name
        for name in _names_after(_MARKER, text)
        if matching._fold(name).lower() not in contacts
    ]


def _edits(a: str, b: str) -> int:
    if abs(len(a) - len(b)) > _SAME_SURNAME_EDITS:
        return _SAME_SURNAME_EDITS + 1
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        current = [i]
        for j, cb in enumerate(b, 1):
            current.append(
                min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (ca != cb))
            )
        previous = current
    return previous[-1]


def same_person(contract_person: str, invoice_name: str) -> bool:
    """Osoba z kontraktu to osoba z faktury mimo skrótu albo literówki w nazwisku."""

    return _same_words(_fold_words(contract_person), _fold_words(invoice_name))


def _same_words(ours: list[str], theirs: list[str]) -> bool:
    if len(ours) < 2 or len(theirs) < 2:
        return False
    if set(theirs) <= set(ours) or set(ours) <= set(theirs):
        return True
    return ours[0] == theirs[0] and any(
        _edits(theirs[-1], part) <= _SAME_SURNAME_EDITS for part in ours[1:]
    )


async def _invoices(db: AsyncSession, today: date) -> list[ClientSalesInvoice]:
    year, month = _months_back(today, GAP_MONTHS_BACK)
    return list(
        await db.scalars(
            select(ClientSalesInvoice)
            .where(
                ClientSalesInvoice.match_status.in_(("matched", "unmatched")),
                ClientSalesInvoice.client_id.is_not(None),
                ClientSalesInvoice.invoice_kind == "original",
                ClientSalesInvoice.period_year.is_not(None),
                or_(
                    ClientSalesInvoice.period_year > year,
                    and_(
                        ClientSalesInvoice.period_year == year,
                        ClientSalesInvoice.period_month >= month,
                    ),
                ),
            )
            .order_by(ClientSalesInvoice.id)
        )
    )


@dataclass(frozen=True)
class _Known:
    #: Imiona i nazwiska osób z kontraktem, już jako słowa bez znaków (raz na klienta).
    people: tuple[tuple[str, ...], ...]
    person_numbers: frozenset[str]


async def _known(db: AsyncSession, members: set[int]) -> _Known:
    rows = await db.execute(
        select(Candidate.name, Candidate.lastname)
        .join(Contract, Contract.candidate_id == Candidate.id)
        .where(Contract.client_id.in_(members), Contract.status != ContractStatus.void)
        .distinct()
    )
    numbers = await db.scalars(
        select(ClientExternalId.value).where(
            ClientExternalId.client_id.in_(members),
            ClientExternalId.kind == PERSON_NO_KIND,
        )
    )
    return _Known(
        people=tuple(
            tuple(_fold_words(f"{name or ''} {lastname or ''}"))
            for name, lastname in rows
        ),
        person_numbers=frozenset(str(value).upper() for value in numbers),
    )


def _people_without_contract(item: str, known: _Known) -> list[str]:
    if {no.upper() for no in person_numbers(item)} & known.person_numbers:
        return []
    labels: list[str] = []
    numbers = sorted(person_numbers(item))
    for name in marked_people(item):
        theirs = _fold_words(name)
        if any(_same_words(list(person), theirs) for person in known.people):
            continue
        labels.append(f"{name} (ID {numbers[0]})" if len(numbers) == 1 else name)
    return labels


def _period(invoice: ClientSalesInvoice) -> tuple[int, int]:
    return int(invoice.period_year), int(invoice.period_month)


async def unknown_refs(
    db: AsyncSession, today: date, *, skip_order_check: Iterable[int] = ()
) -> list[UnknownRef]:
    """Osoby bez kontraktu i nieznane numery zamówień z faktur ostatnich miesięcy.

    ``skip_order_check`` to faktury, dla których ``line_gaps`` już wskazał osobę.
    """

    skipped = set(skip_order_check)
    known: dict[int, _Known] = {}
    found: dict[str, UnknownRef] = {}
    for invoice in await _invoices(db, today):
        client_id = int(invoice.client_id)
        year, month = _period(invoice)
        if client_id not in known:
            known[client_id] = await _known(db, await clients.family(db, [client_id]))
        for item in _items(invoice):
            for label in _people_without_contract(item, known[client_id]):
                ref = UnknownRef(
                    invoice.id,
                    invoice.invoice_number,
                    client_id,
                    year,
                    month,
                    "person",
                    label,
                )
                found[ref.entity_key] = ref
        if (
            invoice.match_status == "unmatched"
            and invoice.match_reason == "unknown_order_number"
            and invoice.id not in skipped
        ):
            numbers = matching.named_order_numbers(matching.invoice_texts(invoice))
            label = ", ".join(dict.fromkeys(numbers)) or "z faktury"
            ref = UnknownRef(
                invoice.id,
                invoice.invoice_number,
                client_id,
                year,
                month,
                "order",
                label,
            )
            found[ref.entity_key] = ref
    return list(found.values())


def _items(invoice: ClientSalesInvoice) -> list[str]:
    return [
        str(item.get("name") or "")
        for item in invoice.items or []
        if isinstance(item, dict) and not item.get("before_correction")
    ]


def describe(ref: UnknownRef, client_name: str) -> tuple[str, str]:
    """Tytuł i treść karty DL."""

    period = f"{ref.month:02d}.{ref.year}"
    if ref.kind == "person":
        return (
            f"{client_name} — osoba z faktury bez kontraktu",
            f"📄 {client_name} — faktura {ref.invoice_number} za {period} dotyczy "
            f"{ref.label}, a ta osoba nie ma kontraktu u tego klienta. Dodaj kontrakt "
            "albo popraw imię i nazwisko w istniejącym.",
        )
    return (
        f"{client_name} — zamówienie z faktury nieznane NEXUS-owi",
        f"📄 {client_name} — faktura {ref.invoice_number} za {period} podaje "
        f"zamówienie {ref.label}, którego nie ma w NEXUSIE. Dodaj zamówienie z PDF-u "
        "albo popraw numer istniejącego.",
    )


__all__ = [
    "UnknownRef",
    "describe",
    "marked_people",
    "same_person",
    "unknown_refs",
]
