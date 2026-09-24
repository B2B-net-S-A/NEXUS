"""Rekrutacje z Traffita są w NEXUSIE archiwum (decyzja Artura 24.09.2026).

Od 25.09.2026 Delivery Leadzi zakładają rekrutacje w NEXUSIE, a Traffit
zostaje źródłem historii. Każda rekrutacja z Traffita — dawna i każda, którą
nocny sync zobaczy później — jest w NEXUSIE ZAMKNIĘTA i „Zakończona”: nie ma jej
w otwartych listach, pulach przydziału, follow-upach ani alertach, ale zostaje
źródłem „Podobnych rekrutacji”, przepięć (osoby już wysłane do klienta)
i profili Championa. Wyjątek: rekrutacja przełączona „Prowadzona w NEXUSIE”
(`managed_in_nexus`) — tę prowadzi zespół i sync jej nie rusza.

Dwie połowy, bo kolumny mają różnych właścicieli (`job_column_ownership`):

* ``status`` jest kolumną Traffita — mapper importu zapisuje ``closed`` (a stan
  z Traffita trzyma w ``custom_fields.traffit_status``);
* ``work_state`` i ``is_open`` należą do NEXUSA — ustawia je
  :func:`archive_traffit_jobs` po fazie rekrutacji, NIE ``_UPSERT_JOB``.

``closed_at`` celowo zostaje taki, jak w Trafficie (pusty, dopóki Traffit nie
zamknie rekrutacji). Hit ratio (Liga Mistrzów DL, Portfele DL, Rok do roku)
liczy rekrutacje ZAMKNIĘTE w oknie po ``closed_at`` — stempel „dziś” na ~320
archiwizowanych rekrutacjach wrzuciłby je do mianownika Q3 i zaniżył ligę,
która wypłaca nagrody.
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

#: Jedno źródło SQL — czyta go import, migracja 0377 i lustro w entrypoint.sh.
ARCHIVE_TRAFFIT_JOBS_SQL = """
UPDATE jobs
SET status = 'closed',
    is_open = false,
    work_state = 'finished',
    work_state_changed_at = CASE
        WHEN work_state <> 'finished' THEN now() ELSE work_state_changed_at END,
    updated_at = now()
WHERE external_source = 'traffit'
  AND NOT managed_in_nexus
  AND (status <> 'closed' OR is_open OR work_state <> 'finished')
"""


async def archive_traffit_jobs(db: AsyncSession) -> int:
    """Zamyka w NEXUSIE rekrutacje z Traffita (bez przełączonych do NEXUSA).

    Idempotentne — drugi przebieg nic nie zmienia. Nie commituje.
    """
    result = await db.execute(text(ARCHIVE_TRAFFIT_JOBS_SQL))
    return int(result.rowcount or 0)


__all__ = ["ARCHIVE_TRAFFIT_JOBS_SQL", "archive_traffit_jobs"]
