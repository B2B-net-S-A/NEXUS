"""Premie z placementów — propozycje liczone z kontraktów NEXUSA (D5).

Placement to kontrakt NEXUSA: start, stawki, marża, Delivery Lead i rekruter
rekrutacji są na nim. Compass wymagał co miesiąc importu Excela, mapowania
nazwisk i ręcznego potwierdzenia 168 h — tu automat proponuje, Płace albo
przełożony zatwierdzają.

Dla kontraktu z datą startu (status aktywny, kończący się albo zakończony):

* termin premii = start + 21 polskich dni roboczych (``bonus_rules``),
* okres premii = miesiąc terminu (zamknięty miesiąc → pierwszy otwarty),
* marża/h = stawka klienta − stawka kosztowa z dnia startu, w zł/h:
  stawka godzinowa bez zmian, dzienna (MD) ÷ 8, miesięczna ÷ godziny
  rozliczeniowe kontraktu; waluta obca po kursie NBP z dnia startu (brak
  kursu = brak propozycji, powód w liczbach przebiegu),
* propozycje: DL (10% × marża/h × 168), dodatkowa premia DL z ustawień,
  rekruter (próg marży); ``source_key`` = ``contract:{id}:dl|dl_extra|recruiter``.

Kontrakt zakończony przed terminem (albo anulowany) → propozycje anulowane
przez automat; cofnięcie zakończenia → przywrócone. Gdy miesiąc premii
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
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scheduling import business_today, local_now
from app.core.work_time import HOURS_PER_MONTH
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.contract import Contract, ContractStatus, RateUnit
from app.models.hr_payroll import HrBonus
from app.models.job import Job
from app.models.team_structure import DeliveryLeadClientAssignment
from app.services import fx_service
from app.services.contract_rates import RATE_SCHEDULE_LOADS
from app.services.hr import modules as hr_modules
from app.services.hr.bonus_rules import (
    BonusRules,
    dl_bonus,
    eligible_date,
    extra_dl_recipient,
    load_rules,
    money,
    recruiter_bonus,
    recruiter_tier,
)
from app.services.hr.payroll_bonuses import AUTO_CANCEL_REASONS
from app.services.hr.payroll_periods import closed_months, first_open_month_from
from app.services.order_rate_snapshots import CONTRACT_RATE_SCALE, convert_order_rate

logger = logging.getLogger(__name__)

SOURCE = "contract_placement"
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


async def contract_margin(db: AsyncSession, contract: Contract, on: date) -> Margin:
    """Marża zł/h kontraktu w dniu ``on`` (wymaga ``RATE_SCHEDULE_LOADS``)."""

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
        rate, found = await fx_service.get_rate_to_pln(db, currency, on)
        if not found:
            return Margin(None, snapshot, "fx_missing")
        fx[currency] = Decimal(rate)
    if len(fx) > 1:
        snapshot["fx_to_pln"] = {k: str(v) for k, v in fx.items() if k != "PLN"}
    per_hour = money(client_h * fx[client_currency] - cost_h * fx[cost_currency])
    snapshot["margin_per_hour"] = str(per_hour)
    return Margin(per_hour, snapshot, None)


async def placement_people(
    db: AsyncSession, contract: Contract
) -> tuple[Optional[int], Optional[int], str]:
    """(Delivery Lead, rekruter, skąd DL): z rekrutacji kontraktu, DL zapasowo z klienta."""

    dl_id: Optional[int] = None
    recruiter_id: Optional[int] = None
    if contract.job_id is not None:
        row = (
            await db.execute(
                select(Job.delivery_lead_id, Job.recruiter_id).where(
                    Job.id == contract.job_id
                )
            )
        ).first()
        if row is not None:
            dl_id, recruiter_id = row[0], row[1]
    if dl_id is not None:
        return dl_id, recruiter_id, "job"
    rows = (
        await db.execute(
            select(
                DeliveryLeadClientAssignment.delivery_lead_user_id,
                DeliveryLeadClientAssignment.is_head,
            ).where(DeliveryLeadClientAssignment.client_id == contract.client_id)
        )
    ).all()
    heads = [uid for uid, head in rows if head]
    if len(heads) == 1:
        return heads[0], recruiter_id, "client_head"
    if len(rows) == 1:
        return rows[0][0], recruiter_id, "client_assignment"
    return None, recruiter_id, "none"


async def _names(db: AsyncSession, contract: Contract) -> tuple[str, str]:
    candidate = None
    if contract.candidate_id:
        row = (
            await db.execute(
                select(Candidate.name, Candidate.lastname).where(
                    Candidate.id == contract.candidate_id
                )
            )
        ).first()
        if row is not None:
            candidate = " ".join(part for part in row if part) or None
    client = await db.scalar(select(Client.name).where(Client.id == contract.client_id))
    return candidate or "konsultant", client or "klient"


def _automation_floor(rules: BonusRules, today: date) -> date:
    return rules.automation_since or (today - timedelta(days=rules.lookback_days))


def _auto_cancel(bonus: HrBonus, reason: str) -> None:
    """Anulowanie przez automat: bez autora, z kodem powodu (automat może je cofnąć)."""

    bonus.status = "cancelled"
    bonus.cancelled_by = None
    bonus.cancelled_at = local_now()
    bonus.cancel_reason = reason


def _edited(bonus: HrBonus) -> bool:
    return bool((bonus.rule_snapshot or {}).get("edited_amount"))


async def reconcile_contract(
    db: AsyncSession,
    contract_id: int,
    *,
    today: Optional[date] = None,
    rules: Optional[BonusRules] = None,
) -> dict[str, Any]:
    """Uzgadnia propozycje premii jednego kontraktu z jego stanem (bez commita)."""

    today = today or business_today()
    rules = rules or await load_rules(db)
    counts = {"created": 0, "updated": 0, "cancelled": 0, "restored": 0}
    contract = await db.scalar(
        select(Contract).options(*RATE_SCHEDULE_LOADS).where(Contract.id == contract_id)
    )
    if contract is None:
        return {**counts, "skipped": "not_found"}
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
    if not existing and contract.start_date < _automation_floor(rules, today):
        return {**counts, "skipped": "before_automation_window"}

    start = contract.start_date
    eligible_on = eligible_date(start, rules)
    end = contract.end_date or contract.terminated_at
    ended_early = (end is not None and end < eligible_on) or (
        status == ContractStatus.ended and end is None
    )
    margin = await contract_margin(db, contract, start)
    dl_id, recruiter_id, people_source = await placement_people(db, contract)

    targets: dict[str, tuple[int, Decimal, str]] = {}
    if margin.per_hour is not None:
        dl_amount = dl_bonus(margin.per_hour, rules)
        if dl_id is not None and dl_amount > 0:
            targets["dl"] = (dl_id, dl_amount, "delivery_lead")
            extra = extra_dl_recipient(dl_id, rules)
            if extra is not None:
                targets["dl_extra"] = (extra, dl_amount, "delivery_lead")
        rec_amount = recruiter_bonus(margin.per_hour, rules)
        if recruiter_id is not None and rec_amount is not None:
            targets["recruiter"] = (recruiter_id, rec_amount, "recruiter")

    period = (eligible_on.year, eligible_on.month)
    target_period = await first_open_month_from(db, *period)
    closed = await closed_months(db)
    candidate_name, client_name = await _names(db, contract)
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
        description = (
            f"{ROLE_LABELS[role]} — placement: {candidate_name} ({client_name})"
        )[:1000]
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


async def contracts_to_reconcile(
    db: AsyncSession, *, today: date, rules: BonusRules
) -> list[int]:
    floor = _automation_floor(rules, today)
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
    for contract_id in await contracts_to_reconcile(db, today=today, rules=rules):
        totals["contracts"] += 1
        try:
            async with db.begin_nested():
                counts = await reconcile_contract(
                    db, contract_id, today=today, rules=rules
                )
        except Exception:  # noqa: BLE001 — jeden kontrakt nie zatrzymuje reszty
            logger.exception(
                "[payroll] propozycje premii: błąd kontraktu %s", contract_id
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
        if not modules.get("payroll"):
            return {"skipped": "module_off"}
        async with db.begin_nested():
            return await reconcile_contract(db, contract.id)
    except Exception as exc:  # noqa: BLE001 — patrz docstring
        logger.exception(
            "[payroll] hak %s kontraktu %s nie przeszedł", event, contract.id
        )
        return {"error": type(exc).__name__}


async def on_contract_started(db: AsyncSession, contract: Contract) -> dict[str, Any]:
    return await _hook(db, contract, "started")


async def on_contract_ended(db: AsyncSession, contract: Contract) -> dict[str, Any]:
    return await _hook(db, contract, "ended")


async def on_contract_end_undone(
    db: AsyncSession, contract: Contract
) -> dict[str, Any]:
    return await _hook(db, contract, "end_undone")


__all__ = [
    "ROLES",
    "contract_margin",
    "on_contract_end_undone",
    "on_contract_ended",
    "on_contract_started",
    "placement_people",
    "reconcile_contract",
    "source_key",
    "sync_placements",
]
