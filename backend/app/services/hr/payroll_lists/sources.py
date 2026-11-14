"""Skąd lista płac bierze kwoty brutto i stan roku (K7a).

Pozycje listy:

* **zespół** — zamrożone linie zamkniętego miesiąca Płac (``payroll_lines``,
  godziny × stawka + premie, tylko PLN), forma z linii: ``uop`` albo
  ``zlecenie`` (B2B nie trafia na listę — wystawia faktury),
* **zleceniobiorcy u klientów** — kontrakty ``uzlecenie`` trwające w miesiącu;
  kwota z przyjętego rozliczenia klienta (``client_settlements``, ``actual``,
  ``accepted``, ``amount_cost``),
* **kwota wpisana przez Płace** (``payroll_gross_inputs``) zastępuje oba źródła
  (UoP z pensją miesięczną, L4, niepełny miesiąc, dzieło, zlecenie bez
  rozliczenia); kwota 0 zdejmuje pozycję z listy w tym miesiącu.

Stan roku podatkowego osoby (rok daty wypłaty) = otwarcie z Enovy
(``payroll_year_openings``) + zatwierdzone listy tego roku z wypłatą nie
późniejszą niż ta lista. Wpłata pracodawcy PPK z poprzedniej zatwierdzonej
listy jest przychodem osoby na tej liście (miesiąc przekazania do instytucji).
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.candidate import Candidate
from app.models.client_settlement import ClientSettlement
from app.models.contract import Contract, ContractStatus, ContractType
from app.models.hr_payroll import PayrollLine, PayrollPeriod
from app.models.hr_payroll_lists import (
    PayrollGrossInput,
    PayrollList,
    PayrollListLine,
    PayrollYearOpening,
)
from app.models.user import User
from app.services.hr.payroll_lists.engine import ZERO, YearToDate
from app.services.hr.payroll_periods import month_end, month_start

#: Statusy kontraktu, przy których zlecenie mogło trwać w miesiącu.
MANDATE_STATUSES = (ContractStatus.active, ContractStatus.ending, ContractStatus.ended)
KIND_ORDER = {"uop": 0, "zlecenie": 1, "dzielo": 2}
OPENING_KEYS: tuple[str, ...] = (
    "pension_basis",
    "tax_base",
    "relief_revenue",
    "uop_revenue",
    "uop_kup",
    "uop_social",
    "uop_social_exempt",
    "uop_health",
    "uop_advance",
    "uop_exempt",
    "mandate_revenue",
    "mandate_kup",
    "mandate_social",
    "mandate_social_exempt",
    "mandate_health",
    "mandate_advance",
    "mandate_exempt",
    "flat_tax",
)


@dataclass
class Source:
    """Pozycja do policzenia (przed silnikiem)."""

    key: str
    person_key: str
    name: str
    kind: str
    source: str
    gross: Optional[Decimal]
    user_id: Optional[int] = None
    candidate_id: Optional[int] = None
    contract_id: Optional[int] = None
    basis: dict[str, Any] = field(default_factory=dict)
    problems: list[str] = field(default_factory=list)

    def fingerprint(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "kind": self.kind,
            "source": self.source,
            "gross": None if self.gross is None else str(self.gross),
            "basis": self.basis,
            "problems": sorted(self.problems),
        }


@dataclass
class Gathered:
    sources: list[Source]
    skipped: list[dict[str, Any]]
    problems: list[dict[str, Any]]


def _dec(value: Any) -> Optional[str]:
    return None if value is None else str(value)


async def _inputs(
    db: AsyncSession, period_id: int
) -> tuple[dict[tuple[int, str], PayrollGrossInput], dict[int, PayrollGrossInput]]:
    by_user: dict[tuple[int, str], PayrollGrossInput] = {}
    by_contract: dict[int, PayrollGrossInput] = {}
    for item in await db.scalars(
        select(PayrollGrossInput).where(PayrollGrossInput.period_id == period_id)
    ):
        if item.user_id is not None:
            by_user[(item.user_id, item.kind)] = item
        elif item.contract_id is not None:
            by_contract[item.contract_id] = item
    return by_user, by_contract


def _manual(source: Source, item: PayrollGrossInput) -> None:
    source.basis = {
        **source.basis,
        "replaced_source": source.source,
        "replaced_gross": _dec(source.gross),
        "note": item.note,
        "entered_by": item.entered_by,
    }
    source.source = "manual"
    source.gross = Decimal(item.gross)
    source.problems = [
        code
        for code in source.problems
        if code not in ("rate_missing", "gross_missing")
    ]


async def _team(
    db: AsyncSession,
    period: PayrollPeriod,
    inputs: dict[tuple[int, str], PayrollGrossInput],
    problems: list[dict[str, Any]],
) -> list[Source]:
    lines = list(
        await db.scalars(
            select(PayrollLine)
            .where(PayrollLine.period_id == period.id)
            .order_by(PayrollLine.user_id, PayrollLine.currency)
        )
    )
    by_user: dict[int, list[PayrollLine]] = defaultdict(list)
    for line in lines:
        by_user[line.user_id].append(line)
    out: list[Source] = []
    for user_id, rows in by_user.items():
        head = rows[0]
        kind = head.employment_type
        if kind == "b2b":
            continue
        if kind not in ("uop", "zlecenie"):
            problems.append(
                {
                    "code": "employment_type_missing",
                    "person": head.person_name,
                    "blocking": True,
                }
            )
            continue
        pln = next((row for row in rows if row.currency == "PLN"), None)
        other = [row for row in rows if row.currency != "PLN" and row.total > 0]
        source = Source(
            key=f"u{user_id}:{kind}",
            person_key=f"u{user_id}",
            name=head.person_name,
            kind=kind,
            source="payroll_line",
            gross=Decimal(pln.total) if pln else ZERO,
            user_id=user_id,
            basis={
                "payroll_line_id": pln.id if pln else None,
                "hours": _dec(head.hours),
                "overtime_hours": _dec(head.overtime_hours),
                "hourly_rate": _dec(pln.hourly_rate) if pln else None,
                "hours_amount": _dec(pln.hours_amount) if pln else None,
                "bonus_total": _dec(pln.bonus_total) if pln else None,
                "paid_leave_days": _dec(head.paid_leave_days),
                "other_leave_days": _dec(head.other_leave_days),
                "timesheet_status": head.timesheet_status,
            },
        )
        if other:
            source.problems.append("currency")
        if pln is not None and pln.hourly_rate is None and pln.hours > 0:
            source.problems.append("rate_missing")
        if (pln is None or pln.total <= 0) and not other:
            source.gross = ZERO
            if kind == "uop" and "rate_missing" not in source.problems:
                # Umowa o pracę bez kwoty to brak danych, nie miesiąc bez pracy.
                source.problems.append("gross_missing")
        item = inputs.pop((user_id, kind), None)
        if item is not None:
            _manual(source, item)
            source.problems = [code for code in source.problems if code != "currency"]
        if source.gross is not None and source.gross <= 0 and not source.problems:
            if item is not None:
                problems.append(
                    {"code": "skipped_zero", "person": source.name, "blocking": False}
                )
            continue
        out.append(source)
    # Kwoty Płac dla osób bez linii w tej formie (np. dzieło, UoP spoza raportu).
    extra_users = {user_id for (user_id, _kind) in inputs}
    names: dict[int, str] = {}
    if extra_users:
        names = {
            int(uid): str(name)
            for uid, name in (
                await db.execute(
                    select(User.id, User.name).where(User.id.in_(extra_users))
                )
            ).all()
        }
    for (user_id, kind), item in sorted(inputs.items()):
        if Decimal(item.gross) <= 0 or user_id not in names:
            continue
        source = Source(
            key=f"u{user_id}:{kind}",
            person_key=f"u{user_id}",
            name=names[user_id],
            kind=kind,
            source="manual",
            gross=Decimal(item.gross),
            user_id=user_id,
            basis={"note": item.note, "entered_by": item.entered_by},
        )
        out.append(source)
    return out


async def _mandates(
    db: AsyncSession,
    year: int,
    month: int,
    inputs: dict[int, PayrollGrossInput],
    problems: list[dict[str, Any]],
) -> list[Source]:
    first, last = month_start(year, month), month_end(year, month)
    rows = (
        await db.execute(
            select(Contract, Candidate.name, Candidate.lastname)
            .outerjoin(Candidate, Candidate.id == Contract.candidate_id)
            .where(
                Contract.contract_type == ContractType.uzlecenie,
                Contract.status.in_(MANDATE_STATUSES),
                Contract.start_date.is_not(None),
                Contract.start_date <= last,
                or_(Contract.end_date.is_(None), Contract.end_date >= first),
            )
            .order_by(Contract.id)
        )
    ).all()
    ids = [contract.id for contract, _name, _last in rows]
    settlements: dict[int, ClientSettlement] = {}
    if ids:
        for item in await db.scalars(
            select(ClientSettlement).where(
                and_(
                    ClientSettlement.contract_id.in_(ids),
                    ClientSettlement.period_month == f"{year}-{month:02d}",
                    ClientSettlement.kind == "actual",
                )
            )
        ):
            settlements[item.contract_id] = item
    out: list[Source] = []
    for contract, first, last in rows:
        name = " ".join(part for part in (first, last) if part)
        if contract.candidate_id is None:
            problems.append(
                {
                    "code": "contract_without_person",
                    "contract_id": contract.id,
                    "blocking": True,
                }
            )
            continue
        settlement = settlements.get(contract.id)
        currency = contract.rate_candidate_currency or contract.currency or "PLN"
        source = Source(
            key=f"k{contract.id}",
            person_key=f"c{contract.candidate_id}",
            name=str(name or f"Kontrakt {contract.id}"),
            kind="zlecenie",
            source="missing",
            gross=None,
            candidate_id=contract.candidate_id,
            contract_id=contract.id,
            basis={
                "contract_id": contract.id,
                "client_id": contract.client_id,
                "rate": _dec(contract.rate_candidate),
                "rate_unit": contract.rate_unit.value if contract.rate_unit else None,
                "currency": currency,
                "settlement_id": settlement.id if settlement else None,
                "settlement_status": settlement.status if settlement else None,
                "md_charged": _dec(settlement.md_charged) if settlement else None,
            },
        )
        if settlement is not None and settlement.status == "accepted":
            if settlement.amount_cost is not None:
                source.source = "client_settlement"
                source.gross = Decimal(settlement.amount_cost)
            else:
                source.problems.append("gross_missing")
        elif settlement is not None:
            source.problems.append("settlement_not_accepted")
        else:
            source.problems.append("gross_missing")
        if currency != "PLN":
            source.problems.append("currency")
        item = inputs.pop(contract.id, None)
        if item is not None:
            _manual(source, item)
            source.problems = [
                code
                for code in source.problems
                if code not in ("currency", "settlement_not_accepted")
            ]
            if source.gross is not None and source.gross <= 0:
                problems.append(
                    {"code": "skipped_zero", "person": source.name, "blocking": False}
                )
                continue
        out.append(source)
    return out


async def gather(db: AsyncSession, period: PayrollPeriod) -> Gathered:
    """Pozycje miesiąca w stałej kolejności: osoba (zespół, potem kontrakty), forma."""

    problems: list[dict[str, Any]] = []
    by_user, by_contract = await _inputs(db, period.id)
    team = await _team(db, period, by_user, problems)
    mandates = await _mandates(db, period.year, period.month, by_contract, problems)
    sources = sorted(
        [*team, *mandates],
        key=lambda s: (
            s.name.casefold(),
            s.person_key,
            KIND_ORDER.get(s.kind, 9),
            s.contract_id or 0,
        ),
    )
    return Gathered(sources=sources, skipped=[], problems=problems)


# ── Stan roku ────────────────────────────────────────────────────────────────


def person_key(line: PayrollListLine | PayrollYearOpening) -> str:
    return f"u{line.user_id}" if line.user_id is not None else f"c{line.candidate_id}"


def _amount(data: dict[str, Any], key: str) -> Decimal:
    try:
        return Decimal(str(data.get(key) or "0"))
    except ArithmeticError:
        return ZERO


async def openings(db: AsyncSession, year: int) -> dict[str, PayrollYearOpening]:
    return {
        person_key(item): item
        for item in await db.scalars(
            select(PayrollYearOpening).where(PayrollYearOpening.year == year)
        )
    }


async def approved_lines(
    db: AsyncSession,
    *,
    year: int,
    up_to: Optional[date] = None,
    exclude_list_id: Optional[int] = None,
) -> list[tuple[PayrollList, PayrollListLine]]:
    """Linie zatwierdzonych list z wypłatą w roku ``year`` (do ``up_to`` włącznie)."""

    query = (
        select(PayrollList, PayrollListLine)
        .join(PayrollListLine, PayrollListLine.list_id == PayrollList.id)
        .where(
            PayrollList.status == "approved",
            PayrollList.pay_date >= date(year, 1, 1),
            PayrollList.pay_date <= (up_to or date(year, 12, 31)),
        )
        .order_by(PayrollList.pay_date, PayrollList.id, PayrollListLine.id)
    )
    if exclude_list_id is not None:
        query = query.where(PayrollList.id != exclude_list_id)
    return [(row[0], row[1]) for row in (await db.execute(query)).all()]


async def year_to_date(
    db: AsyncSession, *, year: int, up_to: date, exclude_list_id: Optional[int]
) -> dict[str, YearToDate]:
    states: dict[str, YearToDate] = {}
    for key, opening in (await openings(db, year)).items():
        amounts = opening.amounts or {}
        states[key] = YearToDate(
            pension_basis=_amount(amounts, "pension_basis"),
            tax_base=_amount(amounts, "tax_base"),
            relief_revenue=_amount(amounts, "relief_revenue"),
        )
    for _list, line in await approved_lines(
        db, year=year, up_to=up_to, exclude_list_id=exclude_list_id
    ):
        result = line.result or {}
        key = person_key(line)
        state = states.get(key, YearToDate())
        tax_base = (
            _amount(result, "tax_base")
            if line.kind == "uop" and result.get("tax_kind") == "scale"
            else ZERO
        )
        states[key] = YearToDate(
            pension_basis=state.pension_basis + _amount(result, "pension_basis"),
            tax_base=state.tax_base + tax_base,
            relief_revenue=state.relief_revenue + _amount(result, "exempt_revenue"),
        )
    return states


async def previous_ppk_employer(
    db: AsyncSession, *, before: date, exclude_list_id: Optional[int]
) -> tuple[Optional[int], dict[str, Decimal]]:
    """Wpłaty pracodawcy PPK z ostatniej zatwierdzonej listy przed ``before``."""

    query = (
        select(PayrollList)
        .where(PayrollList.status == "approved", PayrollList.pay_date < before)
        .order_by(PayrollList.pay_date.desc(), PayrollList.id.desc())
        .limit(1)
    )
    if exclude_list_id is not None:
        query = query.where(PayrollList.id != exclude_list_id)
    previous = await db.scalar(query)
    if previous is None:
        return None, {}
    sums: dict[str, Decimal] = defaultdict(lambda: ZERO)
    for line in await db.scalars(
        select(PayrollListLine).where(PayrollListLine.list_id == previous.id)
    ):
        sums[person_key(line)] += _amount(line.result or {}, "ppk_employer")
    return previous.id, {key: value for key, value in sums.items() if value > 0}


async def later_approved(
    db: AsyncSession, *, year: int, after: date, exclude_list_id: Optional[int]
) -> Optional[PayrollList]:
    """Zatwierdzona lista z późniejszą wypłatą w tym samym roku (blokuje przeliczenie)."""

    query = (
        select(PayrollList)
        .where(
            PayrollList.status == "approved",
            PayrollList.pay_date > after,
            PayrollList.pay_date <= date(year, 12, 31),
        )
        .order_by(PayrollList.pay_date)
        .limit(1)
    )
    if exclude_list_id is not None:
        query = query.where(PayrollList.id != exclude_list_id)
    return await db.scalar(query)


__all__ = [
    "Gathered",
    "KIND_ORDER",
    "OPENING_KEYS",
    "Source",
    "approved_lines",
    "gather",
    "later_approved",
    "openings",
    "person_key",
    "previous_ppk_employer",
    "year_to_date",
]
