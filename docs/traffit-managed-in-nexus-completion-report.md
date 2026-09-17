# „Rekrutacja prowadzona w NEXUSIE" (`jobs.managed_in_nexus`) — raport z wdrożenia

Część B planu „Kanban rekrutacji bez bramek + przełączanie rekrutacji z Traffita
do NEXUSA" (17.09.2026). Ten sam PR co część A (bramki kanbana).

## Po co

Tablica rekrutacji czyta NAJNOWSZY wiersz `candidate_stages` dla pary
(kandydat, oferta), a nocny import Traffita dopisuje etapy KAŻDEJ rekrutacji
z Traffita. Ruch zrobiony w NEXUSIE przegrywał więc nazajutrz z etapem z importu
— w 90 dniach tylko 131 z 32 872 ruchów (0,4 %) powstało w NEXUSIE. Decyzja
Artura: przełącznik PER REKRUTACJA, ustawiany ręcznie, żeby przenosić zespół
falami.

## Co się zmieniło

### Baza
- Migracja `0326_jobs_managed_in_nexus` (na `0325_pending_verification_retired`):
  `jobs.managed_in_nexus BOOLEAN NOT NULL DEFAULT false`,
  `managed_in_nexus_at TIMESTAMPTZ`, `managed_in_nexus_by INTEGER → users(id) ON DELETE SET NULL`.
- Lustro 1:1 na końcu `_COLUMN_STATEMENTS` w `backend/entrypoint.sh` (prod alembic
  bywa osierocony). Pilnuje `tests/test_managed_in_nexus_migration_mirror.py`.
- Jedna głowa alembica: `0326_jobs_managed_in_nexus` (sprawdzone statycznym
  skanem `revision`/`down_revision`).

### Import Traffita
- Faza `pipelines` czyta raz listę ofert z flagą (`_build_managed_job_ids`) i
  POMIJA ich ruchy — po mapperze, przed `dry_run` (próbny bieg liczy tak samo).
  Licznik `skipped_managed` jest osobny od `skipped` i przechodzi przez obie
  whitelisty statystyk (`PhaseProgress.as_dict`, `_summarize`).
- `_UPSERT_JOB`: `title`, `status`, `closed_at` przełączonej oferty zostają
  wartościami NEXUSA (CASE jak `recruiter_id`↔`is_open`); unieważnienie
  `matching_requirements`/`requirements_reviewed` jest wtedy wyłączone.
- **Świadomie bez zmian:** `deadline`, `opened_at`, `client_id`,
  `pipeline_template_id`, `reference_number` nadal DOPEŁNIAJĄ puste pola z
  Traffita (COALESCE), `custom_fields` scala JSONB — także dla przełączonych
  ofert. `rejection_backfill` nietknięty (zmienia tylko powód/notatki, nie etap).
- `GET /api/admin/traffit/sync/status` niesie `managed_in_nexus_jobs` (liczba,
  nie lista); karta Traffita w Ustawieniach pokazuje tę liczbę.

### API
- `POST /api/jobs/{id}/manage-in-nexus` body `{enabled: bool}`, odpowiedź
  `JobResponse` (dostał `external_source`, `managed_in_nexus`, `managed_in_nexus_at`,
  `managed_in_nexus_by`).
  - `TacPlus` + członkostwo w rekrutacji; brak oferty → 404 (członkostwo
    sprawdzane PO odczycie oferty, bo `ensure_job_membership` dawałby 403);
  - rekrutacja spoza Traffita → 409;
  - wyłączenie (powrót do Traffita) tylko admin / Delivery Lead → 403 dla reszty;
  - idempotentne; realna zmiana zapisuje `activities.action='managed_in_nexus_changed'`
    z `{enabled, previous}` oraz stempel `_at`/`_by`.

### UI
- `frontend/src/components/v2/jobs/ManagedInNexusSwitch.tsx`:
  - baner nad tablicą (zakładka Pipeline) dla nieprzełączonych rekrutacji
    z Traffita — ostrzeżenie „Ruchy wykonane tutaj nadpisze nocny import."
    + przycisk „Przełącz do NEXUSA" (zapis pipeline + `job.update`), z oknem
    potwierdzenia;
  - chip „Prowadzona w NEXUSIE od {data}" w nagłówku rekrutacji; kliknięcie
    (admin / Delivery Lead, poza trybem podglądu) otwiera okno „Wróć do Traffita".
- `jobsApi.setManagedInNexus`, typ `JobManagedInNexus` w `lib/api.ts`.

## Testy

| Plik | Zakres |
|---|---|
| `tests/test_job_column_ownership.py` | nowe kolumny w `NEXUS_OWNED`; CASE `title/status/closed_at` i wymagań wykonywany w SQLite dla managed=1/0 |
| `tests/test_managed_in_nexus_migration_mirror.py` | łańcuch rewizji + lustro DDL w entrypoincie |
| `tests/test_traffit_managed_in_nexus.py` | faza `pipelines` pomija ruch (0 wierszy, `skipped_managed=1`, także w dry-run), nieprzełączona importuje; obie whitelisty; `_UPSERT_JOB` na Postgresie |
| `tests/test_job_managed_in_nexus_api.py` | włączenie + audyt, idempotencja, TAC spoza zespołu 403, TAC-członek włącza / nie wyłącza, admin wyłącza, `manual` 409, brak oferty 404 (admin i TAC) |
| `tests/test_traffit_status_service.py` | `managed_in_nexus_jobs` w statusie |
| `tests/test_traffit_pipelines_resume.py` | mock nowego lookupu (fake DB nie ma `fetchall`) |
| `frontend/.../__tests__/ManagedInNexusSwitch.test.tsx` | 8 przypadków banera i chipu |

## Znane ograniczenia / do sprawdzenia po wdrożeniu

- Przełączenie działa od najbliższego biegu importu — etapy zaimportowane
  wcześniej zostają w historii.
- Smoke na produkcji (z planu): przełączenie rekrutacji z Traffita, następnego
  dnia `skipped_managed` w statusie syncu i brak etapów z importu na tablicy.
- Poza tą falą: chip „w NEXUSIE" na liście rekrutacji, harness `/preview`,
  wskaźnik adopcji per rekruter.
