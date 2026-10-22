"""Premie z placementów — propozycje liczone z kontraktów NEXUSA (D5).

Placement to kontrakt NEXUSA: start, stawki i marża są na nim, odbiorcy
wynikają z rekrutacji (reguła niżej). Compass wymagał co miesiąc importu Excela, mapowania
nazwisk i ręcznego potwierdzenia 168 h — tu automat proponuje, Płace albo
przełożony zatwierdzają.

Dla kontraktu z datą startu (status aktywny, kończący się albo zakończony):

* termin premii = start + 21 dni roboczych firmy (``bonus_rules``, kalendarz
  firmy z dniami wolnymi — jak urlop),
* okres premii = miesiąc terminu (zamknięty miesiąc → pierwszy otwarty),
  wybierany pod blokadą współdzieloną okresu — miesiąc, który właśnie się
  zamyka, automat omija, zamiast dorzucić do niego propozycję,
* marża/h = stawka klienta − stawka kosztowa z dnia startu, w zł/h:
  stawka godzinowa bez zmian, dzienna (MD) ÷ 8, miesięczna ÷ godziny
  rozliczeniowe kontraktu; waluta obca po kursie NBP z dnia startu (brak
  kursu = brak propozycji, powód w liczbach przebiegu),
* propozycje: DL (10% × marża/h × 168), dodatkowa premia DL z ustawień,
  rekruter (próg marży); ``source_key`` = ``contract:{id}:dl|dl_extra|recruiter``,
* odbiorcy jak w Compassie (decyzja Artura 18.10.2026): rekruter = osoba, która
  jako pierwsza zweryfikowała kandydata w tej rekrutacji (etap „Zweryfikowany”,
  ta sama zasada co KPI i Liga), a nie prowadzący (``jobs.recruiter_id`` —
  w rekrutacjach sprzed 10.2026 siedzi tam zwykle Delivery Lead); DL =
  ``jobs.delivery_lead_id``, a gdy go brak — prowadzący rekrutację, jeśli ma
  rolę Delivery Leada, a dopiero potem DL klienta (głowa albo jedyne
  przypisanie). Bez weryfikującego premii rekrutera nie ma — ani gdy
  weryfikującym jest ten sam Delivery Lead (22.10.2026: DL, który sam
  przeprowadził osobę, dostaje jedną premię, DL-a).

Kontrakt zakończony przed terminem (albo anulowany) → propozycje anulowane
przez automat; cofnięcie zakończenia → przywrócone. Kontrakt usunięty trwale →
propozycje anulowane na stałe (``contract_deleted``, poza
``AUTO_CANCEL_REASONS``: nie ma czego przywracać), przyznane zostają. Gdy miesiąc premii
zamknięto w międzyczasie, przywrócona propozycja idzie na pierwszy otwarty
miesiąc (``restored_from_closed_period`` w migawce) — o wypłacie i tak
decydują Płace, bo to znów propozycja. Premii zatwierdzonej
albo anulowanej ręcznie automat nie rusza; kwoty poprawionej przez Płace
też nie. „Powrót po przerwie” (``returned_from_contract_id``) to nie nowy
placement.

Haki ``on_contract_started`` / ``on_contract_ended`` / ``on_contract_end_undone``
wpina koordynator w ``app/api/contracts.py``; codzienny przebieg
(``payroll_jobs.run_once``) uzgadnia wszystko i tak.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scheduling import business_today, local_now
from app.core.work_time import HOURS_PER_MONTH
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.contract import Contract, ContractStatus, RateUnit
from app.models.hr_payroll import HrBonus
from app.models.job import Job
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.models.team_structure import DeliveryLeadClientAssignment
from app.models.user import User, UserRole, known_roles
from app.services import fx_service
from app.services.contract_rates import RATE_SCHEDULE_LOADS
from app.services.hr import audit
from app.services.hr import modules as hr_modules
from app.services.hr.bonus_rules import (
    BonusRules,
    automation_floor_for,
    dl_bonus,
    eligible_date,
    extra_dl_recipient,
    load_bonus_calendar,
    load_rules,
    money,
    recruiter_bonus,
    recruiter_tier,
)
from app.services.hr.calendar import WorkCalendar
from app.services.hr.modules import HrModule
from app.services.hr.payroll_bonuses import AUTO_CANCEL_REASONS
from app.services.hr.payroll_periods import (
    YearMonth,
    closed_months,
    first_open_month_locked,
    lock_period_shared,
)
from app.services.order_rate_snapshots import CONTRACT_RATE_SCALE, convert_order_rate

logger = logging.getLogger(__name__)

SOURCE = "contract_placement"
#: Powód anulowania propozycji kontraktu usuniętego trwale (bez przywracania).
DELETED_REASON = "contract_deleted"
ROLES: tuple[str, ...] = ("dl", "dl_extra", "recruiter")
ROLE_LABELS: dict[str, str] = {
    "dl": "Premia DL",
    "dl_extra": "Dodatkowa premia DL",
    "recruiter": "Premia rekrutera",
}
STARTED_STATUSES: frozenset[ContractStatus] = frozenset(
    {ContractStatus.active, ContractStatus.ending, ContractStatus.ended}
)


def source_key(contract_id: int, role: str) -> str:
    return f"contract:{contract_id}:{role}"


@dataclass(frozen=True)
class Margin:
    per_hour: Optional[Decimal]
    snapshot: dict[str, Any]
    reason: Optional[str]


def _status(contract: Contract) -> ContractStatus:
    return ContractStatus(getattr(contract.status, "value", contract.status))


async def contract_margin(
    db: AsyncSession,
    contract: Contract,
    on: date,
    *,
    fx_rates: Optional[Mapping[str, Optional[Decimal]]] = None,
) -> Margin:
    """Marża zł/h kontraktu w dniu ``on`` (wymaga ``RATE_SCHEDULE_LOADS``).

    ``fx_rates`` — kursy do PLN na dzień ``on`` wczytane hurtem dla paczki
    kontraktów (``fx_service.rates_to_pln_by_date``, prognoza „w drodze”);
    bez nich kurs czyta ``fx_service.get_rate_to_pln``. Brak kursu =
    ``fx_missing``.
    """

    unit = RateUnit(getattr(contract.rate_unit, "value", contract.rate_unit))
    hours = contract.billing_hours_per_month or HOURS_PER_MONTH
    snapshot: dict[str, Any] = {
        "rates_on": on.isoformat(),
        "rate_unit": unit.value,
        "billing_hours_per_month": hours,
    }
    client = contract.effective_client_rate(on)
    cost = contract.effective_candidate_rate(on)
    if client is None or cost is None:
        return Margin(None, snapshot, "missing_rates")
    client_h = convert_order_rate(
        client, unit, RateUnit.hourly, hours, scale=CONTRACT_RATE_SCALE
    )
    cost_h = convert_order_rate(
        cost, unit, RateUnit.hourly, hours, scale=CONTRACT_RATE_SCALE
    )
    assert client_h is not None and cost_h is not None
    client_currency = contract.resolved_rate_client_currency
    cost_currency = contract.resolved_rate_candidate_currency
    snapshot.update(
        {
            "client_rate_per_hour": str(client_h),
            "cost_rate_per_hour": str(cost_h),
            "client_currency": client_currency,
            "cost_currency": cost_currency,
        }
    )
    fx: dict[str, Decimal] = {"PLN": Decimal(1)}
    for currency in {client_currency, cost_currency} - {"PLN"}:
        if fx_rates is not None:
            rate = fx_rates.get(currency)
            found = rate is not None
        else:
            rate, found = await fx_service.get_rate_to_pln(db, currency, on)
        if not found:
            return Margin(None, snapshot, "fx_missing")
        fx[currency] = Decimal(rate)
    if len(fx) > 1:
        snapshot["fx_to_pln"] = {k: str(v) for k, v in fx.items() if k != "PLN"}
    per_hour = money(client_h * fx[client_currency] - cost_h * fx[cost_currency])
    snapshot["margin_per_hour"] = str(per_hour)
    return Margin(per_hour, snapshot, None)


@dataclass(frozen=True)
class PlacementContext:
    """Rekrutacje, Delivery Leadzi klientów i nazwy dla paczki kontraktów.

    Wczytane hurtowo (``load_context``): prognoza „w drodze” pyta bazę tyle
    samo razy dla jednego i dla dwudziestu kontraktów.
    """

    #: rekrutacja → Delivery Lead rekrutacji
    jobs: dict[int, Optional[int]]
    #: klient → [(Delivery Lead, czy „głowa”)] — tylko klienci bez DL z rekrutacji
    client_leads: dict[int, list[tuple[int, bool]]]
    candidates: dict[int, str]
    clients: dict[int, str]
    #: (kandydat, rekrutacja) → pierwszy weryfikujący (etap „Zweryfikowany”)
    verifiers: dict[tuple[int, int], int] = field(default_factory=dict)
    #: rekrutacja bez DL → prowadzący (``jobs.recruiter_id``) z rolą Delivery Leada
    job_leads: dict[int, int] = field(default_factory=dict)

    def people(self, contract: Contract) -> tuple[Optional[int], Optional[int], str]:
        """(Delivery Lead, rekruter, skąd DL).

        Rekruter = pierwszy weryfikujący kandydata w rekrutacji kontraktu;
        DL z rekrutacji, potem prowadzący z rolą DL, zapasowo DL klienta
        (decyzje Artura 18.10.2026). DL, który sam zweryfikował osobę, nie
        dostaje do premii DL-a premii rekrutera (decyzja Artura 22.10.2026).
        """

        recruiter_id = (
            self.verifiers.get((contract.candidate_id, contract.job_id))
            if contract.candidate_id is not None and contract.job_id is not None
            else None
        )
        dl_id, source = self._delivery_lead(contract)
        if dl_id is not None and recruiter_id == dl_id:
            recruiter_id = None
        return dl_id, recruiter_id, source

    def _delivery_lead(self, contract: Contract) -> tuple[Optional[int], str]:
        dl_id = self.jobs.get(contract.job_id)
        if dl_id is not None:
            return dl_id, "job"
        lead_id = self.job_leads.get(contract.job_id)
        if lead_id is not None:
            return lead_id, "job_lead"
        rows = self.client_leads.get(contract.client_id, [])
        heads = [uid for uid, head in rows if head]
        if len(heads) == 1:
            return heads[0], "client_head"
        if len(rows) == 1:
            return rows[0][0], "client_assignment"
        return None, "none"

    def names(self, contract: Contract) -> tuple[str, str]:
        """(konsultant, klient) do opisu premii — z zapasowymi słowami bez nazw."""

        candidate = self.candidates.get(contract.candidate_id) or "konsultant"
        client = self.clients.get(contract.client_id) or "klient"
        return candidate, client


async def load_context(
    db: AsyncSession, contracts: Sequence[Contract]
) -> PlacementContext:
    """Najwyżej pięć zapytań niezależnie od liczby kontraktów."""

    job_ids = sorted({c.job_id for c in contracts if c.job_id is not None})
    jobs: dict[int, Optional[int]] = {}
    job_leads: dict[int, int] = {}
    if job_ids:
        rows = await db.execute(
            select(
                Job.id, Job.delivery_lead_id, Job.recruiter_id, User.role, User.roles
            )
            .outerjoin(User, User.id == Job.recruiter_id)
            .where(Job.id.in_(job_ids))
        )
        for job_id, dl, lead, role, roles in rows.all():
            jobs[job_id] = dl
            if dl is None and lead is not None and holds_dl_role(role, roles):
                job_leads[job_id] = lead
    verifiers = await load_verifiers(
        db,
        {
            (c.candidate_id, c.job_id)
            for c in contracts
            if c.candidate_id is not None and c.job_id is not None
        },
    )
    # DL klienta potrzebny tylko tam, gdzie rekrutacja go nie wskazuje.
    fallback_clients = sorted(
        {
            c.client_id
            for c in contracts
            if c.client_id is not None
            and jobs.get(c.job_id) is None
            and c.job_id not in job_leads
        }
    )
    client_leads: dict[int, list[tuple[int, bool]]] = {}
    if fallback_clients:
        rows = await db.execute(
            select(
                DeliveryLeadClientAssignment.client_id,
                DeliveryLeadClientAssignment.delivery_lead_user_id,
                DeliveryLeadClientAssignment.is_head,
            ).where(DeliveryLeadClientAssignment.client_id.in_(fallback_clients))
        )
        for client_id, lead_id, is_head in rows.all():
            client_leads.setdefault(client_id, []).append((lead_id, is_head))
    candidate_ids = sorted({c.candidate_id for c in contracts if c.candidate_id})
    candidates: dict[int, str] = {}
    if candidate_ids:
        rows = await db.execute(
            select(Candidate.id, Candidate.name, Candidate.lastname).where(
                Candidate.id.in_(candidate_ids)
            )
        )
        for candidate_id, *parts in rows.all():
            full = " ".join(part for part in parts if part)
            if full:
                candidates[candidate_id] = full
    client_ids = sorted({c.client_id for c in contracts if c.client_id is not None})
    clients: dict[int, str] = {}
    if client_ids:
        rows = await db.execute(
            select(Client.id, Client.name).where(Client.id.in_(client_ids))
        )
        clients = {client_id: name for client_id, name in rows.all() if name}
    return PlacementContext(
        jobs, client_leads, candidates, clients, verifiers, job_leads
    )


def holds_dl_role(role: object, roles: object) -> bool:
    """Czy konto ma rolę Delivery Leada — główną albo dodatkową."""

    primary = getattr(role, "value", role)
    if primary == UserRole.delivery_lead.value:
        return True
    extra = roles if isinstance(roles, (list, tuple)) else ()
    return UserRole.delivery_lead in known_roles(extra)


async def load_verifiers(
    db: AsyncSession, pairs: set[tuple[int, int]]
) -> dict[tuple[int, int], int]:
    """Pierwszy weryfikujący per (kandydat, rekrutacja) — jedno zapytanie.

    Kolejność jak w KPI (``kpi_panel.VERIFIER_ANCHORED_CTE``): czas akceptacji
    etapu „Zweryfikowany”, a bez niej czas ruchu, potem id. Wiersz bez autora
    ruchu (import) nikogo nie wskazuje.
    """

    if not pairs:
        return {}
    candidate_ids = sorted({candidate for candidate, _job in pairs})
    job_ids = sorted({job for _candidate, job in pairs})
    rows = await db.execute(
        select(
            CandidateStage.candidate_id, CandidateStage.job_id, CandidateStage.moved_by
        )
        .where(
            CandidateStage.stage == PipelineStage.verified,
            CandidateStage.candidate_id.in_(candidate_ids),
            CandidateStage.job_id.in_(job_ids),
            CandidateStage.moved_by.is_not(None),
        )
        .order_by(
            func.coalesce(CandidateStage.approved_at, CandidateStage.moved_at),
            CandidateStage.id,
        )
    )
    found: dict[tuple[int, int], int] = {}
    for candidate_id, job_id, moved_by in rows.all():
        pair = (candidate_id, job_id)
        if pair in pairs:
            found.setdefault(pair, moved_by)
    return found


def automation_floor(rules: BonusRules, today: date) -> date:
    """Najwcześniejszy start kontraktu, dla którego automat zakłada propozycje."""

    return automation_floor_for(rules, today)


@dataclass(frozen=True)
class PlacementTarget:
    """Komu i ile automat przyznałby z placementu (jedna rola)."""

    role: str
    recipient_user_id: int
    #: ``None`` = marża nieznana (brak stawki albo kursu) — kwoty nie da się policzyć.
    amount: Optional[Decimal]
    category: str


def placement_targets(
    margin_per_hour: Optional[Decimal],
    dl_id: Optional[int],
    recruiter_id: Optional[int],
    rules: BonusRules,
) -> dict[str, PlacementTarget]:
    """Odbiorcy i kwoty premii z placementu — czysta reguła automatu.

    Przy znanej marży: DL dostaje premię dodatnią, dodatkowa premia DL idzie
    za DL-em (z ustawień), rekruter — gdy marża nie jest ujemna. Przy
    nieznanej marży role są te same, a kwota ``None``: automat takich nie
    zapisuje, prognoza „w drodze” pokazuje je bez kwoty.
    """

    targets: dict[str, PlacementTarget] = {}
    if dl_id is not None:
        dl_amount = (
            None if margin_per_hour is None else dl_bonus(margin_per_hour, rules)
        )
        if dl_amount is None or dl_amount > 0:
            targets["dl"] = PlacementTarget("dl", dl_id, dl_amount, "delivery_lead")
            extra = extra_dl_recipient(dl_id, rules)
            if extra is not None:
                targets["dl_extra"] = PlacementTarget(
                    "dl_extra", extra, dl_amount, "delivery_lead"
                )
    if recruiter_id is not None:
        rec_amount = (
            None if margin_per_hour is None else recruiter_bonus(margin_per_hour, rules)
        )
        if margin_per_hour is None or rec_amount is not None:
            targets["recruiter"] = PlacementTarget(
                "recruiter", recruiter_id, rec_amount, "recruiter"
            )
    return targets


def ends_before_deadline(contract: Contract, eligible_on: date) -> bool:
    """Kontrakt kończy się przed terminem premii (albo zakończony bez daty)."""

    end = contract.end_date or contract.terminated_at
    return (end is not None and end < eligible_on) or (
        _status(contract) == ContractStatus.ended and end is None
    )


def placement_description(role: str, candidate_name: str, client_name: str) -> str:
    return (f"{ROLE_LABELS[role]} — placement: {candidate_name} ({client_name})")[:1000]


def _auto_cancel(bonus: HrBonus, reason: str) -> None:
    """Anulowanie przez automat: bez autora, z kodem powodu (automat może je cofnąć)."""

    bonus.status = "cancelled"
    bonus.cancelled_by = None
    bonus.cancelled_at = local_now()
    bonus.cancel_reason = reason


def _edited(bonus: HrBonus) -> bool:
    return bool((bonus.rule_snapshot or {}).get("edited_amount"))


async def _lock_periods(
    db: AsyncSession,
    contract: Contract,
    rules: BonusRules,
    today: date,
    calendar: Optional[WorkCalendar],
) -> Optional[YearMonth]:
    """Okresy premii kontraktu pod ``FOR SHARE``, ZANIM ruszymy premie.

    Ta sama kolejność co zamknięcie miesiąca i akceptacje: okres, potem
    wiersze. Blokujemy miesiące istniejących propozycji (przesunięcie albo
    przywrócenie) i wybieramy miesiąc docelowy nowych; zwraca go, gdy kontrakt
    w ogóle dostaje propozycje.
    """

    held = sorted(
        {
            (int(year), int(month))
            for year, month in (
                await db.execute(
                    select(HrBonus.period_year, HrBonus.period_month).where(
                        HrBonus.source == SOURCE, HrBonus.contract_id == contract.id
                    )
                )
            ).all()
        }
    )
    for year, month in held:
        await lock_period_shared(db, year, month)
    if contract.start_date is None or _status(contract) not in STARTED_STATUSES:
        return None
    if not held and contract.start_date < automation_floor(rules, today):
        return None
    assert calendar is not None
    eligible_on = eligible_date(contract.start_date, rules, calendar=calendar)
    return await first_open_month_locked(db, eligible_on.year, eligible_on.month)


async def reconcile_contract(
    db: AsyncSession,
    contract_id: int,
    *,
    today: Optional[date] = None,
    rules: Optional[BonusRules] = None,
    calendar: Optional[WorkCalendar] = None,
) -> dict[str, Any]:
    """Uzgadnia propozycje premii jednego kontraktu z jego stanem (bez commita).

    ``calendar`` — kalendarz firmy z dniami wolnymi (przebieg dzienny podaje
    jeden dla wszystkich kontraktów); bez niego wczytany dla tego kontraktu.
    """

    today = today or business_today()
    rules = rules or await load_rules(db)
    counts = {"created": 0, "updated": 0, "cancelled": 0, "restored": 0}
    contract = await db.scalar(
        select(Contract).options(*RATE_SCHEDULE_LOADS).where(Contract.id == contract_id)
    )
    if contract is None:
        return {**counts, "skipped": "not_found"}
    if calendar is None and contract.start_date is not None:
        start = contract.start_date
        calendar = await load_bonus_calendar(db, start, max(start, today), rules)
    locked_target = await _lock_periods(db, contract, rules, today, calendar)
    existing = {
        bonus.source_key: bonus
        for bonus in await db.scalars(
            select(HrBonus)
            .where(HrBonus.source == SOURCE, HrBonus.contract_id == contract_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    }
    status = _status(contract)
    if status == ContractStatus.void:
        for bonus in existing.values():
            if bonus.status == "proposed":
                _auto_cancel(bonus, "contract_void")
                counts["cancelled"] += 1
        await db.flush()
        return counts
    if status not in STARTED_STATUSES or contract.start_date is None:
        return {**counts, "skipped": "not_started"}
    if contract.returned_from_contract_id is not None:
        return {**counts, "skipped": "return_after_break"}
    if not existing and contract.start_date < automation_floor(rules, today):
        return {**counts, "skipped": "before_automation_window"}

    start = contract.start_date
    assert calendar is not None
    eligible_on = eligible_date(start, rules, calendar=calendar)
    ended_early = ends_before_deadline(contract, eligible_on)
    margin = await contract_margin(db, contract, start)
    context = await load_context(db, [contract])
    dl_id, recruiter_id, people_source = context.people(contract)

    # Nieznana marża (brak stawki albo kursu) = brak propozycji automatu.
    targets: dict[str, tuple[int, Decimal, str]] = {
        role: (target.recipient_user_id, target.amount, target.category)
        for role, target in placement_targets(
            margin.per_hour, dl_id, recruiter_id, rules
        ).items()
        if target.amount is not None
    }

    period = (eligible_on.year, eligible_on.month)
    target_period = locked_target or await first_open_month_locked(db, *period)
    closed = await closed_months(db)
    candidate_name, client_name = context.names(contract)
    common: dict[str, Any] = {
        "rule": "placement",
        "contract_id": contract.id,
        "start_date": start.isoformat(),
        "eligible_on": eligible_on.isoformat(),
        "eligible_business_days": rules.eligible_business_days,
        "dl_percent": str(rules.dl_percent),
        "monthly_hours": rules.monthly_hours,
        "recruiter_tier_bounds": [str(v) for v in rules.recruiter_tier_bounds],
        "recruiter_tier_amounts": [str(v) for v in rules.recruiter_tier_amounts],
        "people_source": people_source,
        **margin.snapshot,
    }
    if margin.reason:
        common["skip_reason"] = margin.reason
    if target_period != period:
        common["period_shifted_from"] = f"{period[0]}-{period[1]:02d}"

    for role in ROLES:
        key = source_key(contract.id, role)
        bonus = existing.get(key)
        target = targets.get(role)
        if ended_early:
            if bonus is not None and bonus.status == "proposed":
                _auto_cancel(bonus, "contract_ended")
                counts["cancelled"] += 1
            continue
        if target is None:
            # Np. rekrutacja straciła DL — propozycji poprawionej ręcznie nie ruszamy.
            if bonus is not None and bonus.status == "proposed" and not _edited(bonus):
                _auto_cancel(bonus, "rule_no_longer_applies")
                counts["cancelled"] += 1
            continue
        recipient, amount, category = target
        snapshot = {**common, "role": role}
        if role == "recruiter" and margin.per_hour is not None:
            snapshot["tier"] = recruiter_tier(margin.per_hour, rules)
        description = placement_description(role, candidate_name, client_name)
        if bonus is None:
            db.add(
                HrBonus(
                    recipient_user_id=recipient,
                    proposed_by=None,
                    amount=amount,
                    currency=rules.currency,
                    category=category,
                    period_year=target_period[0],
                    period_month=target_period[1],
                    status="proposed",
                    source=SOURCE,
                    source_key=key,
                    rule_snapshot=snapshot,
                    contract_id=contract.id,
                    eligible_on=eligible_on,
                    description=description,
                )
            )
            counts["created"] += 1
            continue
        restorable = (
            bonus.status == "cancelled" and bonus.cancel_reason in AUTO_CANCEL_REASONS
        )
        if not restorable and bonus.status != "proposed":
            continue
        closed_period = (bonus.period_year, bonus.period_month) in closed
        if closed_period and not restorable:
            continue
        if restorable:
            bonus.status = "proposed"
            bonus.cancel_reason = None
            bonus.cancelled_at = None
            bonus.cancelled_by = None
            counts["restored"] += 1
        if closed_period:
            # Anulowana przez automat w miesiącu, który potem zamknięto:
            # wraca jako propozycja w pierwszym otwartym miesiącu.
            moved_from = f"{bonus.period_year}-{bonus.period_month:02d}"
            snapshot["restored_from_closed_period"] = moved_from
            bonus.period_year, bonus.period_month = target_period
            if _edited(bonus):
                bonus.rule_snapshot = {
                    **(bonus.rule_snapshot or {}),
                    "restored_from_closed_period": moved_from,
                }
        if _edited(bonus):
            bonus.eligible_on = eligible_on
            continue
        changed = (
            bonus.recipient_user_id != recipient
            or bonus.amount != amount
            or (bonus.period_year, bonus.period_month) != target_period
            or bonus.eligible_on != eligible_on
        )
        bonus.recipient_user_id = recipient
        bonus.amount = amount
        bonus.category = category
        bonus.period_year, bonus.period_month = target_period
        bonus.eligible_on = eligible_on
        bonus.rule_snapshot = snapshot
        bonus.description = description
        if changed and not restorable:
            counts["updated"] += 1
    await db.flush()
    return counts


async def ended_early_bonus_ids(
    db: AsyncSession, bonuses: Sequence[HrBonus]
) -> set[int]:
    """Premie z placementu PRZYZNANE, choć kontrakt kończy się przed terminem.

    Automat anuluje tylko propozycje; przyznanej (np. kontrakt zamknięty w
    systemie datą wsteczną po zatwierdzeniu) nie rusza — o wypłacie decydują
    Płace, a ekran i zamknięcie miesiąca ich ostrzegają (decyzja Artura
    19.10.2026).
    """

    candidates = [
        bonus
        for bonus in bonuses
        if bonus.source == SOURCE
        and bonus.status == "assigned"
        and bonus.contract_id is not None
        and bonus.eligible_on is not None
    ]
    if not candidates:
        return set()
    contracts = {
        contract.id: contract
        for contract in await db.scalars(
            select(Contract).where(
                Contract.id.in_(sorted({b.contract_id for b in candidates}))
            )
        )
    }
    found: set[int] = set()
    for bonus in candidates:
        contract = contracts.get(bonus.contract_id)
        assert bonus.eligible_on is not None
        if contract is not None and ends_before_deadline(contract, bonus.eligible_on):
            found.add(bonus.id)
    return found


async def contracts_to_reconcile(
    db: AsyncSession, *, today: date, rules: BonusRules
) -> list[int]:
    floor = automation_floor(rules, today)
    fresh = await db.scalars(
        select(Contract.id).where(
            Contract.start_date >= floor,
            Contract.status.in_([*STARTED_STATUSES, ContractStatus.void]),
        )
    )
    open_proposals = await db.scalars(
        select(HrBonus.contract_id)
        .where(
            HrBonus.source == SOURCE,
            HrBonus.contract_id.is_not(None),
            or_(
                HrBonus.status == "proposed",
                (HrBonus.status == "cancelled")
                & HrBonus.cancel_reason.in_(sorted(AUTO_CANCEL_REASONS)),
            ),
        )
        .distinct()
    )
    return sorted({*fresh, *(cid for cid in open_proposals if cid is not None)})


async def sync_placements(
    db: AsyncSession, *, today: date, rules: Optional[BonusRules] = None
) -> dict[str, int]:
    """Uzgadnia wszystkie kontrakty z okna automatu (każdy w osobnym savepoincie)."""

    rules = rules or await load_rules(db)
    totals = {
        "contracts": 0,
        "created": 0,
        "updated": 0,
        "cancelled": 0,
        "restored": 0,
        "errors": 0,
    }
    skipped: dict[str, int] = {}
    contract_ids = await contracts_to_reconcile(db, today=today, rules=rules)
    calendar: Optional[WorkCalendar] = None
    if contract_ids:
        # Jeden kalendarz firmy na przebieg (a nie zapytanie na kontrakt).
        first, last = (
            await db.execute(
                select(
                    func.min(Contract.start_date), func.max(Contract.start_date)
                ).where(Contract.id.in_(contract_ids))
            )
        ).one()
        calendar = await load_bonus_calendar(
            db, first or today, max(last or today, today), rules
        )
    for contract_id in contract_ids:
        totals["contracts"] += 1
        try:
            async with db.begin_nested():
                counts = await reconcile_contract(
                    db, contract_id, today=today, rules=rules, calendar=calendar
                )
        except Exception as exc:  # noqa: BLE001 — jeden kontrakt nie zatrzymuje reszty
            # Klasa wyjątku, nie treść — DETAIL Postgresa niesie kwoty wiersza.
            logger.error(
                "[payroll] propozycje premii: błąd kontraktu %s (%s)",
                contract_id,
                type(exc).__name__,
            )
            totals["errors"] += 1
            continue
        for name in ("created", "updated", "cancelled", "restored"):
            totals[name] += int(counts.get(name, 0))
        if counts.get("skipped"):
            skipped[counts["skipped"]] = skipped.get(counts["skipped"], 0) + 1
    return {**totals, **{f"skipped_{k}": v for k, v in sorted(skipped.items())}}


async def _hook(db: AsyncSession, contract: Contract, event: str) -> dict[str, Any]:
    """Wspólne ciało haków: moduł Płac włączony → uzgodnij kontrakt w savepoincie.

    Błąd automatu premii nigdy nie cofa operacji na kontrakcie — wynik to
    liczby albo ``{"error": nazwa}``. Commit robi wołający.
    """

    try:
        modules = await hr_modules.load_modules(db)
        if not modules.get(HrModule.payroll):
            return {"status": "disabled"}
        async with db.begin_nested():
            return await reconcile_contract(db, contract.id)
    except Exception as exc:  # noqa: BLE001 — patrz docstring
        # Klasa wyjątku, nie treść — DETAIL Postgresa niesie kwoty wiersza.
        logger.error(
            "[payroll] hak %s kontraktu %s nie przeszedł (%s)",
            event,
            contract.id,
            type(exc).__name__,
        )
        return {"error": type(exc).__name__}


async def on_contract_started(db: AsyncSession, contract: Contract) -> dict[str, Any]:
    return await _hook(db, contract, "started")


async def on_contract_ended(db: AsyncSession, contract: Contract) -> dict[str, Any]:
    return await _hook(db, contract, "ended")


async def on_contract_deleted(db: AsyncSession, contract: Contract) -> int:
    """Przed trwałym usunięciem kontraktu: jego propozycje automatu → anulowane.

    FK zeruje ``hr_bonuses.contract_id``; propozycja bez kontraktu wisiałaby
    jako „do decyzji” i blokowała zamknięcie miesiąca (``pending_bonuses``).
    Premie przyznane zostają bez zmian. Bez sprawdzania modułu Płac — po
    wyłączeniu modułu stare propozycje i tak nie mogą zostać bez kontraktu.
    Zwraca liczbę anulowanych; nie commituje.
    """

    proposals = await db.scalars(
        select(HrBonus)
        .where(
            HrBonus.source == SOURCE,
            HrBonus.contract_id == contract.id,
            HrBonus.status == "proposed",
        )
        .order_by(HrBonus.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    cancelled = 0
    for bonus in proposals:
        _auto_cancel(bonus, DELETED_REASON)
        audit.record(
            db,
            actor_user_id=None,
            subject_user_id=bonus.recipient_user_id,
            entity_type="hr_bonus",
            entity_id=bonus.id,
            action="bonus_cancelled",
            sensitivity="payroll",
            details={
                "amount": str(bonus.amount),
                "currency": bonus.currency,
                "category": bonus.category,
                "period": f"{bonus.period_year}-{bonus.period_month:02d}",
                "source": bonus.source,
                "status": bonus.status,
                "reason": DELETED_REASON,
                "contract_id": contract.id,
            },
        )
        cancelled += 1
    await db.flush()
    return cancelled


async def on_contract_end_undone(
    db: AsyncSession, contract: Contract
) -> dict[str, Any]:
    return await _hook(db, contract, "end_undone")


__all__ = [
    "ROLES",
    "PlacementContext",
    "PlacementTarget",
    "automation_floor",
    "contract_margin",
    "ended_early_bonus_ids",
    "ends_before_deadline",
    "load_context",
    "holds_dl_role",
    "load_verifiers",
    "on_contract_deleted",
    "on_contract_end_undone",
    "on_contract_ended",
    "on_contract_started",
    "placement_description",
    "placement_targets",
    "reconcile_contract",
    "source_key",
    "sync_placements",
]
