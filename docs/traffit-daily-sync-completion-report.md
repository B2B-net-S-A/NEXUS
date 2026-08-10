# Traffit daily sync — completion report

> Sesja 2026-06-17. Cel (Artur): „schedule daily import from traffit all data —
> make sure it is actually all data and placed into correct places into nexus,
> so there is no notatka missing or rekrutacja or files or anything."
> Plan: `~/.claude/plans/sparkling-bouncing-umbrella.md`.

## Problem

Migracja Traffit→Nexus (maj 2026, `docs/traffit-migration-completion-report.md`)
była **jednorazowa** (CLI `python -m app.cli.import_traffit`). Brak schedulera =
Nexus driftuje od Traffita. Analiza importera + prod DB wykazała 3 luki łamiące
„nic nie ginie" dla zadania cyklicznego:

1. **Brak schedulera / brak delty.** Każda faza full-scanuje (49k kandydatów,
   367k activities, 166k stages) — godziny na run. Tabela watermark
   (`traffit_import_runs`) z planu nigdy nie powstała. Traffit API wspiera
   `X-Request-Filter: {"updated_at":{"comparison":">="}}` ale klient go nie wysyłał.
2. **Notatki NIE były synchronizowane.** `notes` zapełniła **jednorazowo**
   migracja `0077_promote_traffit_notes`. Importer pisze tylko do `activities`.
   Nowe notatki Traffita nigdy nie trafiały do zakładki „Notatki". (Prod: `activities`
   świeże = dziś, `notes.max(created_at)` = 2026-06-08.) ← dokładnie obawa Artura.
3. **Aktualizacje plików/CV pomijane.** `import_candidates_cv` (`cv_storage_key IS NULL`)
   i `import_candidate_files` (`HAVING count=0`) na zawsze pomijały kandydata, który
   już ma plik → podmienione CV nigdy się nie syncowały.

## Rozwiązanie (delta + tygodniowy full reconcile, kill-switch, idempotent)

| Komponent | Plik |
|---|---|
| Delta filtr (`X-Request-Filter`, 400→full-scan fallback) | `backend/app/services/traffit/client.py` |
| `since` w fazach + `promote_notes()` + delta plików | `backend/app/services/traffit/importer.py` |
| Watermark model + migracja `0136` (na `0135`) | `backend/app/models/traffit_sync_state.py`, `backend/alembic/versions/0136_traffit_sync_state.py` |
| Settings (`TRAFFIT_SYNC_*`) | `backend/app/core/config.py` |
| Background loop + scheduler (pure helpers) | `backend/app/tasks/traffit_sync.py` |
| Lifespan + `/api/health.checks.traffit` | `backend/app/main.py` |
| Admin trigger/status (admin-only) | `backend/app/api/admin_traffit.py` |
| Testy (helpery + filtr klienta + promote SQL) | `backend/tests/test_traffit_sync.py` |

### Jak działa

- **Loop** `traffit_daily_sync_loop` (lifespan task `traffit_sync`) budzi się co
  `TRAFFIT_SYNC_CHECK_INTERVAL_SECONDS` (30 min) i decyduje z **persisted**
  `traffit_sync_state` (markery `__daily__`/`__full__`) → restart-safe.
- **delta** (~02:00 UTC): `updated_at>=since` (kandydaci/joby), `created_at>=since`
  (activities/pipelines/sources); małe master-data (users/clients/contacts/workflows/
  talents) full-scan (tanie). `since = last_synced - 48h` lub `now - 45d` na pierwszy run.
- **full** (niedz. ~02:00): full-scan reconcile (safety net). Full advance'uje też
  watermark `__daily__`.
- **Notatki**: `promote_notes(since)` = idempotentna replika `0077`
  (dedup `NOT EXISTS (candidate_id, created_at)`, `source_ref='traffit:activity:<id>'`),
  wołana w `import_candidate_activities`.
- **Pliki delta**: scope = kandydaci dotknięci w tym runie (`updated_at>=run_start`,
  tj. Traffit-zmienieni, których faza candidates właśnie upsertowała), NIE 45-dniowe
  okno (bo edycje w Nexusie bumpują `updated_at` wszystkich 49k → 2.7h zbędnych calli).
  Pobiera tylko brakujące `file_id` (po `external_id`).
- **Idempotencja**: każdy zapis `ON CONFLICT (external_source, external_id)`;
  notatki przez `(candidate_id, created_at)`. Brak DELETE — hard-delete w Traffit
  wychodzi w licznikach tygodniowego reconcile, nie jest auto-aplikowany.

### Env vars (Coolify, runtime)

| Var | Default | Rola |
|---|---|---|
| `TRAFFIT_SYNC_ENABLED` | `false` | kill-switch |
| `TRAFFIT_SYNC_CHECK_INTERVAL_SECONDS` | `1800` | cadence budzenia loopa |
| `TRAFFIT_SYNC_HOUR_UTC` | `2` | godzina delty |
| `TRAFFIT_SYNC_FULL_WEEKDAY` | `6` | dzień full reconcile (0=pon) |
| `TRAFFIT_SYNC_DELTA_LOOKBACK_HOURS` | `48` | overlap window |
| `TRAFFIT_SYNC_INITIAL_BACKFILL_DAYS` | `45` | zasięg pierwszej delty |

Sekrety (`TRAFFIT_TENANT`, `TRAFFIT_CLIENT_ID`, `TRAFFIT_CLIENT_SECRET`,
`TRAFFIT_THROTTLE_RPS`) — bez zmian, czytane przez `TraffitConfig.from_env()`.

## Aktywacja (turn it ON)

1. Coolify env vault: `TRAFFIT_SYNC_ENABLED=true` (secrety Traffita już są z migracji).
2. Redeploy / restart kontenera.
3. `/api/health.checks.traffit` powinno być `degraded` (włączony, jeszcze nie ruszył),
   NIE `unconfigured`/`misconfigured`.
4. `POST /api/admin/traffit/sync?mode=delta` (admin) → pierwszy run (45d backfill).
5. `GET /api/admin/traffit/sync/status` → watermark + per-phase stats.

## Weryfikacja

- Unit: `pytest tests/test_traffit_sync.py tests/test_traffit_mappers.py` (132 passed).
- Po pierwszym delcie: `notes.max(created_at)` rośnie; kandydat z nową notatką Traffita
  widzi ją w zakładce „Notatki"; świeżo zmieniony kandydat ma nowy plik w „Pliki";
  drugi run delty → `inserted≈0` (idempotent).

## Znane ograniczenia

- `author_id` notatek jest best-effort (mapa po emailu) i niemutowalny po wstawieniu
  (jak dziś). Tygodniowy full nie duplikuje (dedup po `created_at`).
- Delta dla plików łapie nowe `file_id`; podmiana o tym samym `file_id` (rzadkie)
  wymaga full reconcile.
- Day-granular filtr + 48h lookback: delta re-skanuje ~2-3 dni zmian dziennie (tanie,
  idempotentne).

---

## Fix 2026-08-03: bloker `candidate_activities` ReadTimeout → permanentny `degraded`

### Objaw
Od 2026-07-20 `checks.traffit=degraded`, a od ~2026-07-27 nowe notatki z Traffita
przestały przybywać. 14 z 16 faz syncowało się poprawnie; blokowała jedna faza.

### Root cause (potwierdzony)
- Read timeout klienta = zahardkodowane **30 s** (`TraffitConfig.timeout_s`), a pętla
  retry w `_get_raw` **nie łapała wyjątków transportowych** — `httpx.ReadTimeout`
  z `await self._http.get(...)` leciała od razu w górę (choć proxycurl/m365 je łapią).
- Pętla paginacji w `import_candidate_activities` była **nieopakowana** → timeout
  wychodził z fazy → generyczny `except` orkiestratora stemplował `error` i **pomijał
  blok kwarantanny/summary**. `promote_notes` stoi **za** pętlą → pomijana → brak notatek.
- `since` dla delty liczone z globalnego `__daily__`. Bo watermark zamrożony, okno
  activities rosło codziennie (~16+ dni) → fetch coraz większy → timeout się powtarzał
  (błędne koło). Activities to największy feed (~43k wierszy).

### Stage 1 — klient (rdzeń, zdejmuje `degraded`) — `backend/app/services/traffit/client.py`
- **Split timeout**: `httpx.Timeout(timeout_s, connect=connect_timeout_s, read=read_timeout_s)`
  — read domyślnie **180 s** (przeciska duże strony catch-upu), connect ciasny 10 s.
  Nowe pola `TraffitConfig.connect_timeout_s`/`read_timeout_s`, czytane w `from_env()`
  z `TRAFFIT_READ_TIMEOUT_S`/`TRAFFIT_CONNECT_TIMEOUT_S` (konwencja: NIE w `Settings`).
- **Retry transportu**: `_get_raw` łapie `httpx.TransportError`, backoff `2**attempt`,
  re-raise po wyczerpaniu. Automatycznie obejmuje też fazę `pipelines` i poller
  `candidate_contact_traffit` (dzielą klienta).

### Stage 2 — importer (odporność) — `backend/app/services/traffit/importer.py`
- Pętla activities opakowana wewnętrznym generatorem łapiącym `(httpx.TransportError,
  RuntimeError)`: częściowy batch commitowany, `promote_notes` płynie z zacommitowanych
  wierszy, zapisywany **nieatrybuowalny** błąd (zamraża watermark → ogon re-coverowany
  następnego biegu). Faza **zwraca** zamiast rzucać → nie omija kwarantanny.
- Probe `total_count` już nie robi early-return przy timeoucie (nie pomija importu+notatek);
  jego błąd jest **tylko logowany** (nie liczony jako blokujący `errors`), więc czysty bieg
  z wolnym probe nie zamraża watermarku.
- **Uwaga:** Stage 2 sam nie zdejmuje `degraded` (błąd nieatrybuowalny blokuje aż do
  pełnego przejścia) — to Stage 1 pozwala biegowi się dopiąć; Stage 2 trzyma notatki
  i utrwala częściowy postęp w trakcie przejścia.

### Stage 3 — wznawialna paginacja (spike, ODŁOŻONA — gated na API)
Discovery (desk): **brak dowodu** że Traffit `X-Request-Filter` wspiera numeryczne
`id >` i AND wielu pól — całe użycie w repo to pojedynczy `created_at/updated_at >=`.
Plan dwukierunkowy jedynie *aspiruje* do kursora `(timestamp, id)` (§ reconcile). Live
probe wymaga tenant creds → **do wykonania przy aktywacji sandboxa** przed wyborem
Opcji A (kursor `id`) vs B (checkpoint strony) + budżet per-run. NIE jest potrzebna do
zdjęcia obecnego `degraded` (Stage 1 wystarcza: po pierwszym pełnym biegu okno wraca do 48h).

### Testy
- `tests/test_traffit_client_timeout.py` (nowy): retry-then-success, reraise-po-wyczerpaniu,
  from_env split timeout, domyślne wartości.
- `tests/test_traffit_activities_partial.py` (nowy): timeout mid-stream → faza zwraca
  `PhaseProgress` (nie rzuca), `errors≥1` nieatrybuowalne, partial commit, notatki promowane;
  timeout probe → import+notatki dalej biegną.
- `tests/test_traffit_watermark_on_failure.py`: + przypadek „niekompletna paginacja
  activities zamraża watermark".
- Lokalnie (Docker `nexus-deps-test:pytest`, Python 3.13): **43 passed** na testach
  dotyczących zmiany, ruff czysty. Testy DB-integracyjne (pipelines/cortex) wymagają Postgresa
  (CI) — nie dotyczą zmienionych ścieżek.

### Rollout / weryfikacja prod (po merge)
1. Merge → Coolify build. Nowy `read_timeout` domyślnie 180 s (env override opcjonalny).
2. `POST /api/admin/traffit/sync?mode=delta` (admin) → obserwuj `GET /sync/status` aż
   `candidate_activities` ma `errors=0`.
3. `GET /api/health.checks.traffit` → `healthy` (po pełnym biegu). `notes_promoted > 0`.

---

## Fix 2026-08-10: „w Nexusie mniej CV niż w Traffit" — full reconcile omijał kandydatów z plikami

### Objaw
Pytanie Artura: skoro sync chodzi codziennie, czemu w Nexusie jest wyraźnie mniej CV
niż w Traffit? Prod `/api/health.checks.traffit` = **`healthy`** — czyli sync NIE był
zepsuty. Health mierzy wyłącznie świeżość ostatniego `__daily__`
(`last_run_finished_at` < 36 h + `last_status='ok'`, `main.py`), **nie kompletność
plików** — dlatego zielona sonda i realna luka współistniały bez alarmu.

### Root cause (potwierdzony w kodzie)
`import_candidate_files` w trybie **full** wybierał kandydatów bramką
`HAVING count(cd.id) = 0` — czyli **tylko tych z zerem plików**. Posiadanie
jakiegokolwiek dokumentu było więc **trwałym zwolnieniem ze sweepu**:

- kandydat, któremu migracja (maj 2026) pobrała 2 z 5 plików — reszta padła na
  `/content` non-200 albo timeoucie — **nigdy nie był oglądany ponownie**;
- **delta** go nie ratuje, bo jej scope to kandydaci zmienieni w Traffit
  (`updated_at >= run_start`), a rekordy historyczne się nie zmieniają;
- **full** go nie ratuje, bo ma ≥1 plik → wypada z `HAVING count=0`.

Luka była więc **strukturalnie niedomykalna** — żadna częstotliwość syncu jej nie
zasypie. Dodatkowo full reconcile bywał historycznie blokowany (ReadTimeout na
`candidate_activities` do 2026-08-03, kolizja primary-CV), a wielogodzinny bieg
ubija każdy redeploy Coolify — wtedy start dopiero w kolejną niedzielę.

### Zmiana — `backend/app/services/traffit/importer.py`
- Full przemiata **wszystkich** kandydatów Traffita (`c.id > :after_id ORDER BY c.id
  LIMIT :limit`), bez bramki na liczbę dokumentów. Pobiera nadal **wyłącznie
  brakujące `file_id`** (preload `existing_docs` po `external_id`), więc kandydat
  kompletny kosztuje jeden listing `/files` i **zero** transferów `/content`.
- Pełny sweep to ~49k calli `/files` (~2,7 h przy `TRAFFIT_THROTTLE_RPS=5`) — dłużej
  niż odstęp między redeployami, więc skan jest **budżetowany**
  (`TRAFFIT_SYNC_FULL_FILES_LIMIT`, default 10000) i **wznawialny**: kursor
  `{"after_id": N}` w `traffit_sync_state.cursor_payload`, na wierszu fazy
  `candidate_files` (nazwa z `_phase_plan`, **nie** `PhaseProgress.phase`
  = `candidates_files` — inaczej UPSERT założyłby drugi, widmowy wiersz w
  `/sync/status`). Reużyte helpery `_read/_write/_clear_sync_cursor` (Stage 3).
- Kursor zapisywany **w tej samej transakcji** co dokumenty, które rozlicza (co 50
  kandydatów + w transakcji zamykającej) — przerwany bieg nie zgłasza postępu,
  którego nie utrwalił.
- **Krótszy batch niż budżet ⇒ koniec przebiegu ⇒ kursor kasowany** (także przy
  pustym batchu). Bez tego kursor zaparkowałby na końcu tabeli i faza stałaby się
  trwałym no-opem — dokładnie ta klasa błędu, którą fix usuwa.
- Delta **bez zmian** i bez dostępu do kursora (redeploy-driven delta nie może
  przewinąć reconcile'u ponad kandydatów, których nie obejrzała).

### Konsekwencja operacyjna
Zaległość domyka się szybciej **wielokrotnym** `POST /api/admin/traffit/sync?mode=full`
— każdy bieg przesuwa kursor o kolejny budżet, zamiast czekać tydzień na jeden slice.

### Testy
`backend/tests/test_traffit_files_full_sweep.py` (nowy, 6 przypadków): regresja
(kandydat z plikiem JEST odwiedzany, dociągany tylko brakujący plik), budżet +
zapis kursora, wznowienie z kursora i skasowanie po domknięciu przebiegu, kursor
za ostatnim kandydatem też kasowany, staging kursora w trakcie biegu (co 50),
delta nie rusza kursora.

### Uwaga na przyszłość
`checks.traffit=healthy` **nie jest** dowodem kompletności — to sonda świeżości.
Kompletność mierzy się porównaniem liczników, np.
`count(candidates WHERE cv_storage_key IS NOT NULL)` + `candidate_documents` vs
Traffit. Uwaga przy liczeniu: **primary CV siedzi w `candidates.cv_storage_key`**,
a nie w `candidate_documents` — liczenie samych wierszy `candidate_documents`
zaniża wynik i samo w sobie potrafi wyglądać jak „brakujące CV".
