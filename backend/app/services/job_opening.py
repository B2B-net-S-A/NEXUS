"""Bieżące otwarcie rekrutacji — od „Otwórz ponownie” (decyzja Artura 05.11.2026).

Ponowne otwarcie zmieniało tylko status, więc karty i zatrudnienia z
poprzedniego otwarcia liczyły się jak bieżąca praca. Symulacja na kopii
produkcji z 04.11.2026: otwarcie 76 zamkniętych rekrutacji z kartą
w Akceptacji podnosiło „Akceptacje do domknięcia” z 7 do 92, a prognozę
z 6–7 do 82–83 placementów. Rekrutacje otwarte ponownie miały 0 wakatów
przez stare zatrudnienie i nie dawały się zamknąć jako „nie liczy się”.

``jobs.cycle_started_at`` to chwila ostatniego ponownego otwarcia. Od niej
liczą się wyłącznie stany „na teraz”:

* obsada i wakaty (``job_fill.filled_by_job``), miejsca Championów,
  podpowiedź „komplet obsady”, bramka powodu zamknięcia i „wygrana”
  w raporcie zamknięć;
* „W drodze”, prognoza z akceptacji, „Teraz” w „Lejku po etapach”,
  ostrzeżenie i wiadomości przy zamknięciu.

Karta liczy się w bieżącym otwarciu, gdy jej najnowszy ruch jest od tej
chwili, więc osoba z poprzedniego otwarcia, którą rekruter ruszy, wraca do
liczb. Historia (placementy, lejek „Doszło”, Liga, KPI) się nie zmienia:
placement to nadal pierwsze „Zatrudniony” pary (D2).

Przeniesienie z Traffita (``traffit_transfer``) też otwiera rekrutację, ale
to ta sama praca, nie nowe otwarcie — znacznika nie stawia.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from app.models.job import Job

# Jednorazowe uzupełnienie w ``entrypoint.sh`` (lustro migracji 0653).
BACKFILL_MARKER = "0653_job_opening_backfill"

# Ostatnie ponowne otwarcie przez człowieka (``publish_core`` zapisuje
# ``published`` z ``reopened: true``). Bez przeniesień z Traffita.
BACKFILL_SQL = """
    UPDATE jobs j
       SET cycle_started_at = r.reopened_at
      FROM (
        SELECT entity_id AS job_id, max(created_at) AS reopened_at
          FROM activities
         WHERE entity_type = 'job'
           AND action = 'published'
           AND details->>'reopened' = 'true'
           AND coalesce(details->>'reason', '') <> 'traffit_transfer'
         GROUP BY entity_id
      ) r
     WHERE j.id = r.job_id
       AND j.cycle_started_at IS NULL
"""


def start_new_opening(job: "Job", at: Optional[datetime] = None) -> None:
    """„Otwórz ponownie” zaczyna nowe otwarcie. Bez commitu."""

    job.cycle_started_at = at or datetime.now(timezone.utc)


def in_opening(moved_at: datetime, opening_started_at: Optional[datetime]) -> bool:
    """Czy ruch karty należy do bieżącego otwarcia rekrutacji."""

    return opening_started_at is None or moved_at >= opening_started_at


def in_opening_sql(job_alias: str, moved_at_sql: str) -> str:
    """Lustro ``in_opening`` dla surowego SQL-a."""

    return (
        f"({job_alias}.cycle_started_at IS NULL "
        f"OR {moved_at_sql} >= {job_alias}.cycle_started_at)"
    )


__all__ = [
    "BACKFILL_MARKER",
    "BACKFILL_SQL",
    "in_opening",
    "in_opening_sql",
    "start_new_opening",
]
