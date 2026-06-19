# Talent Pools — auto-przydział kandydatów „wysłanych do klienta”

> Raport z realizacji. PR [#547](https://github.com/artur-t-96/Nexus/pull/547), wdrożone na prod 2026-06-19 (SHA `4ae599d`).

## Problem (Jest → Ma być)

- **Jest:** kandydaci nie byli automatycznie przydzielani do pul talentów — `/talents` pokazywał ~wszystkie pule z licznikiem `0`.
- **Ma być:** kandydaci, którzy byli **wysłani do klientów** (etap `cv_sent` = „CV wysłane do klienta”), są rozdysponowani po wszystkich pulach.

## Diagnoza

- **8 411** distinct kandydatów przeszło etap `cv_sent` (19 131 wierszy `candidate_stages`), ale istniało tylko **40** członkostw w pulach.
- Trigger `auto_add_on_cv_sent` wyprowadzał nazwę puli z `job.subcategory + job.seniority`. Joby z importu Traffita **nie mają** tych pól (**3354/3355** jobów `cv_sent` puste) → trigger pomijał ~100% ruchów.
- **101** zaimportowanych pul ról (taksonomia Traffit) stało pustych; tylko 5 ręcznych pul miało członków.
- Jobs mają natomiast `competence_category_id` (~91% `cv_sent` jobów) oraz **tytuł**, który niesie rolę nawet bez subcategory.

## Rozwiązanie

Klasyfikator **tytuł oferty → istniejąca pula z katalogu** (+ skille kandydata jako fallback do rozróżniania wariantów), użyty zarówno przez live-trigger jak i przez backfill historii.

### Nowe pliki
- `backend/app/services/job_to_pool.py` — deterministyczny klasyfikator. Uporządkowane reguły (QA/security → data → management → infra → software), najpierw najbardziej szczegółowe. **Precyzja > recall**: niejednoznaczny tytuł (gołe „Developer”, „Automation Tester” bez języka) → `None` (pomiń), nie zgaduje wariantu. `competence_category_id` **nie jest bramką** (job-CC bywa błędny, np. „Senior JAVA Developer” otagowany `management_delivery`) — decyduje token w tytule. Skille kandydata konsultowane **tylko** gdy sam tytuł jest niejednoznaczny (nie nadpisują jasnego tytułu). Match na **pulę firmową** (`is_personal=False, is_marketplace=False`).
- `backend/app/services/talent_pool_backfill.py` — współdzielony, idempotentny backfill (replay `cv_sent` → `auto_add_on_cv_sent`), batch-commit co 500, candidate-aware, retry na `IntegrityError`.
- `backend/app/api/admin_talent_pools.py` — `POST /api/admin/talent-pools/backfill` (+ `since`, `limit`) i `GET /api/admin/talent-pools/backfill/status` (admin-only, w tle).
- `backend/tests/test_job_to_pool.py` — locked `title→pool` na realnych tytułach z prod, fallback po skillach, integralność nazw katalogu (żadna reguła nie emituje nazwy spoza katalogu), `javascript ≠ java`.

### Zmienione pliki
- `backend/app/services/talent_pool_auto_add.py` — kolejność: (1) klasyfikator → **istniejąca** pula (bez tworzenia nowych), (2) legacy `subcategory/seniority` (tworzy/heal), (3) skip. Przyjmuje `candidate` do disambiguacji. Zachowuje idempotencję (`uq_pool_candidate`), Activity log (z `resolved_via`), inwalidację centroidu. Filtr pul firmowych (jak PR #546).
- `backend/app/api/pipeline.py` — trigger `cv_sent` w `move_candidate` przekazuje `candidate`; dodany trigger także w `/bulk-move` (kanban).
- `backend/app/api/talent_pools.py` — lista pul liczy członków agregatem `func.count` (zamiast `selectinload(memberships)` + `len()`); endpoint kandydatów puli **paginowany** (`limit`/`offset`, domyślnie 500) z prawdziwym `total`.
- `frontend/src/app/talents/page.tsx` — licznik puli używa `total` z API + przypis „pokazano N z M” gdy lista ucięta.
- `backend/scripts/backfill_talent_pools.py` — Phase B deleguje do `services.talent_pool_backfill`.

### Migracje
**Brak** — feature reużywa istniejących tabel `talent_pools` / `talent_pool_memberships`.

## Wyniki (prod, po backfillu)

- Członkostwa: **40 → 7 264** (distinct `(pula, kandydat)`), **84 / 106** pul ma członków.
- Pokrycie samym tytułem ~**64%** par kandydat–oferta; reszta to skille-fallback + poprawnie pomijane nie-role.
- Top pule: Manual Tester 1048, Java 818, IT Analyst (Business) 638, Business Analyst (General) 419, SRE/DevOps 375, IT Project Manager 365, Scrum Master 227, Security Engineer 208, PMO 203, …
- Guard działa: **0** członkostw `cv_sent` na pulach osobistych/marketplace.
- UI zweryfikowane (Chrome): `/talents` pokazuje liczniki; pula „Java” → 818, badge „Z CV → Klient” na kandydatach, przypis „pokazano 500 z 818”.

## Aktywacja / ponowne uruchomienie

```
POST /api/admin/talent-pools/backfill            # pełny replay (idempotentny)
POST /api/admin/talent-pools/backfill?since=...  # tylko nowsze cv_sent
GET  /api/admin/talent-pools/backfill/status     # running + stats ostatniego runu
```

Live-trigger (`/pipeline/move` + `/pipeline/bulk-move` na `cv_sent`) utrzymuje pule aktualne na bieżąco.

## Znane ograniczenia

- **Status backfillu w pamięci** — `GET /backfill/status` trzyma `last_run` w pamięci procesu; przy wielu workerach uvicorn GET może trafić w innego workera niż ten, który uruchomił run (wtedy `last_run: {}`). Sam backfill commituje poprawnie (idempotentny). Źródło prawdy: liczniki w `/api/talent-pools`.
- **Granularne warianty** — pule wymagające języka/narzędzia z samego tytułu nierozróżnialne (7 wariantów „Tester Automatyzujący”, frameworki frontu) zostają puste, jeśli skille kandydata nie zdradzają technologii. Świadomy wybór precyzji (lepiej puste niż błędne).
- **Pre-existing:** w liście kandydatów puli pole `location` części kandydatów renderuje się jako surowy JSON geokodera — osobny task (nie z tej zmiany).

## Pliki

Backend: `services/job_to_pool.py` (new), `services/talent_pool_backfill.py` (new), `api/admin_talent_pools.py` (new), `services/talent_pool_auto_add.py`, `api/pipeline.py`, `api/talent_pools.py`, `main.py`, `scripts/backfill_talent_pools.py`, `tests/test_job_to_pool.py` (new), `tests/test_talent_pool_auto_add.py`.
Frontend: `app/talents/page.tsx`.
