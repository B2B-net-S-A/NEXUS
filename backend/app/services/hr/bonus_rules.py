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
  ``{dl_user_id → recipient_user_id}`` z opcjonalną listą klientów
  (``client_ids``, decyzja Artura 02.11.2026), domyślnie pusta (repo jest
  publiczne, w kodzie nie ma nikogo),
* **stała premia rekrutera dla roli** (``fixed_role_amounts``, decyzja Artura
  05.11.2026): Talent Community Manager dostaje 1000 zł bez progów marży,
* **premia 200%** (``double_bonus``, decyzja Artura 05.11.2026): w wybranych
  miesiącach placement podpisany w miesiącu, w którym osoba zrobiła cel, daje
  premię ×2 wypłacaną w tym miesiącu (``services/hr/double_bonus.py``).

Funkcje liczące są czyste (bez bazy), żeby testy granic nie potrzebowały
Postgresa; kalendarz firmy z dniami wolnymi podaje wołający
(``load_bonus_calendar``). Zapis ustawień: ``save_rules`` (Płace albo admin).
"""

from __future__ import annotations

import hashlib
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
from app.models.user import UserRole
from app.services.hr.calendar import WorkCalendar, load_calendar

logger = logging.getLogger(__name__)

SETTING_KEY = "hr_bonus_rules"
CENT = Decimal("0.01")
#: Data startu automatu przy zepsutym wpisie bez czytelnej daty: automat nie
#: zakłada nic nowego (lepiej brak propozycji niż premie zdublowane z Compassem).
AUTOMATION_STOPPED = date.max

#: Rywalizacje z nagrodą pieniężną wypłacaną przez płace: kwartalna Liga i od
#: października 2026 oba wyścigi miesięczne (decyzja Artura 06.11.2026, wcześniej
#: voucher). Ustawienie w Płacach może to zawęzić.
DEFAULT_LEAGUE_TYPES: tuple[str, ...] = (
    CompetitionType.quarterly_champions_dl.value,
    CompetitionType.quarterly_champions_recruiter.value,
    CompetitionType.monthly_recommendations.value,
    CompetitionType.monthly_placements.value,
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
    #: Pusta lista = każdy klient; inaczej reguła działa tylko u tych klientów.
    client_ids: tuple[int, ...] = ()

    def covers(self, client_id: Optional[int]) -> bool:
        return not self.client_ids or client_id in self.client_ids


@dataclass(frozen=True)
class DlHoursRule:
    """Delivery Lead z innymi godzinami premii niż ``monthly_hours`` (umowa)."""

    user_id: int
    hours: int


@dataclass(frozen=True)
class IndividualRecruiterRule:
    """Rekruter z własnym systemem: procent marży miesięcznej zamiast progów.

    Od 3. startu w miesiącu procent rośnie o ``step_percent`` na każdy start od 3.
    i o ``expert_percent``, dla wszystkich premii tego miesiąca. W kodzie nie ma
    osoby: lista jest w ustawieniach.
    """

    user_id: int
    base_percent: Decimal
    step_percent: Decimal
    expert_percent: Decimal


@dataclass(frozen=True)
class RuleItem:
    """Pozycja poza regułami wpisana przez admina: automat ją przyznaje.

    Zastępuje wpisywanie premii ręcznie (decyzja Artura 09.11.2026), np. premia
    za punkty z arkusza Delivery, dopóki nie ma na nią wzoru.
    """

    user_id: int
    amount: Decimal
    month: tuple[int, int]
    reason: str

    @property
    def key(self) -> str:
        text = f"{self.user_id}|{self.amount}|{self.month[0]}-{self.month[1]:02d}|{self.reason}"
        return hashlib.sha256(text.encode()).hexdigest()[:24]


@dataclass(frozen=True)
class FixedRoleAmount:
    """Rola główna rekrutera ze stałą premią zamiast progów marży (np. TCM)."""

    role: str
    amount: Decimal


@dataclass(frozen=True)
class DoubleBonusRule:
    """Premia 200% za placementy podpisane w miesiącu z ``months``.

    Rekruter: placementy podpisane ≥ cel KPI osoby, weryfikacje na dzień pracy
    ≥ ``verifications_per_day``, precision ≥ ``precision_pct``. DL: średnia marża
    zł/h placementów podpisanych w miesiącu > ``dl_min_margin`` (50,00 nie wystarcza).
    """

    months: tuple[tuple[int, int], ...]
    verifications_per_day: Decimal = Decimal("4")
    precision_pct: Decimal = Decimal("75")
    dl_min_margin: Decimal = Decimal("50")
    multiplier: Decimal = Decimal("2")

    def covers(self, year: int, month: int) -> bool:
        return (year, month) in self.months


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
    dl_hours: tuple[DlHoursRule, ...] = ()
    individual_recruiters: tuple[IndividualRecruiterRule, ...] = ()
    automation_since: Optional[date] = None
    league_types: tuple[str, ...] = DEFAULT_LEAGUE_TYPES
    lookback_days: int = field(default=DEFAULT_LOOKBACK_DAYS)
    fixed_role_amounts: tuple[FixedRoleAmount, ...] = ()
    double_bonus: Optional[DoubleBonusRule] = None
    #: Godziny premii każdego DL-a; ``None`` = ``monthly_hours`` (od 11.2026: 160 h).
    dl_default_hours: Optional[int] = None
    #: Od tego miesiąca premii automat sam przyznaje, a ręcznie zmienia tylko admin.
    auto_assign_from: Optional[tuple[int, int]] = None
    rule_items: tuple[RuleItem, ...] = ()


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


def fixed_amount_for(role: object, rules: BonusRules) -> Optional[Decimal]:
    """Stała premia rekrutera dla roli głównej osoby; ``None`` = progi marży."""

    value = getattr(role, "value", role)
    for rule in rules.fixed_role_amounts:
        if rule.role == value:
            return rule.amount
    return None


def dl_hours_for(dl_user_id: Optional[int], rules: BonusRules) -> int:
    """Godziny premii DL: wyjątek osoby, potem domyślne dla DL-i, potem ``monthly_hours``."""

    for rule in rules.dl_hours:
        if rule.user_id == dl_user_id:
            return rule.hours
    return rules.dl_default_hours or rules.monthly_hours


def dl_bonus(
    margin_per_hour: Decimal,
    rules: BonusRules = DEFAULT_RULES,
    *,
    dl_user_id: Optional[int] = None,
) -> Decimal:
    """10% marży miesięcznej (marża/h × godziny DL), w groszach."""

    monthly_margin = margin_per_hour * Decimal(dl_hours_for(dl_user_id, rules))
    return money(monthly_margin * rules.dl_percent / Decimal(100))


def individual_rule_for(
    user_id: Optional[int], rules: BonusRules
) -> Optional[IndividualRecruiterRule]:
    for rule in rules.individual_recruiters:
        if rule.user_id == user_id:
            return rule
    return None


def individual_percent(rule: IndividualRecruiterRule, starts_in_month: int) -> Decimal:
    """Procent przy ``starts_in_month`` startach: 2 → baza, 3 → baza + krok + ekspert."""

    if starts_in_month < 3:
        return rule.base_percent
    steps = Decimal(starts_in_month - 2)
    return rule.base_percent + steps * rule.step_percent + rule.expert_percent


def individual_recruiter_bonus(
    margin_per_hour: Decimal,
    rule: IndividualRecruiterRule,
    starts_in_month: int,
    rules: BonusRules = DEFAULT_RULES,
) -> Optional[Decimal]:
    if margin_per_hour < 0:
        return None
    monthly_margin = margin_per_hour * Decimal(rules.monthly_hours)
    percent = individual_percent(rule, starts_in_month)
    return money(monthly_margin * percent / Decimal(100))


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
            "Data startu automatu jest potrzebna, dopóki w rozliczeniach są premie "
            "z Compassa — bez niej automat zaproponuje drugi raz premie "
            "za placementy sprzed przełączenia."
        )
    if current is not None and new < current:
        return (
            f"Data startu automatu nie może być wcześniejsza niż {current:%d.%m.%Y}: "
            "premie za placementy sprzed niej przyszły z Compassa."
        )
    return None


def extra_dl_recipient(
    dl_user_id: int, rules: BonusRules, *, client_id: Optional[int] = None
) -> Optional[int]:
    """Odbiorca dodatkowej premii; reguła z listą klientów działa tylko u nich."""

    for rule in rules.extra_dl:
        if rule.dl_user_id == dl_user_id and rule.covers(client_id):
            return rule.recipient_user_id
    return None


def rule_amount(snapshot: Mapping[str, Any], role: str) -> Optional[Decimal]:
    """Kwota z reguły według migawki kontraktu; ``None`` = migawka bez marży.

    Liczy z wartości zapisanych w migawce, więc porównanie z kwotą z arkusza nie
    zmienia się po późniejszej zmianie progów w ustawieniach.
    """

    raw = snapshot.get("margin_per_hour")
    if raw is None:
        return None
    try:
        margin = Decimal(str(raw))
        hours = Decimal(str(snapshot.get("monthly_hours") or HOURS_PER_MONTH))
        if role != "recruiter":
            percent = Decimal(
                str(snapshot.get("dl_percent") or DEFAULT_RULES.dl_percent)
            )
            dl_hours = Decimal(str(snapshot.get("dl_hours") or hours))
            return money(margin * dl_hours * percent / Decimal(100))
        if margin < 0:
            return None
        if snapshot.get("fixed_amount") is not None:
            return money(Decimal(str(snapshot["fixed_amount"])))
        if snapshot.get("individual_percent") is not None:
            percent = Decimal(str(snapshot["individual_percent"]))
            return money(margin * hours * percent / Decimal(100))
        bounds = snapshot.get("recruiter_tier_bounds")
        amounts = snapshot.get("recruiter_tier_amounts")
        if not bounds or not amounts:
            return recruiter_bonus(margin)
        low, high = Decimal(str(bounds[0])), Decimal(str(bounds[1]))
        index = 0 if margin <= low else 1 if margin < high else 2
        return money(Decimal(str(amounts[index])))
    except (InvalidOperation, ValueError, IndexError, TypeError):
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


def _year_month(value: object, label: str) -> tuple[int, int]:
    try:
        year_text, month_text = str(value).split("-")
        year, month = int(year_text), int(month_text)
    except ValueError as exc:
        raise BonusRulesError(f"{label}: miesiąc w formacie RRRR-MM.") from exc
    if not (2020 <= year <= 2100 and 1 <= month <= 12):
        raise BonusRulesError(f"{label}: miesiąc w formacie RRRR-MM.")
    return year, month


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

    dl_default_hours: Optional[int] = None
    if source.get("dl_default_hours") not in (None, ""):
        dl_default_hours = _int(
            source["dl_default_hours"], "Godziny premii DL", low=1, high=744
        )

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
        raw_clients = item.get("client_ids") or ()
        if not isinstance(raw_clients, (list, tuple)):
            raise BonusRulesError("Dodatkowa premia DL: niepoprawna lista klientów.")
        clients = tuple(
            dict.fromkeys(
                _int(value, "Klient", low=1, high=2**31 - 1) for value in raw_clients
            )
        )
        extra.append(
            ExtraDlRule(
                dl_user_id=dl_id, recipient_user_id=recipient, client_ids=clients
            )
        )

    dl_hours: list[DlHoursRule] = []
    seen_hours: set[int] = set()
    for item in source.get("dl_hours") or ():
        if not isinstance(item, Mapping):
            raise BonusRulesError("Godziny DL: niepoprawny wpis.")
        user_id = _int(item.get("user_id"), "Delivery Lead", low=1, high=2**31 - 1)
        if user_id in seen_hours:
            raise BonusRulesError("Godziny DL: jedna osoba może mieć jeden wpis.")
        seen_hours.add(user_id)
        dl_hours.append(
            DlHoursRule(
                user_id=user_id,
                hours=_int(item.get("hours"), "Godziny DL", low=1, high=744),
            )
        )

    individual: list[IndividualRecruiterRule] = []
    seen_individual: set[int] = set()
    for item in source.get("individual_recruiters") or ():
        if not isinstance(item, Mapping):
            raise BonusRulesError("System indywidualny: niepoprawny wpis.")
        user_id = _int(item.get("user_id"), "Rekruter", low=1, high=2**31 - 1)
        if user_id in seen_individual:
            raise BonusRulesError("System indywidualny: jedna osoba, jeden wpis.")
        seen_individual.add(user_id)
        values = {
            key: _decimal(item.get(key), label)
            for key, label in (
                ("base_percent", "Procent bazowy"),
                ("step_percent", "Procent na start od 3."),
                ("expert_percent", "Procent eksperta"),
            )
        }
        if any(not Decimal(0) <= value <= Decimal(100) for value in values.values()):
            raise BonusRulesError("System indywidualny: procenty od 0 do 100.")
        individual.append(IndividualRecruiterRule(user_id=user_id, **values))

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

    fixed: list[FixedRoleAmount] = []
    for item in source.get("fixed_role_amounts") or ():
        if not isinstance(item, Mapping):
            raise BonusRulesError("Stała premia dla roli: niepoprawny wpis.")
        role = str(item.get("role") or "")
        if role not in {r.value for r in UserRole}:
            raise BonusRulesError("Stała premia dla roli: nieznana rola.")
        if any(rule.role == role for rule in fixed):
            raise BonusRulesError("Stała premia dla roli: jedna rola, jeden wpis.")
        amount = _decimal(item.get("amount"), "Stała premia dla roli")
        if not Decimal(0) < amount <= Decimal(1_000_000):
            raise BonusRulesError("Stała premia dla roli: od 0,01 do 1 000 000.")
        fixed.append(FixedRoleAmount(role=role, amount=money(amount)))

    double: Optional[DoubleBonusRule] = None
    raw_double = source.get("double_bonus")
    if raw_double:
        if not isinstance(raw_double, Mapping):
            raise BonusRulesError("Premia 200%: niepoprawny wpis.")
        months: list[tuple[int, int]] = []
        for value in raw_double.get("months") or ():
            try:
                year_text, month_text = str(value).split("-")
                month_key = (int(year_text), int(month_text))
            except ValueError as exc:
                raise BonusRulesError(
                    "Premia 200%: miesiące w formacie RRRR-MM."
                ) from exc
            if not (2020 <= month_key[0] <= 2100 and 1 <= month_key[1] <= 12):
                raise BonusRulesError("Premia 200%: miesiące w formacie RRRR-MM.")
            months.append(month_key)
        if not months:
            raise BonusRulesError("Premia 200%: podaj co najmniej jeden miesiąc.")
        per_day = _decimal(
            raw_double.get("verifications_per_day", "4"), "Premia 200%: weryfikacje"
        )
        precision = _decimal(
            raw_double.get("precision_pct", "75"), "Premia 200%: precision"
        )
        dl_margin = _decimal(
            raw_double.get("dl_min_margin", "50"), "Premia 200%: marża DL"
        )
        if per_day < 0 or not Decimal(0) <= precision <= Decimal(100) or dl_margin < 0:
            raise BonusRulesError(
                "Premia 200%: weryfikacje i marża nieujemne, precision od 0 do 100."
            )
        double = DoubleBonusRule(
            months=tuple(sorted(set(months))),
            verifications_per_day=per_day,
            precision_pct=precision,
            dl_min_margin=dl_margin,
        )

    auto_assign_from: Optional[tuple[int, int]] = None
    if source.get("auto_assign_from"):
        auto_assign_from = _year_month(
            source["auto_assign_from"], "Automat przyznaje od"
        )

    rule_items: list[RuleItem] = []
    for item in source.get("rule_items") or ():
        if not isinstance(item, Mapping):
            raise BonusRulesError("Pozycje poza regułami: niepoprawny wpis.")
        user_id = _int(
            item.get("user_id"),
            "Pozycje poza regułami: osoba",
            low=1,
            high=2_147_483_647,
        )
        amount = _decimal(item.get("amount"), "Pozycje poza regułami: kwota")
        if not Decimal(0) < amount <= Decimal(1_000_000):
            raise BonusRulesError("Pozycje poza regułami: kwota od 0,01 do 1 000 000.")
        reason = str(item.get("reason") or "").strip()
        if not 3 <= len(reason) <= 200:
            raise BonusRulesError("Pozycje poza regułami: podaj powód (3–200 znaków).")
        rule_items.append(
            RuleItem(
                user_id=user_id,
                amount=money(amount),
                month=_year_month(item.get("month"), "Pozycje poza regułami: miesiąc"),
                reason=reason,
            )
        )

    return BonusRules(
        recruiter_tier_bounds=bounds,
        recruiter_tier_amounts=amounts,
        dl_percent=percent,
        monthly_hours=hours,
        eligible_business_days=days,
        currency=defaults.currency,
        extra_dl=tuple(extra),
        dl_hours=tuple(dl_hours),
        individual_recruiters=tuple(individual),
        automation_since=since,
        league_types=league_types,
        lookback_days=defaults.lookback_days,
        fixed_role_amounts=tuple(fixed),
        double_bonus=double,
        dl_default_hours=dl_default_hours,
        auto_assign_from=auto_assign_from,
        rule_items=tuple(rule_items),
    )


def rules_payload(rules: BonusRules) -> dict[str, Any]:
    """Postać JSON (zapis w ``app_settings`` i odpowiedź API)."""

    return {
        "recruiter_tier_bounds": [str(v) for v in rules.recruiter_tier_bounds],
        "recruiter_tier_amounts": [str(v) for v in rules.recruiter_tier_amounts],
        "dl_percent": str(rules.dl_percent),
        "monthly_hours": rules.monthly_hours,
        "dl_default_hours": rules.dl_default_hours,
        "eligible_business_days": rules.eligible_business_days,
        "currency": rules.currency,
        "extra_dl": [
            {
                "dl_user_id": r.dl_user_id,
                "recipient_user_id": r.recipient_user_id,
                "client_ids": list(r.client_ids),
            }
            for r in rules.extra_dl
        ],
        "dl_hours": [{"user_id": r.user_id, "hours": r.hours} for r in rules.dl_hours],
        "individual_recruiters": [
            {
                "user_id": r.user_id,
                "base_percent": str(r.base_percent),
                "step_percent": str(r.step_percent),
                "expert_percent": str(r.expert_percent),
            }
            for r in rules.individual_recruiters
        ],
        "automation_since": rules.automation_since.isoformat()
        if rules.automation_since
        else None,
        "league_types": list(rules.league_types),
        "fixed_role_amounts": [
            {"role": r.role, "amount": str(r.amount)} for r in rules.fixed_role_amounts
        ],
        "double_bonus": (
            {
                "months": [f"{y}-{m:02d}" for y, m in rules.double_bonus.months],
                "verifications_per_day": str(rules.double_bonus.verifications_per_day),
                "precision_pct": str(rules.double_bonus.precision_pct),
                "dl_min_margin": str(rules.double_bonus.dl_min_margin),
            }
            if rules.double_bonus
            else None
        ),
        "auto_assign_from": (
            f"{rules.auto_assign_from[0]}-{rules.auto_assign_from[1]:02d}"
            if rules.auto_assign_from
            else None
        ),
        "rule_items": [
            {
                "user_id": item.user_id,
                "amount": str(item.amount),
                "month": f"{item.month[0]}-{item.month[1]:02d}",
                "reason": item.reason,
            }
            for item in rules.rule_items
        ],
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
    "RuleItem",
    "AUTOMATION_STOPPED",
    "BonusRulesError",
    "DlHoursRule",
    "DoubleBonusRule",
    "FixedRoleAmount",
    "ExtraDlRule",
    "IndividualRecruiterRule",
    "automation_floor_for",
    "automation_since_change_error",
    "business_days_elapsed",
    "calendar_reach",
    "dl_bonus",
    "dl_hours_for",
    "individual_percent",
    "individual_recruiter_bonus",
    "individual_rule_for",
    "eligible_date",
    "extra_dl_recipient",
    "fixed_amount_for",
    "load_bonus_calendar",
    "load_rules",
    "money",
    "parse_rules",
    "payout_period",
    "recruiter_bonus",
    "recruiter_tier",
    "rule_amount",
    "rules_payload",
    "save_rules",
]
