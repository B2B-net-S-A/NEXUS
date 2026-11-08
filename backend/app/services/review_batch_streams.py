"""Dwa strumienie wysłanych CV a blokada porcji (audyt 08.11.2026, P4).

Blokada odcina ręczne wyszukiwanie, z którego szło 55% wysłanych CV, żeby
wypchnąć karty od systemu (18%). Baza to 14 dni przed włączeniem: 62 od systemu,
187 z ręcznych dodań, 341 razem (kopia z 06.11.2026). Kryterium zatrzymania:
wszystkie wysłane CV spadają o więcej niż 10% przez 2 pełne tygodnie.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.scheduling import business_today, local_day_start_utc

BASELINE_14D = {"system": 62, "manual": 187, "all": 341}
STOP_DROP = 0.10
STOP_WEEKS = 2

_FIRST_SENT = text(
    """
    WITH first_sent AS (
        SELECT job_id, candidate_id, min(moved_at) AS sent_at
        FROM candidate_stages
        WHERE stage = 'cv_sent'
        GROUP BY job_id, candidate_id
        HAVING min(moved_at) >= :since
    )
    SELECT f.sent_at, p.entry_source, p.entry_meta ->> 'found_via' AS found_via
    FROM first_sent f
    LEFT JOIN LATERAL (
        SELECT rp.entry_source, rp.entry_meta
        FROM recruitment_processes rp
        WHERE rp.job_id = f.job_id
          AND rp.candidate_id = f.candidate_id
          AND rp.voided_at IS NULL
          AND rp.opened_at <= f.sent_at
        ORDER BY rp.opened_at DESC
        LIMIT 1
    ) p ON true
    """
)


def _monday(day: date) -> date:
    return day - timedelta(days=day.weekday())


def stop_triggered(weeks: list[dict]) -> bool:
    """Ostatnie ``STOP_WEEKS`` pełnych tygodni: każdy poniżej bazy o ponad 10%."""
    limit = BASELINE_14D["all"] / 2 * (1 - STOP_DROP)
    complete = [week for week in weeks if week["complete"]]
    last = complete[-STOP_WEEKS:]
    return len(last) == STOP_WEEKS and all(week["all"] < limit for week in last)


async def weekly_streams(db: AsyncSession, *, now: datetime, weeks: int = 4) -> dict:
    tz = settings.BUSINESS_TZ
    zone = ZoneInfo(tz)
    this_week = _monday(business_today())
    first = this_week - timedelta(days=7 * weeks)
    since = local_day_start_utc(first, tz)
    buckets = {
        first + timedelta(days=7 * i): {
            "start": (first + timedelta(days=7 * i)).isoformat(),
            "system": 0,
            "manual": 0,
            "all": 0,
            "found_via": {},
            "complete": first + timedelta(days=7 * i) < this_week,
        }
        for i in range(weeks + 1)
    }
    rows = (await db.execute(_FIRST_SENT, {"since": since})).all()
    for sent_at, source, found_via in rows:
        bucket = buckets.get(_monday(sent_at.astimezone(zone).date()))
        if bucket is None:
            continue
        bucket["all"] += 1
        if source == "system":
            bucket["system"] += 1
        elif source == "added_manual":
            bucket["manual"] += 1
            key = found_via or "unknown"
            bucket["found_via"][key] = bucket["found_via"].get(key, 0) + 1
    ordered = [buckets[key] for key in sorted(buckets)]
    return {
        "weeks": ordered,
        "baseline_week": {key: value / 2 for key, value in BASELINE_14D.items()},
        "stop_drop_percent": int(STOP_DROP * 100),
        "stop_weeks": STOP_WEEKS,
        "stop": stop_triggered(ordered),
    }


def format_report(report: dict) -> str:
    base = report["baseline_week"]
    lines = [
        f"Baza na tydzień: system {base['system']:g}, ręczne {base['manual']:g}, "
        f"razem {base['all']:g}.",
        "Tydzień od     system  ręczne  razem  skąd ręczne",
    ]
    for week in report["weeks"]:
        via = ", ".join(f"{k} {v}" for k, v in sorted(week["found_via"].items()))
        mark = "" if week["complete"] else " (trwa)"
        lines.append(
            f"{week['start']}  {week['system']:>6}  {week['manual']:>6}  "
            f"{week['all']:>5}  {via}{mark}"
        )
    verdict = "TAK, zatrzymać" if report["stop"] else "nie"
    lines.append(
        f"Kryterium zatrzymania (spadek razem > {report['stop_drop_percent']}% przez "
        f"{report['stop_weeks']} pełne tygodnie): {verdict}."
    )
    return "\n".join(lines)
