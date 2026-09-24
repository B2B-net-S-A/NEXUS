"""Praktykant — czyste reguły listy telefonów (0371).

Bez bazy: reguły z ``app_settings``, dni robocze programu, braki w profilu,
dopasowanie kandydata do rekrutacji i przeliczenie minimalnej stawki. Moduły
z bazą (``trainee_call_list``, ``trainee_program``) składają te funkcje.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Iterable, Mapping, Optional

from app.core.scheduling import is_business_day
from app.core.work_time import HOURS_PER_MD_DEC, HOURS_PER_MONTH_DEC

RULES_KEY = "trainee_call_rules"
POOL_STATS_KEY = "trainee_call_pool_stats"

DEFAULT_RULES: dict[str, Any] = {
    "min_fits": 2,
    "window_months": 18,
    "rate_stale_months": 6,
    "verified_recently_days": 90,
    "process_active_days": 30,
    "my_people_contact_days": 30,
    "trainee_recall_days": 60,
    "missing_rate": True,
    "missing_availability": True,
    "missing_work_mode": True,
    "missing_consents": True,
    "missing_b2b": True,
    "missing_work_time": True,
}
_INT_BOUNDS: dict[str, tuple[int, int]] = {
    "min_fits": (1, 20),
    "window_months": (1, 36),
    "rate_stale_months": (1, 36),
    "verified_recently_days": (1, 365),
    "process_active_days": (1, 180),
    "my_people_contact_days": (1, 180),
    "trainee_recall_days": (1, 365),
}

#: Kandydat „pasuje” do rekrutacji, gdy pokrywa tyle jej must-have.
MIN_COVERAGE = 0.6
#: Ponowna próba po „Nie odbiera”.
RETRY_AFTER = timedelta(hours=3)
#: Maks. rozsądna stawka godzinowa (lustro notatek) — reszta to pomyłka jednostki.
MAX_HOURLY_PLN = Decimal("2000")

MISSING_CODES = (
    "rate_missing",
    "rate_stale",
    "b2b",
    "work_time",
    "work_mode",
    "below_min_consent",
    "office_consent",
    "availability",
)


def normalize_rules(raw: Optional[Mapping[str, Any]]) -> dict[str, Any]:
    """Reguły z bazy albo z formularza → pełny słownik w granicach."""
    rules = dict(DEFAULT_RULES)
    for key, value in (raw or {}).items():
        if key not in DEFAULT_RULES:
            continue
        default = DEFAULT_RULES[key]
        if isinstance(default, bool):
            if isinstance(value, bool):
                rules[key] = value
            continue
        if isinstance(value, bool):
            continue
        try:
            number = int(value)
        except (TypeError, ValueError):
            continue
        low, high = _INT_BOUNDS[key]
        rules[key] = min(max(number, low), high)
    return rules


# ── Dni robocze programu ──────────────────────────────────────────────────


def is_workday(day: date) -> bool:
    return is_business_day(datetime(day.year, day.month, day.day, 12))


def next_workday(day: date) -> date:
    while not is_workday(day):
        day += timedelta(days=1)
    return day


def workdays_between(start: date, end: date) -> int:
    """Dni robocze w ``[start, end]`` (0, gdy ``end < start``)."""
    if end < start:
        return 0
    count = 0
    day = start
    while day <= end:
        if is_workday(day):
            count += 1
        day += timedelta(days=1)
    return count


def program_end_date(start: date, total_workdays: int) -> date:
    """Ostatni dzień roboczy programu (``total_workdays``-ty od startu)."""
    day = next_workday(start)
    counted = 1
    while counted < max(total_workdays, 1):
        day += timedelta(days=1)
        if is_workday(day):
            counted += 1
    return day


def workdays_left(today: date, end: date) -> int:
    """Dni robocze po dziś do końca programu włącznie."""
    return workdays_between(today + timedelta(days=1), end)


# ── Braki w profilu ───────────────────────────────────────────────────────


def _months_ago(now: datetime, months: int) -> datetime:
    return now - timedelta(days=round(months * 30.44))


def missing_codes(row: Any, rules: Mapping[str, Any], *, now: datetime) -> list[str]:
    """Czego brakuje w profilu — powód telefonu i kryterium puli.

    ``row`` to wiersz albo obiekt kandydata z kolumnami profilu.
    """
    out: list[str] = []
    if rules.get("missing_rate", True):
        rate = getattr(row, "expected_rate_hourly", None)
        updated = getattr(row, "profile_rate_updated_at", None)
        if rate is None:
            out.append("rate_missing")
        elif updated is None or updated < _months_ago(
            now, int(rules.get("rate_stale_months", 6))
        ):
            out.append("rate_stale")
    if rules.get("missing_b2b", True) and getattr(row, "b2b_willingness", None) is None:
        out.append("b2b")
    if (
        rules.get("missing_work_time", True)
        and getattr(row, "work_time_preference", None) is None
    ):
        out.append("work_time")
    if rules.get("missing_work_mode", True):
        modes = getattr(row, "remote_modes", None)
        if modes is None:
            prefs = getattr(row, "preferences", None) or {}
            modes = prefs.get("remote_modes") if isinstance(prefs, dict) else None
        if not modes and getattr(row, "max_onsite_days_per_week", None) is None:
            out.append("work_mode")
    if rules.get("missing_consents", True):
        if getattr(row, "accepts_below_min_rate", None) is None:
            out.append("below_min_consent")
        if getattr(row, "accepts_more_office_days", None) is None:
            out.append("office_consent")
    if rules.get("missing_availability", True):
        status = getattr(row, "availability_status", None)
        status = getattr(status, "value", status)
        if (status in (None, "unknown")) and getattr(
            row, "availability_date", None
        ) is None:
            out.append("availability")
    return out


# ── Popyt: dopasowanie kandydata do rekrutacji ────────────────────────────


@dataclass(frozen=True)
class DemandJob:
    id: int
    skills: frozenset[str]
    competence_category_id: Optional[int]
    is_open: bool


@dataclass(frozen=True)
class Demand:
    fits: int
    open_fits: int
    stack: tuple[str, ...]
    job_ids: tuple[int, ...]


def build_index(jobs: Iterable[DemandJob]) -> dict[str, list[DemandJob]]:
    index: dict[str, list[DemandJob]] = {}
    for job in jobs:
        if not job.skills:
            continue
        for skill in job.skills:
            index.setdefault(skill, []).append(job)
    return index


def job_fits(
    candidate_skills: frozenset[str],
    candidate_cc: Optional[int],
    job: DemandJob,
) -> bool:
    """Ta sama kategoria (gdy obie znane) i pokrycie ≥ 60% must-have."""
    if not job.skills or not candidate_skills:
        return False
    if (
        candidate_cc is not None
        and job.competence_category_id is not None
        and candidate_cc != job.competence_category_id
    ):
        return False
    covered = len(job.skills & candidate_skills)
    return covered >= 1 and covered / len(job.skills) >= MIN_COVERAGE


def demand_for(
    candidate_skills: frozenset[str],
    candidate_cc: Optional[int],
    index: Mapping[str, list[DemandJob]],
) -> Demand:
    seen: dict[int, DemandJob] = {}
    for skill in candidate_skills:
        for job in index.get(skill, ()):
            seen[job.id] = job
    matched = [
        job for job in seen.values() if job_fits(candidate_skills, candidate_cc, job)
    ]
    counts: dict[str, int] = {}
    for job in matched:
        for skill in job.skills & candidate_skills:
            counts[skill] = counts.get(skill, 0) + 1
    stack = tuple(
        name for name, _ in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:4]
    )
    return Demand(
        fits=len(matched),
        open_fits=sum(1 for job in matched if job.is_open),
        stack=stack,
        job_ids=tuple(sorted(job.id for job in matched)),
    )


def rank_key(candidate_id: int, demand: Demand, missing: list[str]) -> tuple:
    """Najpierw otwarte rekrutacje, potem liczba dopasowań, potem luki."""
    return (-demand.open_fits, -demand.fits, -len(missing), -candidate_id)


# ── Stawka z rozmowy ──────────────────────────────────────────────────────

RATE_UNITS = ("hour", "day", "month")


def hourly_min_rate(value: Any, unit: str) -> Decimal:
    """Minimalna stawka B2B netto z formularza → PLN/h (MD ÷ 8, miesiąc ÷ 168).

    ``ValueError`` z polskim komunikatem dla wartości spoza zakresu.
    """
    if unit not in RATE_UNITS:
        raise ValueError("Nieznana jednostka stawki")
    if isinstance(value, bool):
        raise ValueError("Podaj stawkę liczbą")
    try:
        amount = Decimal(str(value))
    except (ArithmeticError, ValueError) as exc:
        raise ValueError("Podaj stawkę liczbą") from exc
    if not amount.is_finite() or amount <= 0:
        raise ValueError("Stawka musi być większa od zera")
    divisor = {
        "hour": Decimal("1"),
        "day": HOURS_PER_MD_DEC,
        "month": HOURS_PER_MONTH_DEC,
    }[unit]
    hourly = (amount / divisor).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if hourly <= 0 or hourly >= MAX_HOURLY_PLN:
        raise ValueError("Stawka poza rozsądnym zakresem — sprawdź jednostkę")
    return hourly


def answered_pct(connected: int, no_answer: int) -> Optional[float]:
    total = connected + no_answer
    if total <= 0:
        return None
    return round(connected * 100 / total, 1)
