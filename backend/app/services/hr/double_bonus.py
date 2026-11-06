"""Premia 200% w miesiącach z ``hr_bonus_rules.double_bonus`` (decyzje Artura 05.11.2026).

Placement podpisany w miesiącu programu daje premię ×2 wypłacaną w miesiącu
podpisu (bez czekania na próg dni roboczych), gdy osoba zrobiła w tym miesiącu cel:

* **rekruter** — placementy podpisane w miesiącu ≥ cel KPI osoby (junior 1,
  senior 2, ekspert 3, ten sam cel co Insights → Zespół, w proporcji do dni
  pracy), weryfikacje na dzień pracy ≥ próg i precision ≥ próg. Wszystkie
  poziomy mają te same KPI ilościowe. Rekruterzy z systemem indywidualnym
  i ze stałą premią dla roli (TCM) są poza programem;
* **Delivery Lead** — średnia marża zł/h placementów podpisanych w miesiącu, za
  które należy mu się premia DL, większa niż próg (50,00 nie wystarcza);
  dodatkowa premia DL idzie za wynikiem DL-a.

Miesiąc podpisu = dzień potwierdzenia podpisu obu stron w NEXUSIE
(``b2b_generated_contracts.signed_at``); kontrakt bez umowy z Generatora liczy
się od dnia założenia. Wynik znamy dopiero po ostatnim dniu miesiąca: automat
zapisuje go raz (``app_settings['hr_double_bonus_results']``) i wtedy podwaja
propozycje, a w trakcie miesiąca ekran pokazuje tylko postęp. Konsultant, który
odejdzie przed progiem, nie odbiera premii 200% — ryzyko firmy.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, Iterable, Optional

from sqlalchemy import exists, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scheduling import DEFAULT_TZ, business_date, local_month_bounds, local_now
from app.models.app_setting import AppSetting
from app.models.b2b_generated_contract import B2BGeneratedContract
from app.models.contract import Contract
from app.models.user import User
from app.services.hr.bonus_rules import (
    BonusRules,
    DoubleBonusRule,
    fixed_amount_for,
    individual_rule_for,
    money,
)
from app.services.hr.payroll_periods import YearMonth

RESULTS_KEY = "hr_double_bonus_results"
SIGNED_BOTH = "signed_both"


@dataclass(frozen=True)
class Decision:
    """Role kontraktu z premią 200% i miesiąc wypłaty (miesiąc podpisu)."""

    month: YearMonth
    roles: frozenset[str]
    multiplier: Decimal


def month_key(month: YearMonth) -> str:
    return f"{month[0]}-{month[1]:02d}"


def month_ended(month: YearMonth, today: date) -> bool:
    year, number = month
    last = date(year + (number == 12), number % 12 + 1, 1) - timedelta(days=1)
    return today > last


async def signed_dates(
    db: AsyncSession, contract_ids: Iterable[int]
) -> dict[int, tuple[date, str]]:
    """Dzień podpisu kontraktów: potwierdzenie obu stron, zapasowo dzień założenia.

    Liczy się ostatnia umowa kontraktu z podpisem obu stron. Kontrakt, który ma
    umowę z Generatora bez podpisu, nie jest podpisany.
    """

    ids = sorted(set(contract_ids))
    if not ids:
        return {}
    found: dict[int, tuple[date, str]] = {}
    with_agreement: set[int] = set()
    rows = await db.execute(
        select(
            B2BGeneratedContract.contract_id,
            B2BGeneratedContract.signature_status,
            B2BGeneratedContract.signed_at,
        )
        .where(B2BGeneratedContract.contract_id.in_(ids))
        .order_by(B2BGeneratedContract.id)
    )
    for contract_id, status, signed_at in rows.all():
        with_agreement.add(contract_id)
        if status == SIGNED_BOTH and signed_at is not None:
            found[contract_id] = (business_date(signed_at, DEFAULT_TZ), "signed")
    missing = [cid for cid in ids if cid not in with_agreement]
    if missing:
        rows = await db.execute(
            select(Contract.id, Contract.created_at).where(Contract.id.in_(missing))
        )
        for contract_id, created_at in rows.all():
            if created_at is not None:
                found[contract_id] = (business_date(created_at, DEFAULT_TZ), "created")
    return found


async def month_contracts(db: AsyncSession, year: int, month: int) -> list[Contract]:
    """Kontrakty podpisane w miesiącu (bez szkiców, unieważnionych i powrotów).

    Bez kandydatów wskazanych przez klienta (0655): nie liczą się rekruterowi
    do celu ani do średniej marży DL-a (decyzja Artura 06.11.2026).
    """

    from app.services.contract_rates import RATE_SCHEDULE_LOADS
    from app.services.hr.placement_bonuses import STARTED_STATUSES

    bounds = local_month_bounds(date(year, month, 1))
    signed = await db.scalars(
        select(B2BGeneratedContract.contract_id).where(
            B2BGeneratedContract.contract_id.is_not(None),
            B2BGeneratedContract.signature_status == SIGNED_BOTH,
            B2BGeneratedContract.signed_at >= bounds.start_utc,
            B2BGeneratedContract.signed_at < bounds.end_utc,
        )
    )
    created = await db.scalars(
        select(Contract.id).where(
            Contract.created_at >= bounds.start_utc,
            Contract.created_at < bounds.end_utc,
            ~exists().where(B2BGeneratedContract.contract_id == Contract.id),
        )
    )
    candidates = {*signed, *created}
    dates = await signed_dates(db, candidates)
    ids = [
        cid
        for cid, (day, _source) in dates.items()
        if (day.year, day.month) == (year, month)
    ]
    if not ids:
        return []
    return list(
        await db.scalars(
            select(Contract)
            .options(*RATE_SCHEDULE_LOADS)
            .where(
                Contract.id.in_(ids),
                Contract.status.in_(list(STARTED_STATUSES)),
                Contract.returned_from_contract_id.is_(None),
                Contract.is_client_referral.is_not(True),
            )
            .order_by(Contract.id)
        )
    )


async def _kpi_rows(
    db: AsyncSession, year: int, month: int, today: date
) -> dict[int, dict[str, Any]]:
    """Weryfikacje na dzień pracy, precision i cel placementów jak w Insights → Zespół."""

    from zoneinfo import ZoneInfo

    from app.analytics.periods import Period, PeriodKind
    from app.services.insights_team_signals import people_payload, team_people

    zone = ZoneInfo(DEFAULT_TZ)
    start = datetime(year, month, 1, tzinfo=zone)
    end = datetime(year + (month == 12), month % 12 + 1, 1, tzinfo=zone)
    now = min(local_now(), end - timedelta(seconds=1))
    last_day = min(today, (end - timedelta(days=1)).date())
    people = await team_people(
        db, Period(PeriodKind.month, start, end), now=now, today=last_day
    )
    return {row["user_id"]: row for row in people_payload(people)["rows"]}


def _number(value: object) -> Optional[Decimal]:
    return None if value is None else Decimal(str(value))


def _recruiter_row(
    user: User,
    contracts: list[dict[str, Any]],
    kpi: Optional[dict[str, Any]],
    rule: DoubleBonusRule,
    rules: BonusRules,
) -> dict[str, Any]:
    excluded: Optional[str] = None
    if not user.is_active:
        excluded = "inactive"
    elif individual_rule_for(user.id, rules) is not None:
        excluded = "individual"
    elif fixed_amount_for(user.role, rules) is not None:
        excluded = "fixed_role"
    target = kpi.get("placements_target") if kpi else None
    per_day = _number(kpi.get("verifications_per_workday")) if kpi else None
    precision = _number(kpi.get("precision_pct")) if kpi else None
    checks = {
        "placements": target is not None and len(contracts) >= int(target),
        "verifications": per_day is not None and per_day >= rule.verifications_per_day,
        "precision": precision is not None and precision >= rule.precision_pct,
    }
    return {
        "user_id": user.id,
        "name": user.name,
        "kind": "recruiter",
        "placements": len(contracts),
        "target": target,
        "verifications_per_day": None if per_day is None else str(per_day),
        "precision_pct": None if precision is None else str(precision),
        "checks": checks,
        "excluded": excluded,
        "qualified": excluded is None and all(checks.values()),
        "contracts": contracts,
    }


def _dl_row(
    user: User, contracts: list[dict[str, Any]], rule: DoubleBonusRule
) -> dict[str, Any]:
    margins = [Decimal(c["margin_per_hour"]) for c in contracts if c["margin_per_hour"]]
    average = money(sum(margins) / len(margins)) if margins else None
    missing = len(contracts) - len(margins)
    qualified = (
        user.is_active
        and average is not None
        and missing == 0
        and average > rule.dl_min_margin
    )
    return {
        "user_id": user.id,
        "name": user.name,
        "kind": "dl",
        "placements": len(contracts),
        "average_margin": None if average is None else str(average),
        "missing_margins": missing,
        "excluded": None if user.is_active else "inactive",
        "qualified": bool(qualified),
        "contracts": contracts,
    }


async def evaluate_month(
    db: AsyncSession, year: int, month: int, rules: BonusRules, *, today: date
) -> dict[str, Any]:
    """Wynik programu dla miesiąca (w trakcie miesiąca: postęp, nie decyzja)."""

    # Import w funkcji: automat premii woła ``contract_decision`` z tego modułu.
    from app.services.hr import placement_bonuses

    rule = rules.double_bonus
    payload: dict[str, Any] = {
        "year": year,
        "month": month,
        "in_program": bool(rule and rule.covers(year, month)),
        "final": month_ended((year, month), today),
        "recruiters": [],
        "dls": [],
        "stored": (await stored_results(db)).get(month_key((year, month))),
    }
    if rule is None or not rule.covers(year, month):
        return payload
    payload["thresholds"] = {
        "verifications_per_day": str(rule.verifications_per_day),
        "precision_pct": str(rule.precision_pct),
        "dl_min_margin": str(rule.dl_min_margin),
        "multiplier": str(rule.multiplier),
    }
    contracts = await month_contracts(db, year, month)
    context = await placement_bonuses.load_context(db, contracts)
    dates = await signed_dates(db, [c.id for c in contracts])
    by_recruiter: dict[int, list[dict[str, Any]]] = {}
    by_dl: dict[int, list[dict[str, Any]]] = {}
    for contract in contracts:
        dl_id, recruiter_id, _source = context.people(contract)
        candidate, client = context.names(contract)
        margin = await placement_bonuses.contract_margin(
            db, contract, contract.start_date or dates[contract.id][0]
        )
        item = {
            "contract_id": contract.id,
            "label": f"{candidate} ({client})",
            "signed_on": dates[contract.id][0].isoformat(),
            "signed_source": dates[contract.id][1],
            "margin_per_hour": None
            if margin.per_hour is None
            else str(margin.per_hour),
        }
        if recruiter_id is not None:
            by_recruiter.setdefault(recruiter_id, []).append(item)
        if dl_id is not None and not await placement_bonuses.guarantee_lost_dl(
            db, contract, dl_id
        ):
            by_dl.setdefault(dl_id, []).append(item)

    kpi = await _kpi_rows(db, year, month, today)
    recruiter_ids = set(by_recruiter)
    users_by_id: dict[int, User] = {}
    pool = set(kpi) | recruiter_ids | set(by_dl)
    if pool:
        users_by_id = {
            user.id: user
            for user in await db.scalars(select(User).where(User.id.in_(sorted(pool))))
        }
    for user_id, user in users_by_id.items():
        if user_id not in recruiter_ids and (
            not user.is_active
            or not placement_bonuses.holds_recruiter_role(user.role, user.roles)
            or user_id not in kpi
        ):
            continue
        payload["recruiters"].append(
            _recruiter_row(
                user, by_recruiter.get(user_id, []), kpi.get(user_id), rule, rules
            )
        )
    for user_id, items in by_dl.items():
        user = users_by_id.get(user_id)
        if user is not None:
            payload["dls"].append(_dl_row(user, items, rule))
    payload["recruiters"].sort(
        key=lambda row: (not row["qualified"], row["name"] or "")
    )
    payload["dls"].sort(key=lambda row: (not row["qualified"], row["name"] or ""))
    stored = payload["stored"]
    if isinstance(stored, dict):
        # Po zapisie liczy się decyzja, nie stan na dziś (np. stawka dopisana później).
        for kind, key in (("recruiters", "recruiters"), ("dls", "dls")):
            decided = set(stored.get(key) or ())
            for row in payload[kind]:
                row["decided"] = row["user_id"] in decided
    return payload


#: ``/me/double-bonus`` pyta przy każdym wejściu w zakładkę; ocena liczy całą firmę.
_CACHE_SECONDS = 300
_cache: dict[tuple[Any, ...], tuple[float, dict[str, Any]]] = {}


async def cached_evaluation(
    db: AsyncSession, year: int, month: int, rules: BonusRules, *, today: date
) -> dict[str, Any]:
    """Ocena miesiąca z pamięci procesu na 5 minut (tylko do odczytu postępu)."""

    import json
    import time

    from app.services.hr.bonus_rules import rules_payload

    key = (year, month, today, json.dumps(rules_payload(rules), sort_keys=True))
    hit = _cache.get(key)
    now = time.monotonic()
    if hit is not None and now - hit[0] < _CACHE_SECONDS:
        return hit[1]
    evaluation = await evaluate_month(db, year, month, rules, today=today)
    _cache.clear()
    _cache[key] = (now, evaluation)
    return evaluation


def rows_for(
    evaluation: dict[str, Any], user: User, rules: BonusRules
) -> list[dict[str, Any]]:
    """Wiersze jednej osoby; DL bez podpisanego placementu dostaje pusty wiersz.

    Bez marży poszczególnych kontraktów: rekruter nie widzi stawek klienta, a marża
    przy znanej stawce konsultanta by ją zdradziła. DL ma tylko średnią.
    """

    from app.services.hr.placement_bonuses import holds_dl_role

    rows = [
        {
            **row,
            "contracts": [
                {k: v for k, v in item.items() if k != "margin_per_hour"}
                for item in row["contracts"]
            ],
        }
        for row in (*evaluation["recruiters"], *evaluation["dls"])
        if row["user_id"] == user.id
    ]
    rule = rules.double_bonus
    if (
        rule is not None
        and evaluation["in_program"]
        and not any(row["kind"] == "dl" for row in rows)
        and holds_dl_role(user.role, user.roles)
    ):
        rows.append(_dl_row(user, [], rule))
    return rows


async def stored_results(db: AsyncSession) -> dict[str, Any]:
    raw = await db.scalar(select(AppSetting.value).where(AppSetting.key == RESULTS_KEY))
    return raw if isinstance(raw, dict) else {}


async def store_result(
    db: AsyncSession, evaluation: dict[str, Any], *, actor_id: Optional[int] = None
) -> dict[str, Any]:
    """Zapisuje decyzję miesiąca (kto dostaje 200%); bez commita."""

    key = month_key((evaluation["year"], evaluation["month"]))
    recruiters = [r for r in evaluation["recruiters"] if r["qualified"]]
    dls = [r for r in evaluation["dls"] if r["qualified"]]
    entry = {
        "recruiters": [r["user_id"] for r in recruiters],
        "dls": [r["user_id"] for r in dls],
        # Kontrakty zamrożone z decyzją: późniejsza umowa albo podpis nie przenosi
        # ich do innego miesiąca ani nie zabiera 200%.
        "recruiter_contracts": {
            str(item["contract_id"]): row["user_id"]
            for row in recruiters
            for item in row["contracts"]
        },
        "dl_contracts": {
            str(item["contract_id"]): row["user_id"]
            for row in dls
            for item in row["contracts"]
        },
        "computed_at": local_now().isoformat(),
        "computed_by": actor_id,
    }
    current = await stored_results(db)
    value = {**current, key: entry}
    statement = insert(AppSetting).values(
        key=RESULTS_KEY, value=value, updated_by=actor_id
    )
    await db.execute(
        statement.on_conflict_do_update(
            index_elements=[AppSetting.key],
            set_={"value": statement.excluded.value, "updated_by": actor_id},
        )
    )
    return entry


async def contract_decision(
    db: AsyncSession,
    contract: Contract,
    rules: BonusRules,
    *,
    dl_id: Optional[int],
    recruiter_id: Optional[int],
) -> Optional[Decision]:
    """Role kontraktu z premią 200%; ``None`` poza programem albo przed końcem miesiąca."""

    rule = rules.double_bonus
    if rule is None:
        return None
    stored = await stored_results(db)
    key = str(contract.id)
    for month in rule.months:
        entry = stored.get(month_key(month))
        if not isinstance(entry, dict):
            continue
        recruiters = entry.get("recruiter_contracts") or {}
        dls = entry.get("dl_contracts") or {}
        if key not in recruiters and key not in dls:
            continue
        roles: set[str] = set()
        # Zmiana odbiorcy po decyzji (np. „Prowadzi”) nie przenosi 200% na kogoś innego.
        if recruiter_id is not None and recruiters.get(key) == recruiter_id:
            roles.add("recruiter")
        if dl_id is not None and dls.get(key) == dl_id:
            roles |= {"dl", "dl_extra"}
        if not roles:
            return None
        return Decision(month=month, roles=frozenset(roles), multiplier=rule.multiplier)
    return None


async def settle_month(
    db: AsyncSession,
    year: int,
    month: int,
    rules: BonusRules,
    *,
    today: date,
    actor_id: Optional[int] = None,
) -> tuple[dict[str, Any], list[int]]:
    """Ocena po końcu miesiąca: zapis decyzji i kontrakty do uzgodnienia (bez commita)."""

    evaluation = await evaluate_month(db, year, month, rules, today=today)
    if not evaluation["in_program"] or not evaluation["final"]:
        return evaluation, []
    evaluation["stored"] = await store_result(db, evaluation, actor_id=actor_id)
    return evaluation, [c.id for c in await month_contracts(db, year, month)]


async def settle_due_months(
    db: AsyncSession, rules: BonusRules, *, today: date
) -> list[int]:
    """Miesiące programu po końcu, jeszcze bez decyzji: ocena raz.

    Zwraca kontrakty podpisane w tych miesiącach — automat uzgadnia je w tym
    samym przebiegu, więc premie ×2 pojawiają się w miesiącu podpisu.
    """

    rule = rules.double_bonus
    if rule is None:
        return []
    stored = await stored_results(db)
    contract_ids: list[int] = []
    for month in rule.months:
        if month_key(month) in stored or not month_ended(month, today):
            continue
        _evaluation, ids = await settle_month(db, *month, rules, today=today)
        contract_ids.extend(ids)
    return contract_ids


__all__ = [
    "Decision",
    "RESULTS_KEY",
    "cached_evaluation",
    "contract_decision",
    "evaluate_month",
    "month_contracts",
    "month_ended",
    "rows_for",
    "settle_due_months",
    "settle_month",
    "signed_dates",
    "stored_results",
]
