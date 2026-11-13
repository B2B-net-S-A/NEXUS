"""Raport godzin od klienta (Time for Teams) — plan Nordei N1 (``docs/rozliczenia-nordea-plan.md``).

* Kartoteka (N1.1): numer osoby u klienta i NIDS przy kontrakcie
  (``client_external_ids``). Pierwsze wypełnienie z opisów pozycji faktur do
  klienta w KSeF (``ID:M…``, ``NIDS:…``) przypiętych do linii zamówienia osoby;
  numer z faktury jest potwierdzony, bo fakturę przypięło już dopasowanie po
  osobie. Osoba z raportu bez numeru w kartotece dostaje podpowiedź po imieniu
  i nazwisku (do zatwierdzenia, jak NIP w E4.0); imiennicy podpowiedzi nie mają.
* Wersje raportu (N1.2): każdy wgrany arkusz to wersja z datą otrzymania,
  wiersze surowe zapisane per wersja; ten sam plik drugi raz nie tworzy wersji.
* Statusy (N1.3, ``time_report_engine``) liczone przy odczycie z wierszy wersji
  i faktur kontraktorów z KSeF (E4). Godziny z faktury = netto ÷ stawka
  kosztowa z kontraktu (N1.4, decyzja Artura z 13.11: bez pobierania XML-a).

Widok włącza reguła klienta ``report.time_for_teams`` (dane, nie nazwa klienta).
"""

from __future__ import annotations

import hashlib
import io
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Iterable, Optional

from sqlalchemy import func, insert, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.candidate import Candidate
from app.models.client import Client
from app.models.client_order import ClientOrder
from app.models.client_sales_invoice import ClientSalesInvoice, ClientSalesInvoiceLink
from app.models.client_settlement import (
    ClientContractorInvoice,
    ClientSettlementRuleSet,
)
from app.models.client_time_report import (
    ClientExternalId,
    ClientTimeReport,
    ClientTimeReportRow,
)
from app.models.contract import Contract, ContractStatus, RateUnit
from app.models.user import User
from app.services.client_order_lines import month_bounds
from app.services.client_settlements import contractor_invoices, rules_catalog, t4t
from app.services.client_settlements import time_report_engine as engine
from app.services.client_settlements.rcp_checks import name_tokens
from app.services.client_settlements.service import SettlementError

RULE_KEY = "report.time_for_teams"
PERSON_NO, PROJECT_NO = "client_person_no", "project_no"
CONFIRMED, SUGGESTED, REJECTED = "confirmed", "suggested", "rejected"
KSEF_ITEM, REPORT_NAME, MANUAL = "ksef_item", "report_name", "manual"
INSERT_CHUNK = 1_000
HOURS_Q = Decimal("0.01")
#: Kontrakt zakończony dawno nie dostaje podpowiedzi z raportu.
ENDED_GRACE = timedelta(days=92)

_PERSON_NO_RE = re.compile(r"\bID:\s*([A-Z][A-Z0-9]{3,15})\b", re.IGNORECASE)
_PROJECT_NO_RE = re.compile(r"\bNIDS:\s*(\d{4}-\d{6})\b")
_VALUE_RE = {
    PERSON_NO: re.compile(r"^[A-Z][A-Z0-9]{3,15}$"),
    PROJECT_NO: re.compile(r"^\d{4}-\d{6}$"),
}
_FULL_NAME = func.nullif(func.concat_ws(" ", Candidate.name, Candidate.lastname), "")


def _dec(value: Optional[Decimal]) -> Optional[str]:
    return None if value is None else f"{Decimal(value):.2f}"


def _iso(day: Optional[date]) -> Optional[str]:
    return day.isoformat() if day else None


def _month_of(year: Optional[int], month: Optional[int], fallback: date) -> str:
    if year and month:
        return f"{year}-{month:02d}"
    return f"{fallback:%Y-%m}"


def person_numbers(text: str) -> set[str]:
    return {m.upper() for m in _PERSON_NO_RE.findall(text or "")}


def project_numbers(text: str) -> set[str]:
    return set(_PROJECT_NO_RE.findall(text or ""))


# ── Włączenie widoku ─────────────────────────────────────────────────────────


async def enabled_clients(db: AsyncSession, month: str) -> list[int]:
    """Klienci z regułą ``report.time_for_teams`` na miesiąc albo z wgranym raportem."""

    latest: dict[int, tuple[str, dict[str, Any]]] = {}
    for client_id, effective_from, rules in (
        await db.execute(
            select(
                ClientSettlementRuleSet.client_id,
                ClientSettlementRuleSet.effective_from,
                ClientSettlementRuleSet.rules,
            ).where(ClientSettlementRuleSet.effective_from <= month)
        )
    ).all():
        if client_id not in latest or effective_from > latest[client_id][0]:
            latest[client_id] = (effective_from, rules)
    on = {
        cid
        for cid, (_, rules) in latest.items()
        if rules_catalog.effective(rules)[RULE_KEY]["level"] != "off"
    }
    with_reports = set(
        (await db.scalars(select(ClientTimeReport.client_id).distinct())).all()
    )
    return sorted(on | with_reports)


async def _client(db: AsyncSession, client_id: int) -> Client:
    client = await db.get(Client, client_id)
    if client is None:
        raise SettlementError("Nie ma takiego klienta.", status=404)
    return client


# ── Kartoteka (N1.1) ─────────────────────────────────────────────────────────


@dataclass
class _Span:
    first: date
    last: date

    def widen(self, first: date, last: date) -> None:
        self.first, self.last = min(self.first, first), max(self.last, last)


async def _ids(db: AsyncSession, client_id: int) -> list[ClientExternalId]:
    return list(
        (
            await db.scalars(
                select(ClientExternalId)
                .where(ClientExternalId.client_id == client_id)
                .order_by(ClientExternalId.id)
            )
        ).all()
    )


async def fill_from_ksef(
    db: AsyncSession, client_id: int, *, now: datetime
) -> dict[str, int]:
    """Numery osób i NIDS z opisów pozycji faktur do klienta w KSeF."""

    await _client(db, client_id)
    rows = await db.execute(
        select(
            ClientSalesInvoice.id,
            ClientSalesInvoice.items,
            ClientSalesInvoice.issue_date,
            ClientSalesInvoiceLink.period_year,
            ClientSalesInvoiceLink.period_month,
            ClientOrder.contract_id,
        )
        .join(
            ClientSalesInvoiceLink,
            ClientSalesInvoiceLink.invoice_id == ClientSalesInvoice.id,
        )
        .join(ClientOrder, ClientOrder.id == ClientSalesInvoiceLink.order_id)
        .where(ClientSalesInvoice.client_id == client_id)
    )
    by_invoice: dict[int, dict[str, Any]] = {}
    for invoice_id, items, issue_date, year, month, contract_id in rows.all():
        entry = by_invoice.setdefault(
            invoice_id, {"items": items or [], "contracts": set(), "months": set()}
        )
        entry["contracts"].add(int(contract_id))
        entry["months"].add(_month_of(year, month, issue_date))
    found: dict[tuple[int, str, str], _Span] = {}
    skipped = 0
    contracts = await _contracts(db, client_id)
    for entry in by_invoice.values():
        names = " ".join(
            str(item.get("name") or "")
            for item in entry["items"]
            if isinstance(item, dict)
        )
        people = person_numbers(names)
        if len(entry["contracts"]) != 1 or len(people) > 1:
            skipped += 1
            continue
        contract_id = next(iter(entry["contracts"]))
        # Faktura przypięta do linii zamówienia innej osoby (kopia z 13.11: jedna
        # linia z czterema numerami) nie może dać numeru: opis pozycji musi
        # wymieniać osobę z kontraktu.
        person = contracts.get(contract_id)
        if (
            person is None
            or len(person.tokens) < 2
            or not person.tokens <= _tokens(names)
        ):
            skipped += 1
            continue
        bounds = [month_bounds(m) for m in entry["months"]]
        first, last = min(b[0] for b in bounds), max(b[1] for b in bounds)
        values = [(PERSON_NO, v) for v in people] + [
            (PROJECT_NO, v) for v in project_numbers(names)
        ]
        for kind, value in values:
            key = (contract_id, kind, value)
            if key in found:
                found[key].widen(first, last)
            else:
                found[key] = _Span(first, last)
    existing = {(e.contract_id, e.kind, e.value): e for e in await _ids(db, client_id)}
    added = updated = 0
    for (contract_id, kind, value), span in found.items():
        row = existing.get((contract_id, kind, value))
        if row is None:
            db.add(
                ClientExternalId(
                    client_id=client_id,
                    contract_id=contract_id,
                    kind=kind,
                    value=value,
                    valid_from=span.first,
                    valid_to=span.last,
                    source=KSEF_ITEM,
                    state=CONFIRMED,
                    confirmed_at=now,
                )
            )
            added += 1
            continue
        if row.state == REJECTED:
            continue
        changed = False
        if row.state == SUGGESTED:
            row.state, row.source, row.confirmed_at = CONFIRMED, KSEF_ITEM, now
            changed = True
        if row.source == KSEF_ITEM:
            first = min(filter(None, (row.valid_from, span.first)))
            last = max(filter(None, (row.valid_to, span.last)))
            if (first, last) != (row.valid_from, row.valid_to):
                row.valid_from, row.valid_to = first, last
                changed = True
        updated += changed
    await db.flush()
    suggested = await _suggest_for_reports(db, client_id)
    return {
        "invoices": len(by_invoice),
        "added": added,
        "updated": updated,
        "skipped": skipped,
        "suggested": suggested,
    }


async def _suggest_for_reports(db: AsyncSession, client_id: int) -> int:
    """Podpowiedzi dla osób z najnowszej wersji raportu każdego miesiąca."""

    latest: dict[str, int] = {}
    for report in (
        await db.scalars(
            select(ClientTimeReport)
            .where(ClientTimeReport.client_id == client_id)
            .order_by(ClientTimeReport.received_on, ClientTimeReport.version_no)
        )
    ).all():
        latest[report.period_month] = report.id
    added = 0
    for month, report_id in sorted(latest.items()):
        people = {
            number: name
            for number, name in (
                await db.execute(
                    select(
                        ClientTimeReportRow.person_no, ClientTimeReportRow.person_name
                    )
                    .where(ClientTimeReportRow.report_id == report_id)
                    .distinct()
                )
            ).all()
        }
        added += await suggest_from_report(db, client_id, month, people)
    return added


@dataclass(frozen=True)
class _Contract:
    contract: Contract
    name: str
    tokens: frozenset[str]


async def _contracts(db: AsyncSession, client_id: int) -> dict[int, _Contract]:
    rows = await db.execute(
        select(Contract, _FULL_NAME)
        .outerjoin(Candidate, Candidate.id == Contract.candidate_id)
        .options(selectinload(Contract.candidate_rate_schedule))
        .where(
            Contract.client_id == client_id,
            Contract.status.in_(
                (ContractStatus.active, ContractStatus.ending, ContractStatus.ended)
            ),
        )
    )
    return {
        contract.id: _Contract(
            contract,
            name or f"Kontrakt {contract.id}",
            _tokens(name),
        )
        for contract, name in rows.all()
    }


def _overlaps(contract: Contract, first: date, last: date) -> bool:
    return (contract.start_date is None or contract.start_date <= last) and (
        contract.end_date is None or contract.end_date >= first
    )


def _pick_contract(
    ids: Iterable[int], contracts: dict[int, _Contract], month: str
) -> Optional[int]:
    """Kontrakt osoby w miesiącu: trwający w nim, potem najpóźniej zaczęty."""

    first, last = month_bounds(month)
    known = [contracts[i] for i in ids if i in contracts]
    if not known:
        return None
    within = [c for c in known if _overlaps(c.contract, first, last)] or known
    best = max(within, key=lambda c: (c.contract.start_date or date.min, c.contract.id))
    return best.contract.id


def _tokens(text: Optional[str]) -> frozenset[str]:
    """Imię i nazwisko bez znaków diakrytycznych; „ł” NFKD nie rozkłada."""

    folded = (text or "").replace("ł", "l").replace("Ł", "L")
    return frozenset(name_tokens(folded))


def _same_person(
    report_tokens: frozenset[str], contract_tokens: frozenset[str]
) -> bool:
    """Imię i nazwisko z raportu ↔ z kontraktu; drugie imię po jednej stronie nie przeszkadza."""

    if len(report_tokens) < 2 or len(contract_tokens) < 2:
        return False
    return contract_tokens <= report_tokens or report_tokens <= contract_tokens


async def suggest_from_report(
    db: AsyncSession, client_id: int, month: str, people: dict[str, Optional[str]]
) -> int:
    """Podpowiedzi numeru osoby po imieniu i nazwisku dla osób z raportu bez kartoteki."""

    ids = await _ids(db, client_id)
    known_numbers = {
        e.value
        for e in ids
        if e.kind == PERSON_NO and e.state in (CONFIRMED, SUGGESTED)
    }
    rejected = {(e.value, e.contract_id) for e in ids if e.state == REJECTED}
    taken = {
        e.contract_id
        for e in ids
        if e.kind == PERSON_NO and e.state in (CONFIRMED, SUGGESTED)
    }
    first, last = month_bounds(month)
    contracts = [
        c
        for c in (await _contracts(db, client_id)).values()
        if c.contract.id not in taken
        and (c.contract.end_date is None or c.contract.end_date >= first - ENDED_GRACE)
        and (c.contract.start_date is None or c.contract.start_date <= last)
    ]
    added = 0
    for number, name in sorted(people.items()):
        if number in known_numbers:
            continue
        tokens = _tokens(name)
        matches = [
            c
            for c in contracts
            if _same_person(tokens, c.tokens)
            and (number, c.contract.id) not in rejected
        ]
        if len({c.tokens for c in matches}) != 1:
            continue  # brak albo imiennicy — rozstrzyga człowiek
        chosen = _pick_contract(
            [c.contract.id for c in matches], {c.contract.id: c for c in matches}, month
        )
        if chosen is None:
            continue
        db.add(
            ClientExternalId(
                client_id=client_id,
                contract_id=chosen,
                kind=PERSON_NO,
                value=number,
                valid_from=first,
                source=REPORT_NAME,
                state=SUGGESTED,
            )
        )
        known_numbers.add(number)
        taken.add(chosen)
        contracts = [c for c in contracts if c.contract.id != chosen]
        added += 1
    await db.flush()
    return added


async def decide_id(
    db: AsyncSession, id_id: int, *, approve: bool, actor: User, now: datetime
) -> ClientExternalId:
    row = await db.get(ClientExternalId, id_id)
    if row is None:
        raise SettlementError("Nie ma takiej pozycji kartoteki.", status=404)
    if row.state != SUGGESTED:
        raise SettlementError("Ta pozycja kartoteki jest już rozstrzygnięta.")
    row.state = CONFIRMED if approve else REJECTED
    row.confirmed_by, row.confirmed_at = actor.id, now
    await db.flush()
    return row


async def add_manual_id(
    db: AsyncSession,
    client_id: int,
    *,
    contract_id: int,
    kind: str,
    value: str,
    actor: User,
    now: datetime,
) -> ClientExternalId:
    value = (value or "").strip().upper()
    pattern = _VALUE_RE.get(kind)
    if pattern is None:
        raise SettlementError("Nieznany rodzaj identyfikatora.", status=422)
    if not pattern.match(value):
        hint = "np. M012345" if kind == PERSON_NO else "np. 2024-001690"
        raise SettlementError(f"Niepoprawny numer ({hint}).", status=422)
    contract = await db.get(Contract, contract_id)
    if contract is None or contract.client_id != client_id:
        raise SettlementError("Ten kontrakt nie należy do klienta.", status=422)
    row = await db.scalar(
        select(ClientExternalId).where(
            ClientExternalId.client_id == client_id,
            ClientExternalId.contract_id == contract_id,
            ClientExternalId.kind == kind,
            ClientExternalId.value == value,
        )
    )
    if row is None:
        row = ClientExternalId(
            client_id=client_id,
            contract_id=contract_id,
            kind=kind,
            value=value,
            source=MANUAL,
        )
        db.add(row)
    row.state, row.confirmed_by, row.confirmed_at = CONFIRMED, actor.id, now
    if kind == PERSON_NO:
        # Ten sam numer podpowiedziany innym osobom przestaje czekać.
        for other in await _ids(db, client_id):
            if (
                other.kind == PERSON_NO
                and other.value == value
                and other.state == SUGGESTED
                and other.contract_id != contract_id
            ):
                other.state, other.confirmed_by, other.confirmed_at = (
                    REJECTED,
                    actor.id,
                    now,
                )
    await db.flush()
    return row


# ── Wersje raportu (N1.2) ────────────────────────────────────────────────────


async def _reports(
    db: AsyncSession, client_id: int, month: str
) -> list[ClientTimeReport]:
    return list(
        (
            await db.scalars(
                select(ClientTimeReport)
                .where(
                    ClientTimeReport.client_id == client_id,
                    ClientTimeReport.period_month == month,
                )
                .order_by(
                    ClientTimeReport.received_on,
                    ClientTimeReport.version_no,
                )
            )
        ).all()
    )


def _version(report: ClientTimeReport) -> dict[str, Any]:
    return {
        "id": report.id,
        "version_no": report.version_no,
        "received_on": report.received_on.isoformat(),
        "file_name": report.file_name,
        "sheet_name": report.sheet_name,
        "rows_count": report.rows_count,
        "people_count": report.people_count,
        "hours_approved": _dec(report.hours_approved),
        "hours_submitted": _dec(report.hours_submitted),
    }


async def upload(
    db: AsyncSession,
    client_id: int,
    month: str,
    *,
    received_on: date,
    file_name: Optional[str],
    content: bytes,
    sheet: Optional[str],
    actor: User,
) -> dict[str, Any]:
    """Wersja raportu z pliku. Kilka arkuszy raportu bez wyboru = lista arkuszy."""

    await _client(db, client_id)
    try:
        sheets = t4t.read(content)
    except t4t.T4tError as exc:
        raise SettlementError(str(exc), status=422) from exc
    if len(sheets) > 1 and not sheet:
        return {
            "needs_sheet": True,
            "sheets": [
                {
                    "name": s.name,
                    "rows": len(s.rows),
                    "people": len({r.person_no for r in s.rows}),
                    "month": s.month,
                }
                for s in sheets
            ],
        }
    try:
        chosen = t4t.pick(sheets, sheet)
    except t4t.T4tError as exc:
        raise SettlementError(str(exc), status=422) from exc
    if not chosen.rows:
        raise SettlementError(
            f"Arkusz „{chosen.name}” nie ma wierszy raportu.", status=422
        )
    if chosen.month != month:
        raise SettlementError(
            f"Raport jest za {chosen.month}, a wybrany miesiąc to {month}.", status=422
        )
    digest = hashlib.sha256(content)
    if len(sheets) > 1:
        digest.update(b"\x00" + chosen.name.encode())
    sha = digest.hexdigest()
    existing = await db.scalar(
        select(ClientTimeReport).where(
            ClientTimeReport.client_id == client_id, ClientTimeReport.sha256 == sha
        )
    )
    if existing is not None:
        return {"duplicate": True, "version": _version(existing)}
    version_no = (
        await db.scalar(
            select(func.max(ClientTimeReport.version_no)).where(
                ClientTimeReport.client_id == client_id,
                ClientTimeReport.period_month == month,
            )
        )
        or 0
    ) + 1
    report = ClientTimeReport(
        client_id=client_id,
        period_month=month,
        version_no=version_no,
        received_on=received_on,
        file_name=(file_name or "")[:255] or None,
        sheet_name=chosen.name[:64] if len(sheets) > 1 else None,
        sha256=sha,
        rows_count=len(chosen.rows),
        people_count=len({r.person_no for r in chosen.rows}),
        hours_approved=sum(
            (r.hours for r in chosen.rows if r.status == engine.APPROVED), Decimal("0")
        ),
        hours_submitted=sum(
            (r.hours for r in chosen.rows if r.status == engine.SUBMITTED), Decimal("0")
        ),
        uploaded_by=actor.id,
    )
    db.add(report)
    await db.flush()
    values = [
        {
            "report_id": report.id,
            "person_no": r.person_no,
            "person_name": r.person_name,
            "project_no": r.project_no,
            "project_name": r.project_name,
            "period_start": r.period_start,
            "period_end": r.period_end,
            "work_date": r.work_date,
            "hours": r.hours,
            "status": r.status,
            "charge_code": r.charge_code,
            "company": r.company,
        }
        for r in chosen.rows
    ]
    for start in range(0, len(values), INSERT_CHUNK):
        await db.execute(
            insert(ClientTimeReportRow), values[start : start + INSERT_CHUNK]
        )
    people = {r.person_no: r.person_name for r in chosen.rows}
    suggested = await suggest_from_report(db, client_id, month, people)
    return {
        "duplicate": False,
        "version": _version(report),
        "skipped_rows": chosen.skipped,
        "suggested": suggested,
    }


# ── Statusy miesiąca (N1.3–N1.5) ─────────────────────────────────────────────


@dataclass(frozen=True)
class _Row:
    report_id: int
    person_no: str
    person_name: Optional[str]
    project_no: Optional[str]
    project_name: Optional[str]
    entry: engine.Entry


async def _rows(db: AsyncSession, report_ids: list[int]) -> list[_Row]:
    if not report_ids:
        return []
    result = await db.execute(
        select(
            ClientTimeReportRow.report_id,
            ClientTimeReportRow.person_no,
            ClientTimeReportRow.person_name,
            ClientTimeReportRow.project_no,
            ClientTimeReportRow.project_name,
            ClientTimeReportRow.period_start,
            ClientTimeReportRow.period_end,
            ClientTimeReportRow.hours,
            ClientTimeReportRow.status,
        ).where(ClientTimeReportRow.report_id.in_(report_ids))
    )
    return [
        _Row(
            rid,
            pno,
            pname,
            project,
            project_name,
            engine.Entry(project, start, end, Decimal(hours), int(status)),
        )
        for rid, pno, pname, project, project_name, start, end, hours, status in result.all()
    ]


@dataclass(frozen=True)
class InvoiceHours:
    hours: Optional[Decimal]
    net: Optional[Decimal]
    rate: Optional[Decimal]
    note: Optional[str]
    invoices: tuple[ClientContractorInvoice, ...]


def invoice_hours(
    contract: Contract,
    invoices: list[ClientContractorInvoice],
    month: str,
    *,
    extras: Decimal = Decimal("0"),
    shared: Decimal = Decimal("0"),
) -> Optional[InvoiceHours]:
    """Godziny z faktury kontraktora: netto ÷ stawka kosztowa (N1.4).

    ``extras`` — zatwierdzone dodatki do rozliczenia (polecenie, weryfikacja,
    szkolenie; odpowiedź rozliczeń R1 z 13.11, mechanizm w osobnym PR-ze), które
    kontraktor dolicza do faktury. ``shared`` — część faktury za pracę u innego
    klienta, gdy jedna faktura obejmuje oba kontrakty osoby (przypadek c).
    """

    if not invoices:
        return None
    bound = [i for i in invoices if i.nip_state in contractor_invoices.BOUND]
    if not bound:
        return InvoiceHours(
            None,
            None,
            None,
            "Faktura z KSeF czeka na zatwierdzenie NIP-u.",
            tuple(invoices),
        )
    nets = [i.net_amount for i in bound]
    if any(n is None for n in nets):
        return InvoiceHours(
            None, None, None, "Faktura bez kwoty netto w KSeF.", tuple(bound)
        )
    invoiced = sum((Decimal(n) for n in nets), Decimal("0"))
    net = invoiced - extras - shared
    notes = []
    if shared > 0:
        notes.append(
            "Faktura obejmuje też pracę u innego klienta: odjęta kwota jego rozliczenia."
        )
    if extras > 0:
        notes.append("Odjęte zatwierdzone dodatki do rozliczenia.")
    note = " ".join(notes) or None
    first, _ = month_bounds(month)
    raw_rate = contract.effective_candidate_rate(first)
    rate = Decimal(raw_rate) if raw_rate else None
    currencies = {i.currency for i in bound}
    if currencies != {contract.resolved_rate_candidate_currency}:
        return InvoiceHours(
            None, net, rate, "Waluta faktury inna niż stawki kontraktu.", tuple(bound)
        )
    if rate is None or rate <= 0:
        return InvoiceHours(
            None, net, None, "Kontrakt bez stawki kosztowej.", tuple(bound)
        )
    if contract.rate_unit == RateUnit.hourly:
        hours = net / rate
    elif contract.rate_unit == RateUnit.daily:
        hours = net / rate * engine.HOURS_PER_DAY
    else:
        return InvoiceHours(
            None,
            net,
            rate,
            "Stawka miesięczna: godzin z faktury nie da się policzyć.",
            tuple(bound),
        )
    return InvoiceHours(
        hours.quantize(HOURS_Q, rounding=ROUND_HALF_UP),
        invoiced,
        rate,
        note,
        tuple(bound),
    )


def _hours_to_amount(
    contract: Contract, hours: Decimal, month: str
) -> Optional[Decimal]:
    first, _ = month_bounds(month)
    raw = contract.effective_candidate_rate(first)
    if not raw:
        return None
    rate = Decimal(raw)
    if contract.rate_unit == RateUnit.hourly:
        amount = hours * rate
    elif contract.rate_unit == RateUnit.daily:
        amount = hours / engine.HOURS_PER_DAY * rate
    else:
        return None
    return amount.quantize(HOURS_Q, rounding=ROUND_HALF_UP)


async def _approved_by_contract(
    db: AsyncSession, contract_ids: list[int], months: list[str]
) -> dict[tuple[int, str], Decimal]:
    """Godziny w statusie 2 z najnowszej wersji raportu: (kontrakt, miesiąc) → h."""

    if not contract_ids or not months:
        return {}
    numbers: dict[tuple[int, str], list[int]] = defaultdict(list)
    for client_id, contract_id, value in (
        await db.execute(
            select(
                ClientExternalId.client_id,
                ClientExternalId.contract_id,
                ClientExternalId.value,
            ).where(
                ClientExternalId.contract_id.in_(contract_ids),
                ClientExternalId.kind == PERSON_NO,
                ClientExternalId.state == CONFIRMED,
            )
        )
    ).all():
        numbers[(client_id, value)].append(contract_id)
    if not numbers:
        return {}
    clients = {client_id for client_id, _ in numbers}
    latest: dict[tuple[int, str], int] = {}
    for report in (
        await db.scalars(
            select(ClientTimeReport)
            .where(
                ClientTimeReport.client_id.in_(clients),
                ClientTimeReport.period_month.in_(months),
            )
            .order_by(ClientTimeReport.received_on, ClientTimeReport.version_no)
        )
    ).all():
        latest[(report.client_id, report.period_month)] = report.id
    if not latest:
        return {}
    by_report = {rid: key for key, rid in latest.items()}
    out: dict[tuple[int, str], Decimal] = defaultdict(Decimal)
    for report_id, person_no, hours in (
        await db.execute(
            select(
                ClientTimeReportRow.report_id,
                ClientTimeReportRow.person_no,
                func.sum(ClientTimeReportRow.hours),
            )
            .where(
                ClientTimeReportRow.report_id.in_(list(by_report)),
                ClientTimeReportRow.status == engine.APPROVED,
            )
            .group_by(ClientTimeReportRow.report_id, ClientTimeReportRow.person_no)
        )
    ).all():
        client_id, month = by_report[report_id]
        for contract_id in numbers.get((client_id, person_no), []):
            out[(contract_id, month)] += Decimal(hours)
    return dict(out)


async def expected_amounts(
    db: AsyncSession, contract_ids: list[int], months: list[str]
) -> dict[tuple[int, str], Decimal]:
    """Oczekiwana kwota faktury kontraktora z raportu klienta: godziny w statusie
    2 × stawka kosztowa. Dopasowanie faktury do osoby (``contractor_invoices._place``)
    używa jej tam, gdzie nie ma rozliczenia z RCP."""

    approved = await _approved_by_contract(db, contract_ids, months)
    if not approved:
        return {}
    contracts = {
        c.id: c
        for c in (
            await db.scalars(
                select(Contract)
                .options(selectinload(Contract.candidate_rate_schedule))
                .where(Contract.id.in_({cid for cid, _ in approved}))
            )
        ).all()
    }
    out: dict[tuple[int, str], Decimal] = {}
    for (contract_id, month), hours in approved.items():
        contract = contracts.get(contract_id)
        amount = _hours_to_amount(contract, hours, month) if contract else None
        if amount is not None:
            out[(contract_id, month)] = amount
    return out


@dataclass
class _Month:
    client: Client
    month: str
    reports: list[ClientTimeReport]
    rows: list[_Row]
    periods: tuple[engine.Period, ...]
    contracts: dict[int, _Contract]
    person_contract: dict[str, int]
    mapping_state: dict[str, str]
    invoices: dict[int, InvoiceHours]
    numbers_by_contract: dict[int, list[str]]


async def _load(db: AsyncSession, client_id: int, month: str) -> _Month:
    client = await _client(db, client_id)
    reports = await _reports(db, client_id, month)
    rows = await _rows(db, [r.id for r in reports])
    first, last = month_bounds(month)
    periods = engine.month_periods((r.entry for r in rows), first, last)
    contracts = await _contracts(db, client_id)
    by_number: dict[str, list[int]] = defaultdict(list)
    states: dict[str, str] = {}
    numbers_by_contract: dict[int, list[str]] = defaultdict(list)
    for e in await _ids(db, client_id):
        if e.kind != PERSON_NO or e.state == REJECTED:
            continue
        if e.state == CONFIRMED:
            by_number[e.value].append(e.contract_id)
            states[e.value] = CONFIRMED
            numbers_by_contract[e.contract_id].append(e.value)
        else:
            states.setdefault(e.value, SUGGESTED)
    person_contract = {
        number: chosen
        for number, ids in by_number.items()
        if (chosen := _pick_contract(ids, contracts, month)) is not None
    }
    found = await contractor_invoices.for_month(db, list(contracts), month)
    invoices = {
        cid: hours
        for cid, items in found.items()
        if cid in contracts
        and (hours := invoice_hours(contracts[cid].contract, items, month)) is not None
    }
    approved = await _approved_by_contract(db, list(contracts), [month])
    invoices.update(
        await _shared_invoices(db, client_id, month, contracts, found, approved)
    )
    return _Month(
        client,
        month,
        reports,
        rows,
        periods,
        contracts,
        person_contract,
        states,
        invoices,
        numbers_by_contract,
    )


async def _shared_invoices(
    db: AsyncSession,
    client_id: int,
    month: str,
    contracts: dict[int, _Contract],
    found: dict[int, list[ClientContractorInvoice]],
    approved: dict[tuple[int, str], Decimal],
) -> dict[int, InvoiceHours]:
    """Jedna faktura za pracę osoby u dwóch klientów (odpowiedź rozliczeń 13.11, c).

    Kontrakt osoby u innego klienta bez własnej faktury za miesiąc, z kwotą
    rozliczenia (RCP albo raport klienta): jego kwotę odejmujemy od faktury,
    jeśli dopiero wtedy godziny są równe zatwierdzonym w raporcie. Faktura
    przypięta do drugiego kontraktu działa tak samo w drugą stronę.
    """

    by_candidate: dict[int, list[int]] = defaultdict(list)
    for cid, c in contracts.items():
        if c.contract.candidate_id is not None:
            by_candidate[c.contract.candidate_id].append(cid)
    if not by_candidate:
        return {}
    siblings: dict[int, list[Contract]] = defaultdict(list)
    for sibling in (
        await db.scalars(
            select(Contract)
            .options(selectinload(Contract.candidate_rate_schedule))
            .where(
                Contract.candidate_id.in_(list(by_candidate)),
                Contract.client_id != client_id,
            )
        )
    ).all():
        siblings[sibling.candidate_id].append(sibling)
    if not siblings:
        return {}
    sibling_ids = [s.id for items in siblings.values() for s in items]
    amounts = await contractor_invoices.settlement_amounts(db, sibling_ids, [month])
    for key, value in (await expected_amounts(db, sibling_ids, [month])).items():
        amounts.setdefault(key, value)
    sibling_invoices = await contractor_invoices.for_month(db, sibling_ids, month)
    out: dict[int, InvoiceHours] = {}
    for candidate_id, own_ids in by_candidate.items():
        for cid in own_ids:
            target = approved.get((cid, month))
            if target is None:
                continue
            contract = contracts[cid].contract
            for sibling in siblings.get(candidate_id, []):
                share = amounts.get((sibling.id, month))
                if share is None:
                    continue
                if found.get(cid) and not sibling_invoices.get(sibling.id):
                    items = found[cid]
                elif not found.get(cid) and sibling_invoices.get(sibling.id):
                    items = sibling_invoices[sibling.id]
                else:
                    continue
                hours = invoice_hours(contract, items, month, shared=share)
                if (
                    hours is not None
                    and hours.hours is not None
                    and abs(hours.hours - target) <= engine.TOLERANCE
                ):
                    out[cid] = hours
                    break
    return out


def _classify(
    data: _Month, rows: list[_Row], contract_id: Optional[int]
) -> Optional[engine.Outcome]:
    _, last = month_bounds(data.month)
    invoice = data.invoices.get(contract_id) if contract_id is not None else None
    return engine.classify(
        [r.entry for r in rows],
        invoice.hours if invoice else None,
        data.periods,
        last,
        invoice_note=invoice.note if invoice else None,
    )


def _statuses(
    data: _Month, report_id: int
) -> dict[str, tuple[Optional[int], engine.Outcome, list[_Row]]]:
    """Klucz osoby → (kontrakt, wynik, wiersze) dla jednej wersji raportu."""

    per_person: dict[str, list[_Row]] = defaultdict(list)
    for row in data.rows:
        if row.report_id == report_id:
            per_person[row.person_no].append(row)
    out: dict[str, tuple[Optional[int], engine.Outcome, list[_Row]]] = {}
    in_report_contracts: set[int] = set()
    for number, rows in per_person.items():
        contract_id = data.person_contract.get(number)
        if contract_id is not None:
            in_report_contracts.add(contract_id)
        outcome = _classify(data, rows, contract_id)
        if outcome is not None:
            out[number] = (contract_id, outcome, rows)
    for contract_id in data.invoices:
        if contract_id in in_report_contracts:
            continue
        outcome = _classify(data, [], contract_id)
        if outcome is not None:
            out[f"c{contract_id}"] = (contract_id, outcome, [])
    return out


UNMATCHED = "unmatched"
_CONTRACT_KEY = re.compile(r"^c(\d+)$")


def _is_contract_key(key: str) -> bool:
    """Klucz wiersza bez numeru osoby (faktura bez raportu): ``c<kontrakt>``."""

    return _CONTRACT_KEY.match(key) is not None


def _status_of(key: str, contract_id: Optional[int], outcome: engine.Outcome) -> str:
    if contract_id is None and not _is_contract_key(key):
        return UNMATCHED
    return outcome.status


def _weeks(
    weeks: tuple[engine.Week, ...], periods: tuple[engine.Period, ...]
) -> list[list[str]]:
    by_start = {w.start: w for w in weeks}
    return [
        [
            _dec(by_start[p.start].approved) if p.start in by_start else "0.00",
            _dec(by_start[p.start].submitted) if p.start in by_start else "0.00",
        ]
        for p in periods
    ]


def _select(
    data: _Month, version_id: Optional[int]
) -> tuple[Optional[ClientTimeReport], Optional[ClientTimeReport]]:
    if not data.reports:
        return None, None
    index = len(data.reports) - 1
    if version_id is not None:
        found = [i for i, r in enumerate(data.reports) if r.id == version_id]
        if not found:
            raise SettlementError(
                "Nie ma takiej wersji raportu w tym miesiącu.", status=404
            )
        index = found[0]
    previous = data.reports[index - 1] if index > 0 else None
    return data.reports[index], previous


COUNT_KEYS = (*engine.STATUSES, UNMATCHED)


async def month_view(
    db: AsyncSession, client_id: int, month: str, *, version_id: Optional[int] = None
) -> dict[str, Any]:
    data = await _load(db, client_id, month)
    current, previous = _select(data, version_id)
    versions = []
    for report in data.reports:
        counts = {k: 0 for k in COUNT_KEYS}
        for key, (cid, outcome, _) in _statuses(data, report.id).items():
            counts[_status_of(key, cid, outcome)] += 1
        versions.append({**_version(report), "counts": counts})
    rows: list[dict[str, Any]] = []
    counts = {k: 0 for k in COUNT_KEYS}
    changed = 0
    if current is not None:
        now = _statuses(data, current.id)
        before = _statuses(data, previous.id) if previous is not None else {}
        for key, (cid, outcome, person_rows) in now.items():
            status = _status_of(key, cid, outcome)
            prev = before.get(key)
            prev_status = _status_of(key, prev[0], prev[1]) if prev else None
            is_changed = previous is not None and prev_status != status
            changed += is_changed
            counts[status] += 1
            contract = data.contracts.get(cid) if cid is not None else None
            report_name = next(
                (r.person_name for r in person_rows if r.person_name), None
            )
            rows.append(
                {
                    "key": key,
                    "person_no": None if _is_contract_key(key) else key,
                    "name": contract.name if contract else (report_name or key),
                    "report_name": report_name,
                    "contract_id": cid,
                    "contract_status": contract.contract.status.value
                    if contract
                    else None,
                    "mapping": CONFIRMED
                    if _is_contract_key(key)
                    else data.mapping_state.get(key),
                    "projects": sorted(
                        {r.project_no for r in person_rows if r.project_no}
                    ),
                    "status": status,
                    "previous_status": prev_status,
                    "changed": is_changed,
                    "approved": _dec(outcome.approved),
                    "submitted": _dec(outcome.submitted),
                    "invoice_hours": _dec(outcome.invoice),
                    "difference": _dec(outcome.difference),
                    "notes": list(outcome.notes),
                    "weeks": _weeks(outcome.weeks, data.periods),
                }
            )
    rows.sort(key=lambda r: (r["name"] or "").lower())
    return {
        "client_id": data.client.id,
        "client_name": data.client.name,
        "month": month,
        "versions": versions,
        "version_id": current.id if current else None,
        "previous_version_id": previous.id if previous else None,
        "periods": [
            {"start": p.start.isoformat(), "end": p.end.isoformat()}
            for p in data.periods
        ],
        "counts": {**counts, "changed": changed, "all": len(rows)},
        "rows": rows,
    }


async def person_card(
    db: AsyncSession,
    client_id: int,
    month: str,
    key: str,
    *,
    version_id: Optional[int] = None,
    amounts: bool,
) -> dict[str, Any]:
    data = await _load(db, client_id, month)
    current, _ = _select(data, version_id)
    match = _CONTRACT_KEY.match(key)
    if match:
        contract_id: Optional[int] = int(match.group(1))
        number = None
    else:
        number = key.upper()
        contract_id = data.person_contract.get(number)
    history = []
    selected: Optional[dict[str, Any]] = None
    report_name: Optional[str] = None
    for report in data.reports:
        rows = [
            r
            for r in data.rows
            if r.report_id == report.id and number is not None and r.person_no == number
        ]
        report_name = report_name or next(
            (r.person_name for r in rows if r.person_name), None
        )
        outcome = _classify(data, rows, contract_id)
        projects = []
        names = {r.project_no: r.project_name for r in rows}
        if outcome is not None:
            for project in outcome.projects:
                projects.append(
                    {
                        "project_no": project.project_no,
                        "project_name": names.get(project.project_no),
                        "weeks": _weeks(project.weeks, data.periods),
                    }
                )
        entry = {
            **_version(report),
            "status": _status_of(key, contract_id, outcome) if outcome else None,
            "approved": _dec(outcome.approved) if outcome else None,
            "submitted": _dec(outcome.submitted) if outcome else None,
            "difference": _dec(outcome.difference) if outcome else None,
            "notes": list(outcome.notes) if outcome else [],
            "weeks": _weeks(outcome.weeks, data.periods) if outcome else [],
            "projects": projects,
        }
        history.append(entry)
        if current is not None and report.id == current.id:
            selected = entry
    if (
        contract_id is None
        and number is not None
        and not any(h["status"] for h in history)
    ):
        raise SettlementError("Tej osoby nie ma w raporcie za ten miesiąc.", status=404)
    contract = data.contracts.get(contract_id) if contract_id is not None else None
    if match and contract is None:
        raise SettlementError("Nie ma takiego kontraktu u klienta.", status=404)
    invoice = data.invoices.get(contract_id) if contract_id is not None else None
    ids = [
        {
            "id": e.id,
            "kind": e.kind,
            "value": e.value,
            "source": e.source,
            "state": e.state,
            "valid_from": _iso(e.valid_from),
            "valid_to": _iso(e.valid_to),
        }
        for e in await _ids(db, client_id)
        if (contract_id is not None and e.contract_id == contract_id)
        or (number is not None and e.kind == PERSON_NO and e.value == number)
    ]
    return {
        "client_id": client_id,
        "month": month,
        "key": key,
        "person_no": number,
        "name": contract.name if contract else (report_name or key),
        "report_name": report_name,
        "can_see_amounts": amounts,
        "contract": (
            {
                "id": contract.contract.id,
                "status": contract.contract.status.value,
                "start_date": _iso(contract.contract.start_date),
                "end_date": _iso(contract.contract.end_date),
            }
            if contract
            else None
        ),
        "periods": [
            {"start": p.start.isoformat(), "end": p.end.isoformat()}
            for p in data.periods
        ],
        "version_id": current.id if current else None,
        "selected": selected,
        "history": history,
        "invoice": (
            {
                "hours": _dec(invoice.hours),
                "source": "net_by_rate",
                "note": invoice.note,
                "net": _dec(invoice.net) if amounts else None,
                "rate": _dec(invoice.rate) if amounts else None,
                "invoices": [
                    {
                        "id": i.id,
                        "ksef_number": i.ksef_number,
                        "invoice_number": i.invoice_number,
                        "issue_date": _iso(i.issue_date),
                        "nip_state": i.nip_state,
                        "net_amount": _dec(i.net_amount) if amounts else None,
                    }
                    for i in invoice.invoices
                ],
            }
            if invoice
            else None
        ),
        "ids": ids,
    }


async def ids_view(db: AsyncSession, client_id: int, month: str) -> dict[str, Any]:
    """Ekran „Kartoteka”: podpowiedzi, osoby z raportu bez numeru, zakończone kontrakty."""

    data = await _load(db, client_id, month)
    ids = await _ids(db, client_id)
    latest = data.reports[-1] if data.reports else None
    people: dict[str, dict[str, Any]] = {}
    if latest is not None:
        for row in data.rows:
            if row.report_id != latest.id:
                continue
            p = people.setdefault(
                row.person_no,
                {"name": row.person_name, "hours": Decimal("0"), "projects": set()},
            )
            if row.entry.status in (engine.APPROVED, engine.SUBMITTED):
                p["hours"] += row.entry.hours
            if row.project_no:
                p["projects"].add(row.project_no)

    def contract_info(cid: int) -> dict[str, Any]:
        c = data.contracts.get(cid)
        return {
            "contract_id": cid,
            "name": c.name if c else f"Kontrakt {cid}",
            "contract_status": c.contract.status.value if c else None,
            "start_date": _iso(c.contract.start_date) if c else None,
            "end_date": _iso(c.contract.end_date) if c else None,
        }

    suggestions = [
        {
            "id": e.id,
            "value": e.value,
            "report_name": (people.get(e.value) or {}).get("name"),
            **contract_info(e.contract_id),
        }
        for e in ids
        if e.kind == PERSON_NO and e.state == SUGGESTED
    ]
    pending = {s["value"] for s in suggestions}
    unmatched = [
        {
            "person_no": number,
            "report_name": p["name"],
            "hours": _dec(p["hours"]),
            "projects": sorted(p["projects"]),
        }
        for number, p in sorted(people.items(), key=lambda kv: kv[1]["name"] or kv[0])
        if number not in data.person_contract and number not in pending
    ]
    first, _ = month_bounds(month)
    ended = [
        {"person_no": number, "hours": _dec(p["hours"]), **contract_info(cid)}
        for number, p in people.items()
        if (cid := data.person_contract.get(number)) is not None
        and data.contracts[cid].contract.end_date is not None
        and data.contracts[cid].contract.end_date < first
    ]
    with_number = {
        e.contract_id for e in ids if e.kind == PERSON_NO and e.state == CONFIRMED
    }
    _, last = month_bounds(month)
    without = [
        contract_info(cid)
        for cid, c in sorted(data.contracts.items(), key=lambda kv: kv[1].name.lower())
        if cid not in with_number and _overlaps(c.contract, first - ENDED_GRACE, last)
    ]
    confirmed = defaultdict(
        lambda: {"person_no": [], "project_no": [], "sources": set()}
    )
    for e in ids:
        if e.state != CONFIRMED:
            continue
        item = confirmed[e.contract_id]
        item["person_no" if e.kind == PERSON_NO else "project_no"].append(e.value)
        item["sources"].add(e.source)
    return {
        "client_id": client_id,
        "month": month,
        "version_id": latest.id if latest else None,
        "counts": {
            "confirmed": len(data.person_contract),
            "suggested": len(suggestions),
            "unmatched": len(unmatched),
            "ended": len(ended),
            "without_number": len(without),
        },
        "suggestions": suggestions,
        "unmatched": unmatched,
        "ended": ended,
        "without_number": without,
        "confirmed": [
            {
                **contract_info(cid),
                "person_no": sorted(item["person_no"]),
                "project_no": sorted(item["project_no"]),
                "sources": sorted(item["sources"]),
            }
            for cid, item in sorted(
                confirmed.items(),
                key=lambda kv: (
                    data.contracts[kv[0]].name.lower()
                    if kv[0] in data.contracts
                    else ""
                ),
            )
        ],
    }


NEXT_ROUND_HEADER = ("Imię i nazwisko", "Numer osoby", "NIDS", "Status w NEXUS-ie")
_STATUS_LABEL = {
    engine.OK: "Zgodne",
    engine.WAITING: "Czekamy",
    engine.NO_APPROVAL: "Brak akceptacji",
    engine.DIFFERS: "Rozbieżność",
    engine.OTHER_AMOUNT: "Inna kwota",
    engine.NO_INVOICE: "Brak faktury",
    engine.NOT_IN_REPORT: "Brak w raporcie",
    UNMATCHED: "Bez kartoteki",
}


async def next_round(
    db: AsyncSession, client_id: int, month: str, *, version_id: Optional[int] = None
) -> tuple[bytes, int]:
    """Lista osób do kolejnej tury raportu u klienta (odpowiedź rozliczeń R2):
    wszyscy bez zgodności i bez faktury, z numerem osoby z kartoteki."""

    import openpyxl

    view = await month_view(db, client_id, month, version_id=version_id)
    data_numbers: dict[int, list[str]] = defaultdict(list)
    for e in await _ids(db, client_id):
        if e.kind == PERSON_NO and e.state == CONFIRMED:
            data_numbers[e.contract_id].append(e.value)
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "Lista"
    sheet.append(NEXT_ROUND_HEADER)
    count = 0
    for row in view["rows"]:
        if row["status"] == engine.OK:
            continue
        number = row["person_no"] or ", ".join(
            sorted(data_numbers.get(row["contract_id"] or 0, []))
        )
        sheet.append(
            (
                row["name"],
                number,
                ", ".join(row["projects"]),
                _STATUS_LABEL.get(row["status"], row["status"]),
            )
        )
        count += 1
    for column, width in zip("ABCD", (34, 14, 28, 20)):
        sheet.column_dimensions[column].width = width
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue(), count
