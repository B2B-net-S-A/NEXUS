"""Jednorazowe archiwum rekrutacji sprzed startu NEXUSA (decyzja Artura 25.09.2026).

Od 25.09.2026 Delivery Leadzi zakładają rekrutacje w NEXUSIE. Rekrutacje
z Traffita są archiwum od 24.09 (`services/traffit_job_archive.py`); ta korekta
domyka resztę: każdą rekrutację założoną PRZED 25.09.2026 (czas warszawski),
która nie jest jeszcze zamknięta — dowolnego źródła, także założoną ręcznie
w NEXUSIE (15 rekrutacji demo z kwietnia, do których scraper dalej dopisywał
aplikacje, szkice SMOKE/TEST). Otwarte zostają wyłącznie rekrutacje założone
od 25.09.

Jednorazowo (znacznik w `app_settings`), a nie jako stała reguła: rekrutacji
otwartej świadomie z powrotem nikt nie powinien zamykać po cichu.

``closed_at`` zostaje nietknięty, jak w archiwum Traffita — hit ratio Ligi DL
liczy rekrutacje zamknięte w oknie po ``closed_at``, a stempel „dziś” na
rekrutacjach demo zaniżyłby ligę, która wypłaca nagrody. Każda zamknięta
rekrutacja dostaje wpis ``archived`` w historii (bez autora — to korekta).
"""

from __future__ import annotations

MARKER_KEY = "0378_archive_jobs_before_nexus_start"

#: Jedno źródło SQL — czyta go migracja 0378 i lustro w entrypoint.sh.
ARCHIVE_JOBS_BEFORE_NEXUS_START_SQL = """
WITH marker AS (
    INSERT INTO app_settings (key, value)
    VALUES ('0378_archive_jobs_before_nexus_start', to_jsonb(true))
    ON CONFLICT (key) DO NOTHING
    RETURNING key
), archived AS (
    UPDATE jobs
    SET status = 'closed',
        is_open = false,
        work_state = 'finished',
        work_state_changed_at = CASE
            WHEN work_state <> 'finished' THEN now() ELSE work_state_changed_at END,
        updated_at = now()
    WHERE created_at < make_timestamptz(2026, 9, 25, 0, 0, 0, 'Europe/Warsaw')
      AND (status <> 'closed' OR is_open OR work_state <> 'finished')
      AND EXISTS (SELECT 1 FROM marker)
    RETURNING id
)
INSERT INTO activities (entity_type, entity_id, action, details, external_source)
SELECT 'job', id, 'archived',
       jsonb_build_object('reason', 'archive_before_nexus_start',
                          'cutoff', '2026-09-25'),
       'manual'
  FROM archived
"""


__all__ = ["ARCHIVE_JOBS_BEFORE_NEXUS_START_SQL", "MARKER_KEY"]
