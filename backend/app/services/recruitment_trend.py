"""Trend miesięczny kamieni milowych rekrutacji + konwersje lejka.

Zasila blok `trend` sekcji „Statystyki rekrutacji" na /dashboard (composite
`/api/dashboard/v2/recruitment-stats`). Liczy na tym samym CTE atrybucji co
panel KPI (`VERIFIER_ANCHORED_CTE`), więc suma miesiąca zgadza się z kaflami
i tabelą zespołu — celowo NIE na surowym widoku `analytics_first_milestones`,
który nie filtruje `kpi_eligible`.

Konwersje to stosunek ZLICZEŃ w tym samym oknie (period conversions), nie
kohorty — kandydat zweryfikowany w maju może mieć placement w lipcu, więc
przy małych mianownikach wartości mogą przekraczać 100%.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.kpi_engine import WARSAW
from app.services.kpi_panel import VERIFIER_ANCHORED_CTE

# Kubełki miesięczne w Europe/Warsaw (reached_at jest timestamptz w UTC —
# `AT TIME ZONE` przenosi na czas lokalny PRZED przycięciem do miesiąca,
# więc zdarzenie z 23:30 UTC ostatniego dnia miesiąca ląduje w następnym).
_TREND_SQL = text(
    VERIFIER_ANCHORED_CTE
    + """
    SELECT to_char(reached_at AT TIME ZONE 'Europe/Warsaw', 'YYYY-MM') AS mo,
           stage,
           count(*) AS cnt
    FROM credited
    WHERE reached_at >= :from_ts
    GROUP BY 1, 2
    """
)

_STAGE_FIELDS = {
    "verified": "weryfikacje",
    "cv_sent": "rekomendacje",
    "interview": "interview",
    "acceptance": "akceptacje",
    "hired": "placementy",
}

_MAX_MONTHS = 24


@dataclass(frozen=True)
class MonthlyTrendPoint:
    """Zliczenia kamieni milowych w jednym miesiącu kalendarzowym (Warsaw)."""

    month: str  # "YYYY-MM"
    weryfikacje: int
    rekomendacje: int
    interview: int
    akceptacje: int
    placementy: int


@dataclass(frozen=True)
class FunnelConversions:
    """Konwersje lejka w %, zaokrąglone do 0.1; None gdy mianownik == 0."""

    verified_to_recommendation_pct: Optional[float]
    recommendation_to_interview_pct: Optional[float]
    interview_to_acceptance_pct: Optional[float]
    acceptance_to_placement_pct: Optional[float]
    interview_to_placement_pct: Optional[float]
    overall_pct: Optional[float]  # weryfikacje → placementy


def _month_key(year: int, month: int) -> str:
    return f"{year:04d}-{month:02d}"


def _month_keys_window(now_warsaw: datetime, months: int) -> list[str]:
    """Klucze "YYYY-MM" od (months-1) miesięcy wstecz do bieżącego, rosnąco."""
    end_idx = now_warsaw.year * 12 + (now_warsaw.month - 1)
    keys = []
    for idx in range(end_idx - (months - 1), end_idx + 1):
        y, m0 = divmod(idx, 12)
        keys.append(_month_key(y, m0 + 1))
    return keys


def _window_start(now_warsaw: datetime, months: int) -> datetime:
    """Pierwszy dzień najstarszego miesiąca okna, 00:00 Warsaw."""
    idx = now_warsaw.year * 12 + (now_warsaw.month - 1) - (months - 1)
    y, m0 = divmod(idx, 12)
    return datetime(y, m0 + 1, 1, tzinfo=WARSAW)


async def monthly_milestone_trend(
    db: AsyncSession, *, months: int = 12, now: Optional[datetime] = None
) -> tuple[MonthlyTrendPoint, ...]:
    """Miesięczne zliczenia 5 kamieni milowych za ostatnie `months` miesięcy.

    Zawsze zwraca dokładnie `months` punktów (najstarszy → bieżący); miesiące
    bez aktywności mają zera — to PRAWDZIWE zera (okres istniał, źródło
    odpowiedziało), w odróżnieniu od awarii źródła, którą obsługuje warstwa
    quality composite'u.
    """
    months = max(1, min(_MAX_MONTHS, months))
    if now is None:
        now = datetime.now(WARSAW)
    now_w = now.astimezone(WARSAW)

    rows = (
        (await db.execute(_TREND_SQL, {"from_ts": _window_start(now_w, months)}))
        .mappings()
        .all()
    )

    by_month: dict[str, dict[str, int]] = {}
    for r in rows:
        field = _STAGE_FIELDS.get(r["stage"])
        if field is None:
            continue
        by_month.setdefault(r["mo"], {})[field] = int(r["cnt"])

    points = []
    for key in _month_keys_window(now_w, months):
        counts = by_month.get(key, {})
        points.append(
            MonthlyTrendPoint(
                month=key,
                weryfikacje=counts.get("weryfikacje", 0),
                rekomendacje=counts.get("rekomendacje", 0),
                interview=counts.get("interview", 0),
                akceptacje=counts.get("akceptacje", 0),
                placementy=counts.get("placementy", 0),
            )
        )
    return tuple(points)


def _ratio_pct(numerator: int, denominator: int) -> Optional[float]:
    if denominator <= 0:
        return None
    return round(100.0 * numerator / denominator, 1)


def funnel_conversions(
    *,
    weryfikacje: int,
    rekomendacje: int,
    interview: int,
    akceptacje: int,
    placementy: int,
) -> FunnelConversions:
    """Konwersje lejka z sum okresu (czysta funkcja, bez DB).

    Mianownik 0 → None („—" na froncie) — nigdy 0.0, bo „brak próby" to nie
    to samo co „0% skuteczności".
    """
    return FunnelConversions(
        verified_to_recommendation_pct=_ratio_pct(rekomendacje, weryfikacje),
        recommendation_to_interview_pct=_ratio_pct(interview, rekomendacje),
        interview_to_acceptance_pct=_ratio_pct(akceptacje, interview),
        acceptance_to_placement_pct=_ratio_pct(placementy, akceptacje),
        interview_to_placement_pct=_ratio_pct(placementy, interview),
        overall_pct=_ratio_pct(placementy, weryfikacje),
    )


__all__ = [
    "MonthlyTrendPoint",
    "FunnelConversions",
    "monthly_milestone_trend",
    "funnel_conversions",
]
