"""Placementy per klient i miesiąc — przed 12.10.2026 wyłącznie z DynaReportera.

Decyzja Artura 18.10.2026: przed 12.10.2026 statystyki nie biorą ruchów
Tablicy (import z Traffita). Podział placementów na klientów:

* od 12.10.2026 — pary Tablicy (`analytics_first_milestones`, definicja D2),
* 1.01–11.10.2026 — placementy z klientem z DynaReportera
  (`dr_placement_details` × `dr_clients`),
* przed 2026 — miesięczne placementy klientów z raportu Rady DynaReportera
  (`dr_board_placement_clients`, dzień = pierwszy dzień miesiąca).

Nazwę klienta DynaReportera łączymy z klientem NEXUS-a po nazwie albo nazwie
wyświetlanej (bez wielkości liter), żeby ten sam klient z obu źródeł był jednym
wycinkiem; bez dopasowania zostaje nazwa z DynaReportera i `client_id = None`.
Suma bywa inna niż „Suma placementów” (ta przed 12.10 liczy tygodniowe wpisy
rekruterów) — konsumenci podają ją osobno (`client_placements`).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Optional
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scheduling import DEFAULT_TZ
from app.services import competition_history


@dataclass(frozen=True)
class ClientPlacements:
    month: date
    client_id: Optional[int]
    client_name: Optional[str]
    # Para Tablicy, której rekrutacji nie ma już w bazie (luka w danych).
    job_missing: bool
    count: int


_SQL = """
    WITH board_pairs AS (
        SELECT date_trunc(
                   'month', fm.first_reached_at AT TIME ZONE 'Europe/Warsaw'
               )::date AS month,
               c.id AS client_id,
               c.name AS client_name,
               (j.id IS NULL) AS job_missing,
               count(*) AS cnt
        FROM analytics_first_milestones fm
        LEFT JOIN jobs j ON j.id = fm.job_id
        LEFT JOIN clients c ON c.id = j.client_id
        WHERE fm.stage::text = 'hired'
          AND fm.first_reached_at >= :board_start
          AND fm.first_reached_at < :end
        GROUP BY 1, 2, 3, 4
    ),
    dr_rows AS (
        SELECT date_trunc('month', p.placement_date)::date AS month,
               dc.name AS dr_name,
               count(*) AS cnt
        FROM dr_placement_details p
        JOIN dr_clients dc ON dc.id = p.client_id
        WHERE p.placement_date >= GREATEST(CAST(:start_day AS date), :dr_start)
          AND p.placement_date < LEAST(CAST(:end_day AS date), :cutover)
        GROUP BY 1, 2
        UNION ALL
        SELECT b.report_month AS month, b.client_name AS dr_name,
               b.placement_count AS cnt
        FROM dr_board_placement_clients b
        WHERE b.report_month >= CAST(:start_day AS date)
          AND b.report_month < LEAST(CAST(:end_day AS date), :dr_start)
    ),
    dr AS (
        SELECT d.month,
               m.id AS client_id,
               COALESCE(m.name, d.dr_name) AS client_name,
               false AS job_missing,
               sum(d.cnt) AS cnt
        FROM dr_rows d
        LEFT JOIN LATERAL (
            SELECT c.id, c.name
            FROM clients c
            WHERE lower(c.name) = lower(d.dr_name)
               OR lower(c.display_name) = lower(d.dr_name)
            ORDER BY c.id
            LIMIT 1
        ) m ON TRUE
        GROUP BY 1, 2, 3, 4
    )
    SELECT month, client_id, client_name, job_missing, cnt FROM board_pairs
    UNION ALL
    SELECT month, client_id, client_name, job_missing, cnt FROM dr
"""


def _local_day(moment: datetime) -> date:
    return moment.astimezone(ZoneInfo(DEFAULT_TZ)).date()


async def client_placements(
    db: AsyncSession, start: datetime, end: datetime
) -> list[ClientPlacements]:
    """Placementy klientów w oknie `[start, end)`, miesiąc po miesiącu."""
    rows = (
        await db.execute(
            text(_SQL),
            {
                "board_start": competition_history.board_start(start),
                "end": end,
                "start_day": _local_day(start),
                "end_day": _local_day(end),
                "dr_start": competition_history.DR_HISTORY_START,
                "cutover": competition_history.RESULTS_CUTOVER,
            },
        )
    ).all()
    return [
        ClientPlacements(
            month=r.month,
            client_id=None if r.client_id is None else int(r.client_id),
            client_name=r.client_name,
            job_missing=bool(r.job_missing),
            count=int(r.cnt),
        )
        for r in rows
    ]
