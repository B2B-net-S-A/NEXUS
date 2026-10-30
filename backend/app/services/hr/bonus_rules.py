"""Reguły premii z placementów i z Ligi (``app_settings['hr_bonus_rules']``).

Wartości domyślne to reguły Compassa (``lib/types/bonus.ts:242-253``,
``lib/types/placement.ts``, ``lib/placements/import.ts:28-58``):

* **termin premii** = start kontraktu + 21 dni roboczych firmy (168 h
  po 8 h; weekendy, święta ustawowe i dni wolne firmy pominięte),
* **premia Delivery Leada** = 10% × marża/h × 168 h,
* **premia rekrutera** według progu marży PLN/h: do 40 włącznie → 1000,
  powyżej 40 i poniżej 50 → 1500, od 50 → 2000; marża ujemna = bez premii,
* **dodatkowa premia DL** — w Compassie reguła zaszyta w kodzie razem
  z adresami e-mail dwóch osób. Tu to USTAWIENIE: lista par
  ``{dl_user_id → recipient_user_id}``, domyślnie pusta (repo jest publiczne,
  w kodzie nie ma nikogo).

Funkcje liczące są czyste (bez bazy), żeby testy granic nie potrzebowały
Postgresa; kalendarz firmy z dniami wolnymi podaje wołający
(``load_bonus_calendar``). Zapis ustawień: ``save_rules`` (Płace albo admin).
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.work_time import HOURS_PER_MONTH, MD_PER_MONTH
from app.models.app_setting import AppSetting
from app.models.competition_winner import CompetitionType
from app.services.hr.calendar import WorkCalendar, load_calendar

logger = logging.getLogger(__name__)

SETTING_KEY = "hr_bonus_rules"
CENT = Decimal("0.01")
#: Data startu automatu przy zepsutym wpisie bez czytelnej daty: automat nie
#: zakłada nic nowego (lepiej brak propozycji niż premie zdublowane z Compassem).
AUTOMATION_STOPPED = date.max

#: Rywalizacje z nagrodą pieniężną wypłacaną przez płace (kwartalna Liga).
#: Wyścig miesięczny daje voucher, nie przelew — domyślnie poza płacami.
DEFAULT_LEAGUE_TYPES: tuple[str, ...] = (
    CompetitionType.quarterly_champions_dl.value,
    CompetitionType.quarterly_champions_recruiter.value,
)
KNOWN_LEAGUE_TYPES: frozenset[str] = frozenset(
    {
        CompetitionType.quarterly_champions_dl.value,
        CompetitionType.quarterly_champions_recruiter.value,
        CompetitionType.monthly_recommendations.value,
        CompetitionType.monthly_placements.value,
    }
)

#: Ile dni wstecz automat szuka startów kontraktów i zamkniętych okresów Ligi,
#: gdy nie ustawiono daty ``automation_since`` (przełączenie z Compassa).
DEFAULT_LOOKBACK_DAYS = 120


class BonusRulesError(ValueError):
    """Niepoprawne ustawienia premii (komunikat po polsku, dla użytkownika)."""


@dataclass(frozen=True)
class ExtraDlRule:
    dl_user_id: int
    recipient_user_id: int


@dataclass(frozen=True)
class BonusRules:
    #: Dwie granice marży PLN/h: ≤ pierwsza → próg I, < druga → próg II, reszta → III.
    recruiter_tier_bounds: tuple[Decimal, Decimal] = (Decimal("40"), Decimal("50"))
    recruiter_tier_amounts: tuple[Decimal, Decimal, Decimal] = (
        Decimal("1000"),
        Decimal("1500"),
        Decimal("2000"),
    )
    dl_percent: Decimal = Decimal("10")
    monthly_hours: int = HOURS_PER_MONTH
    #: 168 h po 8 h = 21 dni roboczych (miesiąc roboczy z ``app.core.work_time``).
    eligible_business_days: int = MD_PER_MONTH
    currency: str = "PLN"
    extra_dl: tuple[ExtraDlRule, ...] = ()
    automation_since: Optional[date] = None
    league_types: tuple[str, ...] = DEFAULT_LEAGUE_TYPES
    lookback_days: int = field(default=DEFAULT_LOOKBACK_DAYS)


DEFAULT_RULES = BonusRules()


# ── Czyste reguły ─────────────────────────────────────────────────────────────


def money(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def recruiter_tier(
    margin_per_hour: Decimal, rules: BonusRules = DEFAULT_RULES
) -> Optional[int]:
    """Próg premii rekrutera (1–3) dla marży PLN/h; ``None`` = marża ujemna."""

    low, high = rules.recruiter_tier_bounds
    if margin_per_hour < 0:
        return None
    if margin_per_hour <= low:
        return 1
    if margin_per_hour < high:
        return 2
    return 3


def recruiter_bonus(
    margin_per_hour: Decimal, rules: BonusRules = DEFAULT_RULES
) -> Optional[Decimal]:
    tier = recruiter_tier(margin_per_hour, rules)
    if tier is None:
        return None
    return rules.recruiter_tier_amounts[tier - 1]


def dl_bonus(margin_per_hour: Decimal, rules: BonusRules = DEFAULT_RULES) -> Decimal:
    """10% marży miesięcznej (marża/h × 168 h), w groszach."""

    monthly_margin = margin_per_hour * Decimal(rules.monthly_hours)
    return money(monthly_margin * rules.dl_percent / Decimal(100))


def eligible_date(start: date, rules: BonusRules, *, calendar: WorkCalendar) -> date:
    """Start + N dni roboczych firmy (dzień startu się nie liczy — jak w Compassie).

    Kalendarz firmy jak przy urlopach (``hr.calendar``): weekendy, święta
    ustawowe (biblioteka ``holidays``) i dni wolne firmy (decyzja 17.10.2026).
    Compass do 08.2026 pomijał tylko weekendy i termin wypadał za wcześnie
    o każde święto w oknie.
    """

    day = start
    added = 0
    while added < rules.eligible_business_days:
        day += timedelta(days=1)
        if calendar.is_working_day(day):
            added += 1
    return day


def payout_period(start: date, eligible_on: date) -> tuple[int, int]:
    """Miesiąc wypłaty: następny po starcie, nigdy przed terminem premii.

    Decyzja Artura z 30.10.2026 za arkuszem Delivery: na potwierdzenie godzin
    trzeba czekać, więc start we wrześniu to rozliczenie październikowe.
    Termin wypada zwykle w tym samym miesiącu; później tylko przy świętach.
    """

    after_start = (
        (start.year + 1, 1) if start.month == 12 else (start.year, start.month + 1)
    )
    return max(after_start, (eligible_on.year, eligible_on.month))


def business_days_elapsed(start: date, today: date, *, calendar: WorkCalendar) -> int:
    """Ile dni roboczych po starcie minęło do ``today`` włącznie (pasek „liczy się”)."""

    if today <= start:
        return 0
    return len(calendar.working_days(start + timedelta(days=1), today))


def calendar_reach(rules: BonusRules) -> timedelta:
    """Zapas za startem, w którym na pewno wypada termin: N dni roboczych to
    najwyżej ok. 1,4 N dni kalendarzowych plus święta i dni wolne firmy."""

    return timedelta(days=rules.eligible_business_days * 2 + 14)


async def load_bonus_calendar(
    db: AsyncSession, first_start: date, last_day: date, rules: BonusRules
) -> WorkCalendar:
    """Kalendarz firmy dla terminów i postępu premii startów od ``first_start``
    (ten sam loader co urlopy, jedno zapytanie na przebieg albo ekran)."""

    return await load_calendar(db, first_start, last_day + calendar_reach(rules))


def automation_floor_for(rules: BonusRules, today: date) -> date:
    """Najwcześniejszy start kontraktu (koniec okresu Ligi), dla którego automat
    zakłada propozycje: ``automation_since`` albo okno ``lookback_days`` wstecz."""

    return rules.automation_since or (today - timedelta(days=rules.lookback_days))


def automation_since_change_error(
    current: Optional[date], new: Optional[date], *, has_compass_imports: bool
) -> Optional[str]:
    """Komunikat odmowy, gdy zmiana daty startu automatu cofnęłaby go przed
    przełączenie z Compassa (``None`` = zmiana dozwolona).

    Premie sprzed tej daty przyszły importem z Compassa (``compass_import``, bez
    kontraktu NEXUSA) — automat nie umie ich rozpoznać, więc data pusta albo
    wcześniejsza niż zapisana dałaby drugie propozycje za te same placementy.
    """

    if not has_compass_imports:
        return None
    if new is None:
        return (
            "Data startu automatu jest potrzebna, dopóki w płacach są premie "
            "z Compassa — bez niej automat zaproponuje drugi raz premie "
            "za placementy sprzed przełączenia."
        )
    if current is not None and new < current:
        return (
            f"Data startu automatu nie może być wcześniejsza niż {current:%d.%m.%Y}: "
            "premie za placementy sprzed niej przyszły z Compassa."
        )
    return None


def extra_dl_recipient(dl_user_id: int, rules: BonusRules) -> Optional[int]:
    for rule in rules.extra_dl:
        if rule.dl_user_id == dl_user_id:
            return rule.recipient_user_id
    return None


# ── Ustawienia ────────────────────────────────────────────────────────────────


def _decimal(value: object, label: str) -> Decimal:
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise BonusRulesError(f"{label}: podaj liczbę.") from exc
    if not number.is_finite():
        raise BonusRulesError(f"{label}: podaj liczbę.")
    return number


def _int(value: object, label: str, *, low: int, high: int) -> int:
    if isinstance(value, bool):
        raise BonusRulesError(f"{label}: podaj liczbę całkowitą.")
    try:
        number = int(str(value))
    except (ValueError, TypeError) as exc:
        raise BonusRulesError(f"{label}: podaj liczbę całkowitą.") from exc
    if not low <= number <= high:
        raise BonusRulesError(f"{label}: wartość od {low} do {high}.")
    return number


def parse_rules(raw: object) -> BonusRules:
    """Ustawienia z bazy albo z żądania → ``BonusRules`` (brak klucza = domyślne).

    Rzuca ``BonusRulesError`` z opisem pola, gdy wartość jest niepoprawna.
    """

    source: Mapping[str, Any] = raw if isinstance(raw, Mapping) else {}
    defaults = DEFAULT_RULES

    bounds = defaults.recruiter_tier_bounds
    if "recruiter_tier_bounds" in source:
        values = source["recruiter_tier_bounds"]
        if not isinstance(values, (list, tuple)) or len(values) != 2:
            raise BonusRulesError("Progi rekrutera: podaj dwie granice marży.")
        low = _decimal(values[0], "Granica progu I")
        high = _decimal(values[1], "Granica progu II")
        if not Decimal(0) <= low < high:
            raise BonusRulesError(
                "Progi rekrutera: druga granica musi być większa od pierwszej."
            )
        bounds = (low, high)

    amounts = defaults.recruiter_tier_amounts
    if "recruiter_tier_amounts" in source:
        values = source["recruiter_tier_amounts"]
        if not isinstance(values, (list, tuple)) or len(values) != 3:
            raise BonusRulesError("Kwoty progów rekrutera: podaj trzy kwoty.")
        parsed = tuple(
            _decimal(v, f"Kwota progu {i + 1}") for i, v in enumerate(values)
        )
        if any(amount <= 0 or amount > Decimal(1_000_000) for amount in parsed):
            raise BonusRulesError("Kwoty progów rekrutera: od 0,01 do 1 000 000.")
        amounts = (money(parsed[0]), money(parsed[1]), money(parsed[2]))

    percent = defaults.dl_percent
    if "dl_percent" in source:
        percent = _decimal(source["dl_percent"], "Procent premii DL")
        if not Decimal(0) < percent <= Decimal(100):
            raise BonusRulesError("Procent premii DL: od 0 do 100.")

    hours = defaults.monthly_hours
    if "monthly_hours" in source:
        hours = _int(source["monthly_hours"], "Godziny w miesiącu", low=1, high=744)

    days = defaults.eligible_business_days
    if "eligible_business_days" in source:
        days = _int(
            source["eligible_business_days"], "Dni robocze do premii", low=1, high=260
        )

    extra: list[ExtraDlRule] = []
    seen: set[int] = set()
    for item in source.get("extra_dl") or ():
        if not isinstance(item, Mapping):
            raise BonusRulesError("Dodatkowa premia DL: niepoprawny wpis.")
        dl_id = _int(item.get("dl_user_id"), "Delivery Lead", low=1, high=2**31 - 1)
        recipient = _int(
            item.get("recipient_user_id"), "Odbiorca", low=1, high=2**31 - 1
        )
        if dl_id == recipient:
            raise BonusRulesError(
                "Dodatkowa premia DL: odbiorca musi być inną osobą niż Delivery Lead."
            )
        if dl_id in seen:
            raise BonusRulesError(
                "Dodatkowa premia DL: jeden Delivery Lead może mieć jedną regułę."
            )
        seen.add(dl_id)
        extra.append(ExtraDlRule(dl_user_id=dl_id, recipient_user_id=recipient))

    since: Optional[date] = None
    if source.get("automation_since"):
        try:
            since = date.fromisoformat(str(source["automation_since"]))
        except ValueError as exc:
            raise BonusRulesError("Data startu automatu: format RRRR-MM-DD.") from exc

    league_types = defaults.league_types
    if "league_types" in source:
        values = source["league_types"] or []
        if not isinstance(values, (list, tuple)) or any(
            str(v) not in KNOWN_LEAGUE_TYPES for v in values
        ):
            raise BonusRulesError("Liga: nieznany rodzaj rywalizacji.")
        league_types = tuple(dict.fromkeys(str(v) for v in values))

    return BonusRules(
        recruiter_tier_bounds=bounds,
        recruiter_tier_amounts=amounts,
        dl_percent=percent,
        monthly_hours=hours,
        eligible_business_days=days,
        currency=defaults.currency,
        extra_dl=tuple(extra),
        automation_since=since,
        league_types=league_types,
        lookback_days=defaults.lookback_days,
    )


def rules_payload(rules: BonusRules) -> dict[str, Any]:
    """Postać JSON (zapis w ``app_settings`` i odpowiedź API)."""

    return {
        "recruiter_tier_bounds": [str(v) for v in rules.recruiter_tier_bounds],
        "recruiter_tier_amounts": [str(v) for v in rules.recruiter_tier_amounts],
        "dl_percent": str(rules.dl_percent),
        "monthly_hours": rules.monthly_hours,
        "eligible_business_days": rules.eligible_business_days,
        "currency": rules.currency,
        "extra_dl": [
            {"dl_user_id": r.dl_user_id, "recipient_user_id": r.recipient_user_id}
            for r in rules.extra_dl
        ],
        "automation_since": rules.automation_since.isoformat()
        if rules.automation_since
        else None,
        "league_types": list(rules.league_types),
    }


def _readable_since(raw: object) -> Optional[date]:
    if not isinstance(raw, Mapping) or not raw.get("automation_since"):
        return None
    try:
        return date.fromisoformat(str(raw["automation_since"]))
    except ValueError:
        return AUTOMATION_STOPPED


async def load_rules(db: AsyncSession) -> BonusRules:
    """Reguły z bazy; zepsuty wpis nie zatrzymuje płac — wtedy domyślne.

    Domyślne, ale z zapisaną datą startu automatu: bez niej automat sięgnąłby
    120 dni wstecz i zdublował premie zaimportowane z Compassa. Data nieczytelna
    = automat nie zakłada nowych propozycji (``AUTOMATION_STOPPED``).
    """

    raw = await db.scalar(select(AppSetting.value).where(AppSetting.key == SETTING_KEY))
    try:
        return parse_rules(raw)
    except BonusRulesError:
        logger.error("[payroll] %s niepoprawne — reguły domyślne", SETTING_KEY)
        return replace(DEFAULT_RULES, automation_since=_readable_since(raw))


async def save_rules(
    db: AsyncSession, raw: Mapping[str, Any], *, actor_id: int
) -> BonusRules:
    """Waliduje i zapisuje reguły (bez commita)."""

    rules = parse_rules(raw)
    payload = rules_payload(rules)
    statement = insert(AppSetting).values(
        key=SETTING_KEY, value=payload, updated_by=actor_id
    )
    await db.execute(
        statement.on_conflict_do_update(
            index_elements=[AppSetting.key],
            set_={"value": statement.excluded.value, "updated_by": actor_id},
        )
    )
    return rules


__all__ = [
    "DEFAULT_RULES",
    "BonusRules",
    "AUTOMATION_STOPPED",
    "BonusRulesError",
    "ExtraDlRule",
    "automation_floor_for",
    "automation_since_change_error",
    "business_days_elapsed",
    "calendar_reach",
    "dl_bonus",
    "eligible_date",
    "extra_dl_recipient",
    "load_bonus_calendar",
    "load_rules",
    "money",
    "parse_rules",
    "payout_period",
    "recruiter_bonus",
    "recruiter_tier",
    "rules_payload",
    "save_rules",
]
