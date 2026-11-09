"""Termin rozmowy u klienta i start współpracy pary (kandydat, rekrutacja).

Prośba z 09.11.2026: listy w Insights pokazywały chwilę przesunięcia karty
na „Rozmowę u klienta”, a nie termin rozmowy, który średnio wypada kilka dni
później. Jedna reguła dla listy „Kto się liczy”, „W drodze” i profilu kandydata:

* **termin** — wydarzenie ``client_interview`` z kalendarza, bez odwołanych:
  najbliższa runda, a gdy żadnej nie ma przed nami, ostatnia;
* **propozycja** — otwarty wniosek o terminy: termin wybrany z kandydatem albo
  najwcześniejszy jeszcze aktualny (jak ``interview_cycle.tentative_interview_start``);
* **start** — data z kontraktu pary (bez unieważnionych), a bez kontraktu
  planowany start z najnowszej akceptacji z datą, jak na karcie Tablicy.

Granicą „przed nami” jest początek dnia w kalendarzu firmy, tak jak na ekranie:
rozmowa z dzisiejszego ranka nadal jest „dziś”, a nie „minęła”.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Iterable, Optional
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scheduling import DEFAULT_TZ


def term_from(today: date) -> datetime:
    """Wartość parametru ``:term_from``: początek dnia w kalendarzu firmy."""
    return datetime.combine(today, time.min, tzinfo=ZoneInfo(DEFAULT_TZ))


def pair_terms_lateral(candidate_sql: str, job_sql: str) -> str:
    """Złączenia dające ``interview_term``, ``interview_proposal``, ``pair_start``."""
    pair = (
        "{alias}.candidate_id = " + candidate_sql + " AND {alias}.job_id = " + job_sql
    )
    return f"""
    LEFT JOIN LATERAL (
        SELECT min(calendar_event.start_time) FILTER (
                   WHERE calendar_event.start_time >= :term_from
               ) AS next_at,
               max(calendar_event.start_time) FILTER (
                   WHERE calendar_event.start_time < :term_from
               ) AS last_at
        FROM calendar_events calendar_event
        WHERE {pair.format(alias="calendar_event")}
          AND calendar_event.event_type = 'client_interview'
          AND calendar_event.status <> 'cancelled'
    ) interview_term ON TRUE
    LEFT JOIN LATERAL (
        SELECT min(proposed.start_at) AS tentative_at
        FROM client_interview_slot_requests slot_request
        CROSS JOIN LATERAL jsonb_array_elements(slot_request.slots)
            WITH ORDINALITY AS slot(value, position)
        CROSS JOIN LATERAL (
            SELECT (slot.value ->> 'start')::timestamptz AS start_at
        ) proposed
        WHERE {pair.format(alias="slot_request")}
          AND slot_request.status IN ('awaiting_recruiter', 'awaiting_dl')
          AND proposed.start_at >= :term_from
          AND (
              slot_request.status <> 'awaiting_dl'
              OR slot_request.chosen_index IS NULL
              OR slot.position - 1 = slot_request.chosen_index
          )
    ) interview_proposal ON TRUE
    LEFT JOIN LATERAL (
        SELECT coalesce(
            (
                SELECT max(contract.start_date)
                FROM contracts contract
                WHERE {pair.format(alias="contract")}
                  AND contract.status <> 'void'
            ),
            (
                SELECT accepted.planned_start_on
                FROM candidate_stages accepted
                WHERE {pair.format(alias="accepted")}
                  AND accepted.stage::text = 'acceptance'
                ORDER BY accepted.client_accepted_on IS NOT NULL DESC,
                         accepted.moved_at DESC,
                         accepted.id DESC
                LIMIT 1
            )
        ) AS start_on
    ) pair_start ON TRUE
"""


@dataclass(frozen=True)
class PairTerms:
    next_at: Optional[datetime] = None
    last_at: Optional[datetime] = None
    tentative_at: Optional[datetime] = None
    start_on: Optional[date] = None

    @property
    def interview_at(self) -> Optional[datetime]:
        return self.next_at or self.last_at


_PAIR_TERMS_SQL = text(
    """
    SELECT pair.candidate_id,
           pair.job_id,
           interview_term.next_at,
           interview_term.last_at,
           interview_proposal.tentative_at,
           pair_start.start_on
    FROM unnest(CAST(:candidate_ids AS int[]), CAST(:job_ids AS int[]))
        AS pair(candidate_id, job_id)
    """
    + pair_terms_lateral("pair.candidate_id", "pair.job_id")
)


async def load_pair_terms(
    db: AsyncSession,
    pairs: Iterable[tuple[int, int]],
    *,
    today: date,
) -> dict[tuple[int, int], PairTerms]:
    """Terminy dla wielu par jednym zapytaniem; para bez niczego ma puste pola."""
    unique = sorted(set(pairs))
    if not unique:
        return {}
    rows = await db.execute(
        _PAIR_TERMS_SQL,
        {
            "candidate_ids": [candidate_id for candidate_id, _ in unique],
            "job_ids": [job_id for _, job_id in unique],
            "term_from": term_from(today),
        },
    )
    return {
        (row["candidate_id"], row["job_id"]): PairTerms(
            next_at=row["next_at"],
            last_at=row["last_at"],
            tentative_at=row["tentative_at"],
            start_on=row["start_on"],
        )
        for row in rows.mappings()
    }
