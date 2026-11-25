"""Numer nabywcy dopisywany do klienta bez Finansów, gdy dane dowodzą, kto kupuje.

Decyzja Artura z 25.11.2026: „uzupełniaj sam i zapisz jako regułę”. Faktura,
której numeru nabywcy (NIP albo VAT UE) nie ma żaden klient, czeka jako
``unmatched``/``unknown_buyer`` w Finanse → „Nieznani nabywcy”, aż Finanse dopiszą
numer klientowi (``matching.save_buyer_number``). Automat robi to samo, gdy ma
jeden z dwóch dowodów:

1. **osoby z pozycji** (``auto_persons``, pierwsze źródło) — bieżące pozycje
   czekających faktur nabywcy (bez „przed korektą”) nazywają pełnym imieniem
   i nazwiskiem (``matching.person_named_in``) osoby z kontraktem, który nie jest
   unieważniony. Pozycja wskazuje klienta kanonicznego kontraktów tych osób
   trwających w miesiącu usługi faktury, a gdy takich nie ma — wszystkich ich
   kontraktów. Pozycja, która wskazuje kilku klientów (np. osoba z kontraktami
   u dwóch klientów w tym miesiącu), nie głosuje. Dowód: co najmniej
   ``MIN_NAMED_POSITIONS`` pozycje wskazują klienta i żadna nie wskazuje innego,
   a nazwa nabywcy nie przeczy nazwom prawnym: nie jest nazwą prawną innego
   klienta, a klient z nazwą prawną ma właśnie tę. Spółka z grupy z własnym
   numerem bywa fakturowana za osoby z kontraktem u klienta siostry (pomiar
   z 25.11.2026: dwa numery, jeden klient), a jej numer nie należy do tego klienta;
2. **nazwa prawna** (``auto_legal_name``) — najnowsza nazwa nabywcy z jego faktur
   to ``legal_name`` dokładnie jednego klienta (bez nieaktywnych), a żaden inny
   klient nie ma jej w żadnym polu nazwy: podpowiedź z „Nieznani nabywcy” jest
   jednoznaczna i trafia nazwą prawną. Osoby z pozycji wskazujące innego klienta
   odbierają ten dowód.

Numer zapisujemy tylko w stanie ``add`` (``clients.add_buyer_number``): klient nie
ma numeru, a tego numeru nie ma nikt inny. ``differs`` (np. spółka zależna
z własnym VAT, gdy klient matka ma już numer), ``taken`` i ``same`` zostają
Finansom. Tak samo dwa numery z dowodem na jednego klienta w jednym przebiegu:
klient ma jeden numer, a kolejność dopisania nie jest dowodem.

Przebieg idzie w pętli faktur sprzedaży tuż przed ``matching.rematch_pending``,
każdy nabywca w osobnym SAVEPOINT. Zapis jak „Przypisz” w „Nieznani nabywcy”:
numer u klienta, od razu dopasowanie pozostałych faktur nabywcy i wpis w Historii
zdarzeń (``client.registry_number_added``) bez autora, ze źródłem dowodu. Logi:
identyfikatory i liczby, bez nazwisk, nazw i numerów.
"""

from __future__ import annotations

import calendar
import logging
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.candidate import Candidate
from app.models.client import Client, ClientStatus
from app.models.client_sales_invoice import ClientSalesInvoice
from app.models.contract import Contract, ContractStatus
from app.services import critical_events
from app.services.client_identity import visible_client_predicates
from app.services.client_invoicing import clients, matching
from app.services.order_client_identity import normalize_buyer_number

logger = logging.getLogger(__name__)

#: Jedna pozycja bywa przypadkiem (imiennik, osoba wpisana na fakturę innego
#: nabywcy); dwie to powtarzalny ślad, a dopisanie i tak wymaga stanu ``add``.
MIN_NAMED_POSITIONS = 2
SOURCE_PERSONS = "auto_persons"
SOURCE_LEGAL_NAME = "auto_legal_name"
EVENT_TYPE = "client.registry_number_added"

Period = tuple[int, int]


@dataclass(frozen=True)
class Stint:
    """Kontrakt osoby: klient kanoniczny i daty (brak daty = bez granicy)."""

    client_id: int
    start: Optional[date] = None
    end: Optional[date] = None

    def overlaps(self, period: Period) -> bool:
        first = date(period[0], period[1], 1)
        last = date(period[0], period[1], calendar.monthrange(*period)[1])
        return (self.start is None or self.start <= last) and (
            self.end is None or self.end >= first
        )


@dataclass(frozen=True)
class Person:
    """Osoba z kontraktem (bez unieważnionych): pełne imię i nazwisko i kontrakty."""

    name: str
    stints: tuple[Stint, ...]

    def clients_in(self, period: Optional[Period]) -> frozenset[int]:
        """Klienci kontraktów trwających w miesiącu usługi, a bez nich — wszystkich."""

        within = [
            stint
            for stint in self.stints
            if period is not None and stint.overlaps(period)
        ]
        return frozenset(stint.client_id for stint in within or self.stints)


class People:
    """Osoby z kontraktem do szukania w pozycjach faktur.

    ``person_named_in`` składa tekst i kompiluje wyrażenia przy każdym wywołaniu.
    Na kopii produkcji z 25.11.2026 (1 756 pozycji, 574 osoby) każda para to 3,6 s
    pracy w pętli procesu web, a odsiew 0,03 s przy tym samym wyniku. Wyrażenie
    liczymy więc tylko dla osób, których wszystkie części stoją w pozycji jako
    podciąg (``matching.name_key``), a o trafieniu decyduje dalej ``person_named_in``.
    """

    def __init__(self, people: Iterable[Person]) -> None:
        self._people: list[tuple[Person, list[str]]] = []
        for person in people:
            parts = matching.name_key(person.name).split()
            if len(parts) >= 2:
                # Najdłuższa część (zwykle nazwisko) odrzuca najwięcej pozycji.
                self._people.append((person, sorted(parts, key=len, reverse=True)))

    def named_in(self, text: str) -> list[Person]:
        key = matching.name_key(text)
        return [
            person
            for person, parts in self._people
            if parts[0] in key
            and all(part in key for part in parts[1:])
            and matching.person_named_in(person.name, text)
        ]


def position_client(named: Sequence[Person], period: Optional[Period]) -> Optional[int]:
    """Klient pozycji: jedyny klient kontraktów nazwanych osób, inaczej bez głosu."""

    found = frozenset().union(*(person.clients_in(period) for person in named))
    return next(iter(found)) if len(found) == 1 else None


@dataclass(frozen=True)
class Proof:
    """Klient i źródło dowodu albo powód, dla którego numer zostaje Finansom."""

    client_id: Optional[int] = None
    source: Optional[str] = None
    #: Pozycje z osobami, które wskazują tego klienta.
    named: int = 0
    reason: Optional[str] = None


def decide(
    votes: Sequence[Optional[int]],
    legal_client: Optional[int],
    *,
    buyer_name: str = "",
    legal_names: Optional[Mapping[int, str]] = None,
) -> Proof:
    """Dowód nabywcy z pozycji z osobami i z nazwy prawnej (czysta funkcja).

    ``votes`` — klient każdej pozycji, która nazywa osobę z kontraktem (``None`` =
    pozycja nie głosuje); ``legal_client`` — jedyny klient, którego nazwą prawną
    jest nazwa nabywcy; ``legal_names`` — nazwy prawne klientów, a ``buyer_name``
    — nazwa nabywcy, obie w postaci ``_name_key``.
    """

    counted = Counter(vote for vote in votes if vote is not None)
    if len(counted) > 1:
        return Proof(reason="persons_disagree")
    client_id, named = next(iter(counted.items()), (None, 0))
    if client_id is not None and named >= MIN_NAMED_POSITIONS:
        if legal_client not in (None, client_id):
            return Proof(named=named, reason="sources_differ")
        legal_name = (legal_names or {}).get(client_id)
        if legal_name and legal_name != buyer_name:
            return Proof(named=named, reason="legal_name_differs")
        return Proof(client_id, SOURCE_PERSONS, named)
    if legal_client is None:
        return Proof(named=named, reason="no_proof")
    if client_id not in (None, legal_client):
        return Proof(named=named, reason="sources_differ")
    return Proof(legal_client, SOURCE_LEGAL_NAME, named)


@dataclass(frozen=True)
class Proposal:
    """Nabywca z czekającymi fakturami: dowód i stan numeru u klienta z dowodu."""

    number: str
    invoices: int
    proof: Proof
    #: ``clients.check_buyer_number`` dla klienta z dowodu albo ``several_numbers``.
    state: Optional[str] = None

    @property
    def ready(self) -> bool:
        return self.state == "add"


@dataclass(frozen=True)
class _Waiting:
    buyer_name: Optional[str]
    period: Optional[Period]
    #: Nazwy bieżących pozycji (bez „przed korektą”).
    items: tuple[str, ...]


def _name_key(name: Optional[str]) -> str:
    """Nazwa bez wielkości liter i zbędnych spacji, jak w podpowiedzi klienta."""

    return " ".join((name or "").casefold().split())


async def _waiting(db: AsyncSession) -> dict[str, list[_Waiting]]:
    """Faktury ``unknown_buyer`` bez klienta po numerze nabywcy, od najstarszej.

    Same kolumny, nie obiekty: sesja nie wygasza obiektów po commicie, a
    ``rematch_pending`` w tej samej sesji ma czytać faktury z bazy.
    """

    rows = await db.execute(
        select(
            ClientSalesInvoice.buyer_nip,
            ClientSalesInvoice.buyer_foreign_id,
            ClientSalesInvoice.buyer_name,
            ClientSalesInvoice.period_year,
            ClientSalesInvoice.period_month,
            ClientSalesInvoice.items,
        )
        .where(
            ClientSalesInvoice.match_status == "unmatched",
            ClientSalesInvoice.match_reason == "unknown_buyer",
            ClientSalesInvoice.client_id.is_(None),
        )
        .order_by(ClientSalesInvoice.issue_date, ClientSalesInvoice.id)
    )
    groups: dict[str, list[_Waiting]] = defaultdict(list)
    for nip, foreign_id, buyer_name, year, month, items in rows:
        # Ten sam klucz co ``matching.buyer_number`` w ``save_buyer_number``.
        number = normalize_buyer_number(nip or foreign_id or "")
        if not clients.is_registry_key(number):
            continue
        groups[number].append(
            _Waiting(
                buyer_name=buyer_name,
                period=(int(year), int(month)) if year and month else None,
                items=tuple(
                    str(item.get("name") or "")
                    for item in items or []
                    if isinstance(item, dict) and not item.get("before_correction")
                ),
            )
        )
    return groups


async def _people(db: AsyncSession) -> People:
    canonical = await clients.canonical_clients(db)
    rows = await db.execute(
        select(
            Contract.candidate_id,
            Candidate.name,
            Candidate.lastname,
            Contract.client_id,
            Contract.start_date,
            Contract.end_date,
        )
        .join(Candidate, Candidate.id == Contract.candidate_id)
        .where(Contract.status != ContractStatus.void)
    )
    names: dict[int, str] = {}
    stints: dict[int, list[Stint]] = defaultdict(list)
    for candidate_id, first, last, client_id, start, end in rows:
        target = canonical.get(int(client_id))
        if target is None:
            continue
        names[int(candidate_id)] = f"{first or ''} {last or ''}".strip()
        stints[int(candidate_id)].append(Stint(target, start, end))
    return People(Person(name, tuple(stints[cid])) for cid, name in names.items())


async def _legal_names(db: AsyncSession) -> tuple[dict[str, int], dict[int, str]]:
    """Nazwa prawna każdego klienta i nazwa → klient, gdy nikt inny jej nie nosi.

    Drugie to podpowiedź z „Nieznani nabywcy” (klienci bez nieaktywnych, nazwa
    prawna, wyświetlana i źródłowa) zawężona do trafienia nazwą prawną.
    """

    of_client: dict[int, str] = {}
    for client_id, legal_name in await db.execute(
        select(Client.id, Client.legal_name).where(Client.legal_name.is_not(None))
    ):
        key = _name_key(legal_name)
        if key:
            of_client[int(client_id)] = key
    owners: dict[str, set[int]] = defaultdict(set)
    for client_id, *names in await db.execute(
        select(Client.id, Client.legal_name, Client.display_name, Client.name).where(
            *visible_client_predicates(), Client.status != ClientStatus.inactive
        )
    ):
        for name in names:
            key = _name_key(name)
            if key:
                owners[key].add(int(client_id))
    by_name = {
        key: next(iter(ids))
        for key, ids in owners.items()
        if len(ids) == 1 and of_client.get(next(iter(ids))) == key
    }
    return by_name, of_client


def _votes(invoices: Sequence[_Waiting], people: People) -> list[Optional[int]]:
    votes: list[Optional[int]] = []
    for invoice in invoices:
        for item in invoice.items:
            named = people.named_in(item)
            if named:
                votes.append(position_client(named, invoice.period))
    return votes


def _one_number_per_client(proposals: list[Proposal]) -> list[Proposal]:
    """Dwa numery z dowodem na jednego klienta: żaden, bo klient ma jeden numer.

    Dopisanie pierwszego dałoby drugiemu ``differs``, więc o numerze klienta
    decydowałaby kolejność nabywców w przebiegu.
    """

    ready = Counter(
        proposal.proof.client_id for proposal in proposals if proposal.ready
    )
    return [
        replace(proposal, state="several_numbers")
        if proposal.ready and ready[proposal.proof.client_id] > 1
        else proposal
        for proposal in proposals
    ]


async def plan(db: AsyncSession) -> list[Proposal]:
    """Dowód dla każdego nabywcy z czekającymi fakturami; tylko odczyt (na sucho)."""

    groups = await _waiting(db)
    if not groups:
        return []
    people = await _people(db)
    legal_by_name, legal_of_client = await _legal_names(db)
    proposals: list[Proposal] = []
    for number, invoices in groups.items():
        buyer_name = next(
            (
                invoice.buyer_name
                for invoice in reversed(invoices)
                if invoice.buyer_name
            ),
            None,
        )
        buyer_key = _name_key(buyer_name)
        proof = decide(
            _votes(invoices, people),
            legal_by_name.get(buyer_key),
            buyer_name=buyer_key,
            legal_names=legal_of_client,
        )
        state = None
        if proof.client_id is not None:
            check = await clients.check_buyer_number(db, proof.client_id, number)
            state = check.state
        proposals.append(Proposal(number, len(invoices), proof, state))
    return _one_number_per_client(proposals)


def _reason(proof: Proof, number: str, invoice_number: str) -> str:
    if proof.source == SOURCE_PERSONS:
        why = f"pozycje z osobami z kontraktem u tego klienta: {proof.named}"
    else:
        why = "nazwa nabywcy to nazwa prawna tego klienta"
    return f"Numer {number} z faktury {invoice_number} dopisany automatycznie ({why})."


async def _save(db: AsyncSession, proposal: Proposal) -> Optional[dict[str, Any]]:
    # Faktury przed klientem, jak „Przypisz” w „Nieznani nabywcy”: ta sama kolejność
    # blokad, a faktury przypisane przed chwilą przez Finanse już nie czekają.
    waiting = await matching.invoices_waiting_for_number(db, proposal.number)
    if not waiting:
        return None
    invoice = waiting[-1]
    saved = await matching.save_buyer_number(
        db, invoice, client_id=proposal.proof.client_id
    )
    if saved["saved"]:
        await critical_events.record_executed(
            db,
            actor=None,
            event_type=EVENT_TYPE,
            entity_type="client",
            entity_id=saved["client_id"],
            client_id=saved["client_id"],
            reason=_reason(proposal.proof, saved["number"], invoice.invoice_number),
            details={
                "invoice_id": invoice.id,
                "retried": saved["retried"],
                "matched": saved["matched"],
                "source": proposal.proof.source,
                "named_positions": proposal.proof.named,
            },
        )
    return saved


async def attach(db: AsyncSession) -> dict[str, int]:
    """Dopisuje numery z dowodem w stanie ``add``. Commit należy do wołającego."""

    proposals = await plan(db)
    added = matched = 0
    for proposal in proposals:
        if not proposal.ready:
            continue
        try:
            async with db.begin_nested():
                saved = await _save(db, proposal)
        except Exception:  # noqa: BLE001 — nabywca zostaje Finansom, reszta idzie dalej
            logger.exception(
                "[client-invoicing] numer nabywcy z dowodu nieudany (klient %s)",
                proposal.proof.client_id,
            )
            continue
        if saved is None or not saved["saved"]:
            continue
        added += 1
        matched += saved["matched"]
        logger.info(
            "[client-invoicing] numer nabywcy dopisany automatycznie: klient %s, "
            "źródło %s, pozycje z osobami %s, faktury %s, dopasowane %s",
            saved["client_id"],
            proposal.proof.source,
            proposal.proof.named,
            saved["retried"],
            saved["matched"],
        )
    return {
        "proven": sum(1 for proposal in proposals if proposal.ready),
        "added": added,
        "matched": matched,
    }


__all__ = [
    "MIN_NAMED_POSITIONS",
    "People",
    "Person",
    "Proof",
    "Proposal",
    "SOURCE_LEGAL_NAME",
    "SOURCE_PERSONS",
    "Stint",
    "attach",
    "decide",
    "plan",
    "position_client",
]
