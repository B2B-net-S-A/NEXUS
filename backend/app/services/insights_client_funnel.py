"""Insights → „Klienci”: lejek i hit ratio per klient dla całej firmy (08.11.2026).

Teza B3 z audytu 08.11.2026: jeden klient dostaje większość CV, a daje
mniejszość zatrudnień, i bez widoku per klient nie da się o tym rozmawiać.

Definicje biorą się z istniejących ekranów, żeby ten sam request nie liczył się
tu inaczej niż w raporcie „Zamknięcia i hit ratio”:

* **Zdarzenia** (CV, rozmowy u klienta, zatrudnienia) = pierwsze wejście pary
  (kandydat, rekrutacja) na etap w oknie, z widoku
  ``analytics_first_milestones``. Widok pomija wykluczone placementy.
  Zatrudnienie w oknie może pochodzić z CV sprzed okna, więc „CV na
  zatrudnienie” to przelicznik okresu, a nie kohorta.
* **Rozstrzygnięte rekrutacje** = grupy z ``hit_ratio_closures.closure_group``
  (zamknięte od ``competition_history.cutover_utc()``, czyli 12.10.2026: wcześniej
  powodów zamknięcia nie było). Wygrana to zamknięcie z zatrudnieniem, przegrana
  to powód ``competitor`` albo ``no_activity`` bez zatrudnienia.
* **Różnica wobec „Zamknięć i hit ratio”:** zamknięcia „do przejrzenia” (brak
  powodu albo ``other``) są osobną kolumną i NIE wchodzą do mianownika. Weryfikacja
  audytu pokazała, że część z nich to rekrutacje z zatrudnieniem albo bez żadnej
  decyzji, więc liczenie ich jak przegranych zaniżało wynik klienta.
* **Mediana pierwszego CV** = dni od otwarcia rekrutacji do pierwszego CV do
  klienta, dla rekrutacji, których pierwsze CV wypadło w oknie.

Kwot tu nie ma, stąd bramka jak ``/clients/hit-ratio``, a nie ``BoardReader``.
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.client import Client
from app.models.job import Job, JobStatus
from app.services import competition_history
from app.services.client_identity import (
    client_display_name_expression,
    visible_client_predicates,
)
from app.services.hit_ratio_closures import closure_group
from app.services.insights_clients import ratio_pct
from app.services.job_fill import filled_by_job

_EVENTS_SQL = text(
    """
    SELECT j.client_id, fm.stage::text AS stage, count(*) AS n
    FROM analytics_first_milestones fm
    JOIN jobs j ON j.id = fm.job_id
    WHERE fm.stage::text IN ('cv_sent', 'client_interview', 'hired')
      AND fm.first_reached_at >= :start
      AND fm.first_reached_at < :end
      AND j.client_id IS NOT NULL
    GROUP BY j.client_id, fm.stage
    """
)

_FIRST_CV_SQL = text(
    """
    WITH first_cv AS (
        SELECT fm.job_id, min(fm.first_reached_at) AS first_at
        FROM analytics_first_milestones fm
        WHERE fm.stage::text = 'cv_sent'
        GROUP BY fm.job_id
    )
    SELECT j.client_id,
           GREATEST(
               EXTRACT(EPOCH FROM f.first_at - COALESCE(j.opened_at, j.created_at)),
               0
           ) / 86400 AS days
    FROM first_cv f
    JOIN jobs j ON j.id = f.job_id
    WHERE f.first_at >= :start
      AND f.first_at < :end
      AND j.client_id IS NOT NULL
    """
)


@dataclass(frozen=True)
class ClientFunnelRow:
    client_id: int
    client_name: str
    cv_sent: int
    client_interviews: int
    hires: int
    # Puste przy braku zatrudnień: „nie ma czego dzielić” to nie zero.
    cv_per_hire: Optional[float]
    won: int
    lost: int
    # Zamknięte bez powodu albo z powodem „Inny”; osobno, poza hit ratio.
    unreviewed: int
    hit_ratio: Optional[float]
    first_cv_median_days: Optional[float]
    first_cv_jobs: int


def cv_per_hire(cv_sent: int, hires: int) -> Optional[float]:
    return round(cv_sent / hires, 1) if hires > 0 else None


def _median_days(days: Iterable[float]) -> Optional[float]:
    values = list(days)
    return round(statistics.median(values), 1) if values else None


async def _closure_counts(
    db: AsyncSession, *, start: datetime, end: datetime
) -> dict[int, dict[str, int]]:
    """Wygrane, przegrane i „do przejrzenia” per klient; zamknięcia od 12.10."""
    since = max(start, competition_history.cutover_utc())
    if since >= end:
        return {}
    rows = (
        await db.execute(
            select(Job.id, Job.client_id, Job.close_reason).where(
                Job.status == JobStatus.closed,
                Job.closed_at >= since,
                Job.closed_at < end,
                Job.client_id.isnot(None),
            )
        )
    ).all()
    hired = await filled_by_job(db, [r.id for r in rows])
    counts: dict[int, dict[str, int]] = defaultdict(
        lambda: {"won": 0, "lost": 0, "unreviewed": 0}
    )
    for row in rows:
        group = closure_group(row.close_reason, bool(hired.get(row.id)))
        if group != "neutral":
            counts[row.client_id][group] += 1
    return dict(counts)


async def compute_client_funnel(
    db: AsyncSession, *, start: datetime, end: datetime
) -> list[ClientFunnelRow]:
    """Wiersz na klienta z jakimkolwiek zdarzeniem w oknie, od największej liczby CV."""
    window = {"start": start, "end": end}
    events: dict[int, dict[str, int]] = defaultdict(dict)
    for client_id, stage, n in (await db.execute(_EVENTS_SQL, window)).all():
        events[client_id][stage] = int(n)
    first_cv: dict[int, list[float]] = defaultdict(list)
    for client_id, days in (await db.execute(_FIRST_CV_SQL, window)).all():
        first_cv[client_id].append(float(days))
    closures = await _closure_counts(db, start=start, end=end)

    client_ids = set(events) | set(closures)
    if not client_ids:
        return []
    names = dict(
        (
            await db.execute(
                select(Client.id, client_display_name_expression()).where(
                    Client.id.in_(client_ids), *visible_client_predicates()
                )
            )
        ).all()
    )

    rows: list[ClientFunnelRow] = []
    for client_id, name in names.items():
        event = events.get(client_id, {})
        closure = closures.get(client_id, {"won": 0, "lost": 0, "unreviewed": 0})
        cv_sent = event.get("cv_sent", 0)
        hires = event.get("hired", 0)
        days = first_cv.get(client_id, [])
        rows.append(
            ClientFunnelRow(
                client_id=client_id,
                client_name=name,
                cv_sent=cv_sent,
                client_interviews=event.get("client_interview", 0),
                hires=hires,
                cv_per_hire=cv_per_hire(cv_sent, hires),
                won=closure["won"],
                lost=closure["lost"],
                unreviewed=closure["unreviewed"],
                hit_ratio=ratio_pct(closure["won"], closure["won"] + closure["lost"]),
                first_cv_median_days=_median_days(days),
                first_cv_jobs=len(days),
            )
        )
    rows.sort(key=lambda r: (-r.cv_sent, -r.hires, r.client_name))
    return rows


def fold_funnel_totals(rows: list[ClientFunnelRow]) -> dict:
    """Podsumowanie z tych samych wierszy, które widać w tabeli."""
    cv_sent = sum(r.cv_sent for r in rows)
    hires = sum(r.hires for r in rows)
    won = sum(r.won for r in rows)
    lost = sum(r.lost for r in rows)
    return {
        "clients": len(rows),
        "cv_sent": cv_sent,
        "client_interviews": sum(r.client_interviews for r in rows),
        "hires": hires,
        "cv_per_hire": cv_per_hire(cv_sent, hires),
        "won": won,
        "lost": lost,
        "unreviewed": sum(r.unreviewed for r in rows),
        "hit_ratio": ratio_pct(won, won + lost),
    }
