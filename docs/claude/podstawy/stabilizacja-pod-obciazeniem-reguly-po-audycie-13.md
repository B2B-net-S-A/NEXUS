# Stabilizacja pod obciążeniem — reguły po audycie 13.09 i reaudycie 14.09.2026

<!-- indeks: deploy = przerwa dla użytkowników, ponowienia HTTP, polling, single-flight cache, eksport XLSX, uploady -->

Audyt `docs/performance-and-availability-audit-2026-09-13.md`, reaudyt
`docs/performance-and-availability-reaudit-2026-09-14.md` i dwa PR-y naprawcze
ustaliły reguły, które łatwo cofnąć „przy okazji”:

- **„No available server” to przede wszystkim DEPLOYE, nie obciążenie.** Oba
  zarejestrowane 503 frontendu (06.09 18:13, 08.09 06:21 UTC) wypadły w trakcie
  deployu; 31.08–11.09 było 81 przebudów produkcji w godzinach pracy (do 17
  dziennie). Codex zmierzył to wprost przy deployu #1509 (14.09): frontend
  ~105 s „no available server”, API ~52 s 502/503, przy zielonym workflow.
  Dopóki nie ma bezprzerwowego deployu, merguj na `main` poza godzinami pracy
  albo zbieraj zmiany w jeden merge.
- **Każdy deploy raportuje przerwę widzianą przez użytkowników** (krok „Report
  user-facing downtime” w `deploy.yml`: sonda `/login` + `/api/health/live` co
  ~2 s, tabela w podsumowaniu biegu, `::notice::` z najdłuższą przerwą). To
  jedyna liczba mówiąca, czy prace nad ciągłością (F03) działają — nie usuwaj.
- **Frontend w `docker-compose.yml` NIE zależy od backendu** (bez `depends_on`).
  Zależność od zdrowego backendu zatrzymywała frontend na cały czas migracji
  przy każdym deployu. Pilnuje tego `test_delivery_contract.py`.
- **Czas faz startu backendu jest w logach kontenera** (`[startup-timing]` z
  `entrypoint.sh`, także podfazy siatki DDL). Zanim skrócisz start, sprawdź tam,
  co naprawdę trwa. Deploy sam je odczytuje (krok „Czasy faz startu backendu”,
  notice „Start backendu”), a ręcznie: `coolify-ops.yml` → `startup-timing`
  (skrypt przepuszcza WYŁĄCZNIE linie `[startup-timing]` — logi Actions są publiczne).
- **Raport przerwy (`.github/scripts/deploy_downtime_report.py`) podaje frontend
  i API osobno oraz „Postgres restartował”** — porównanie
  `postgres_started_at` z `/api/health/deep` przed webhookiem i po smoke teście.
  To pole jest informacją, nie sondą: nie wchodzi do `checks`.
- **Backend zamyka się łagodnie przy deployu:** `UVICORN_TIMEOUT_GRACEFUL_SHUTDOWN=8`
  (uvicorn czyta opcje z env) + `stop_grace_period: 15s`. Nie wydłużaj limitu:
  stary kontener czekający na długie żądanie wydłuża przerwę wszystkim.
- **Odczyt bez odpowiedzi widocznej dla przeglądarki ponawia się ≈ 22 s**
  (`NETWORK_READ_RETRY_MAX` w `lib/api.ts`, tylko GET/HEAD/OPTIONS i tylko online) —
  tak wygląda restart API. Zapisy i odpowiedzi 5xx z CORS zostają przy dwóch próbach.
- **`runtime_metrics` co minutę w Loki** (`app/tasks/runtime_metrics_monitor.py`):
  opóźnienie pętli zdarzeń, szczyt wypożyczonych połączeń, czas wypożyczenia
  jednego połączenia. To dane do decyzji o puli i procesach (F06) — zanim
  zmienisz `pool_size`/`max_overflow`, spójrz na nie. Połączenia mają
  `application_name=nexus-backend` w `pg_stat_activity`.
- **Błąd ładowania chunka JS przeładowuje stronę raz** (`lib/chunk-reload.ts`,
  `ChunkReloadGuard` w layoucie + `app/error.tsx`) — stara karta po deployu.

- **Ponowienia HTTP należą do interceptora axios (`lib/api.ts`), nie do react-query.**
  `QueryProvider` ma `retry: 0`. Druga warstwa mnożyła jeden odczyt do 6 żądań przy
  503 z bramy. Zapisy ponawiane są WYŁĄCZNIE na 502/503 z realną odpowiedzią — tej
  logiki nie ujednolicaj z odczytami (test `api-transient-retry.test.ts`). Żaden
  komponent nie ustawia własnego `retry: N>0` (pilnuje `QueryProvider.test.tsx`).
  `Retry-After` NIE jest czytany: CORS go nie wystawia, więc byłby martwym kodem.
- **Interwały odpytywania w tle są stałymi w `frontend/src/lib/polling.ts`.** Dzwonek,
  KPI i sekcje dashboardu to siatka bezpieczeństwa pod WebSocketem (5 min), nie źródło
  świeżości. Do 09.2026 sam otwarty dashboard robił ~9,5 GET/min na kartę bez klikania.
  Nowy `refetchInterval` w komponencie shellu/dashboardu = import stałej stamtąd.
  Rzadki polling działa tylko dlatego, że powrót gniazda (`useNotifications`,
  `onopen` po zerwaniu) odświeża powiadomienia i KPI — nie usuwaj tego odświeżenia.
  Ponowne łączenie ma rozrzut 50–100% (`reconnectDelayMs`), fallback pomija ukrytą kartę.
- **Insights nie ma już długich stron z paskiem sekcji** (przebudowa 24.09.2026):
  widoki są krótkie, a rzadkie treści żyją w osobnych raportach
  (`?tab=raporty&report=`), więc `DeferUntilVisible`, `InsightsSectionNav`
  i `lib/anchor-pin.ts` usunięto. Nie wracaj do jednej strony z kilkunastoma
  sekcjami — to ją trzeba było doczytywać leniwie i przypinać kotwice.
- **Drogi snapshot pod jednym kluczem cache liczy jeden wykonawca:** `cache_single_flight`
  z `app/core/cache.py` (podwójne sprawdzenie w środku) + `jitter_seconds` w `cache_set`.
  `_lock` w tym module chroni słownik, nie obliczenie. Przekazuj `db=db`: oczekujący
  przy kontencji oddaje połączenie do puli (`release_idle_connection`). Helper wołaj
  WYŁĄCZNIE po fazie tylko do odczytu; i tak odmawia, gdy transakcja mogła coś zapisać
  (`session_has_uncommitted_writes`: zmiany ORM, wykonany `flush()` albo instrukcja inna
  niż SELECT — znacznik z eventów `Session` w `core/database.py`). `rollback()` odpada,
  bo wygasza `current_user`. Całe ciało `cache_single_flight` po zwiększeniu licznika
  jest w `try/finally` — anulowanie w trakcie oddawania sesji nie może zostawić blokady.
- **KPI zespołu HoR: `metrics.team_kpis(..., operational_roles_only=False)`.** Roster
  jest ustalany po WSZYSTKICH rolach (`has_any_role`); filtr głównej roli wycinał np.
  TCM z dodatkową rolą recruiter. Brak wiersza którejkolwiek osoby z rosteru = sekcja
  `partial`, nie niższa suma.
- **Demandy priorytetów serializuj hurtowo (`_serialize_demands`)** — stała liczba
  zapytań; `_serialize_demand` to nakładka dla pojedynczego wiersza. Wersja per wiersz
  wołana bez `current_assignments` ładowała cały plan dla każdego demandu.
- **Eksport XLSX buduje `_build_xlsx_bytes` w `asyncio.to_thread`**, na małych wierszach,
  nie na ORM; `GET /api/candidates/export` jest legacy bez konsumenta i dzieli pomocniki
  z `POST`. `UPDATE candidate_documents … document_kind='cv'` w `entrypoint.sh` MUSI mieć
  `IS DISTINCT FROM 'cv'` — bez tego przepisuje ~136 tys. wierszy na każdy deploy.
- **Pliki robocze uploadów: `tempfile.NamedTemporaryFile`, nigdy nazwa z przeglądarki.**
  `from-cv` do 09.2026 dzielił jedną ścieżkę między równoległymi żądaniami o tej samej
  nazwie pliku (kolizja treści CV). Upload czytaj przez `_read_upload_bounded`
  (limit + 1 bajt), nie `await file.read()` — API nie stoi za Cloudflare, więc nic
  wcześniej nie tnie ciała żądania.
- **Błędy zapytań i mutacji react-query raportuje `lib/query-error-telemetry.ts`**
  (QueryCache/MutationCache w `QueryProvider`): tylko sieć/timeout/5xx, syntetyczne
  zdarzenie bez treści żądania, próbka 10% z deduplikacją. ChunkLoadError jest w Sentry
  próbkowany (5%), nie ignorowany — to pomiar wpływu deployów na otwarte karty.

Świadomie poza tym PR-em (wymagają decyzji i pracy w Coolify): wydzielenie workera
(4 moduły pętli piszą na WS przez in-process manager), deploy bez przerwy (compose build
pack Coolify nie ma rolling update), budżet pul przy drugim procesie.
