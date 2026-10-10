# Healthcheck endpoint

- **Zewnętrzne sondy i alerty:** stan oraz konfiguracja Grafana Synthetic
  Monitoring są opisane w `docs/uptime-monitoring.md`.
- **Standard URL:** `/api/health` z full shape `{status, version, deployedAt, checks: {database}}` (Faza 1.B done 2026-04-29, PR #61).
- **Legacy URL:** `/health` zachowane jako alias (uptime-probe.yml legacy compat).
- **Implementation:** `app/main.py` (`/api/health` z DB ping z 2s timeout).
- **Compose healthcheck = `/api/health/live`, NIE `/api/health` (od 11.09.2026).**
  `/live` odpowiada, że proces obsługuje żądania — bez bazy, puli, locków i sond
  zewnętrznych. Pełne `/api/health` robi kilkanaście zapytań z timeoutami i przy
  ciężkim pełnym przeglądzie bazy trzy razy z rzędu nie mieściło się w 5 s: Docker
  oznaczał DZIAŁAJĄCY backend jako unhealthy, Traefik zdejmował go z ruchu („no
  available server”). `/api/health` zostaje sondą smoke testu po deployu i
  uptime-probe. Sonda w `docker-compose.yml` (jedyny plik czytany przez Coolify)
  i w overlayu prod musi być ta sama.
- **Naprawy schematu przy starcie mają `lock_timeout` 10 s** (`startup_locks.py`,
  moduły `allocation_schema_bootstrap`, `cv_schema_bootstrap`,
  `signature_policy_bootstrap`). Nocny `pg_dump` trzyma locki, a DDL czekający bez
  limitu wieszał boot. Timeout zatrzymuje start tylko wtedy, gdy schemat NAPRAWDĘ
  jest niekompletny. Polityka podpisów jest miękka WYŁĄCZNIE przy timeoucie zamka
  (SQLSTATE 55P03); każdy inny błąd zatrzymuje start jak dawniej.
- **`checks.m365` (`services/m365_health.py`, od 09.2026) nie patrzy na wiek
  `last_sync_at`** — każda nieudana próba go odświeża, a pętla ponawia co 30 min,
  więc skrzynka w błędzie od tygodni wyglądała na świeżą. `degraded` = brak
  aktywnego połączenia ALBO aktywna skrzynka, której ostatnia próba padła, ALBO
  połączenie wyłączone przez awarię (`is_active=False`) u aktywnego pracownika.
  Odłączenie przez użytkownika kasuje wiersz, więc nieaktywny wiersz to zawsze
  awaria. Sonda jest informacyjna — nie daje `unhealthy`.
- **`checks.m365_mail` pyta o wysyłkę app-only, niezależnie od synchronizacji
  skrzynek rekruterów.** Stan i blokada ponowień żyją w `mail_delivery_state`
  (0331), per hash tenanta/aplikacji/nadawcy; restart nie resetuje awarii.
  403/odrzucone uwierzytelnienie: pojedyncza próba odzyskania po 15 minutach;
  401: najpierw jedno odświeżenie tokenu. 429 respektuje `Retry-After`.
  Sentry dostaje zmianę stanu, pełne próby liczy `app_mail_outcome`, a niezależny
  `app_mail_monitor` co minutę mierzy awarię, zaległość i niepewne wysyłki.
  `email_delivery_uncertain` chroni chat fallback przed duplikatem po utracie
  odpowiedzi/crashu. Nie czyścić tej flagi bez ustalenia wyniku dostawy.
  `unknown` nie jest sukcesem; sonda nie zmienia liveness ani routingu HTTP.

- **`checks.compass_lifecycle` (od 14.09.2026, MON-04/INT-10):** pętla
  `compass_lifecycle_sync` stempluje każdy bieg w `app_settings['compass_lifecycle_state']`
  (`last_run_at`, `last_status`, `last_success_at`, `last_error` = kod + klasa
  wyjątku, bez URL/treści); sonda: `unconfigured` (wyłączona) / `misconfigured`
  (brak URL/sekretu) / `degraded` (ostatni bieg padł albo brak sukcesu > 2
  odstępy pętli) / `healthy`. Informacyjna — nie daje `unhealthy`. Zapis jest
  scaleniem jsonb, więc nie kasuje mapy `exit_since` per osoba.
- **`GET /api/admin/traffit/sync/status` niesie `freshness` per faza i
  `phases_stale`** (INT-09): progi po TYPIE fazy (zwykłe 36 h, kursorowane/
  budżetowane 72 h, znacznik `__full__` 8 dni); `checks.traffit` nadal czyta
  wyłącznie `__daily__` — to sonda świeżości importu, nie kompletności.
- **Deploy sprawdza wersję FRONTENDU** (DEP-03): `frontend/public/version.json`
  pisany przez `scripts/write-version.mjs` przed `next build` (SHA z build arga
  `NEXT_PUBLIC_GIT_SHA`), smoke wymaga równości z wersją przyjętą przez smoke
  backendu (ACCEPTED_SHA); `sha: "unknown"` = build bez arga = czerwony deploy.
  Podsumowanie joba pokazuje TARGET_SHA, RELEASE_SHA, ACCEPTED_SHA i SHA
  serwowane przez backend/frontend.
- **`checks.migrations` (DEP-02, od 15.09.2026):** `entrypoint.sh` zapisuje wynik
  `alembic upgrade heads` do `/tmp/nexus-alembic-status.json` i NADAL nie
  zatrzymuje startu (brak rolling update = exit 1 to pętla restartów). Nieudany
  upgrade daje `logger.error` przy starcie (→ Sentry) i `checks.migrations`
  `degraded` (gdy siatka domknęła schemat i rewizje się zgadzają) albo
  `unhealthy` (rozjazd bookmarku bazy z heads kodu → issue z uptime-probe). Logika porównania rewizji jest JEDNA (`services/migration_health.py`) —
  czyta ją również `/api/health/alembic`. Nie dopisuj `exit` do bloku alembica
  (test `test_migration_health.py` go wykonuje).
- **`checks.background_tasks` zna zawieszone pętle (MON-04, od 15.09.2026):**
  krytyczne pętle robią `beat.tick()` na początku iteracji
  (`services/loop_heartbeat.py`, w pamięci procesu — backend to jeden uvicorn);
  cisza dłuższa niż próg pętli = `unhealthy: stalled a,b` (od 22.09.2026 →
  issue z joba `health-checks` w uptime-probe; tydzień 15–22.09 w `degraded`
  dał 0 × `stalled` na 43 odczytach; `status`/503 nadal zależy tylko od bazy;
  wartość składa `loop_heartbeat.health_value`). Nowa pętla w
  `app.state.background_tasks` musi mieć heartbeat albo wpis w `EXEMPT`
  z powodem (`test_loop_heartbeat.py`). Progi obejmują najdłuższy bieg (Traffit
  full: 12 h ponad interwał).
- **Uptime probe:** `.github/workflows/uptime-probe.yml` — cron na `/api/health` z `jq -e '.status != "unhealthy"'`. GitHub uruchamia „godzinowy” cron co 1–6 h, więc to NIE jest sonda dostępności — od tego jest zewnętrzna sonda Grafana Synthetic Monitoring (MON-05). Awaria joba `probe` albo `backup-freshness` z crona otwiera issue (job `alert`), tak jak `health-checks`, restore drill i digest Sentry.
- **E2E po deployu (MON-02):** `e2e.yml` biegnie po każdym udanym Deploy z projektem `prod-smoke` (odczyty po zalogowaniu, bez `@stack`/`@writes`), gdy zmienna repo `E2E_POST_DEPLOY_ENABLED=true` (włączyć PO założeniu konta E2E; bez konta bieg jest czerwony + issue). Produkcja jest SSO-only (`/api/auth/methods` → `password:false`), więc `/login` nie ma formularza hasła: setup loguje się wtedy przez API i oddaje token sondzie sesji (`e2e/helpers/session.ts`), a adres konta E2E musi być na `PASSWORD_LOGIN_BREAK_GLASS_EMAILS`.
- **GIT_SHA / BUILT_AT:** SHA pochodzi z tagu obrazu budowanego przez Coolify (`release.sh` → `/app/.nexus-build-sha`, #1524), nie z env `$SOURCE_COMMIT`.
