"""Widok Zespół w /insights: ludzie, rekrutacje bez ruchu i sygnały „Do uwagi".

Przebudowa Insights z 24.09.2026 (makiety: widok Zespół). Trzy rzeczy, które
łatwo cofnąć:

* **Tabela ludzi liczy się tą samą atrybucją co wyścigi i „Mój miesiąc”**
  (`kpi_team.compute_team_panel`, verifier-anchored). Rekruter porównujący
  swój wiersz z kaflem „Mój miesiąc” i z wyścigiem placementów musi zobaczyć
  tę samą liczbę — trzecia definicja placementu na jednym ekranie czyta się
  jak błąd.
* **Porównanie z poprzednim okresem idzie po TYM SAMYM odcinku.** 24 dni
  września przeciw całemu sierpniowi dałyby spadek, którego nie ma.
* **„Do uwagi” oddaje tylko sygnały ponad próg.** Pusta lista znaczy „nic nie
  wymaga uwagi” — liczby poniżej progu nie są tu pokazywane jako zera.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.periods import Period
from app.services.kpi_team import TeamPanelResult, compute_team_panel
from app.services.order_burn_rate import workdays_between

# Rekrutacja opublikowana bez żadnego ruchu w pipeline od tylu dni.
STALE_JOB_DAYS = 14
# Precyzja rekomendacji (30 dni) poniżej tej wartości = sygnał dla lidera.
LOW_PRECISION_PCT = 50.0


def previous_matching_window(
    period: Period, now: datetime
) -> tuple[datetime, datetime]:
    """Poprzedni okres tej samej długości, przycięty do upłyniętej części.

    Okres w toku (koniec w przyszłości) porównujemy z tym samym odcinkiem
    poprzedniego okresu: 1–24 września z 1–24 sierpnia. Okres zamknięty — z
    całym poprzednim okresem tej samej długości kalendarzowej.
    """
    start, end = period.start, period.end
    if period.kind.value == "month":
        prev_month_last = start - timedelta(days=1)
        prev_start = start.replace(
            year=prev_month_last.year, month=prev_month_last.month, day=1
        )
    elif period.kind.value == "quarter":
        month = start.month - 3
        year = start.year
        if month < 1:
            month += 12
            year -= 1
        prev_start = start.replace(year=year, month=month, day=1)
    elif period.kind.value == "year":
        prev_start = start.replace(year=start.year - 1)
    else:
        prev_start = start - (end - start)
    if end > now:
        # Te same DNI kalendarzowe (1–24 września → 1–24 sierpnia), jak
        # `previousSameStretch` we froncie — kafle i tabela porównują to samo
        # okno. Koniec nigdy nie wchodzi w bieżący okres: 31 marca porównuje
        # się z całym lutym, nie z lutym i trzema dniami marca.
        days = max((now.date() - start.date()).days + 1, 0)
        return prev_start, min(prev_start + timedelta(days=days), start)
    return prev_start, start


def workdays_in_window(start: datetime, end: datetime, today: date) -> int:
    """Dni robocze okna [start, end) do dziś włącznie (Pon–Pt bez świąt)."""
    last = min((end - timedelta(microseconds=1)).date(), today)
    return workdays_between(start.date(), last)


@dataclass(frozen=True)
class TeamPeople:
    current: TeamPanelResult
    previous: TeamPanelResult
    workdays: int


async def team_people(
    db: AsyncSession, period: Period, *, now: datetime, today: date
) -> TeamPeople:
    current = await compute_team_panel(
        db, bounds=(period.start, period.end), period_label=period.kind.value, now=now
    )
    prev_start, prev_end = previous_matching_window(period, now)
    previous = await compute_team_panel(
        db, bounds=(prev_start, prev_end), period_label="previous", now=now
    )
    return TeamPeople(
        current=current,
        previous=previous,
        workdays=workdays_in_window(period.start, period.end, today),
    )


def people_payload(people: TeamPeople) -> dict:
    previous = {r.user_id: r for r in people.previous.rows}
    rows = []
    for r in people.current.rows:
        prev = previous.get(r.user_id)
        rows.append(
            {
                "user_id": r.user_id,
                "name": r.name,
                "role": r.role,
                "is_active": r.is_active,
                "verifications": r.weryfikacje,
                "recommendations": r.rekomendacje,
                "interviews": r.interview,
                "placements": r.placementy,
                "previous_placements": prev.placementy if prev else 0,
                "verifications_per_workday": (
                    round(r.weryfikacje / people.workdays, 1)
                    if people.workdays
                    else None
                ),
                # Kohorta: z par zweryfikowanych w 30 dniach, ile ma „CV wysłane"
                # (≤ 100%). None = mniej niż 5 weryfikacji, „nie policzono".
                "precision_pct": r.precision_pct,
            }
        )
    rows.sort(key=lambda row: (-row["placements"], -row["verifications"], row["name"]))
    totals = people.current.totals
    prev_totals = people.previous.totals
    return {
        "rows": rows,
        "workdays": people.workdays,
        "precision_target_pct": people.current.precision_target_pct,
        "low_precision_pct": LOW_PRECISION_PCT,
        "totals": {
            "verifications": totals.weryfikacje,
            "recommendations": totals.rekomendacje,
            "interviews": totals.interview,
            "placements": totals.placementy,
            "precision_pct": totals.precision_pct,
            "people": totals.people,
            "unattributed": totals.unattributed,
        },
        "previous_totals": {
            "verifications": prev_totals.weryfikacje,
            "recommendations": prev_totals.rekomendacje,
            "interviews": prev_totals.interview,
            "placements": prev_totals.placementy,
        },
    }


_STALE_JOBS_SQL = text(
    """
    SELECT j.id AS job_id,
           j.title,
           j.client_id,
           COALESCE(NULLIF(c.display_name, ''), c.name) AS client_name,
           j.recruiter_id,
           u.name AS recruiter_name,
           COALESCE(ls.last_move, j.opened_at, j.created_at) AS last_move_at,
           COALESCE(ls.people, 0) AS people
    FROM jobs j
    JOIN clients c
      ON c.id = j.client_id
     AND c.hidden IS NOT TRUE
     AND c.deleted_at IS NULL
    LEFT JOIN users u ON u.id = j.recruiter_id
    LEFT JOIN LATERAL (
        SELECT max(cs.moved_at) AS last_move,
               count(DISTINCT cs.candidate_id) AS people
        FROM candidate_stages cs
        WHERE cs.job_id = j.id
    ) ls ON TRUE
    WHERE j.status::text = 'published'
      AND COALESCE(ls.last_move, j.opened_at, j.created_at) < :cutoff
    ORDER BY COALESCE(ls.last_move, j.opened_at, j.created_at) ASC, j.id ASC
    """
)


async def stale_jobs(
    db: AsyncSession, *, now: datetime, days: int = STALE_JOB_DAYS
) -> list[dict]:
    """Opublikowane rekrutacje bez ruchu w pipeline od ``days`` dni.

    Rekrutacja bez żadnego etapu liczy się od daty otwarcia — pusta tablica
    od trzech tygodni to ten sam problem co tablica, która stanęła.
    """
    rows = (
        (await db.execute(_STALE_JOBS_SQL, {"cutoff": now - timedelta(days=days)}))
        .mappings()
        .all()
    )
    out = []
    for r in rows:
        last: Optional[datetime] = r["last_move_at"]
        out.append(
            {
                "job_id": int(r["job_id"]),
                "title": r["title"],
                "client_id": r["client_id"],
                "client_name": r["client_name"],
                "recruiter_id": r["recruiter_id"],
                "recruiter_name": r["recruiter_name"],
                "last_move_at": last.isoformat() if last else None,
                "days_without_move": (now - last).days if last else None,
                "people": int(r["people"] or 0),
            }
        )
    return out


__all__ = [
    "LOW_PRECISION_PCT",
    "STALE_JOB_DAYS",
    "people_payload",
    "previous_matching_window",
    "stale_jobs",
    "team_people",
    "workdays_in_window",
]
