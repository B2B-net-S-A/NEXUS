# Generator CV — generacja w tle (odporna na wyjście z karty)

**Data:** 2026-07-01
**Problem (zgłoszenie):** „generator CV — Jest: nie generuje jak się wychodzi z karty / ma być: generuje po wyjściu z karty".

## Co było

Generacja CV była **synchronicznym, blokującym** requestem: `POST /api/cv-generator/generate`
zwracał gotowy DOCX w ciele odpowiedzi po 60–90 s (Claude + render). Kod wprost
traktował „kartę" jako kartę przeglądarki (`beforeunload` guard, tekst „nie
zamykaj karty…"). Zamknięcie/opuszczenie karty w trakcie generacji **przerywało
request i gubiło wynik bez śladu** — rekruter musiał pilnować karty przez całą
generację.

## Co jest teraz

Generacja leci **w tle** (FastAPI `BackgroundTasks`), 202 wraca natychmiast.
Rekruter może zamknąć/opuścić kartę — CV i tak dokończy się serwerowo i wyląduje
na liście „Wygenerowane CV" ze statusem `ready` (Podgląd/Pobierz) albo `failed`
(z czytelnym powodem). Lista sama się odpytuje (polling) dopóki coś jest w toku.

Potwierdzone przez Artura jako oczekiwane zachowanie (opcja „Generacja w tle,
odporna na wyjście").

## Zmiany

### Backend
- **`app/models/cv_generated_document.py`** — nowe kolumny: `status`
  (`processing`|`ready`|`failed`, default `ready`, indeks częściowy dla reapera),
  `error_message`, `warnings` (JSONB — wcześniej wracały tylko nagłówkiem
  `X-Generator-Warnings`, którego przy async już nie ma).
- **`alembic/versions/0152_cv_generated_async_status.py`** — migracja
  (ADD COLUMN / CREATE INDEX IF NOT EXISTS, na bazie `0151`). Jedyny head.
- **`app/api/cv_generator_b2b.py`**:
  - `POST /generate` i `POST /generate-upload` → **enqueue + 202**
    (`GenerateEnqueuedResponse {id, status, candidate_name}`) zamiast blobu DOCX.
    Tworzą wiersz-placeholder `processing`, commit (widoczny dla pollingu i
    joba), potem `background_tasks.add_task(...)`.
  - Nowe helpery `_create_pending_row` / `_finalize_success` / `_finalize_failure`
    (zastąpiły `_persist_generated`).
  - Workery `_run_generate_new_job` / `_run_generate_upload_job` — **własna
    sesja DB** (`AsyncSessionLocal`), łapią wszystko (błąd → wiersz `failed`),
    audyt `Activity` przeniesiony do joba (rejestruje faktyczne ukończenie).
  - `GET /generated` zwraca `status`/`error_message`/`warnings`;
    `can_download = status=="ready" && render_payload != None`.
- **`app/main.py`** (lifespan) — **reaper na starcie**: świeży proces = żadne
  zadanie w tle nie przeżyło, więc każde osierocone `processing` (np. po
  redeployu Coolify w trakcie generacji) → `failed` z czytelnym komunikatem
  (zamiast wiecznego spinnera).

### Frontend
- **`components/v2/pages/CVGeneratorStandaloneV2.tsx`**:
  - Mutacje (new + upload) → enqueue (JSON), toast „Generacja ruszyła w tle…".
  - `generatedQuery` — `refetchInterval` 4 s dopóki któreś CV jest `processing`.
  - Nowy `GeneratedCvRow` — status-aware: spinner „Generuję…" / błąd + powód /
    gotowe (Podgląd/Pobierz) + rozwijane „N uwag".
  - Usunięty `beforeunload` guard (wyjście jest teraz bezpieczne). Auto-download
    zachowany jako opcja: CV wygenerowane w tej sesji pobiera się automatycznie,
    gdy przeskoczy na `ready` (dla tych, co zostają na stronie).
- **`components/v2/modals/CVGeneratorV2.tsx`** (z karty kandydata) — enqueue +
  panel sukcesu („Generacja ruszyła w tle… otwórz Generator CV"), bez
  auto-downloadu (async). Reset przy zamknięciu.

### Testy / CI
- **`tests/test_cv_generator_b2b_async.py`** — unit testy tranzycji
  `processing → ready/failed` (finalizery, bez DB/HTTP). Dopisane do listy
  selektywnej w `ci.yml`.

## Weryfikacja
- Backend: `ruff` ✓, `py_compile` ✓. Testy pipeline/headers bez zmian
  (`_build_docx_response` + pipeline zachowane) → dalej zielone; nowe unit testy
  finalizerów w CI.
- Frontend: `tsc --noEmit` ✓, `next lint` ✓ (oba zmienione pliki czyste).
- Migracja: `ADD COLUMN IF NOT EXISTS`, chained na `0151`, single head; CI robi
  `alembic upgrade heads`.

## Znane ograniczenia
- `BackgroundTasks` żyje w procesie serwera: redeploy/restart w trakcie generacji
  ubija zadanie. Pokryte reaperem na starcie (`processing → failed`, „wygeneruj
  ponownie"). Okno naraża tylko trwające ~60–90 s generacje.
- Model single-instance (1 kontener uvicorn na NEXUS). Przy skalowaniu poziomym
  reaper „mark all processing on startup" trzeba by ograniczyć do własnej
  instancji.

## Po merge (do zrobienia)
- Chrome smoke na `nexus.dynaminds.pl`: Generator CV → wybierz kandydata +
  rekrutację → „Generuj CV w tle" → wiersz `processing` → polling → `ready` →
  Pobierz. Sprawdzić też wariant modala z karty kandydata.
- `curl /api/health` → nowy `GIT_SHA`.
