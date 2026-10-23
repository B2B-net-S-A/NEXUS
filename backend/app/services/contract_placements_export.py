"""Eksport „Placementy” — kontrakty w układzie arkusza „Placementy”.

Delivery prowadził ręcznie arkusz placementów (kolumny niżej, w tej
kolejności): stawki i start brał z kontraktu, DL i rekrutera z rekrutacji,
datę akceptacji z panelu osoby, podpis z Generatora, premię z Płac. Ten
eksport składa to samo z danych NEXUSA, jeden wiersz na kontrakt ze startem
w wybranym okresie.

* DL i rekruter — ta sama reguła co premie z placementów
  (``placement_bonuses.load_context`` / ``PlacementContext.people``), żeby
  plik i Płace wskazywały te same osoby. Rekruter = pierwszy weryfikujący;
  gdy zweryfikował sam DL, kolumna pokazuje DL-a, a uwaga mówi, że premii
  rekrutera nie ma.
* Stawki i marża — z dnia startu, w zł/h jak premia (``contract_margin``):
  dzienna ÷ 8, miesięczna ÷ godziny rozliczeniowe. Marża mies. = marża/h ×
  168 h. Waluta obca: stawki w swojej walucie, marża po kursie NBP z dnia
  startu; brak kursu albo stawki = pusta komórka, nigdy zgadnięta liczba.
* Data akceptacji — z okna „Klient zaakceptował” (``client_accepted_on``);
  bez niej dzień pierwszego ruchu karty na „Akceptację”, z uwagą.
* Data podpisania — najwcześniejszy podpis umowy z Generatora powiązanej
  z kontraktem; umowy spoza Generatora daty nie mają (uwaga).
* Premia — premie automatu Płac do tego kontraktu (bez anulowanych), tylko te,
  które pobierający widzi w Płacach (``PayrollViewer.sees_person``: Płace,
  sama osoba, przełożony). Bramka trasy (stawki i marża) przepuszcza też
  „Moduł Finanse” bez Płac — premii innych osób ta osoba nie dostaje.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.scheduling import business_date
from app.core.work_time import HOURS_PER_MONTH
from app.models.b2b_generated_contract import B2BGeneratedContract
from app.models.contract import Contract, ContractStatus
from app.models.hr_payroll import HrBonus
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.models.user import User
from app.services.contract_rates import RATE_SCHEDULE_LOADS
from app.services.hr.placement_bonuses import (
    PlacementContext,
    contract_margin,
    load_context,
)

PLACEMENT_EXPORT_COLUMNS: tuple[str, ...] = (
    "Konsultant",
    "Klient",
    "DL",
    "Stanowisko",
    "Stawka kosztowa",
    "Stawka przychodowa",
    "Marża",
    "Marża mies.",
    "Data podpisania",
    "Start day",
    "Data akceptacji",
    "Rekruter",
    "Premia",
    "Uwagi",
)

#: Kolumny z datą — arkusz dostaje datę, nie napis (sortowanie i filtr w Excelu).
DATE_COLUMNS: frozenset[str] = frozenset(
    {"Data podpisania", "Start day", "Data akceptacji"}
)

#: Placement = kontrakt, który wystartował — jak premie z placementów.
PLACEMENT_STATUSES: tuple[ContractStatus, ...] = (
    ContractStatus.active,
    ContractStatus.ending,
    ContractStatus.ended,
)

#: Najdłuższy okres jednego eksportu (dni) — cała historia NEXUSA z zapasem.
MAX_RANGE_DAYS = 3660

TERMINATION_LABELS: dict[str, str] = {
    "project_ended": "koniec projektu",
    "poached_by_client": "przejście do klienta",
    "client_budget_cut": "cięcie budżetu klienta",
    "consultant_resigned": "konsultant zrezygnował",
    "better_offer": "lepsza oferta",
    "performance_issue": "problem jakościowy",
    "contract_breach": "naruszenie umowy",
    "personal_reasons": "powody osobiste",
    "mutual_agreement": "porozumienie stron",
    "other": "inny powód",
}

BONUS_ROLE_LABELS: dict[str, str] = {
    "recruiter": "rekruter",
    "dl": "DL",
    "dl_extra": "DL dodatkowo",
}
BONUS_ROLE_ORDER: tuple[str, ...] = ("recruiter", "dl", "dl_extra")


@dataclass(frozen=True)
class Acceptance:
    """Akceptacja klienta dla pary kandydat × rekrutacja."""

    on: date
    #: ``True`` = data z okna „Klient zaakceptował”, ``False`` = dzień ruchu karty.
    confirmed: bool


@dataclass(frozen=True)
class SignedContracts:
    """Umowy z Generatora powiązane z kontraktem."""

    count: int
    signed_on: Optional[date]


@dataclass(frozen=True)
class PlacementBonus:
    role: str
    recipient: str
    amount: Decimal
    proposed: bool


@dataclass(frozen=True)
class PlacementFacts:
    """Wszystko, czego wiersz potrzebuje poza samym kontraktem."""

    dl_name: str
    recruiter_name: str
    #: zweryfikował sam DL — premii rekrutera nie ma (reguła Płac)
    verified_by_dl: bool
    margin_per_hour: Optional[Decimal]
    cost_per_hour: Optional[Decimal]
    client_per_hour: Optional[Decimal]
    cost_currency: str
    client_currency: str
    acceptance: Optional[Acceptance]
    generated: SignedContracts
    bonuses: tuple[PlacementBonus, ...]
    #: najbliższe przyszłe kroki harmonogramów: (``"kosztowa"``/``"przychodowa"``, stawka, od)
    upcoming_rates: tuple[tuple[str, Decimal, date], ...]


def _money_text(value: Decimal) -> str:
    """``1500`` / ``772,80`` — bez zbędnych zer, przecinek jak w Excelu."""

    rounded = value.quantize(Decimal("0.01"))
    if rounded == rounded.to_integral_value():
        return str(int(rounded))
    return f"{rounded:.2f}".replace(".", ",")


def bonus_text(bonuses: Iterable[PlacementBonus]) -> str:
    """„rekruter Jan Bąk 1500 zł; DL Ewa Kowal 772,80 zł (propozycja)”."""

    order = {role: idx for idx, role in enumerate(BONUS_ROLE_ORDER)}
    parts = []
    for bonus in sorted(bonuses, key=lambda b: order.get(b.role, len(order))):
        label = BONUS_ROLE_LABELS.get(bonus.role, bonus.role)
        text = f"{label} {bonus.recipient} {_money_text(bonus.amount)} zł"
        if bonus.proposed:
            text += " (propozycja)"
        parts.append(text)
    return "; ".join(parts)


def placement_notes(contract: Contract, facts: PlacementFacts) -> str:
    """Uwagi, które arkusz miał tekstem, złożone z danych kontraktu."""

    notes: list[str] = []
    status = getattr(contract.status, "value", contract.status)
    if status in (ContractStatus.ended.value, ContractStatus.ending.value):
        end = contract.terminated_at or contract.end_date
        if end is not None:
            text = f"Koniec {end:%d.%m.%Y}"
            reason = getattr(
                contract.termination_reason, "value", contract.termination_reason
            )
            if reason:
                text += f" ({TERMINATION_LABELS.get(reason, reason)})"
            notes.append(text)
    if contract.returned_from_contract_id is not None:
        notes.append("Powrót po przerwie")
    if contract.job_id is None:
        notes.append("Kontrakt bez rekrutacji")
    elif facts.verified_by_dl:
        notes.append("Zweryfikował DL — bez premii rekrutera")
    if facts.acceptance is not None and not facts.acceptance.confirmed:
        notes.append("Data akceptacji z ruchu karty")
    if facts.generated.count == 0:
        notes.append("Umowa spoza Generatora")
    elif facts.generated.signed_on is None:
        notes.append("Umowa z Generatora bez podpisu")
    if facts.cost_currency != "PLN" or facts.client_currency != "PLN":
        notes.append(
            f"Stawki: kosztowa {facts.cost_currency}, przychodowa {facts.client_currency}"
        )
    if contract.start_date is not None and facts.margin_per_hour is None:
        notes.append("Brak stawki albo kursu — marża nieznana")
    for side, rate, since in facts.upcoming_rates:
        notes.append(f"Stawka {side} {_money_text(rate)} od {since:%d.%m.%Y}")
    return "; ".join(notes)


def _number(value: Optional[Decimal]) -> Any:
    return "" if value is None else float(value)


def visible_bonuses(
    rows: Iterable[tuple[str, int, Decimal, bool]],
    sees_bonus_of: Callable[[int], bool],
) -> list[tuple[str, int, Decimal, bool]]:
    """Premie, które pobierający widzi w Płacach — reszta nie trafia do pliku."""

    return [row for row in rows if sees_bonus_of(row[1])]


def placement_row(
    contract: Contract, facts: PlacementFacts, candidate: str, client: str
) -> list[Any]:
    """Jeden wiersz w kolejności ``PLACEMENT_EXPORT_COLUMNS``."""

    monthly = (
        None
        if facts.margin_per_hour is None
        else facts.margin_per_hour * HOURS_PER_MONTH
    )
    return [
        candidate,
        client,
        facts.dl_name,
        contract.job.title if contract.job else "",
        _number(facts.cost_per_hour),
        _number(facts.client_per_hour),
        _number(facts.margin_per_hour),
        _number(monthly),
        facts.generated.signed_on or "",
        contract.start_date or "",
        facts.acceptance.on if facts.acceptance else "",
        facts.recruiter_name,
        bonus_text(facts.bonuses),
        placement_notes(contract, facts),
    ]


def upcoming_rate_steps(
    contract: Contract, today: date
) -> tuple[tuple[str, Decimal, date], ...]:
    """Pierwszy przyszły krok każdego harmonogramu (np. podwyżka po 6 mies.)."""

    found: list[tuple[str, Decimal, date]] = []
    for side, schedule in (
        ("kosztowa", contract.candidate_rate_schedule),
        ("przychodowa", contract.client_rate_schedule),
    ):
        future = [step for step in schedule or () if step.effective_from > today]
        if future:
            step = min(future, key=lambda s: s.effective_from)
            found.append((side, Decimal(step.rate), step.effective_from))
    return tuple(found)


async def load_placement_contracts(
    db: AsyncSession, start_from: date, start_to: date
) -> list[Contract]:
    rows = await db.execute(
        select(Contract)
        .options(
            selectinload(Contract.job),
            *RATE_SCHEDULE_LOADS,
        )
        .where(
            Contract.start_date >= start_from,
            Contract.start_date <= start_to,
            Contract.status.in_(PLACEMENT_STATUSES),
        )
        .order_by(Contract.start_date, Contract.id)
    )
    return list(rows.scalars().all())


async def _acceptances(
    db: AsyncSession, pairs: set[tuple[int, int]]
) -> dict[tuple[int, int], Acceptance]:
    """Ostatnia akceptacja z datą, a bez niej dzień pierwszego wejścia na etap."""

    if not pairs:
        return {}
    rows = await db.execute(
        select(
            CandidateStage.candidate_id,
            CandidateStage.job_id,
            CandidateStage.client_accepted_on,
            CandidateStage.moved_at,
        ).where(
            CandidateStage.stage == PipelineStage.acceptance,
            CandidateStage.candidate_id.in_(sorted({c for c, _ in pairs})),
            CandidateStage.job_id.in_(sorted({j for _, j in pairs})),
        )
    )
    confirmed: dict[tuple[int, int], date] = {}
    moved: dict[tuple[int, int], date] = {}
    for candidate_id, job_id, accepted_on, moved_at in rows.all():
        pair = (candidate_id, job_id)
        if pair not in pairs:
            continue
        if accepted_on is not None and accepted_on > confirmed.get(pair, date.min):
            confirmed[pair] = accepted_on
        if moved_at is not None:
            day = business_date(moved_at)
            if day < moved.get(pair, date.max):
                moved[pair] = day
    found = {pair: Acceptance(day, True) for pair, day in confirmed.items()}
    for pair, day in moved.items():
        found.setdefault(pair, Acceptance(day, False))
    return found


async def _generated(
    db: AsyncSession, contract_ids: Sequence[int]
) -> dict[int, SignedContracts]:
    if not contract_ids:
        return {}
    rows = await db.execute(
        select(
            B2BGeneratedContract.contract_id,
            B2BGeneratedContract.signed_on,
            B2BGeneratedContract.signed_at,
        ).where(B2BGeneratedContract.contract_id.in_(contract_ids))
    )
    counts: dict[int, int] = {}
    earliest: dict[int, date] = {}
    for contract_id, signed_on, signed_at in rows.all():
        counts[contract_id] = counts.get(contract_id, 0) + 1
        # Dzień z okna „Oznacz jako podpisaną” (0514); wiersz oznaczony
        # wcześniej ma tylko chwilę oznaczenia — wtedy jej dzień.
        day = signed_on or (business_date(signed_at) if signed_at else None)
        if day is not None and day < earliest.get(contract_id, date.max):
            earliest[contract_id] = day
    return {
        contract_id: SignedContracts(count, earliest.get(contract_id))
        for contract_id, count in counts.items()
    }


async def _bonuses(
    db: AsyncSession, contract_ids: Sequence[int]
) -> dict[int, list[tuple[str, int, Decimal, bool]]]:
    """Premie automatu do kontraktów: (rola, odbiorca, kwota, czy propozycja)."""

    if not contract_ids:
        return {}
    rows = await db.execute(
        select(
            HrBonus.contract_id,
            HrBonus.source_key,
            HrBonus.recipient_user_id,
            HrBonus.amount,
            HrBonus.status,
        ).where(
            HrBonus.contract_id.in_(contract_ids),
            HrBonus.source == "contract_placement",
            HrBonus.status != "cancelled",
        )
    )
    found: dict[int, list[tuple[str, int, Decimal, bool]]] = {}
    for contract_id, source_key, recipient, amount, status in rows.all():
        role = (source_key or "").rsplit(":", 1)[-1]
        found.setdefault(contract_id, []).append(
            (role, recipient, amount, status == "proposed")
        )
    return found


async def _user_names(db: AsyncSession, ids: set[int]) -> dict[int, str]:
    if not ids:
        return {}
    rows = await db.execute(select(User.id, User.name).where(User.id.in_(sorted(ids))))
    return {user_id: name for user_id, name in rows.all() if name}


async def build_placement_rows(
    db: AsyncSession,
    contracts: Sequence[Contract],
    today: date,
    *,
    sees_bonus_of: Callable[[int], bool],
) -> list[list[Any]]:
    """Wiersze eksportu — stała liczba zapytań na paczkę (kurs walut osobno).

    ``sees_bonus_of`` — czy pobierający widzi premie danej osoby w Płacach.
    """

    if not contracts:
        return []
    ctx: PlacementContext = await load_context(db, contracts)
    ids = [c.id for c in contracts]
    pairs = {
        (c.candidate_id, c.job_id)
        for c in contracts
        if c.candidate_id is not None and c.job_id is not None
    }
    acceptances = await _acceptances(db, pairs)
    generated = await _generated(db, ids)
    bonuses = {
        contract_id: visible_bonuses(rows, sees_bonus_of)
        for contract_id, rows in (await _bonuses(db, ids)).items()
    }

    people: dict[int, tuple[Optional[int], Optional[int], Optional[int]]] = {}
    user_ids: set[int] = set()
    for c in contracts:
        dl_id, recruiter_id, _source = ctx.people(c)
        verifier_id = (
            ctx.verifiers.get((c.candidate_id, c.job_id))
            if c.candidate_id is not None and c.job_id is not None
            else None
        )
        people[c.id] = (dl_id, recruiter_id, verifier_id)
        user_ids.update(uid for uid in (dl_id, recruiter_id, verifier_id) if uid)
    for rows in bonuses.values():
        user_ids.update(recipient for _role, recipient, _amount, _p in rows)
    names = await _user_names(db, user_ids)

    out: list[list[Any]] = []
    for c in contracts:
        dl_id, recruiter_id, verifier_id = people[c.id]
        verified_by_dl = recruiter_id is None and verifier_id is not None
        shown_recruiter = recruiter_id if recruiter_id is not None else verifier_id
        margin = (
            await contract_margin(db, c, c.start_date)
            if c.start_date is not None
            else None
        )
        snapshot: Mapping[str, Any] = margin.snapshot if margin else {}
        facts = PlacementFacts(
            dl_name=names.get(dl_id, "") if dl_id else "",
            recruiter_name=names.get(shown_recruiter, "") if shown_recruiter else "",
            verified_by_dl=verified_by_dl,
            margin_per_hour=margin.per_hour if margin else None,
            cost_per_hour=_decimal_or_none(snapshot.get("cost_rate_per_hour")),
            client_per_hour=_decimal_or_none(snapshot.get("client_rate_per_hour")),
            cost_currency=c.resolved_rate_candidate_currency,
            client_currency=c.resolved_rate_client_currency,
            acceptance=(
                acceptances.get((c.candidate_id, c.job_id))
                if c.candidate_id is not None and c.job_id is not None
                else None
            ),
            generated=generated.get(c.id, SignedContracts(0, None)),
            bonuses=tuple(
                PlacementBonus(role, names.get(recipient, "?"), amount, proposed)
                for role, recipient, amount, proposed in bonuses.get(c.id, [])
            ),
            upcoming_rates=upcoming_rate_steps(c, today),
        )
        candidate, client = ctx.names(c)
        out.append(
            placement_row(
                c,
                facts,
                candidate if c.candidate_id in ctx.candidates else "",
                client if c.client_id in ctx.clients else "",
            )
        )
    return out


def _decimal_or_none(raw: object) -> Optional[Decimal]:
    return None if raw in (None, "") else Decimal(str(raw))
