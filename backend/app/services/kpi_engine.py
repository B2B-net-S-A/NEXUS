"""KPI Coach — silnik obliczeń.

Czysta biblioteka bez HTTP/DI. Input: `AsyncSession` + `User`. Output:
listy `KpiResult` (frozen dataclass) oraz helpery czasowe używane też
przez scheduler/nudger.

Strefa czasowa: `Europe/Warsaw`. Wszystkie zakresy czasu są liczone
lokalnie (dni kalendarzowe, tydzień pon-niedz wg ISO, miesiąc kalendarzowy).
Zapytania do DB działają w UTC (TIMESTAMPTZ) i są porównywane z granicami
Warsaw po stronie SQL — aware datetime załatwia to za nas.

Dzień roboczy dla `expected_progress_ratio`: 09:00-17:30 local time
(8.5h). Poza tym oknem ratio = 0 (rano) lub 1 (wieczorem). Dla tygodnia
skalowanie idzie po dniach pon-pt i w obrębie dnia.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import Literal, Optional
from zoneinfo import ZoneInfo

from sqlalchemy import and_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.kpi_target import KpiRoleDefault, UserKpiTarget
from app.models.user import User, UserRole
from app.core.config import settings
from app.services.kpi_catalog import KPI_CATALOG, KpiDef, KpiPeriod

WARSAW = ZoneInfo("Europe/Warsaw")

# Dzień roboczy — początek i koniec (local Warsaw time).
WORKDAY_START = time(9, 0)
WORKDAY_END = time(17, 30)
# 8.5h w minutach, używane przy skalowaniu ratio.
_WORKDAY_MINUTES = (WORKDAY_END.hour * 60 + WORKDAY_END.minute) - (
    WORKDAY_START.hour * 60 + WORKDAY_START.minute
)

# Tydzień roboczy (pon-pt), używany przy skalowaniu tygodniowym.
_WORKDAYS_PER_WEEK = 5


KpiState = Literal["on_track", "ahead", "behind", "hit", "missed"]


@dataclass(frozen=True)
class KpiResult:
    """Wynik oceny pojedynczego KPI dla konkretnego usera w konkretnym
    momencie czasu."""

    kpi_id: str
    period: KpiPeriod
    title_pl: str
    description_pl: str
    target: int
    current: int
    progress_pct: float  # 0.0-100.0+ (może przekroczyć 100 przy over-hit)
    state: KpiState
    deadline_hours_left: float


# ── Granice czasu ────────────────────────────────────────────────────────


def _as_warsaw(now: datetime) -> datetime:
    """Konwersja do Europe/Warsaw. Akceptuje aware datetime w dowolnym tz;
    naive traktowane jako już-Warsaw (odpowiedzialność wywołującego)."""
    if now.tzinfo is None:
        return now.replace(tzinfo=WARSAW)
    return now.astimezone(WARSAW)


def period_bounds(period: KpiPeriod, now: datetime) -> tuple[datetime, datetime]:
    """Zwraca (start, end) okna okresu w Europe/Warsaw.

    start — inkluzywnie (np. 00:00 dnia / poniedziałek 00:00 / 1. dzień
    miesiąca 00:00).
    end — exclusive (czyli "teraz"). Zapytania używają `>= start AND < end`.
    """
    now_w = _as_warsaw(now)

    if period == KpiPeriod.day:
        start = now_w.replace(hour=0, minute=0, second=0, microsecond=0)
    elif period == KpiPeriod.week:
        # weekday() = 0 dla poniedziałku
        monday = now_w - timedelta(days=now_w.weekday())
        start = monday.replace(hour=0, minute=0, second=0, microsecond=0)
    elif period == KpiPeriod.month:
        start = now_w.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    else:  # pragma: no cover — exhaustive
        raise ValueError(f"Unknown period: {period}")

    return start, now_w


def period_bucket_label(period: KpiPeriod, now: datetime) -> str:
    """Deduplikacyjny klucz okresu.

    - day:   "YYYY-MM-DD"
    - week:  "YYYY-Www" (ISO week number, pad 2)
    - month: "YYYY-MM"
    """
    now_w = _as_warsaw(now)
    if period == KpiPeriod.day:
        return now_w.strftime("%Y-%m-%d")
    if period == KpiPeriod.week:
        iso_year, iso_week, _ = now_w.isocalendar()
        return f"{iso_year}-W{iso_week:02d}"
    if period == KpiPeriod.month:
        return now_w.strftime("%Y-%m")
    raise ValueError(f"Unknown period: {period}")  # pragma: no cover


def expected_progress_ratio(period: KpiPeriod, now: datetime) -> float:
    """Jakie % target powinno być zrobione w tym momencie.

    - day: 0% przed 9:00, 100% po 17:30, liniowo w środku.
    - week: (zakończone_dni_robocze * 1.0 + bieżący_ratio_dnia) / 5; cap 1.0
      dla weekendu.
    - month: (day_of_month - 1 + ratio_dnia) / days_in_month.
    """
    now_w = _as_warsaw(now)

    def _intraday_ratio(n: datetime) -> float:
        """Ratio dnia roboczego w chwili `n`."""
        t = n.time()
        if t <= WORKDAY_START:
            return 0.0
        if t >= WORKDAY_END:
            return 1.0
        minutes = (t.hour * 60 + t.minute) - (
            WORKDAY_START.hour * 60 + WORKDAY_START.minute
        )
        return minutes / _WORKDAY_MINUTES

    if period == KpiPeriod.day:
        return _intraday_ratio(now_w)

    if period == KpiPeriod.week:
        weekday = now_w.weekday()  # 0=pon, 6=niedz
        if weekday >= _WORKDAYS_PER_WEEK:
            return 1.0  # weekend — okres praktycznie "zamknięty"
        completed_days = weekday  # pon=0, wt=1 (czyli 1 dzień się skończył)
        today_ratio = _intraday_ratio(now_w)
        return min(1.0, (completed_days + today_ratio) / _WORKDAYS_PER_WEEK)

    if period == KpiPeriod.month:
        # Ile dni w miesiącu
        if now_w.month == 12:
            next_month = now_w.replace(year=now_w.year + 1, month=1, day=1)
        else:
            next_month = now_w.replace(month=now_w.month + 1, day=1)
        days_in_month = (
            next_month.replace(hour=0, minute=0, second=0, microsecond=0)
            - now_w.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        ).days
        completed_days = now_w.day - 1
        today_ratio = _intraday_ratio(now_w)
        return min(1.0, (completed_days + today_ratio) / max(days_in_month, 1))

    raise ValueError(f"Unknown period: {period}")  # pragma: no cover


def derive_state(*, current: int, target: int, expected_ratio: float) -> KpiState:
    """Mapuje (current, target, expected_ratio) na jeden z 5 stanów.

    Zasady:
    - target<=0 → "hit" (KPI nie dotyczy tej roli, nie spamujemy nudge'ami).
    - current >= target → "hit" (wyrobione na 100%+, bez względu na moment).
    - expected_ratio >= 1.0 i current < target → "missed" (okres skończony,
      nie wyrobił).
    - expected_ratio == 0.0 → "on_track" (przed dniem roboczym, nic nie
      wytykać).
    - w przeciwnym razie porównujemy `current` z `target * expected_ratio`
      (expected_count) z tolerancją ±20%.
    """
    if target <= 0:
        return "hit"
    if current >= target:
        return "hit"
    if expected_ratio >= 1.0:
        return "missed"
    if expected_ratio <= 0.0:
        return "on_track"

    expected_count = target * expected_ratio
    # ±20% wokół oczekiwanej wartości — akceptowalny korytarz on_track.
    low = expected_count * 0.8
    high = expected_count * 1.2
    if current < low:
        return "behind"
    if current >= high:
        return "ahead"
    return "on_track"


# ── DB helpers ──────────────────────────────────────────────────────────


_CANONICAL_KPI_COUNT_SQL = {
    # Legacy identifier retained for the two-release adapter.  Its metric is
    # now the canonical Power Calling definition: completed CloudTalk calls.
    "daily_activity_count": text(
        """
        SELECT count(*)
        FROM calls
        WHERE user_id = :user_id
          AND status = 'completed'
          AND coalesce(started_at, created_at) >= :since
          AND coalesce(started_at, created_at) < :until
        """
    ),
    "daily_new_candidates": text(
        """
        SELECT count(*)
        FROM candidates
        WHERE created_by = :user_id
          AND created_at >= :since
          AND created_at < :until
        """
    ),
    "weekly_cvs_sent": text(
        """
        SELECT count(*)
        FROM analytics_first_candidate_milestones
        WHERE credited_user_id = :user_id
          AND stage = 'cv_sent'
          AND reached_at >= :since
          AND reached_at < :until
        """
    ),
    # Kept under its legacy id for response compatibility; this is no longer a
    # UserActivity screening counter.  It is the first verified milestone.
    "weekly_screenings": text(
        """
        SELECT count(*)
        FROM analytics_first_candidate_milestones
        WHERE credited_user_id = :user_id
          AND stage = 'verified'
          AND reached_at >= :since
          AND reached_at < :until
        """
    ),
    "monthly_placements": text(
        """
        SELECT count(*)
        FROM analytics_first_candidate_milestones
        WHERE credited_user_id = :user_id
          AND stage = 'hired'
          AND reached_at >= :since
          AND reached_at < :until
        """
    ),
}


async def resolve_target(db: AsyncSession, *, user: User, kpi_def: KpiDef) -> int:
    """Zwraca efektywny target dla (user, kpi_def):
    user_kpi_targets → kpi_role_defaults → kpi_def.default_targets → 0.
    """
    canonical_target_ids = {
        "daily_activity_count": "calls_daily",
        "daily_new_candidates": "cv_added_daily",
        "weekly_screenings": "verifications_daily",
        "monthly_placements": "placements_monthly",
    }
    canonical_id = canonical_target_ids.get(kpi_def.kpi_id, kpi_def.kpi_id)
    # `weekly_screenings` used to be a weekly target.  Its metric is daily in
    # KPI Coach v2, so treating an old override (for example 7/week) as 7/day
    # would silently change expectations.  Only an explicit canonical daily
    # override/default may win for this KPI.
    target_ids = (
        (canonical_id,)
        if kpi_def.kpi_id == "weekly_screenings"
        else tuple(dict.fromkeys((canonical_id, kpi_def.kpi_id)))
    )

    # 1) Per-user override. Canonical v2 key wins over a legacy alias.
    for target_id in target_ids:
        row = await db.scalar(
            select(UserKpiTarget.target_value).where(
                and_(
                    UserKpiTarget.user_id == user.id,
                    UserKpiTarget.kpi_id == target_id,
                )
            )
        )
        if row is not None:
            return int(row)

    # 2) Primary-role default. Secondary roles grant views, not targets.
    for target_id in target_ids:
        row = await db.scalar(
            select(KpiRoleDefault.target_value).where(
                and_(
                    KpiRoleDefault.role == user.role,
                    KpiRoleDefault.kpi_id == target_id,
                )
            )
        )
        if row is not None:
            return int(row)

    # 3) Runtime-configurable canonical fallbacks, then code catalog.
    if canonical_id == "calls_daily":
        return settings.POWERCALLING_DAILY_TARGET
    if canonical_id == "verifications_daily":
        return settings.VERIFICATIONS_DAILY_TARGET
    return int(kpi_def.default_targets.get(user.role, 0))


async def count_canonical_kpi_in_window(
    db: AsyncSession,
    *,
    kpi_id: str,
    user_id: int,
    since: datetime,
    until: datetime,
) -> int:
    """Count a KPI from canonical ATS entities, never ``UserActivity``."""

    query = _CANONICAL_KPI_COUNT_SQL.get(kpi_id)
    if query is None:
        return 0
    result = await db.scalar(
        query,
        {"user_id": user_id, "since": since, "until": until},
    )
    return int(result or 0)


def _hours_until_period_end(period: KpiPeriod, now: datetime) -> float:
    """Ile godzin zostało do końca bieżącego okresu w Warsaw."""
    now_w = _as_warsaw(now)
    if period == KpiPeriod.day:
        end = now_w.replace(hour=23, minute=59, second=0, microsecond=0)
    elif period == KpiPeriod.week:
        # Koniec piątku 17:30 jako "business week end"
        sunday_end = now_w + timedelta(days=(6 - now_w.weekday()))
        end = sunday_end.replace(hour=23, minute=59, second=0, microsecond=0)
    elif period == KpiPeriod.month:
        if now_w.month == 12:
            first_next = now_w.replace(year=now_w.year + 1, month=1, day=1)
        else:
            first_next = now_w.replace(month=now_w.month + 1, day=1)
        end = (first_next - timedelta(seconds=1)).replace(tzinfo=WARSAW)
    else:  # pragma: no cover
        raise ValueError(f"Unknown period: {period}")
    return max(0.0, (end - now_w).total_seconds() / 3600.0)


# ── Główne API ──────────────────────────────────────────────────────────


async def evaluate_user_kpis(
    db: AsyncSession, *, user: User, now: Optional[datetime] = None
) -> list[KpiResult]:
    """Oblicza wszystkie KPI z katalogu dla usera w momencie `now`.

    Dla roli bez default_targets dla danego KPI (i bez overrides w DB) —
    target=0, więc KPI ma state="hit" ale na liście i tak będzie widoczne.
    Wywołujący filtruje po `target > 0` jeśli nie chce pokazywać irrelevant
    KPI.
    """
    if now is None:
        now = datetime.now(WARSAW)

    results: list[KpiResult] = []
    for kpi_def in KPI_CATALOG:
        target = await resolve_target(db, user=user, kpi_def=kpi_def)
        start, end = period_bounds(kpi_def.period, now)
        calls_unavailable = kpi_def.kpi_id == "daily_activity_count" and not (
            settings.CLOUDTALK_ENABLED
            and settings.CLOUDTALK_API_KEY_ID
            and settings.CLOUDTALK_API_KEY_SECRET
            and settings.CLOUDTALK_WEBHOOK_SECRET
        )
        # The legacy DTO cannot represent an unavailable numeric value.  A
        # zero target hides this row and prevents a false "0 calls" nudge;
        # analytics v1 exposes the explicit unavailable quality state.
        if calls_unavailable:
            target = 0
            current = 0
        else:
            current = await count_canonical_kpi_in_window(
                db,
                kpi_id=kpi_def.kpi_id,
                user_id=user.id,
                since=start,
                until=end,
            )
        ratio = expected_progress_ratio(kpi_def.period, now)
        state = derive_state(current=current, target=target, expected_ratio=ratio)
        progress = (current / target * 100.0) if target > 0 else 0.0
        hours_left = _hours_until_period_end(kpi_def.period, now)

        results.append(
            KpiResult(
                kpi_id=kpi_def.kpi_id,
                period=kpi_def.period,
                title_pl=kpi_def.title_pl,
                description_pl=kpi_def.description_pl,
                target=target,
                current=current,
                progress_pct=progress,
                state=state,
                deadline_hours_left=hours_left,
            )
        )

    return results


__all__ = [
    "KpiResult",
    "KpiState",
    "WARSAW",
    "count_canonical_kpi_in_window",
    "derive_state",
    "evaluate_user_kpis",
    "expected_progress_ratio",
    "period_bounds",
    "period_bucket_label",
    "resolve_target",
]


# ── Compat re-export (dla relatywnie niezależnych importów) ─────────────
def _unused_role_reference() -> UserRole:  # pragma: no cover
    """Trzyma `UserRole` w imporcie — silnik nie używa go bezpośrednio,
    ale dzięki temu mypy widzi kompletność typów przy refactorach."""
    return UserRole.recruiter
