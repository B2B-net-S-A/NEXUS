# Phase 16 — Historia requestu (sibling-request view)

**Data ukończenia:** 2026-04-28  
**Commit:** [`d41e04f`](https://github.com/artur-t-96/Nexus/commit/d41e04f)  
**Branch:** `main` → Coolify auto-deploy → https://nexus.dynaminds.pl

## Cel

Dodać dedykowaną zakładkę **Historia** na widoku joba, pokazującą listę bliźniaczych requestów u tego samego klienta (zamknięte + w toku) z rekruterskim kontekstem: outcome, champion, TTH, fee/rate, owner, similarity score. Plus "Skopiuj jako template" + banner w wizardzie nowego requestu + "Dodaj championa" jako kandydata.

Phase 15 (Champion historical_jobs) miał własny side-panel ograniczony do jobów z `champion_profile`. Ten widok jest szerszy i zorientowany na decyzje DL/TAC ("co u tego klienta poszło na podobnej roli").

## Decyzje (zaakceptowane przez użytkownika)

- Scope v1 = **pełny** (zakładka + Skopiuj jako template + Dodaj championa + Banner w wizardzie).
- "Skopiuj jako template" kopiuje `champion_profile` **tylko gdy same-client**.
- Cross-client toggle default OFF.
- In-progress + closed (z wizualnym podziałem na bucket tabs).

## Co dostarczone

### Backend
- **`backend/app/services/request_history.py`** (NEW) — progressive enhancement: SQL fast-path same-client (zero embedding cost) + Voyage/Qdrant fallback dla cross-client lub gdy SQL daje <top_k. Reuse `_qdrant_search` z `historical_jobs_retrieval.py` — **bez modyfikacji** Phase 15 service'u.
- **`backend/app/schemas/request_history.py`** (NEW) — `RequestHistoryEntry`, `RequestHistoryResponse`, `RequestHistoryPreviewRequest`, `AddCandidateFromHistoryPayload`.
- **`backend/app/api/jobs.py`** — 3 nowe endpointy:
  - `GET /api/jobs/{id}/request-history` (DeliveryLeadPlus) — splituje wynik na `closed` + `in_progress`, liczy `skill_frequency` tylko dla closed, zwraca meta z `sql_count`/`voyage_count`.
  - `POST /api/jobs/request-history/preview` — banner w wizardzie nowego requestu.
  - `POST /api/jobs/{id}/candidates` — dodaj championa do bieżącego pipeline; dedup 409 gdy `(candidate_id, job_id)` już istnieje.
- **`from_job_id` + `copy_questions`** w `JobCreate` (`backend/app/schemas/job.py`). `create_job` (`backend/app/api/jobs.py`):
  - kopiuje brakujące pola z source jobu (description / requirements / skills / train / seniority / industry / subcategory / headcount / work_mode / remote_policy / salary range)
  - kopiuje `champion_profile` **tylko gdy same-client**
  - replikuje pinned `JobQuestion` (idempotent dzięki `UNIQUE (job_id, question_id)`)
  - loguje `Activity(action="created_from_template", details={"source_job_id": ...})`

### Frontend
- **`frontend/src/components/RequestHistorySection.tsx`** (NEW) — sekcja z bucket tabs (Zamknięte / W toku), cross-client toggle, similarity badge z tier'ami koloru (95+ green-emerald, 85+ green, 70+ yellow, <70 gray), CTA per row: Otwórz / Skopiuj jako template / Dodaj championa. Na 409 z addCandidate wyświetla toast "Kandydat już jest w tym pipeline". Empty state z CTA "Spróbuj cross-client".
- **`frontend/src/lib/api.ts`** — `requestHistoryApi.{forJob, preview, addCandidate}`.
- **`frontend/src/app/jobs/[id]/page.tsx`** — zakładka "Historia" (ikona `History`, kolor amber-600) wstawiona między Pipeline a AI Matching.
- **`frontend/src/components/AppShell.tsx`** — `AddJobModal` zyskał:
  - opcjonalny prop `fromJobId` — prefill z source jobu (client_id i title czyszczone — DL wybiera świadomie).
  - banner pre-submit: gdy `client_id` + `title.length >= 5` (debounced 500 ms via inline `useDebouncedValue`), woła `POST /preview` i pokazuje "U tego klienta było już N podobnych requestów" + top 3 z linkami.
  - title modala adaptacyjny: "Skopiuj jako template" gdy `fromJobId != null`, w przeciwnym razie "Dodaj ofertę pracy".

### Testy
- **`backend/tests/test_request_history.py`** (NEW) — 8 jednostkowych testów purefunkcyjnych: `aggregate_meta_counts`, `_build_query_text` (truncation, empty), `RequestHistoryEntry` immutability, sanity constants. **8/8 pass.**
- TypeScript `tsc --noEmit` — 0 nowych błędów (pre-existing 58 legacy errors w niezwiązanych plikach).

## Weryfikacja produkcyjna

### Backend (curl na https://api.nexus.dynaminds.pl)
- `GET /api/jobs/3/request-history` (Bank Pekao, DevOps/Cloud) → zwraca 2 in-progress entries (Job 15 "Scrum Master" + Job 9 "Tech Lead / Architect"), `similarity=1.0`, `similarity_source="sql_same_client"`, `candidates_count` poprawne (2/3).
- `meta`: `sql_count=2, voyage_count=0, total=2` — fast path działa, brak ruchu do Qdrant.
- Health: `https://api.nexus.dynaminds.pl/health` → `{"status":"ok","version":"0.3.0"}`.

### UI (Chrome MCP, claude-admin@b2bnet.pl)
- **/jobs/3 → klik "Historia"** → renderuje sekcję z bucket tabs Zamknięte (0) | W toku (2). Empty state w "Zamknięte" widoczny.
- **W toku (2)** → 2 wiersze z metadanymi: tytuł + similarity badge 100% (green-emerald), status pill "W toku", N kand., 3 CTA (Otwórz / Skopiuj jako template / Dodaj championa).
- "Dodaj championa" automatycznie wyszarzony dla wierszy bez `champion_candidate_id` (oba testowe joby są open / brak hired stage'u — zgodne z planem).
- Toggle "Wszyscy klienci" w prawym górnym rogu.

### Pytest
- `cd backend && python3 -m pytest tests/test_request_history.py -q` → **8 passed in 0.57s**.

## Znane ograniczenia / risks

1. **Closed jobs**: w obecnej prod-bazie **brak** zamkniętych requestów — sekcja "Zamknięte" zawsze będzie pusta dopóki nie zaczniemy zamykać requestów (na shadow-mode na razie). To nie jest bug, to brak danych.
2. **Cross-client embedding**: Voyage fallback działa tylko gdy historyczny job został wcześniej embedded (Phase 2). Dla starszych closed jobów → brak hitu w cross-client. Same-client SQL fast-path działa zawsze.
3. **Multi-hire**: pierwszy hit `DISTINCT ON (job_id) ORDER BY moved_at DESC` (najnowszy hire). UI pokazuje "(+N)" pill gdy `champions_count > 1`.
4. **`skill_frequency`** liczone tylko dla `closed` (in-progress nie ma jeszcze hire-signal). UI surface'uje to przez `meta.skill_freq_sample`.
5. **Banner debounce 500 ms** + `enabled: title.length >= 5` zapobiega spamowaniu `POST /preview`.
6. **Rate limit `/auth/login`** — 5/min. To mieści się w typowym usage; przy testach manualnych użyć `/refresh` zamiast pełnego loginu po wygaśnięciu tokena.

## Pliki

### Modified
- `backend/app/api/jobs.py` (+253 linii)
- `backend/app/schemas/job.py` (+12 linii: `from_job_id`, `copy_questions`)
- `frontend/src/lib/api.ts` (+82 linii: typy + `requestHistoryApi`)
- `frontend/src/app/jobs/[id]/page.tsx` (+18 linii: tab + render block)
- `frontend/src/components/AppShell.tsx` (+114 linii: prop, prefill, banner, useDebouncedValue)

### New
- `backend/app/services/request_history.py` (433 linii)
- `backend/app/schemas/request_history.py` (74 linii)
- `backend/tests/test_request_history.py` (98 linii)
- `frontend/src/components/RequestHistorySection.tsx` (411 linii)

### Migracje Alembic
**Brak.** Wszystkie potrzebne pola (`close_reason`, `champion_profile`, contracts, `train_name`) istnieją od poprzednich migracji.

## v2 (osobny ticket — propozycje)

- Lessons learned w wierszu (z `Contract.termination_lessons`).
- Postmortem field na Jobie / link do call-summary.
- Multi-hire: lista championów (`champions[]`) zamiast pierwszego.
- Drilldown na `Otwórz` jako modal preview (bez przeładowania) z mini-pipeline.
- E2E test (Playwright) dla flow "Skopiuj jako template" — od kliku do zapisu nowego joba z prefilled polami.

## Referencje

- Plan implementacji: `~/.claude/plans/zaplanuj-wszystko-zgodnie-z-cozy-steele.md`
- Phase 15 (Champion historical_jobs): commit `~3 weeks ago`, service `historical_jobs_retrieval.py`
- Memory: `project_champion_historical.md`
