"""NIP kontraktora z faktur KSeF zapisuje się sam (decyzja Artura z 25.11.2026).

Zawęża E4.0 („Finanse zatwierdzają NIP”, ``contractor_invoices``): NIP, którego
dowodzą faktury, NEXUS zapisuje osobie sam, tak jak zatwierdzenie Finansów
(``candidates.nip``, faktura ``confirmed`` bez ``decided_by``). Podpowiedź bez
takiego dowodu dalej czeka na Finanse. Reguła, progi i pułapki:
``docs/claude/finanse-insights/nip-kontraktora-z-ksef-sam.md``.

Dowód pary NIP → osoba z kontraktem:

* każdy dokument z tym NIP-em nazywa imieniem i nazwiskiem tę jedną osobę i nikogo
  innego spośród osób z kontraktem (w każdym stanie) i kont zespołu: faktury
  zakupowe z KSeF (``approval_documents``, ``client_contractor_invoices``; nazwa
  sprzedawcy) i nasze faktury „Benefit” (``client_sales_invoices``, numer
  ``…/Benefit``; nazwa nabywcy). Dokument bez osoby w nazwie wyklucza NIP:
  fundacja-inkubator wystawia pod jednym NIP-em za wielu konsultantów;
* faktura zakupowa i drugi dokument z innego miesiąca wystawienia albo faktura
  „Benefit” na ten NIP (dwa źródła zgodne co do NIP-u i osoby);
* NIP nie należy do innego kandydata, osoby z Płac ani umowy z generatora B2B
  innej osoby, Finanse nie odrzuciły go tej osobie, a osoba nie ma NIP-u.

Korekty się nie liczą: powtarzają nazwę i miesiąc faktury korygowanej.

Dwie drogi: ``confirm_on_arrival`` w ``contractor_invoices.consider`` (nowa
faktura, która byłaby podpowiedzią) i ``backfill`` na historii, raz po wdrożeniu
z pętli zakupów KSeF (``backfill_once``, znacznik ``BACKFILL_KEY``). Przebieg
wstecz zapisuje tylko ``candidates.nip``, bez wierszy faktur z historii;
``dry_run=True`` liczy to samo bez zapisu.
"""

from __future__ import annotations

import logging
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any, Iterable, Optional

from sqlalchemy import or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scheduling import business_date
from app.models.app_setting import AppSetting
from app.models.b2b_generated_contract import B2BGeneratedContract
from app.models.candidate import Candidate
from app.models.client_sales_invoice import ClientSalesInvoice
from app.models.client_settlement import ClientContractorInvoice
from app.models.contract import Contract
from app.models.hr_approval import ApprovalDocument
from app.models.hr_settlement import EmployeeBillingDetails
from app.models.user import User
from app.services.client_settlements import contractor_invoices as ci
from app.services.client_settlements import settings as settlements_module
from app.services.client_settlements.invoice_chain import CORRECTION_TYPES
from app.services.client_settlements.rcp_checks import name_tokens

logger = logging.getLogger(__name__)

BACKFILL_KEY = "contractor_nip_backfill_2026_11"
PURCHASE, BENEFIT = "purchase", "benefit"
#: Odsprzedaż pakietów medycznych i sportowych kontraktorom: ``{n}/{m}/{rrrr}/Benefit``.
BENEFIT_NUMBER = "%/Benefit"

# Wynik sprawdzenia NIP-u; nazwy są kluczami liczników przebiegu wstecz.
PROVEN = "proven"
#: NIP już wiąże faktury (kandydat albo ``partner_nip`` kontraktu z indeksu).
BOUND = "bound"
#: Żaden dokument nie nazywa osoby: dostawca firmy, inkubator.
NO_PERSON = "no_person"
#: Część dokumentów bez osoby w nazwie: NIP wspólny dla wielu ludzi.
UNNAMED = "unnamed"
#: Imiennicy albo kilka osób w nazwach.
SEVERAL_PEOPLE = "several_people"
#: Dokumenty z jednego miesiąca, bez faktury „Benefit”.
SINGLE_MONTH = "single_month"
#: Same faktury „Benefit”, bez faktury zakupowej.
BENEFIT_ONLY = "benefit_only"
#: Osoba z zespołu albo bez kontraktu w indeksie rozliczeń.
NOT_CONTRACTOR = "not_contractor"
#: NIP innego kandydata, osoby z Płac albo umowy innej osoby.
TAKEN = "taken"
#: Finanse odrzuciły ten NIP tej osobie.
REJECTED = "rejected"
#: Osoba ma już NIP (własny albo ``partner_nip`` innej umowy).
HAS_NIP = "has_nip"
#: Osoba z dowodem dla dwóch NIP-ów — wybierają Finanse.
SEVERAL_NIPS = "several_nips"


@dataclass(frozen=True)
class Person:
    """Imię i nazwisko do porównania z nazwą sprzedawcy albo nabywcy.

    ``candidate_id`` ``None`` = konto zespołu: wyklucza imienników, NIP-u nie dostaje.
    """

    candidate_id: Optional[int]
    tokens: frozenset[str]


@dataclass(frozen=True)
class Document:
    key: str  # numer KSeF
    source: str  # PURCHASE albo BENEFIT
    month: str  # RRRR-MM wystawienia, pusty bez daty
    name: Optional[str]


@dataclass
class Registry:
    """Osoby do porównania nazw i NIP-y, które już do kogoś należą."""

    people: list[Person] = field(default_factory=list)
    #: NIP → kandydaci z tym NIP-em; ``None`` = Płace albo umowa bez osoby.
    owners: dict[str, set[Optional[int]]] = field(default_factory=dict)
    nips_of: dict[int, set[str]] = field(default_factory=dict)
    #: Kontrakt → kandydat, wszystkie kontrakty (też zakończone).
    candidate_of: dict[int, int] = field(default_factory=dict)

    def note(self, candidate_id: Optional[int], nip: str) -> None:
        self.owners.setdefault(nip, set()).add(candidate_id)
        if candidate_id is not None:
            self.nips_of.setdefault(candidate_id, set()).add(nip)


def _month(day: Optional[date]) -> str:
    return f"{day.year}-{day.month:02d}" if day else ""


def named(people: Iterable[Person], name: Optional[str]) -> set[Optional[int]]:
    """Osoby, których imię i nazwisko stoi w nazwie (``None`` = konto zespołu)."""

    tokens = name_tokens(name)
    if not tokens:
        return set()
    return {person.candidate_id for person in people if person.tokens <= tokens}


def verdict(
    documents: Iterable[Document], people: list[Person]
) -> tuple[Optional[int], str]:
    """Osoba, którą dokumenty jednego NIP-u nazywają zgodnie, i wynik progu.

    Osoba wraca też przy progu niespełnionym (``SINGLE_MONTH``, ``BENEFIT_ONLY``)
    — do liczników próby na sucho."""

    docs = list(documents)
    holders: set[Optional[int]] = set()
    unnamed = False
    for doc in docs:
        hit = named(people, doc.name)
        holders |= hit
        unnamed = unnamed or not hit
    if not holders:
        return None, NO_PERSON
    if len(holders) > 1:
        return None, SEVERAL_PEOPLE
    if unnamed:
        return None, UNNAMED
    holder = next(iter(holders))
    if holder is None:
        return None, NOT_CONTRACTOR
    sources = {doc.source for doc in docs}
    if PURCHASE not in sources:
        return holder, BENEFIT_ONLY
    months = {doc.month for doc in docs if doc.month}
    if BENEFIT not in sources and len(months) < 2:
        return holder, SINGLE_MONTH
    return holder, PROVEN


def check(
    registry: Registry,
    nip: str,
    candidate_id: int,
    *,
    current: set[int],
    rejected: set[tuple[str, int]],
) -> str:
    """Warunki osoby i NIP-u poza dokumentami (``PROVEN`` = wolno zapisać)."""

    if candidate_id not in current:
        return NOT_CONTRACTOR
    if registry.owners.get(nip, set()) - {candidate_id}:
        return TAKEN
    if any(
        registry.candidate_of.get(contract_id) == candidate_id
        for rejected_nip, contract_id in rejected
        if rejected_nip == nip
    ):
        return REJECTED
    if registry.nips_of.get(candidate_id, set()) - {nip}:
        return HAS_NIP
    return PROVEN


def _current(index: ci.ContractorIndex) -> set[int]:
    people = [*index.without_nip, *(p for ps in index.by_nip.values() for p in ps)]
    return {p.candidate_id for p in people if p.candidate_id is not None}


async def load_registry(db: AsyncSession) -> Registry:
    registry = Registry()
    tokens: dict[int, frozenset[str]] = {}
    rows = await db.execute(
        select(
            Contract.id, Contract.candidate_id, Candidate.name, Candidate.lastname
        ).join(Candidate, Candidate.id == Contract.candidate_id)
    )
    for contract_id, candidate_id, first, last in rows.all():
        registry.candidate_of[int(contract_id)] = int(candidate_id)
        tokens[int(candidate_id)] = frozenset(
            name_tokens(f"{first or ''} {last or ''}")
        )
    staff = {
        frozenset(name_tokens(name)) for name in await db.scalars(select(User.name))
    }
    registry.people = [
        *(Person(c, t) for c, t in sorted(tokens.items()) if len(t) >= 2),
        *(Person(None, t) for t in staff if len(t) >= 2),
    ]
    own = await db.execute(
        select(Candidate.id, Candidate.nip).where(Candidate.nip.is_not(None))
    )
    for candidate_id, raw in own.all():
        if nip := ci.clean_nip(raw):
            registry.note(int(candidate_id), nip)
    partner = await db.execute(
        select(
            B2BGeneratedContract.partner_nip,
            Contract.candidate_id,
            B2BGeneratedContract.candidate_id,
        )
        .outerjoin(Contract, Contract.id == B2BGeneratedContract.contract_id)
        .where(B2BGeneratedContract.partner_nip.is_not(None))
    )
    for raw, *holders in partner.all():
        if nip := ci.clean_nip(raw):
            for holder in {int(h) for h in holders if h is not None} or {None}:
                registry.note(holder, nip)
    payroll = await db.scalars(
        select(EmployeeBillingDetails.nip).where(
            EmployeeBillingDetails.nip.is_not(None)
        )
    )
    for raw in payroll:
        if nip := ci.clean_nip(raw):
            registry.note(None, nip)
    return registry


def _original(column: Any) -> Any:
    return or_(column.is_(None), column.not_in(CORRECTION_TYPES))


async def load_documents(
    db: AsyncSession, nip: Optional[str] = None
) -> dict[str, dict[str, Document]]:
    """NIP → dokumenty po numerze KSeF (ten sam numer bywa w obu tabelach zakupów)."""

    purchases = (
        select(
            ApprovalDocument.seller_nip,
            ApprovalDocument.ksef_number,
            ApprovalDocument.issue_date,
            ApprovalDocument.seller_name,
        ).where(
            ApprovalDocument.source == "ksef",
            ApprovalDocument.ksef_number.is_not(None),
            ApprovalDocument.seller_nip.is_not(None),
            _original(ApprovalDocument.ksef_invoice_type),
        ),
        select(
            ClientContractorInvoice.seller_nip,
            ClientContractorInvoice.ksef_number,
            ClientContractorInvoice.issue_date,
            ClientContractorInvoice.seller_name,
        ).where(_original(ClientContractorInvoice.invoice_type)),
    )
    benefit = select(
        ClientSalesInvoice.buyer_nip,
        ClientSalesInvoice.ksef_number,
        ClientSalesInvoice.issue_date,
        ClientSalesInvoice.buyer_name,
    ).where(
        ClientSalesInvoice.buyer_nip.is_not(None),
        ClientSalesInvoice.invoice_kind == "original",
        ClientSalesInvoice.invoice_number.ilike(BENEFIT_NUMBER),
    )
    if nip is not None:
        purchases = (
            purchases[0].where(ApprovalDocument.seller_nip == nip),
            purchases[1].where(ClientContractorInvoice.seller_nip == nip),
        )
        benefit = benefit.where(ClientSalesInvoice.buyer_nip == nip)
    out: dict[str, dict[str, Document]] = defaultdict(dict)
    for source, statement in (
        (PURCHASE, purchases[0]),
        (PURCHASE, purchases[1]),
        (BENEFIT, benefit),
    ):
        for owner, key, issue, name in (await db.execute(statement)).all():
            out[owner].setdefault(key, Document(key, source, _month(issue), name))
    return out


async def _write(db: AsyncSession, candidate_id: int, nip: str, now: datetime) -> bool:
    """Zapis jak ``contractor_invoices.approve_nip``, bez osoby decydującej."""

    candidate = await db.get(
        Candidate, candidate_id, with_for_update=True, populate_existing=True
    )
    if candidate is None or (candidate.nip or "").strip():
        return False
    candidate.nip = nip
    # Podpowiedzi tego NIP-u dla tej osoby idą za zapisem, jak przy zatwierdzeniu.
    pending = await db.scalars(
        select(ClientContractorInvoice).where(
            ClientContractorInvoice.seller_nip == nip,
            ClientContractorInvoice.nip_state == ci.SUGGESTED,
            ClientContractorInvoice.contract_id.in_(
                select(Contract.id).where(Contract.candidate_id == candidate_id)
            ),
        )
    )
    for row in pending:
        row.nip_state = ci.CONFIRMED
        row.decided_by = None
        row.decided_at = now
    await db.flush()
    return True


def _rebind(index: ci.ContractorIndex, candidate_id: int, nip: str) -> None:
    """Indeks przebiegu jak po ``load_index``: kolejne faktury NIP-u są ``known``."""

    moved = [p for p in index.without_nip if p.candidate_id == candidate_id]
    index.without_nip = [p for p in index.without_nip if p.candidate_id != candidate_id]
    index.by_nip.setdefault(nip, []).extend(
        ci.Contractor(p.contract_id, p.candidate_id, p.tokens, nip) for p in moved
    )


async def confirm_on_arrival(
    db: AsyncSession,
    index: ci.ContractorIndex,
    person: ci.Contractor,
    fields: dict[str, Any],
    ksef_number: str,
    now: datetime,
) -> bool:
    """Faktura, która byłaby podpowiedzią, zapisuje NIP osobie sama, gdy razem
    z historią NIP-u spełnia regułę. ``False`` = podpowiedź dla Finansów."""

    if person.candidate_id is None:
        return False
    nip = fields["seller_nip"]
    if index.registry is None:
        index.registry = await load_registry(db)
    registry = index.registry
    found = (await load_documents(db, nip)).get(nip, {})
    if (fields.get("ksef_invoice_type") or "") not in CORRECTION_TYPES:
        found.setdefault(
            ksef_number,
            Document(
                ksef_number,
                PURCHASE,
                _month(fields["issue_date"]),
                fields["seller_name"],
            ),
        )
    holder, reason = verdict(found.values(), registry.people)
    if reason != PROVEN or holder != person.candidate_id:
        return False
    rule = check(
        registry, nip, holder, current=_current(index), rejected=index.rejected
    )
    if rule != PROVEN or not await _write(db, holder, nip, now):
        return False
    registry.note(holder, nip)
    _rebind(index, holder, nip)
    logger.info(
        "client_settlements: NIP z KSeF zapisany sam (kandydat %s, kontrakt %s)",
        holder,
        person.contract_id,
    )
    return True


# ── Przebieg wstecz (raz po wdrożeniu) ───────────────────────────────────────


@dataclass
class Plan:
    """Reguła na całej historii: kandydat → NIP do zapisu i wynik każdego NIP-u."""

    confirm: dict[int, str] = field(default_factory=dict)
    #: NIP → (osoba z dokumentów, wynik).
    decisions: dict[str, tuple[Optional[int], str]] = field(default_factory=dict)
    #: NIP-y, których dowodem jest dopiero faktura „Benefit” (sam zakup: jeden miesiąc).
    with_benefit: set[str] = field(default_factory=set)

    def counts(self) -> dict[str, int]:
        tally = Counter(reason for _, reason in self.decisions.values())
        return {
            "nips": len(self.decisions),
            "candidates": len(self.confirm),
            "with_benefit": len(self.with_benefit),
            **{reason: tally[reason] for reason in sorted(tally)},
        }


async def plan(db: AsyncSession, today: date) -> Plan:
    index = await ci.load_index(db, today)
    registry = await load_registry(db)
    documents = await load_documents(db)
    current = _current(index)
    result = Plan()
    proven: dict[int, list[str]] = defaultdict(list)
    #: Osoba → NIP-y, których dokumenty nazywają tylko ją (także bez progu).
    named_by: dict[int, set[str]] = defaultdict(set)
    for nip, found in sorted(documents.items()):
        holder, reason = verdict(found.values(), registry.people)
        if holder is not None:
            named_by[holder].add(nip)
        if nip in index.by_nip:
            result.decisions[nip] = (None, BOUND)
            continue
        if reason == PROVEN:
            reason = check(
                registry, nip, holder, current=current, rejected=index.rejected
            )
        result.decisions[nip] = (holder, reason)
        if reason != PROVEN:
            continue
        proven[holder].append(nip)
        purchases = [doc for doc in found.values() if doc.source == PURCHASE]
        if verdict(purchases, registry.people)[1] == SINGLE_MONTH:
            result.with_benefit.add(nip)
    # Drugi NIP z nazwiskiem osoby (zmiana działalności, nowy NIP z jednym
    # miesiącem faktur): zapis starego zamknąłby podpowiedzi nowego.
    for holder, nips in proven.items():
        if len(named_by[holder]) == 1:
            result.confirm[holder] = nips[0]
            continue
        for nip in nips:
            result.decisions[nip] = (holder, SEVERAL_NIPS)
            result.with_benefit.discard(nip)
    return result


async def backfill(
    db: AsyncSession, *, today: date, now: datetime, dry_run: bool = False
) -> dict[str, Any]:
    """Reguła na historii faktur: tylko ``candidates.nip`` osób bez NIP-u.

    Każda osoba we własnym SAVEPOINT; ``dry_run`` zwraca te same liczniki bez
    zapisu. Bez commita."""

    result = await plan(db, today)
    summary: dict[str, Any] = result.counts()
    if dry_run:
        return summary
    written: list[int] = []
    failed = 0
    for candidate_id, nip in sorted(result.confirm.items()):
        try:
            async with db.begin_nested():
                if await _write(db, candidate_id, nip, now):
                    written.append(candidate_id)
        except Exception:  # noqa: BLE001 — jedna osoba nie zatrzymuje reszty
            failed += 1
            logger.exception(
                "client_settlements: NIP z KSeF wstecz nieudany (kandydat %s)",
                candidate_id,
            )
    return {
        **summary,
        "written": len(written),
        "failed": failed,
        "candidate_ids": written,
    }


async def backfill_once(
    db: AsyncSession, *, now: Optional[datetime] = None
) -> Optional[dict[str, Any]]:
    """Przebieg wstecz raz po wdrożeniu, z pętli zakupów KSeF (commit tutaj).

    ``None`` = już był, trwa w innym procesie albo moduł rozliczeń jest wyłączony
    (ruszy po włączeniu). Znacznik trzyma liczniki, ``executed_at`` i ID osób
    z zapisanym NIP-em — do cofnięcia bez szukania po logach."""

    if await db.get(AppSetting, BACKFILL_KEY) is not None:
        return None
    if not await settlements_module.is_enabled(db):
        return None
    locked = await db.scalar(
        text("SELECT pg_try_advisory_xact_lock(hashtext(:key))"), {"key": BACKFILL_KEY}
    )
    taken = await db.scalar(
        select(AppSetting.key).where(AppSetting.key == BACKFILL_KEY)
    )
    if not locked or taken is not None:
        await db.rollback()
        return None
    await db.execute(text("SET LOCAL lock_timeout = '15s'"))
    moment = now or datetime.now(timezone.utc)
    summary = await backfill(db, today=business_date(moment), now=moment)
    db.add(
        AppSetting(
            key=BACKFILL_KEY, value={"executed_at": moment.isoformat(), **summary}
        )
    )
    await db.commit()
    counts = {k: v for k, v in summary.items() if k != "candidate_ids"}
    logger.info("client_settlements: NIP-y kontraktorów z KSeF wstecz %s", counts)
    return summary
