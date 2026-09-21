# CLAUDE.md — NEXUS (ATS)

> Per-app deviations od globalnego standardu w `~/.claude/rules/deployment.md`.
> Plik ładowany automatycznie przy każdej sesji Claude'a w tym repo.

## Stack & ports

- **Backend:** FastAPI 0.115 + SQLAlchemy 2.0 (async, asyncpg) + Alembic — `backend/`, port 8000.
- **Frontend:** Next.js 15.1 (App Router, React 19, TypeScript 5.7) — `frontend/`, port 3000.
- **Database:** Postgres 16-alpine (compose service) + Qdrant (vector DB, embeddings przez Voyage AI).
- **Auth:** JWT + RBAC.
- **Local AI:** Ollama (llama3.2) — opcjonalnie, dla offline pracy.
- **Test:** pytest + pytest-asyncio (BE) + Vitest + Playwright (FE).
- **Sentry:** `sentry-sdk[fastapi]` w `backend/requirements.txt` (status w prod do potwierdzenia).

**Specyfika:** **monorepo** z dwoma podkatalogami `backend/` + `frontend/`, każdy ze swoim Dockerfile i package mgr.

## Nazewnictwo: „Rekrutacja", nie „Oferta" (moduł `/jobs`)

Sekcja `/jobs` nazywa się w UI **„Rekrutacje"** (do 2026-08-10 część powierzchni
mówiła „Oferty", część już „Rekrutacje" — rail otwartych kart, zakładka profilu
kandydata). Ujednolicone: w interfejsie i w komunikatach API zlecenie
rekrutacyjne to **rekrutacja**.

- **Warstwa techniczna zostaje po angielsku** — route `/jobs`, `/api/jobs`,
  tabela `jobs`, kolumny `job_id`, nazwy plików (`JobsListV2.tsx`). Tak jak
  `/candidates` przy „Kandydaci". Nie zmieniaj URL-i: powiadomienia mają
  `link="/jobs/{id}"` **zapisane w bazie** (`job_deadline_alerts.py`,
  `job_chat.py`, `activities.py`) — zmiana routingu zepsułaby historyczne wpisy.
- **Słowo „oferta" ZOSTAJE tam, gdzie znaczy co innego** i nie wolno go tykać:
  etap pipeline'u złożenia propozycji kandydatowi (`offer_sent`,
  `offer_accepted`, „Oferta wysłana/zaakceptowana", „Wycofał się PO akceptacji
  oferty"), status kandydata `open_to_offers` („Otwarty na oferty"), szablon
  maila „Oferta współpracy", oferty handlowe w dynareporterze, oraz treść maila
  wychodzącego do kandydata („Oferta pracy: {tytuł}" — odbiorcą jest kandydat,
  nie rekruter).
- **Prompty LLM (`services/llm_prompts.py`) celowo nietknięte** — „Kontekst
  oferty:" zostaje. Zmiana treści promptu zmienia zachowanie modelu i
  unieważnia cache oparty o hash promptu, bez zysku dla użytkownika.

## Rola `finance` = pełny odczyt biznesowy (decyzje Artura 19.08 i 31.08)

Rola `finance` ma organizacyjny odczyt wszystkich danych biznesowych: kandydatów,
rekrutacji i pipeline'u, klientów wraz z kontaktami/notatkami/materiałami i
dokumentami prawnymi, kontraktów/stawek/zamówień/wykonawców, Cortex/Insights,
raportów, eksportów, czatów audytowych oraz odczytowych sekcji DynaReportera.
Zakres nie zależy od membershipu oferty, przypisania klienta ani
`allowed_sections`; sekcja techniczna DynaReportera `admin` pozostaje wyłączona,
a płatna akcja MINDY nadal wymaga jawnego wpisu w `allowed_sections`.

**Odczyt nie nadaje prawa zapisu.** Nowe powierzchnie Finance muszą używać
dedykowanych read dependencies i read-scope helpers, nigdy globalnego dopisania
roli do `AdminUser`, `TacPlus`, membership command guardów ani mutacji domenowych.
Istniejące przed decyzją 31.08 operacyjne prawa Finance (m.in. tier
`RecruiterPlus`, akcje kandydackie/kalendarzowe i lifecycle zamówień) pozostają
bez zmian; ten kontrakt nie może ich po cichu odebrać. Mutacje techniczne
(użytkownicy/role/konfiguracja/backfille), kuratela Cortexa i sekcja `admin`
pozostają Admin-only, a zapisy finansowe nadal wymagają właściwej capability
`manage_finance`/`approve_finance`.

Wyłączność konta Finance (CHECK `ck_users_exclusive_finance_viewer_roles`) i
bramka własnego modułu Finanse pozostają bez zmian. Historyczne komentarze o
„finance-safe", person-free projections albo Finance „jak recruiter" opisują
stan sprzed decyzji 31.08 i nie są źródłem polityki.

## Design system & UI — ZAWSZE przy pracy nad wyglądem

Przy **każdej** pracy nad UI/UX/designem (nowy ekran, komponent, reskin, layout, login, landing) **ZAWSZE** korzystaj z dwóch kupionych bibliotek (konto `artur.twardowski@b2bnetwork.pl`, zalogowane w Chrome — używaj Chrome MCP):

- **Tailwind Plus** (`tailwindcss.com/plus`, all-access) → **application UI**: shell, dashboardy, tabele, formularze, page headers. Kod kopiujesz z zalogowanej sesji Chrome i **ADAPTUJESZ na tokeny** (to Tailwind v4 + `@tailwindplus/elements` — NIE wklejaj verbatim, przepisz hardcoded `text-gray-*`/`bg-indigo-*` na semantyczne tokeny).
- **shadcnblocks ELITE** (registry `@shadcnblocks` w `frontend/components.json`, klucz w gitignorowanym `frontend/.env.local`) → **marketing / login / landing / onboarding** (bloki sekcyjne). NIE do kompaktowych dashboardów — od tego Tailwind Plus.

Firmowy design system jest na tokenach (slate+indygo, 7 palet, dark/soft/kids) — **token-first, nigdy hardcoded kolory**. Wzorzec dla wszystkich 4 apek (Compass/Atlas/ELEVATE = ten sam kanon). Kluczowe ścieżki:
- **Kit komponentów:** `frontend/src/components/ds/` (StatCard, DataTable, PageHeader, FilterBar, AppModal, EmptyState, Leaderboard/Podium, MatchCard, Kanban, TabbedNav, FormGroup, FunnelChart). Bloki: `frontend/src/components/blocks/` (AuthShell — split-screen login). Prymitywy shadcn: `frontend/src/components/ui/`.
- **Tokeny:** `frontend/src/app/globals.css` + `frontend/tailwind.config.ts`. `--accent` = subtelny neutral (hover), **NIE** brand → emfaza zawsze przez `--primary`.
- **Workflow + cheatsheet color→token: `frontend/docs/ds/ADDING-BLOCKS.md` + `frontend/scripts/add-block.sh` — PRZECZYTAJ przed dodaniem jakiegokolwiek bloku/prymitywu.**
- **Gotchas:** (1) NIE `npx shadcn add` — przeformatowuje `tailwind.config`, remapuje `--sidebar`→`--sidebar-background`, bumpuje deps; pobieraj pliki z rejestru bezpośrednio (`add-block.sh`). (2) Jeśli bump radix wywali type-check na `@hello-pangea/dnd` „`--radix-${string}`" → `"overrides": {"@radix-ui/react-primitive":"2.1.4"}` + **pełny** `rm -rf node_modules package-lock.json && npm install`. (3) **NIE** odpalaj `build` równolegle z `dev`/`start` (oba piszą `.next` → korupcja: unstyled/500).
- **Weryfikacja:** type-check/lint/build zielone + screenshot przez Chrome MCP. Publiczne ekrany (login) renderują się lokalnie; authed → harness `/preview/*` z mock danymi (middleware waliduje JWT, fake-auth nie przejdzie).

## Deploy

- **Hosting:** Coolify v4 self-hosted on Hetzner **CCX33 x86** (8 vCPU / 32 GB, 91.99.199.112). Zweryfikowane w konsoli Hetznera 20.07.2026 — wcześniejszy wpis „CAX21 ARM" był błędny i wysłał audyt 13.09 w niepotrzebne zastrzeżenia o typie hosta.
- **Coolify panel:** `https://coolify-nexus.dynaminds.pl` (HTTPS+LE, public via Traefik route — od 2026-05-04).
- **App UUID (Coolify):** `ocgkwcbovpve9wvf9smxl0kx`.
- **Registry:** **brak GHCR** — Coolify buduje obrazy lokalnie z compose `build:` block (jednolite z Compass + LeadGen).
- **Compose orkiestracja:**
  - `docker-compose.yml` — base z `build:` block (no port bindings, Coolify Traefik routuje przez `expose:`). **Limity pamięci (mem_limit) są TUTAJ** — Coolify czyta wyłącznie ten plik (docker_compose_location), więc limity trzymane w overlayu nigdy nie obowiązywały na prodzie (Memory=0, wykryte i naprawione 2026-08-12).
  - `docker-compose.override.yml` — dev (re-adds host port bindings, auto-loaded przez `docker compose up`).
  - `docker-compose.prod.yml` — prod overlay (ports/env/healthchecks — referencja do ręcznej symulacji prod; BEZ limitów zasobów).
- **Auto-deploy:** ✅ **TAK** — `git push origin main` → `.github/workflows/deploy.yml` (unified template, PR #68 merged 2026-05-04) → Coolify webhook → build + restart → smoke test.
- **Trigger:** push `main` → `.github/workflows/deploy.yml`.
- **Na produkcję wchodzi tylko commit z zieloną bramką (DEP-01, od 15.09.2026).**
  Coolify 4.1.2 buduje ZAWSZE HEAD maina — ignoruje nawet przypięty
  `git_commit_sha` (`check_git_if_build_needed` nadpisuje go `git ls-remote`;
  poprawione w 4.2.0), więc przypinanie nic nie daje. Zamiast tego
  `.github/scripts/select_release_sha.py`: job `select` puszcza deploy tylko
  przy zielonym „CI Gate” HEAD maina (bramka w toku = odroczenie, wdroży go
  jego własny przebieg; czerwona = wstrzymanie z ostrzeżeniem, ręczny dispatch =
  błąd), a smoke przyjmuje RELEASE_SHA albo jego POTOMKA z zieloną bramką
  (merge w trakcie budowy, czeka ≤ 10 min na bramkę w toku). Potomek z czerwoną
  bramką = czerwony deploy z instrukcją wycofania. Czerwony HEAD maina
  wstrzymuje deploye do następnego zielonego commitu — to zamierzone. Zmiana
  bramki deployu z „CI Gate” na „CI” wymaga zmiany `GATE_WORKFLOW` w skrypcie.
- **Rollback:** Coolify panel `https://coolify-nexus.dynaminds.pl` → Resources → nexus → Deployments → poprzedni → Redeploy.
- **Standardy + procedury:** patrz `~/.claude/rules/deployment.md` + `~/.claude/rules/deployment-runbook.md`.

## Healthcheck endpoint

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
  cisza dłuższa niż próg pętli = `degraded: stalled a,b`. Nowa pętla w
  `app.state.background_tasks` musi mieć heartbeat albo wpis w `EXEMPT`
  z powodem (`test_loop_heartbeat.py`). Progi obejmują najdłuższy bieg (Traffit
  full: 12 h ponad interwał).
- **Uptime probe:** `.github/workflows/uptime-probe.yml` — cron na `/api/health` z `jq -e '.status != "unhealthy"'`. GitHub uruchamia „godzinowy” cron co 1–6 h, więc to NIE jest sonda dostępności — od tego jest zewnętrzna sonda Grafana Synthetic Monitoring (MON-05). Awaria joba `probe` albo `backup-freshness` z crona otwiera issue (job `alert`), tak jak `health-checks`, restore drill i digest Sentry.
- **E2E po deployu (MON-02):** `e2e.yml` biegnie po każdym udanym Deploy z projektem `prod-smoke` (odczyty po zalogowaniu, bez `@stack`/`@writes`), gdy zmienna repo `E2E_POST_DEPLOY_ENABLED=true` (włączyć PO założeniu konta E2E; bez konta bieg jest czerwony + issue). Produkcja jest SSO-only (`/api/auth/methods` → `password:false`), więc `/login` nie ma formularza hasła: setup loguje się wtedy przez API i oddaje token sondzie sesji (`e2e/helpers/session.ts`), a adres konta E2E musi być na `PASSWORD_LOGIN_BREAK_GLASS_EMAILS`.
- **GIT_SHA / BUILT_AT:** SHA pochodzi z tagu obrazu budowanego przez Coolify (`release.sh` → `/app/.nexus-build-sha`, #1524), nie z env `$SOURCE_COMMIT`.

## Env vars (build-time vs runtime)

**Build args (FE):**
- `NEXT_PUBLIC_API_URL` (default `http://localhost:8000` w `docker-compose.yml`).
- `GIT_SHA`, `BUILT_AT` (po Fazie 1).

**Runtime env (BE — przez `.env` na serwerze, mapowany do compose `env_file:`):**
- `DATABASE_URL` (postgresql+asyncpg://...)
- `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` (na serwerze override DATABASE_URL przez compose service names)
- `SECRET_KEY` (JWT signing, min 48 chars)
- `CANDIDATE_IDENTITY_FINGERPRINT_KEY` (osobny, stabilny klucz HMAC; nie może być równy `SECRET_KEY`)
- `QDRANT_HOST`, `QDRANT_PORT`
- `VOYAGE_API_KEY` (embeddings)
- `SENTRY_DSN` (opcjonalnie)
- inne per feature

**Walka z surprise:** compose `env_file: .env` — wszystkie sekrety w jednym pliku na serwerze (Coolify env vault).

## CI gotchas

- **Najsilniejsze CI w stacku** (gitleaks + ruff + alembic + pytest + ESLint + tsc + Vitest + Codecov).
- **`needs: secret-scan`** — gitleaks musi przejść przed innymi jobami (świadomy guard).
- **Pytest selective:** wskazane konkretne pliki testów (5 plików), nie `pytest .` — bo cały suite ma live-server tests które są skipowane (`RUN_LIVE_TESTS=0`).
- **Lista `--ignore` w `ci.yml` = suma `_COLLECTION_ERRORS | _LIVE | _FAILING` w `test_ci_coverage_contract.py`** (kontrakt czyta workflow). Od 14.09.2026 (QA-06) `_FAILING` jest PUSTA — 12 czerwonych plików naprawiono (11 nieaktualnych kontraktów testów + 1 błąd produktu: dedup dzienny powiadomień targu wywracał cały skan). Od 15.09.2026 **0 wykluczeń**: 4 pliki live (`test_auth/candidates/jobs/pipeline`) przeniesione na in-process `app_client` z własnymi danymi, 2 „kolekcyjne” (`test_backfill_*`) zbierały się i przechodziły — powód był nieaktualny. Nowy czerwony test = napraw albo dopisz do właściwej kategorii Z POWODEM, nigdy samo `--ignore`. Test skryptu z `backend/scripts` importuj przez `from scripts import …`, nie przez `sys.path.insert(…/scripts)` — zagnieżdżony katalog `scripts/scripts/` trafia wtedy na początek ścieżki pakietu `scripts` i np. `scripts.eval_matching` ładuje się z niego.
- **Pokrycie backendu scala job `backend-coverage-combine`** (QA-01): shardy piszą `.coverage.shard-N` (linie **i gałęzie**, `--cov-branch` + `branch = True` w `.coveragerc`) jako artefakt; combine wymaga kompletu `EXPECTED_SHARDS` i porównuje wynik z **`.github/coverage-baseline.json`** skryptem `.github/scripts/coverage_gate.py` — spadek poniżej baseline − tolerancji = czerwony job, a wymagany kontekst „Backend (pytest)” czyta jego wynik. 80% zostaje progiem RAPORTOWYM. Frontend: `coverage.thresholds` w `vitest.config.ts` (Vitest sam kończy się błędem) + artefakt `frontend-coverage`. **Ratchet:** `::notice::` o wzroście = podbij baseline/progi w tym samym PR; obniżenie tylko z uzasadnieniem. Codecov tylko gdy `CODECOV_TOKEN` ustawiony.
- **Trivy blokuje** (QA-05, 15.09.2026): znalezisko HIGH/CRITICAL z dostępną poprawką (podatność zależności ALBO błędna konfiguracja Dockerfile — liczone są `Total:` i `Failures:`) = czerwony job „Trivy + hadolint”. Wyjątki WYŁĄCZNIE w `.trivyignore` z uzasadnieniem i `exp:RRRR-MM-DD` (pilnuje kontrakt). DS-0002 w `backend/Dockerfile` to fałszywy alarm (entrypoint robi `exec gosu appuser`). Hadolint zostaje advisory. Job nie jest jeszcze wymaganym kontekstem rulesetu — dopisuje go Artur.
- **E2E ma dwa cele** (QA-02/03, 15.09.2026): job `stack` w `e2e.yml` (PR + nocny) stawia `docker-compose.e2e.yml` (te same Dockerfile'e, pusta baza, konta ról z `backend/scripts/seed_e2e.py`) i uruchamia projekt `ci-chromium` = scenariusze z tagiem **`@stack`**; pominięty przypadek = czerwony bieg. Nocny job produkcyjny uruchamia `prod-smoke` (bez `@stack`/`@writes`) i `preview-chromium`. Wywołania API w scenariuszach idą przez `e2e/helpers/api.ts` (Bearer) — fixture `request` Playwrighta NIE niesie tokena z localStorage, więc dawne `request.post` dostawały 401, które przechodziły `status < 500`. Każdy scenariusz zakłada własne dane (`helpers/entities.ts`); asercja = dokładny status + ponowny odczyt. Otwarte przepływy: `docs/uat/09-backlog-scenariuszy-e2e.md` (zamiast `test.fixme`).
- **Testy generatora CV mają fixture `pipeline_mode` (`legacy`/`v10`)** (QA-07) dla trzech kontraktów; `test_cv_generator_legacy_v7.py` pilnuje domyślnego trybu produkcji.
- **M365 webhook: klucz replay = (subskrypcja, id zasobu, `changeType`), TTL 10 min, wpis PO udanym spawnie** (INT-02) — `created` i `updated` tej samej wiadomości oba przechodzą; padnięty spawn = brak wpisu, ponowienie Grapha zadziała.
- **Codecov flags:** `backend` + `frontend` — separate uploads.
- **Lint warnings cap:** `next lint --max-warnings=300` — historyczny dług, nie failować na obecnych warningach.
- **`npm ci --legacy-peer-deps`** w FE (React 19 + niektóre pakiety jeszcze RC).
- **40+ feature branches w remote** — przy `git checkout` weryfikuj że `main` pociągnięty (`git fetch && git log origin/main..HEAD`).
- **Minuty GitHub Actions są płatne od września 2026 — i to NEXUS je zjada.** Pula 50 000 min/mc organizacji `B2B-net-S-A` wyszła: rachunek za wrzesień to 47 273 min, rabat $0.00, $283,64 do zapłaty przy $0,006/min. Z tego **NEXUS to 46 784 min (99,3%)** — ATLAS 138, COMPASS 117, ELEVATE 92. Rozkład (zmierzone z jobów 16–20.09, pokrywa 91% kwoty): **CI 83,7%** (4 shardy pytest 14 470 min + frontend 3 677 min = 96% kosztu CI), E2E 8,9%, CI Gate 5,5%, Deploy 1,5%, crony 0,4%. Crony NIE są problemem — pięć dni roboczych fali naprawczej (14–18.09) to 42 565 min, czyli 90% miesięcznej puli; weekendy po 24–30 min. Cztery cięcia z 20.09, każde z kontraktem w `test_ci_deploy_workflows_contract.py`: (1) **pełne CI zdjęte z `push: main`** — od włączenia kolejki merge'ów `merge_group` waliduje DOKŁADNIE to drzewo, które ląduje na mainie, więc przebieg na push był trzecim wykonaniem tego samego kodu (3 946 min / 5 dni = 18% rachunku); bramką deployu było i jest „CI Gate”, więc nic się nie odbramkowało, ale **tracimy sygnał „main się zepsuł” PO merge'u — gdyby kolejka została wyłączona, `push: branches: [main]` MUSI tu wrócić**; (2) **E2E przeniesione z każdego PR-a do kolejki** (1 506 min / 5 dni za 226 przebiegów, z których czerwone były 3, przy zerowym bramkowaniu — nie jest wymaganym kontekstem); (3) **filtr ścieżek na frontendzie** — 25% PR-ów nie tyka frontendu (29 z 116, zmierzone prawdziwym skryptem filtra uruchomionym z katalogu joba), oszczędza ~16 z 17 min; (4) `claude-review.yml` usunięty (174 przebiegi w 5 dni, wszystkie `skipped` przy `CLAUDE_ENABLED=false`).
- **Filtra ścieżek NIE MA i nie będzie na shardach pytest — policzone, nie przeoczone.** Testy backendu czytają 37 ścieżek spoza `backend/`: parsują workflowy (`test_ci_deploy_workflows_contract`), `docs/`, `scripts/` oraz **29 plików frontendu** jako lustra kontraktów (`test_delivery_contract`, `test_client_tab_links`, `test_orders_procedure_freshness`). Po uwzględnieniu tych sprzężeń backend dałby się pominąć w **4 PR-ach na 116 (3%)** — za to ryzyko, że zmiana frontendu wywróci na mainie kontrakt, którego nikt nie uruchomił. Filtr frontendu jest bezpieczny tylko dlatego, że lustra w drugą stronę (7 ścieżek `backend/app/...` czytanych przez `capabilities.test.ts`) **wylicza z repo grepem, nie z listy w YAML-u** — lista wpisana na sztywno zgniłaby cicho przy pierwszym nowym lustrze. `Frontend (typecheck + build)` jest wymaganym kontekstem rulesetu, więc job **zawsze się zgłasza**; pominięte są tylko jego drogie kroki. Nie zamieniaj tego na `if:` na poziomie joba: „`skipped` liczy się za sukces” to umowa GitHuba, nie nasza, a jej zmiana zaklinowałaby kolejkę (`ALLGREEN`) bez żadnego komunikatu.
- **Sharding pytest NIE jest marnotrawstwem** (sprawdzone przy tym samym audycie kosztów): shard to 3 927 testów w 772 s, a narzut stały (checkout + install + migracje) to ~70 s, czyli 8%. Pełny suite serialnie to dziś ~51 min, nie „~22 min” z historycznego komentarza w `ci.yml`. Nie ma też pojedynczego wolnego testu do wycięcia — najdroższy plik w shardzie to 66 s z 772 s. Koszt backendu to realna praca, nie konfiguracja.
- **Wiele PR-ów naraz = kolejka merge'ów GitHuba (od 17.09.2026).** Repo jest w organizacji `B2B-net-S-A` (Enterprise), więc natywny merge queue jest dostępny: `gh pr merge <pr> --squash` dodaje PR do kolejki, GitHub sam składa gotowe PR-y w grupę na gałęzi `gh-readonly-queue/main/*`, puszcza wymagane konteksty RAZ na grupę (`merge_group` w `ci.yml` i `ci-gate.yml`) i merguje — bez `BEHIND` i bez aktualizowania gałęzi. Deploy grup z kolejki nie widzi (`head_branch == 'main'` w `deploy.yml`); rusza dopiero push na main. **Nie odpalaj `scripts/merge-train.sh` z kilku sesji naraz** — 17.09 trzy równoległe trainy aktualizowały swoje PR-y na wyścigi i żaden nie wchodził (skrypt zostaje jako awaryjny, gdyby kolejka była wyłączona). PR-y, które się wzajemnie wykluczają (te same numery migracji, dwie implementacji tej samej funkcji), kolejka i tak wyrzuci — rozstrzygnij je przed dodaniem. NIE zdejmuj `strict` — squash stalej gałęzi cicho cofa cudze merge'e (incydent 27.07: -6 merge'y na prodzie). Deploye z burstu koalesują się same: deploy rusza tylko przy zielonym HEAD maina i skipuje rebuild, gdy prod serwuje już dokładnie ten commit (deploy.yml 2026-08-07, bramka HEAD 2026-09-15).

## Manual ops cheat sheet

```bash
cd "/Users/arturtwardowski/NEXUS (ATS)"

# Quick checks (lokalnie)
cd backend && ruff check app/ && pytest tests/test_scoring_service.py -v
cd ../frontend && npm run type-check && npm run lint && npm run build

# Local stack up (dev with ports)
docker compose up --build  # auto-loads override.yml

# Local prod simulation
docker compose -f docker-compose.yml -f docker-compose.prod.yml up

# Healthcheck (po Fazie 1)
curl -fsSL https://api.<nexus-url>/api/health | jq .
SHORT_SHA=$(git rev-parse --short=7 HEAD)
curl -fsSL https://api.<nexus-url>/api/health | jq -e ".version == \"$SHORT_SHA\""

# Deploy (Coolify ma webhook na main push)
git push origin main
# Sprawdź Coolify dashboard — build status

# Rollback przez Coolify dashboard (świadomie inny niż Compass/LeadGen):
# → resource → Deployments → wybierz poprzedni → Redeploy
```

## Specyfika tej apki

- **Vector search (Qdrant):** używamy do matching kandydat ↔ stanowisko. Score harness: `scripts/eval_matching.py` lokalnie (waliduj precision/recall przed/po zmianach scoringu).
- **Migracje (Alembic):** `alembic upgrade head` na startup (Coolify entrypoint). Migracje testowane w CI (`alembic upgrade head` na test DB w `backend-lint-test` job).
- **Backup drill:** `.github/workflows/backup-drill.yml` — periodic test pg_dump → pg_restore. Działa, nie ruszamy w fazach 0-4.
- **E2E:** Playwright — stack w CI (`docker-compose.e2e.yml`, scenariusze `@stack`) + nocny `prod-smoke`; szczegóły w „CI gotchas”.
- **40+ feature branches:** historyczne, niektóre stale. Przed merge nowej feature branchy — sprawdź czy nie ma duplikatów.

## Po Fazie 1

Update tej sekcji:
- `/health` zachować, `/api/health` standard shape.
- Update `uptime-probe.yml` na `/api/health` + nowy jq query.
- Dodać `pytest tests/test_health_v2.py` do `backend-lint-test` job.

## Observability

Zobacz `~/.claude/rules/observability.md` dla pełnego standardu (Sentry + Grafana Cloud + Cloudflare). Per-NEXUS odstępstwa:

- **Sentry projekty:** `nexus-be` (FastAPI 0.115 + Python 3.12) + `nexus-fe` (Next.js 15 + React 19) — osobne projekty bo dwa stacki w jednym monorepo.
- **Backend SDK:** `sentry-sdk[fastapi]>=2.20.0` z `AsyncioIntegration` (dla 14 background tasks w lifespan: calendar reminder, match TTL, slack SLA, contract alerts, competition autofreeze, cc centroid sync, ...) + `LoggingIntegration` (auto-bridge `logger.error` → Sentry breadcrumb/event) + `FastApiIntegration(transaction_style="endpoint")`. JSON logger już skonfigurowany przez `python-json-logger` w `app/core/logging_config.py`.
- **Frontend SDK:** `@sentry/nextjs ^9` (nie ^8 jak Compass — Next 15 + React 19 wymaga nowszej wersji). `error.tsx` dodany w PR #109 (App Router error boundary, dotąd brak).
- **Replay privacy:** `maskAllText: true, blockAllMedia: true` — NEXUS trzyma dane kandydatów (RODO ATS).
- **Compose `logging:`** — `json-file 10MB×5 + tag` na 4 services (postgres, qdrant, backend, frontend) przez YAML anchor (`x-logging`).
- **Alloy sidecar:** profile-gated (`profiles: [observability]`). Bez `COMPOSE_PROFILES=observability` w Coolify nie startuje. Po dodaniu Grafana creds → `{app="nexus"}` zwraca logi z 4 services + structured fields (FastAPI JSON logging od PR #108).
- **Cloudflare:** `api.nexus.dynaminds.pl` — proxy ON, Full strict TLS, OWASP CRS PL2, rate limit `/api/auth/*` 10 req/min/IP. Backend ma już `slowapi` rate limiter — Cloudflare to pierwsza linia, slowapi druga.

## Stabilizacja pod obciążeniem — reguły po audycie 13.09 i reaudycie 14.09.2026

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
- **Sekcje Insights poza pierwszą montują się przez `DeferUntilVisible`** — kotwica
  `<InsightsSection id>` zostaje na zewnątrz wrappera, a `InsightsSectionNav` przypina
  cel (`lib/anchor-pin.ts`) na czas doczytywania — bez tego sekcje nad celem rosły
  po skoku i „Źródła” lądowały 3180 px pod ekranem. Przypięcie ustępuje pierwszej
  akcji użytkownika. Pilnuje tego `InsightsSectionNavContract.test.ts` i `anchor-pin.test.ts`.
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

## Integralność i uprawnienia — reguły po audytach Codexa 13–14.09.2026 (PR 1 i PR 2)

Plan i status: `docs/uat/08-audyty-codex-2026-09-14.md`. Reguły, które łatwo
cofnąć „przy okazji”:

- **Feedback z rozmowy jest przypięty do wydarzenia, na które autor ma wgląd.**
  `interview_feedback.py`: router za `PIPELINE_SECTION_DEPENDENCIES`;
  `_bind_feedback_to_event` sprawdza `user_can_view_event` (właściciel, uczestnik,
  role z odczytem kalendarza), potem spójność `event.candidate_id`/`job_id`
  z payloadem (422), a rekrutację dziedziczy z wydarzenia i przepuszcza przez
  `ensure_job_membership`. `needs_attention` zdejmuje autor feedbacku albo ktoś,
  kto może edytować wydarzenie. Do 14.09 dowolny `event_id` z cudzym kandydatem
  przechodził bez sprawdzenia. Uczestnik cudzego spotkania MUSI móc zapisać
  feedback — dlatego bramka to odczyt, nie mutacja (`test_interview_feedback_access.py`).
- **Zmiana statusu kontraktu blokuje wiersz** (`with_for_update()` w
  `update_contract`, `update_contract_status`, `void_contract_endpoint`,
  `activate_contract`, `reopen_contract_endpoint`, `terminate_contract`,
  `create_contract_amendment`, `bulk_mark_ended`, `bulk_extend_contracts`;
  `finalize_contract_draft` przez `_load_contract_with_relations(for_update=True)`;
  pilnuje test AST w `test_contract_status_concurrency.py`). Bez tego `void`
  i równoległy `revert` na przeterminowanym obiekcie oba przechodziły, a ostatni
  zapis wygrywał. `resync_contract` odświeża pola cyklu życia po blokadzie —
  obiekt bywa załadowany przed nią. Znany dług: writery zamówień blokują
  `client_orders` przed `contracts` — kolejność odwrotna niż w cronie
  i handlerach; nie „ujednolicaj” jej w jednym z miejsc bez drugiego.
- **Zakończenie współpracy przechodzi przez maszynę stanów**
  (`_status_after_termination`, `/terminate` i aneks `early_termination`, od
  15.09.2026). Do tego dnia obie ścieżki liczyły status z samej daty końca:
  jedno „Zakończ współpracę” wskrzeszało unieważnioną umowę (`void → ended`,
  przy przyszłej dacie `active`), a szkic z przyszłą datą dostawał `active`
  z pominięciem bramki aktywacji. Teraz `void` = 409 przed jakimkolwiek zapisem,
  a szkic/`ready_for_signature` z przyszłą datą zachowuje status.
- **Każda zalogowana trasa `/api/**` ma bramkę sekcji albo opisany wyjątek**
  (`test_section_ceiling_contract.py`, F02, 15.09.2026). Bramka roli
  (`require_roles`, `OperationalUser`, `RecruitmentReadAccess`…) NIE sprawdza
  sekcji — konto z odebraną sekcją dalej wołało ok. 20 routerów (pulpity, KPI,
  Cortex, priorytety, maile odmów, obecność, struktura zespołu, stary
  DynaReporter). Nowy router: `dependencies=` z `app.api.section_access`
  (`require_section_access`, `_any` gdy zapisujący siedzą w różnych sekcjach,
  `_any_read` dla wspólnych odczytów) albo wpis do `_SECTIONLESS_ALLOWLIST`
  z powodem. Front montuje widżety według `hasSectionAccess`, nie samych ról —
  inaczej odebrana sekcja daje serię kart błędu 403 (`RoleDashboard`,
  `useMyKpis`). `POST /api/fireflies/sync` (dawniej GET —
  zapisuje notatki, więc musi przejść bramkę zapisu).
- **Usunięcie kandydata NIE kasuje plików w żądaniu.** Klucze magazynu idą do
  rejestru `cv_source_cleanup` (`schedule_source_cleanup`) w TEJ SAMEJ transakcji,
  a kasuje je worker `clean_pending_sources` z ponowieniami. Rollback po
  wyjątku w handlerze zostawia pliki na miejscu; do 14.09 pliki znikały przed
  commitem, a wiersz kandydata zostawał. Gałąź 503 „magazyn niedostępny” usunięta.
- **M365: kursor folderu przesuwa się tylko po czystym biegu folderu.** Graph
  daje `deltaLink` dopiero na ostatniej stronie, więc „ostatnia czysta strona”
  nie istnieje — przy jakimkolwiek błędzie importu folder zostaje na starym
  kursorze (upserty są idempotentne), a `last_sync_status = error` z liczbą
  błędów. Trwale zepsuta wiadomość = folder w pętli co 30 min — to sygnał
  w sondzie, nie stan do wyciszenia.
- **Statystyki liczą osoby, nie wiersze etapów.** Uzgodnienie placementów
  deduplikuje próby (`DISTINCT ON (candidate_id, job_id)`, liczba prób
  w `verifier_anchored.attempts`, totale osobnym zapytaniem; klucz złączenia
  `COALESCE(job_id, 0)`, bo PG16 odrzuca `IS NOT DISTINCT FROM` w FULL JOIN).
  Raport DL czyta `analytics_first_milestones.first_reached_at`; wakaty i fill
  rate `count(DISTINCT candidate_id)`. `_sum_finance` oznacza sumę jako
  `partial` z licznikami `contracts_without_cost_leg`/`…revenue_leg`, a ranking
  klientów (`margin_lookup_pln`/`revenue_lookup_pln` → `(sumy, incomplete,
  unpriced)`) oznacza klienta z kontraktem bez jednej nogi jako niepełnego,
  ale zostawia SUMĘ CZĘŚCIOWĄ z wycenionych kontraktów — jak kafel na profilu
  (`active_mrr_unpriced_contracts`); `None` daje wyłącznie brak kursu NBP.
  Podpisana umowa B2B jest aktywna z samą stawką kosztową do czasu zamówienia,
  więc `None` dla całego klienta zdejmowałoby kwoty z większości rankingu
  i z całego wiersza DL w przeglądzie admina. Źródła
  z Traffita idą jako `candidate_source_events` (`note` = `traffit:source:<id>`,
  idempotentnie), więc raport źródeł je widzi. Źródło bez daty ma
  `captured_at` = data importu i dopisek `UNDATED_IMPORT_NOTE_MARK` na końcu
  `note` (przeżywa przycięcie do 500 znaków) — raport źródeł i metryka v1
  pomijają je w oknie (`undated_import_event`), inaczej pełny sync wrzucałby
  historię w „ostatnie 30 dni". Raport niesie model atrybucji (`multi_touch`,
  wiersze się nie sumują), `unique_candidates` i pokrycie nowych kandydatów
  bez źródła. Stary `GET /api/reports/board` usunięty (15.09) — liczył
  powtórne zatrudnienia i nie miał konsumenta; kokpit Rady to `/api/insights/board`.
- **Monitoring nie może być zielony bez odczytu:** `sentry-daily-monitor` bez
  tokenu = `::error::` + `exit 1`, częściowy digest wysyła i kończy `exit 1`;
  deploy ma krok `/api/health/alembic` (bookmark bazy == heads kodu,
  `orphaned == []`) — czerwony deploy przy dryfie jest zamierzony.
- **„Obecny" kontrakt = start nie później niż dziś ALBO brak daty startu —
  JEDNA reguła na każdej powierzchni**
  (`contractor_identity.is_current_contract`/`current_contracts`, UAT B46, PR 2;
  pusta data od 18.09.2026): profil klienta (kafel „Aktywne MRR", liczniki),
  zakładka Analityka (`/my-clients/{id}/dashboard`), ranking Rady
  (`insights_clients`), przegląd admina, licznik katalogu klientów
  (`client_directory.py` — to on jest lustrem tej reguły w SQL i jedynym
  miejscem, w którym może się rozjechać). **„Planowany" to twierdzenie
  o PRZYSZŁOŚCI i wymaga daty, która jeszcze nie nadeszła**; pusta data jest
  brakiem WIEDZY, a konsultant nie przestaje pracować dlatego, że nikt nie
  wpisał dnia rozpoczęcia. Audyt 18.09.2026 zmierzył cenę pierwszej wersji:
  u klienta 15 trzy AKTYWNE kontrakty z żywymi liniami zamówień siedziały
  w „Planowanych", czyli 13 920 PLN/mc (54% marży klienta) poza „Aktywnym MRR"
  przy kaflu deklarującym komplet (`unpriced = 0`). Profil podstawia datę
  reprezentatywnego zamówienia (`fallback_start`), więc umowa bez własnej daty,
  ale z zamówieniem startującym za tydzień, zostaje planowana NAPRAWDĘ.
  Kontrakt z przyszłym startem jedzie na profilu OSOBNO jako „Planowani" —
  z tą samą redakcją kwot co „Obecni". Pierwsza wersja poprawki zmieniła tylko
  profil i ten sam klient pokazywał inną marżę w sąsiedniej zakładce; pilnuje
  tego `test_margin_rounding_parity.py` (kontrakt o przyszłym starcie
  w fixture) i `test_contract_current_without_start_date.py`.
  **Szeregi czasowe (`insights_board`, `insights_board_yoy`) świadomie wymagają
  daty startu** — bez niej nie da się umieścić kontraktu na osi miesięcy.
- **Stan ekranu w adresie:** `/candidates/search` trzyma request w `?s=`
  (`lib/candidate-search-request.ts` — tylko pola o kształcie zgodnym z bazą,
  bo adres pisze użytkownik), porównanie kandydatów wraca z `?sel=`,
  Administracja w Ustawieniach ma `?sub=`, kalendarz otwiera `?event=`
  (+`&action=feedback`) i zdejmuje parametr po zamknięciu albo nieudanym
  odczycie — efekty na WARTOŚCI parametru (miękka nawigacja).
- **Ruch w pipeline ma opcjonalne `expected_state_version`** (`StageMove`,
  F05): rozjazd z `RecruitmentProcess.state_version` pod blokadą = 409
  `PIPELINE_VERSION_CONFLICT` bez zapisu; `None` = bez sprawdzenia (importy,
  ruchy zbiorcze). Karta kanbanu i odpowiedź ruchu niosą
  `process_state_version` (0 = brak procesu; jedno zapytanie hurtowe
  `_process_state_versions`); POJEDYNCZE ruchy z tablicy, doków i warsztatów
  (screening, CV, rozmowy) ją odsyłają, zbiorcze (`checkVersion: false`) nie.
  409 = toast „przesunięty przez kogoś innego”, odświeżenie tablicy (oba
  klucze) i historii doku, BEZ ponowienia (`lib/pipeline-version-conflict.ts`).
  Karta bez liczby NIE wysyła wersji (zgadnięte 0 = fałszywy konflikt).
  `POST /api/auth/refresh` przyjmuje token WYŁĄCZNIE w ciele (F06).
- **`finance_trend` nie miesza źródeł:** każdy punkt niesie `basis`
  (`legacy_monthly_report` | `contracts`) i osobne pola (`mrr` tylko live,
  `monthly_revenue`/`result_after_other_costs` tylko legacy); trend kotwiczony
  na końcu okresu (`end=`), a `source_watermarks`/`quality` czytają świeżość
  syncu Traffita (36 h jak `checks.traffit`).
- **Uczestnik wydarzenia kalendarza ma DWA kształty:** tekst (wydarzenia z NEXUS)
  albo `{address, name}` (synchronizacja M365). Renderuj wyłącznie przez
  `lib/calendar-attendees.ts` (`attendeeLabel`) — obiekt wstawiony wprost wywracał
  cały kalendarz (React #31) dla każdego wydarzenia z Outlooka (retest 15.09.2026).
- **Listy z „Pokaż więcej" idą po `offset` w API** (dzwonek, Targ, pule
  talentów): dzwonek podnosi `limit` zamiast doklejać strony — „nieprzeczytane
  najpierw" przetasowuje kolejność po kliknięciu, więc doklejanie dawało
  duplikaty.

## Generator Umów B2B — trzy zakładki cyklu życia umowy

Rejestr rozbity na trzy zakładki odpowiadające fazom życia umowy (migracje
`0226_b2b_generated_contract_suspended` i `0328_b2b_generated_contract_cancelled`,
na bazie 0203/0224):
**„Umowy bieżące"** (`active` + `in_progress` + `cancelled`) ·
**„Umowy bez projektu"** (`suspended`) · **„Zakończone umowy"** (`closed`).
Wszystko w `components/v2/pages/B2BContractGeneratorV2.tsx`.

- **„Anulowana" (`cancelled`, 0328) = umowa, która NIE DOSZŁA DO SKUTKU** —
  Partner wycofał się przed podpisem. To NIE `closed`: tam skończył się projekt,
  tu umowa nigdy nie zaczęła obowiązywać. Powstał, bo jedynym wyjściem była
  „Zakończona", a numer jest już zużyty i nie wraca do puli (UNIQUE(year, seq)),
  więc wpis musi zostać w rejestrze.
  - **Wiersz ZOSTAJE w pierwszej zakładce** (stąd jej nazwa „Umowy bieżące",
    nie „Umowy aktywne i w trakcie podpisu" — nagłówek wyliczający statusy
    przestałby być prawdziwy). Ma być pod ręką, żeby dało się go cofnąć tam,
    gdzie użytkownik patrzy. Filtr zakładki pyta o TRZY statusy.
  - **BEZ powodu i daty**: `cancelled` jest w gałęzi „pola zamknięcia puste"
    CHECK-a spójności, a NIE w `B2B_CLOSING_STATUSES`. Umowa, która nie doszła
    do skutku, nie ma czego ani kiedy kończyć, a powrót na „W trakcie" ma być
    jednym kliknięciem. Dialog nie pokazuje wtedy pól powodu i daty.
  - **Umowy podpisanej obustronnie nie da się anulować** (409) — ta doszła do
    skutku i kończy się przez „Zakończona". Opcja nie renderuje się w dialogu
    (`canCancel = signature_status !== "signed_both"`).
  - **Z „Anulowanej" nie ma skrótu na „Aktywną"** (422): `active` ustawia
    WYŁĄCZNIE potwierdzenie podpisu obustronnego. Droga wiedzie przez „W trakcie".
  - **Ręczny wybór „W trakcie" zszedł z walidatora DTO do handlera PATCH-a.**
    `B2BGeneratedContractUpdate` odrzucało ten status bezwarunkowo; od 0328 ma
    dokładnie jeden legalny wybór ręczny (powrót z „Anulowanej"), a ten warunek
    zależy od BIEŻĄCEGO statusu wiersza, którego DTO nie widzi. Komunikat dla
    przypadku niedozwolonego (`_IN_PROGRESS_IS_AUTOMATIC`) jest ten sam co był.
  - **Status podpisu zostaje „Niepodpisana"**, zmienia się tylko kolor wskaźnika
    na czerwony (`Badge variant="danger"` — badge nie ma osobnego elementu
    kropki, ikona dziedziczy jego wariant). Etykiety nie ruszamy: podpisu
    naprawdę nie ma.
  - **Przycisk „Oznacz jako podpisaną" chowa `can_confirm_signed` z backendu**
    (+ `blocked_reason` `_CANCELLED_BLOCKS_SIGNATURE`), a `confirm-fully-signed`
    odmawia 409. Jedno i drugie, bo ukryty przycisk nie jest kontrolą — ten
    endpoint do 0328 NIE patrzył na `contract_status` w ogóle.
  - Drugi, łatwy do przeoczenia mirror etykiet:
    `components/v2/jobs/JobContractTab.tsx` (`Record<string, string>`, więc
    TypeScript NIE zgłosi brakującego statusu — wyjdzie surowe `cancelled`).

- **Dostęp: KAŻDA rola (decyzja produktowa, 20.08 — mirror Talent Radar 19.08).**
  Sidebar nigdy nie miał tu `roles` ("Generator Umów B2B — dostępny dla
  wszystkich ról (sourcing tooling)"), ale backendowa `B2BGeneratorAccess`
  (`require_b2b_generator_access` w `contract_access.py`) do 20.08 wpuszczała
  tylko admin/HoR/TAC (+ DL ze scope'em) — dokładnie ten sam gap co przy
  Talent Radar: link widoczny, klik = 403. Otwarte na finance/recruiter/sourcer/
  legacy `user`. **Delivery Lead zostaje WYJĄTKIEM**, nietknięty: nadal wymaga
  jawnego przypisania klienta (operuje na swoim portfelu, nie całej bazie).
  Samo przepuszczenie roli przez bramkę NIE wystarczało — role bez żadnego
  wiersza w `ClientTacAssignment`/`DeliveryLeadClientAssignment`
  (`resolve_client_team_client_ids` zna tylko DL/TAC) dostawałyby trwale pustą
  listę, więc `_generator_unscoped` w `b2b_contract_generator.py` (pełny,
  nieoskopowany dostęp — pierwotnie tylko admin/HoR/TAC, „full-access TAC
  tool") poszerzony w lockstep o te same role. `contract_templates.py` (render
  dla DOWOLNEGO typu kontraktu, nie tylko B2B) stoi za osobną, węższą
  `ContractLegalAccess` i tej decyzji NIE dotyczy — pozostaje admin/HoR/DL/TAC.
  Węższe bramki wewnątrz generatora zostają nietknięte: edycja `client_name`
  (autor albo admin), DELETE (autor albo admin), katalog 29 ról (`AdminUser`),
  `confirm-fully-signed` (`TacPlus` + ścisły client-scope — audytowana,
  jednokierunkowa automatyzacja zatrudnienia, świadomie kontained nawet dla
  pełnodostępowego TAC). Test kontraktowy: `test_contract_legal_access.py`.
- **TCM działa w całej organizacji (decyzja Artura, 10.09.2026).** #1430 dał
  roli TCM `confirm-fully-signed`, a #1421 zmianę statusu kontraktu
  (`PATCH /contracts/{id}/status`) — obie akcje bez zakresu klienta, bo nie ma
  modelu przypisania TCM do klienta. To jest stan docelowy, nie przeoczenie:
  ścisły client-scope z punktu wyżej dotyczy DL/TAC. Jedyna granica TCM to
  sekcja Delivery: wyjątek TCM w `section_access.py` wymaga co najmniej
  odczytu Delivery, więc odebranie sekcji w panelu naprawdę odbiera akcję
  (do 10.09 wyjątek wracał, zanim porównał `granted`).
- **Do kontraktu prowadzi JEDNA droga: „Oznacz jako podpisaną"** (zgłoszenie
  09.2026, umowa 1506/2026). `POST /render` (generowanie DOCX) pisze wyłącznie
  wiersz rejestru (`signature_status="unsigned"`, `contract_status="in_progress"`,
  `contract_id` NULL) i **nie zakłada ani kontraktu, ani zamówienia** — kontakt
  dopisuje fill-only do JUŻ istniejącego kontraktu. Kontrakt (od razu `active`)
  i szkic zamówienia powstają dopiero w `confirm-fully-signed`. Z paska akcji
  generatora zdjęte są trzy przyciski, które wołały `POST /generate` i zakładały
  szkic kontraktu PRZED podpisem: „Wyślij do podpisu (QES)", „Oznacz: wysłana
  mailem", „Wgraj podpisaną (z maila)" — umowy podpisujemy offline (17.09.2026),
  a na produkcji ta ścieżka użyta była 4 razy, wyłącznie 2026-06-05. Endpoint
  `POST /generate`, `signingApi` i `app/services/signing/` **zostają** (nietknięte,
  bez konsumenta w generatorze); `reuseOrGenerateContractId` też — razem z testami.
  Nie dokładaj do generatora akcji, która zakłada kontrakt przed podpisem.
- **Potwierdzenie podpisu mimo różnic = „zachowaj warunki kontraktu", nigdy
  „nadpisz z dokumentu".** Gdy para (kandydat, rekrutacja) ma już żywy
  kontrakt o innych wypełnionych warunkach niż dokument, automatyzacja odmawia
  409 z listą różnic (`conflicts`) i podpowiedzią `can_keep_existing_terms`.
  Drugi, jawny krok — checkbox w dialogu →
  `keep_existing_contract_terms: true` — WIĄŻE podpisaną umowę z kontraktem,
  zapewnia zamówienie (etapu kandydata NIE zmienia — od 17.09.2026 umowę
  podpisujemy offline, a „Zatrudniony" ustawia człowiek na tablicy), ale nie zmienia niczego, co na
  kontrakcie już jest (stawka, jednostka, harmonogram, daty, szczegóły B2B).
  Puste pola nadal uzupełnia z dokumentu (`_complete_absent_terms`), z jednym
  wyjątkiem: stawki GODZINOWEJ z dokumentu nie wpisuje obok jednostki dziennej
  ani obok harmonogramu. Numer umowy w `b2b_contract_details` jest stemplowany
  zawsze — identyfikuje, KTÓRY dokument podpisano, nie jest warunkiem i nigdy
  nie trafia na listę różnic; data podpisania (warunek) zostaje. Zgoda jest
  przypięta do pary (kandydat, rekrutacja): w wierszu historycznym zmiana
  rekrutacji w dialogu kasuje listę różnic i checkbox. Przypadek z 09.2026: Delivery
  założyło kontrakty ręcznie PO wygenerowaniu dokumentu, w jednostce dziennej
  (68 zł/h w dokumencie = 544 zł/dzień w kontrakcie) — to ta sama kwota,
  nie konflikt handlowy. Nadpisywanie z dokumentu jest wykluczone, bo
  `rate_unit` rządzi TAKŻE stawką klienta: dzienna stawka klienta przeczytana
  jako godzinowa rozsadza marżę. Flaga nie obchodzi żadnej innej odmowy
  (duplikaty kontraktorów, inny klient, kontrakt nie-B2B, zdublowane
  zamówienia, umowa już podpisana) i bez różnic nic nie zmienia. Ślad:
  `acknowledged_conflicts` w Activity `fully_signed_confirmed` i
  `existing_terms_kept` w `linked_to_generated_contract`. Kolumna akcji
  rejestru jest ikonowa (`aria-label` + `title`), a autor siedzi pod datą
  w „Wygenerowano": kontener `max-w-7xl` przycinał tabelę na KAŻDYM
  monitorze, a przyklejona kolumna akcji (283 px) zasłaniała to, co pod nią —
  pół „Status podpisu". Testy: `test_b2b_signature_automation.py`
  (`keep_existing_terms*`), `B2BContractGeneratorSignature.test.tsx`.
- **Brak zamówienia po podpisie jest legalny WYŁĄCZNIE z powodem.**
  `_ensure_open_order` zwraca `(order, created, skipped_reason)`; dwa powody:
  `cost_client` (typ zamówienia wybiera Delivery Lead) i `open_group_line`
  (osoba jest już na żywej linii zamówienia MD/kosztowego — auto-szkic
  okresowy dublowałby współpracę na tym samym kontrakcie, #1321). Endpoint
  `confirm-fully-signed` rzuca `RuntimeError` (→ 500, pełny rollback) tylko
  wtedy, gdy zamówienia nie ma i NIE MA powodu. Do 09.2026 bramka pytała
  wyłącznie o klienta kosztowego, więc drugi powód kończył się 500 („Network
  Error") i wycofaniem całego podpisu u BIK/BNP — konsultant, którego Delivery
  obsadziło na linii MD przed potwierdzeniem dokumentu, zostawał niepodpisany
  i niezatrudniony. Linia grupy jest sprawdzana PRZED dźwignią klienta
  kosztowego (Polkomtel jest jednym i drugim — powód „linia grupy" niesie
  właściwy następny krok). Replay (`already_processed`) zwraca w `order_id`
  wyłącznie zamówienie okresowe (nigdy id linii grupy) i liczy powód tak samo.
  Powód idzie w odpowiedzi (`order_skipped_reason`) i w audycie obu Activity
  (`fully_signed_confirmed`, `linked_to_generated_contract`); komunikat po
  polsku nazywa go i wskazuje inny następny krok niż u klienta kosztowego.
  Nie zdejmuj
  `RuntimeError` dla braku bez powodu: cichy „brak zamówienia" zostawiłby
  zatrudnienie bez rekordu, który czytają skaner wygasania, MRR i sync
  terminacji. Testy: `test_confirm_links_a_consultant_already_on_a_group_line_without_500`,
  `test_confirm_still_fails_loudly_when_no_order_and_no_reason`.
- **`suspended` powstał, bo bez niego rejestr kłamał.** Kontraktor kończy projekt
  u klienta, ale umowa B2B dalej obowiązuje — czeka na kolejne zlecenie. `active`
  twierdziłby, że ktoś pracuje; `closed`, że umowy nie ma. Ten status odpowiada na
  pytanie „ilu mamy dziś kontraktorów bez projektu", a to pytanie o pieniądze.
- **Zawiesić można WYŁĄCZNIE umowę `active`** (422 dla reszty). Bez tej reguły
  `in_progress → suspended` byłby ślepym zaułkiem: powrót na `active` wymaga
  powiązanego kontraktu, a ten powstaje dopiero przy potwierdzeniu podpisu.
- **Powrót z zawieszenia wymaga projektu i powiązanego kontraktu.** `job_id`
  obowiązkowy; `contract_id IS NULL` → **409**, nie 422 (to nie błąd w danych,
  tylko stan świata do zmiany gdzie indziej). Klienta wyprowadza SERWER z projektu —
  front go nie przesyła, żeby nie dało się zapisać pary projekt/klient, która
  w bazie do siebie nie należy. Do powiązanego kontraktu leci notatka
  „Poprzedni projekt zakończony: [data], powód: [powód]" (konstrukcja `Note(...)`
  wprost w handlerze — `NoteCreate` nie ma `contract_id`, a `POST /api/notes` stoi
  za bramką `CandidateWriteAccess`, czyli w złej domenie autoryzacji).
- **Przypisanie projektu NIE dotyka `render_payload`** — w odróżnieniu od korekty
  literówki w nazwie Klienta ([[b2b-generated-contract-clientname-dual-write]]).
  Tam poprawiamy to, co MIAŁO być w dokumencie; tu zmienia się fakt handlowy,
  a podpisany DOCX jest zapisem tego, co strony podpisały.
- **Historia żyje w `b2b_generated_contract_status_events`.** Powrót na `active`
  MUSI wyczyścić `closure_*` (wymusza to CHECK), więc bez dziennika data i powód
  zakończenia poprzedniego projektu przepadałyby. `GET /generated/{id}/status-history`
  + dialog „Historia statusów". FK z **ON DELETE CASCADE** — `DELETE /generated/{id}`
  zwalnia numer umowy, RESTRICT zamieniłby dziennik w blokadę tej operacji.
- **Status handlowy ≠ status podpisu.** `contract_status` jest **niezależny** od
  `signature_status`. Podpisaną umowę też się wypowiada, więc PATCH statusu **nie
  jest** blokowany po podpisaniu — blokada 409 obejmuje wyłącznie treść dokumentu
  (`client_name`).
- **Dwie różne bramki w tym samym PATCH-u.** `contract_status` — każdy, kto widzi
  wiersz (`B2BGeneratorAccess` + client-scope; `can_change_status` = `True`).
  `client_name` — nadal autor albo admin. Reguła „autor albo admin" dla statusu
  była za wąska: kontraktora na nowy projekt kieruje delivery, nie osoba, która
  kiedyś kliknęła „generuj" — przycisk byłby niewidoczny dla większości zespołu.
- **Zamknięcie NIE usuwa wiersza** — dopisuje `closure_reason`, opcjonalny
  `closure_reason_other` i obowiązkowy `closure_date`. Powrót na `active` czyści komplet.
- **Powody opisują KONIEC PROJEKTU, nie rozstanie z Partnerem** (jeden katalog dla
  `closed` i `suspended`): `no_client_budget` | `contractor_found_other_project` |
  `contractor_health_reasons` | `contractor_underperformance` | `project_completed` |
  `internalization` | `other`. Trzy wartości sprzed 0226
  (`resignation_before_signing` | `termination` | `mutual_agreement`) **zniknęły
  z pickera, ale ZOSTAJĄ** w Literalu, w CHECK-u i w etykietach: produkcja ma
  wiersze `closed`, które je niosą. Zawężenie domeny wywaliłoby `ADD CONSTRAINT`,
  a usunięcie etykiet zamieniłoby historyczny powód w puste miejsce.
  Etykiety PL żyją w warstwie prezentacji (`B2B_CLOSURE_REASON_LABEL` w komponencie,
  **nie** w `lib/api.ts`) — testy mockują `@/lib/api` w całości, więc stałe trzymane tam
  wychodziłyby w testach jako `undefined`. Wyjątek: `_CLOSURE_REASON_LABEL_PL`
  w API — buduje TREŚĆ NOTATKI zapisywanej do bazy, czyli artefakt, nie widok.
- **Etykieta `closed` to „Zakończona"** (dawniej „Zamknięta"); wartość w bazie bez zmian.
- **Spójność wymuszona w bazie**, nie tylko w API: `ck_b2b_generated_contracts_closure_coherence`
  odrzuca `closed` bez powodu/daty oraz `active` z wypełnionym powodem. `closure_reason_other`
  jest wymagany dokładnie dla `other`. DTO `B2BGeneratedContractUpdate` to lustro tego CHECK-a
  (czytelne 422 po polsku zamiast surowego IntegrityError).
- **PATCH jest częściowy** — pola rozróżniane po `model_fields_set`, więc pominięcie pola
  zostawia je bez zmian. Bez tego zmiana statusu kasowałaby `client_name` (wszystkie pola
  są `Optional[...] = None`).
- **Wyszukiwarka:** `GET /generated?q=` filtruje **po stronie serwera** (nie po pobranych
  `limit` wierszach) po numerze umowy, `partner_name`, `client_name` oraz — przez OUTER JOIN
  na `candidates` — po imieniu/nazwisku powiązanego kandydata (także pełne „Imię Nazwisko"
  jednym ciągiem). Wildcardy `%`/`_` są escapowane, więc `%` szuka znaku, nie zwraca całej
  listy. Dodatkowo `?closure_reason=` jako filtr w zakładkach cyklu życia.
  FE debounce 300 ms.
- **`?contract_status=` jest POWTARZALNY** (`list[str]`), bo zakładka pierwsza pyta
  o dwa statusy naraz. Walidacja w ciele handlera, nie `Query(pattern=…)`: regex na
  `list[str]` FastAPI stosuje do CAŁEJ listy. Nieznana wartość → 422 z nazwą pomyłki;
  ciche zignorowanie filtra zwróciłoby PEŁNĄ listę pod nagłówkiem zakładki, która
  obiecuje wąski podzbiór. Axios musi serializować `indexes: null` — domyślne
  `contract_status[]=` to po stronie FastAPI INNA nazwa pola i filtr milcząco pada.
- **Pusty wynik wyszukiwania ma inny komunikat niż brak umów** — „Brak umów pasujących do
  wyszukiwania" vs „Brak umów aktywnych i w trakcie podpisu" (ten sam błąd co przy 403
  renderowanym jako pustka: pustka czyta się jak utrata danych). Padnięte zapytanie ma
  WŁASNĄ gałąź `isError` z przyciskiem „Ponów" — awaria nie może udawać zera.
- **Safety-net entrypointu** zawiera lustro DDL (kolumny + CHECK-i + `CREATE TABLE`
  dziennika) — prod alembic bywa orphaned. `CREATE TABLE` idzie do listy DDL, NIE przez
  `Base.metadata.create_all`: tamten blok jest jedną transakcją i na prodzie potrafi paść
  w całości (incydent Cortex, PR #664). Uwaga: wpis `ck_..._closure_reason` do 0226 miał
  wyłącznie `EXCEPTION WHEN duplicate_object`, więc poszerzenie katalogu nigdy by na
  prodzie nie zadziałało — dołożony DROP przed ADD. Obie tabele B2B są w `core_checks`
  `/api/health/deep`.
- **Kontener listy:** `max-w-6xl` → `max-w-7xl` (9 kolumn + akcje).

## Centrum e-Zdrowia: umowy ramowe (części) → umowy wykonawcze + zamówienia MD (09.2026)

Ticket „Struktura umów wykonawczych" + ticket danych startowych MD (16.09.2026).
Migracje `0312_ezdrowie_executive_contracts`, `0313_md_optional_scope_and_consumption_status`
(+ lustro DDL i zasiewu w `entrypoint.sh`, sonda `client_executive_contracts`
w `/api/health/deep`). Funkcja dotyczy WYŁĄCZNIE klienta 115 (bramka
`app/services/ezdrowie.py`); u innych klientów pola są NULL, a trasy odpowiadają 422.

- **Umowa ramowa JEST częścią.** `client_framework_contracts.project_part`
  (`cz1|cz2|cz4|cz5|cz6`, jedna ramowa na część u klienta —
  `ux_client_framework_contracts_client_part`). Pod nią `client_executive_contracts`
  (numer unikalny per klient, status `active|ended`, domyślnie `active` — ticket).
  Docelowa struktura (5 ramowych, 3 wykonawcze) jest zasiana idempotentnie z JEDNEGO
  źródła SQL `app/services/ezdrowie_structure.py` (migracja + entrypoint; no-op bez
  klienta 115; `source_key` bez dwukropka — `:cz1` w literale `text()` byłoby
  parametrem wiązanym). Numery „DO UMOWY RAMOWEJ" na dokumentach są BŁĘDNE —
  struktura nigdy nie jest parsowana z treści dokumentu.
- **Konsultant jest przypisany do umowy WYKONAWCZEJ, nie do części.**
  `client_orders.executive_contract_id` i `client_order_groups.executive_contract_id`;
  `project_part` zostaje jako WARTOŚĆ POCHODNA z części umowy ramowej (czytają ją
  dziedziczenie z maila i stare konsumenty). Jedna reguła
  `resolve_ezdrowie_assignment(db, client_id=…, executive_contract_id=…, project_part=…, require=…)`:
  u CeZ przy nowym zamówieniu / przedłużeniu / nowej karcie MD umowa wykonawcza jest
  WYMAGANA („Wybierz umowę wykonawczą" — sama część już nie wystarcza, bo pod jedną
  częścią bywa kilka umów), musi być `active` i tego klienta; jawna część niezgodna
  z umową → 422; u innych klientów oba pola muszą być puste. Wołają ją Flow A/B/PATCH
  w `client_orders.py`, `create_order_group` i przypisanie z ekranu przeglądu.
- **Tag na profilu = reprezentatywne zamówienie kontraktu** (`app/services/representative_order.py`
  — wyniesione z `clients.py`, ta sama reguła co dotąd dla części): `ActiveConsultantItem.executive_contract`.
  Linie kart MD dziedziczą umowę i część z grupy, więc po imporcie startowym tag idzie z linii.
- **Router `app/api/client_executive_contracts.py`** (`DELIVERY_SECTION_DEPENDENCIES`;
  zapis `DlAssignedOrAdmin`): `GET /api/clients/{id}/contract-structure`,
  `POST/PATCH …/executive-contracts[/{ec_id}]` (`ended` z żywymi przypisaniami → 409),
  `GET …/executive-contracts/review` (obecni + planowani bez umowy wykonawczej na
  reprezentatywnym zamówieniu — `suggested_framework_contract_id` to WYŁĄCZNIE
  podświetlenie nagłówka części, ekran NIE preselekcjonuje umowy: ticket zabrania
  automigracji nawet przy jednej umowie pod częścią), `POST …/executive-contracts/assignments`
  (ustawia na reprezentatywnym zamówieniu; kontrakt bez zamówienia dostaje szkic —
  lustro reguły „część umowy zakłada szkic"). Serwis: `app/services/executive_contracts.py`.
- **Front:** `lib/api/executiveContracts.ts` (typy, `useContractStructure`,
  `useExecutiveContractOptions` → grupy `<optgroup>` per część, `frameworkPartHeader`
  „Cz. II — CeZ/145/2025"); profil: `ContractStructureSection` (+ `AddExecutiveContractModal`,
  `ExecutiveContractReviewPanel`, `ExecutiveContractFilter` — pill „Nieprzypisani (n)",
  części bez umów widoczne i nieklikalne); cztery dialogi zamówień i `OrderGroupFormModal`
  mają select umowy wykonawczej zamiast części. Harness `/preview/ezdrowie-contract-structure`.
- **Zamówienia MD (Faza B, WSZYSCY klienci):** `client_orders.md_optional_total` =
  zakres OPCJONALNY (NULL = „brak opcji w umowie"); `md_total` = podstawowy;
  `md_remaining = podstawa + opcja − zejścia + korekta` (`line_budget_total`);
  zużycie wypełnia najpierw podstawę (`split_md_usage` → `md_base_used`/`md_optional_used`).
  `client_order_md_consumptions.status` (`protocol` = „Protokół", `accepted` =
  „Zaakceptowany", NULL = z importu) + `note`; oba statusy liczą się do zużycia.
  Ręczne wpisy per osoba: `GET/PUT/DELETE …/order-groups/{g}/lines/{l}/consumptions[/{RRRR-MM}]`
  (zapis = role cyklu życia zamówienia; linia kosztowa / wspólna pula → 422; import
  XLSX nadpisujący ręczny wpis zeruje status). `replaces_order_id` przy dodaniu linii
  USTAWIA `predecessor_order_id` (poprzednik nie jest zamykany) → poprzednik dostaje
  `replaced_by_*` (tag „Zastąpiony → następca"). **Sumy grupy — reguła pozycji:**
  `md_positions_total`/`contract_value_pln` pomijają linie, na które wskazuje
  `predecessor_order_id` innej linii — ale ZALEŻNIE od rodzaju (`replaced_by_kind`
  z dziennika: `replacement` = zastępstwo przez `replaces_order_id`, następca ma własny
  budżet → poprzednik wnosi tylko zużycie; `swap` = zamiana kontraktora, następca
  przejął POZOSTAŁOŚĆ → poprzednik wnosi swoje zużycie jako część pozycji, inaczej
  „wykorzystano" przekraczałoby wartość umowy); linie `cancelled` nie są pozycjami.
  Zamiana z opcją dzieli POZOSTAŁOŚĆ (z korektą ręczną) na opcję i podstawę bez
  wartości ujemnych; offboarding (`_reduce_legacy_md_budget`) zdejmuje pulę najpierw
  z opcji. Kwoty tylko z finansami. **UI „zakresów" (paski Podstawa/Opcja, nagłówek
  „Wykorzystano wartości umowy", pole „Zakres opcjonalny") renderuje się WYŁĄCZNIE dla
  karty z `executive_contract` / klienta CeZ** — BIK/Polkomtel/BNP widzą dotychczasowy
  pasek „pozostało / całość". `MdScopeBars`, `LineMonthlyHistoryDialog`
  („Rozliczenia miesięczne"). Harness `/preview/order-md-scopes`.
- **Import danych startowych (Faza C):** `POST /api/admin/clients/{id}/ezdrowie-md-orders/import?dry_run=`
  (admin, tylko CeZ) z manifestem JSON (`app/schemas/ezdrowie_md_seed.py`) —
  **manifest żyje poza repo** (nazwiska, stawki). Serwis `app/services/ezdrowie_md_seed.py`:
  osoba po `contract_id` → `candidate_id` → nazwisku (dokładnie jedno trafienie, inaczej
  `ambiguous` z listą kandydatów do wskazania), `create_if_missing` zakłada kandydata
  i kontrakt (godzinowy, MD ÷ 8; `ended` dla poprzedników), grupa o istniejącym numerze =
  `already_exists` (idempotencja), linia jak w `_build_line`, poprzednik `completed`
  z eventem `zakonczenie_konsultanta` `reason=seed_history` (NIE `removed_from_order`),
  szkice z `supersede_order_ids` ANULOWANE (tylko draft bez pliku poza grupą).
  Historia miesięczna wchodzi w DRUGIM przejściu (po utworzeniu następców), a status
  linii zakończonej jest po przeliczeniu przywracany jawnie — inaczej `sync_md_line_status`
  wskrzeszał poprzednika z datą końca „dziś"; linia zakończona ma `skip_sync_for_contract`
  (nie przepisuje kontraktowi stawki z historycznej linii). Dry-run idzie tą samą ścieżką
  i kończy rollbackiem; apply z blokerem = 409 i zero zapisu; paragon
  `app_settings['ezdrowie_md_seed_<sha12>']` = tylko liczniki i ID (ten sam manifest
  ponownie = dopisek `reapplied_at`, nie duplikat klucza).
- **Round-trip migracji 0312 z klientem 115**: downgrade zostawia zasiane umowy ramowe,
  więc zasiew ADOPTUJE wiersz po `(source_system, source_key)` zamiast wstawiać drugi.
  Guard zakończenia umowy wykonawczej liczy także żywe karty MD; przypisanie z ekranu
  przeglądu na osobie, której reprezentatywne zamówienie jest linią karty → 409 (linia
  dziedziczy umowę z karty). PATCH zamówienia z NIEZMIENIONĄ umową nie waliduje jej
  (umowa mogła zostać zakończona po przypisaniu); sama część bez umowy → 422.

## Klienci → Profil: tabela konsultantów + stawki z harmonogramu

Sekcja „Konsultanci" (`app/clients/[id]/ProfileTab.tsx`) renderuje **tabelę**
(`components/client-profile/ConsultantsTable.tsx`), nie karty. Kolumny: `Konsultant`
(nazwisko / tag CC / **rekrutacja**) · `Start date` · `Stawka kosztowa [godz.]` ·
`Stawka przychodowa [godz.]` · `Marża [mc]` (+ `End date` tylko w Archiwum, + `Akcje` w obu).

- **Obie stawki są GODZINOWE i idą Z ZAMÓWIENIA, marża MIESIĘCZNA (ticket 09.2026).**
  Kolumny czytają `hourly_rate_candidate`/`hourly_rate_client` (`clients._order_hourly_leg`
  na `_representative_order` — tym samym, z którego idzie rekrutacja i część umowy;
  w Archiwum na dzień zakończenia). Lustro zakładki „Zamówienia": linia MD/kosztowa
  → `md_rate_*` PLN/MD (waluta obca → `rate_*` linii), zamówienie okresowe → `rate_*`
  w `rate_unit` zamówienia; godzinowa bez przeliczenia, MD ÷ 8. **Nie czytaj tu stawek
  kontraktu jako pierwszych:** na prodzie (14.09.2026, Polkomtel) linie MD nie
  zsynchronizowały stawek do kontraktu (kontrakt 800, zamówienie 750 zł/MD) i profil
  rozjeżdżał się z zakładką Zamówienia. Kontrakt jest wyłącznie zapasem (brak
  zamówienia albo stawki na nim). Typ `GroszePLN` (grosze, `float`), NIE `WholePLN`.
  Marża i kafel „Aktywne MRR" zostają miesięczne z kontraktu (kafel = suma kolumny
  „Marża [mc]") — decyzja Artura; przy rozjechanym kontrakcie marża w wierszu nie
  wynika więc z dwóch stawek obok. Pola godzinowe redagowane razem z miesięcznymi.

- **Stawki idą z HARMONOGRAMÓW, nie z kolumn `contracts.rate_*`.** Kolumna niesie
  wartość zapisaną przy ostatnim ZAPISIE kontraktu, więc stawka progresywna albo
  aneks z datą, która już nadeszła, pokazywały tu STARĄ kwotę — a wraz z nią złą
  marżę i zaniżone „Aktywne MRR". `clients.py` reużywa
  `app.api.contracts._effective_rate_fields` (brak cyklu importów: `contracts.py`
  nie importuje `clients.py`). **Oba zapytania MUSZĄ `selectinload` trzy
  harmonogramy** (`candidate_rate_schedule`, `client_rate_schedule`,
  `framework_rate_schedule`) — bez nich helper robi lazy-load w async i leci
  `MissingGreenlet` 500 bez CORS, w UI „Nie udało się wczytać profilu".
- **Archiwum liczy stawki na DZIEŃ ZAKOŃCZENIA** (`end_date` → `terminated_at` →
  dziś), nie na dziś: to zapis historyczny, a krok harmonogramu zaplanowany po
  zakończeniu projektu nigdy w jego trakcie nie obowiązywał. `total_revenue` i LTV
  dostają tę samą stawkę wstrzykiwaną parametrem — inaczej wiersz pokazywałby sumę
  policzoną z innej kwoty niż ta obok niej.
- **`active_mrr` liczy się z tego samego słownika co wiersze.** Kafel będący sumą
  innych liczb niż widoczne pod nim nie daje się zweryfikować wzrokiem.
- **`HistoricalPlacementItem` dostał `job_id` + trzy kwoty** (`WholePLN`), objęte tą
  samą redakcją `VIEW_FINANCE` co wiersz aktywny — inaczej rola bez uprawnień
  zobaczyłaby w archiwum dokładnie to, co ukrywamy jej w zakładce obok.
- **Brak rekrutacji zostawia PUSTY wiersz**, nie „brak powiązanej rekrutacji" —
  tekst zastępczy w kolumnie danych czyta się jak wartość, a nie jak jej brak.
- **Kwoty renderują się jako „—" (`formatPLN(null)`), nie znikają** — znikająca
  komórka zostawiłaby roli bez `VIEW_FINANCE` trzy puste kolumny bez wyjaśnienia.
- Podzakładki na `ds/TabbedNav` (`role="tab"`/`aria-selected`, liczniki), jak
  w sąsiednim `ProjectsTab`. `ConsultantRow.tsx` i `PlacementRow.tsx` usunięte.
- **Kafle KPI:** `components/StatsCard.tsx` ma układ jednoliniowy (~44 px zamiast
  ~88), `subtitle` przeszedł do tooltipa. Ten komponent ma DOKŁADNIE JEDNEGO
  konsumenta (`client-profile/SummaryBar`) — nie mylić z `components/ds/StatCard`,
  który ma sześć miejsc użycia i którego zmiana dotyka dwóch dashboardów i Cortexu.

## Podgląd CV: pdf.js + lupa „Szukaj w CV” (09.2026)

PDF w podglądzie dokumentu (`FilePreviewContent`/`FilePreviewModal`, snapshot
`CVOriginalPreviewModal`) renderuje **pdf.js** (`SearchablePdfPreview` →
`PdfDocumentViewer`), NIE `<iframe>` z natywną przeglądarką Chrome. Do wnętrza
iframe kod strony nie ma dostępu, więc Ctrl+F przeszukiwał stronę POD oknem.

- **Nie wracaj do `<iframe>`** — zabiera wyszukiwanie. Druk = „Pobierz”.
- `pdfjs-dist` przypięty dokładnie (≥ 6.2.108 — CVE-2026-16633: wykonanie JS z PDF-a; CV to niezaufane pliki); `pdf_viewer.mjs` czyta `globalThis.pdfjsLib`
  przy ewaluacji, więc `lib/pdfjs-loader.ts` podpina bibliotekę PRZED importem
  viewera, a worker to jeden współdzielony `new Worker(new URL(…))`.
- CSS to wycinek `pdf_viewer.css` w `files/pdf-viewer.css` (oryginał 266 KB) —
  przy podbiciu wersji porównaj sekcje `.pdfViewer .page` i `.textLayer`.
- Wyszukiwanie: PDF przez `PDFFindController` (bez wielkości liter i polskich
  znaków), DOCX przez `lib/document-text-search.ts` z tą samą regułą (trafienie
  przez runy Worda, nigdy przez granicę akapitu, bez treści `<style>`). Skan
  i obraz = komunikat „brak tekstu”, bez OCR (decyzja Artura).
- Ctrl+F (`use-document-find-shortcut.ts`): w oknie zawsze, w podglądzie
  osadzonym (profil kandydata) tylko przy kursorze/fokusie w podglądzie. Esc
  w polu z tekstem czyści pole — okna podpinają `keepDialogOpenOnDocumentSearchEscape`
  (Radix łapie Esc w capture, `stopPropagation` w polu nie wystarcza).
- Harness: `/preview/cv-search` (pliki fikcyjne w `public/preview/cv-search/`).

## Zrzut zgody RODO na końcu CV (wymóg PKO BP)

PKO BP wymaga, żeby pod treścią CV był widoczny **zrzut ekranu maila**, w którym
kandydat zgadza się na przetwarzanie danych przez bank. Do 09.2026 generator
tylko OSTRZEGAŁ rekrutera, żeby wkleił go ręcznie przed wysyłką — nie miał skąd
wziąć obrazu. Teraz rekruter wgrywa go przy generacji, a renderer wkleja sam.

- **Sterowane regułą klienta, nie nazwą.** `ClientCvRule.requires_rodo_consent_block`
  (dziś wyłącznie PKO BP) — ten sam przełącznik, który wcześniej włączał samo
  ostrzeżenie. Reguła musi być **zatwierdzona**: `resolve_client_rule` pomija
  propozycje z seeda, a front sprawdza `is_active`. Rozjazd tych dwóch warunków
  dałby przycisk zablokowany regułą, której serwer nie stosuje.
- **W `render_payload` ląduje SAM KLUCZ z magazynu, nie obraz.** DOCX jest
  re-renderowany przy KAŻDYM pobraniu (`rerender_docx_from_payload`), więc zrzut
  musi być trwały — ale zrzut maila waży setki kilobajtów i w JSONB puchłby przy
  każdym odczycie wiersza. Bajty doczytuje `hydrate_consent_screenshot`, na
  KOPII payloadu: zapisany wiersz nie może utyć o obraz.
- **Renderer zostaje czystą funkcją** — nie sięga do magazynu. Bajty wstrzykuje
  wołający pod `consent_screenshot._bytes`. Dzięki temu testy i ponowny render
  działają bez sieci.
- **Osobny endpoint uploadu** (`POST /api/cv-generator/consent-screenshot`),
  a nie pole w `/generate`: tamta ścieżka przyjmuje JSON, więc obraz w base64
  puchnie o jedną trzecią i ląduje w logach requestów. Przy okazji obie ścieżki
  generacji (JSON `/generate` i multipart `/generate-upload`) mają JEDEN
  mechanizm zamiast dwóch, które by się rozjechały.
- **Odmowa jest twarda (422) i pada PRZED naliczeniem kwoty AI.** Dla PKO BP CV
  bez zrzutu jest dokumentem, którego i tak nie da się wysłać — ostrzeżenie
  znaczyłoby „wygenerowaliśmy Ci plik do wyrzucenia", a generacja to najdroższe
  wywołanie modelu w produkcie. Kolejności pilnuje test czytający źródło
  (sprawdzony mutacją).
- **Wstawianie obrazu jest fail-soft.** Nieczytelny plik albo padnięty magazyn
  dają CV BEZ zrzutu, nie wywaloną generację — wyjątek zabrałby też to, za co
  już zapłacono. Dlatego ostrzeżenie „sprawdź, czy zrzut jest widoczny"
  ZOSTAJE w `client_rules`, choć nie mówi już „wklej ręcznie".
- **W normalnym przepływie, nie jako pływak.** Klauzula RODO niżej jest
  kotwiczona do dolnej krawędzi ostatniej strony z oblewaniem „góra i dół",
  więc treść pod nią przechodzi na kolejną stronę zamiast się nakładać. Obraz
  jako drugi pływak nie miałby tej gwarancji i mógłby przykryć klauzulę.
- **Poza zakresem świadomie:** publiczny link do CV (`/cv/i/{token}`) i eksport
  HTML nie niosą zrzutu. Wymóg dotyczy dokumentu wysyłanego do banku, a obraz
  niesie adres e-mail kandydata — inny kanał to osobna decyzja.

## Generator CV — domyślnie ścieżka sprzed przebudowy (`legacy_v7`, 10.09.2026)

Między 09.09 a 10.09 generator przebudowano (#1444 i poprawki #1476/#1478/#1479):
osobne wywołanie AI wyciągające „fakty źródłowe”, redakcja z samego JSON-a
faktów (model nie widzi surowego CV), nowy krótki angielski prompt v10 zamiast
szczegółowego polskiego v7, przepisywanie długich punktów przez AI, pogrubianie
technologii w każdym trybie i końcowa kontrola AI. Zespół zgłosił, że CV
„generują się inaczej”, więc **domyślnie działa przepływ z 2bc6b14f**.

- **Przełącznik:** `CV_GENERATION_PIPELINE` — brak/`legacy` = stary przepływ,
  `v10` = przebudowany. Kod v10 zostaje nietknięty i wybieralny (analiza „co
  poszło nie tak” i ewentualny powrót bez deployu).
- **Kod:** `services/cv_generator_b2b/legacy_v7/` — zamrożone kopie z 2bc6b14f
  (prompt, odczyt PDF/DOCX, sekcja Championa, reguły w prompcie i polityka
  prezentacji, pomocniki lat/normalizacji). Wejścia: `prepare_source_facts`
  i `_run_generation_pipeline` w `standalone_service` (import leniwy —
  `legacy_v7.pipeline` importuje `standalone_service`).
- **Świadomie NIE cofnięte (poprawki błędów):** `apply_date_format`/
  `reformat_dates` (stary regex psuł `15.03.2020`), renderer DOCX (marginesy
  papieru firmowego #1449, filtr „Jest”), streaming/deadline w `provider.py`
  (przywrócenie starego pliku wywala start backendu). Zostaje też cała nowa
  infrastruktura: zadania trwałe, wersje, zatwierdzanie, zgoda RODO, dostęp.
- **Niezależna kontrola AI treści CV — `CV_FINAL_REVIEW_ENABLED`, domyślnie ON
  (0327, decyzja Artura 18.09.2026).** Gotowe CV recenzuje DRUGI model —
  `AIFeatureKey.cv_factual_verification` = **GPT Luna**, fallback Sonnet 5 —
  a nie ten, który je napisał: badanie z 16.09 zmierzyło, że sędzia LLM
  faworyzuje własne wyjście, więc model oceniający własną pracę jest
  systematycznie za łagodny. **Recenzja jest DORADCZA i nigdy nie rzuca**
  (`final_review.run_final_review`): niepotwierdzone twierdzenia jadą jako
  ostrzeżenia `BRAK POKRYCIA (kontrola AI): …`, raport ląduje w
  `render_payload["factual_verification"]` (prywatny — `public_view` to
  allowlista), a plakietka „Kontrola AI: OK / N uwag / niedostępna" stoi
  w wierszu listy CV. Model per env `CV_FACTUAL_VERIFICATION_MODEL`, budżet
  całej recenzji `CV_FINAL_REVIEW_TIMEOUT` (120 s, dzielony między paczki po
  40 twierdzeń). Wyłączenie flagi zdejmuje wydatek i wszystkie uwagi.
  **Nie zamieniaj tego w bramkę** — od blokowania jest osobne
  `CV_SOURCE_EVIDENCE_ENFORCED`; powód w sekcji „AI w generatorze to dodatek,
  nigdy bramka”.
- **Zatwierdzanie przy `CV_SOURCE_EVIDENCE_ENFORCED` wyłączonym (domyślnie):**
  edytowane CV przechodzi kontrolę DORADCZĄ (gdy `CV_FINAL_REVIEW_ENABLED`):
  zatwierdzenie zawsze przechodzi, a wynik ląduje w
  `branded_render_metadata["content_review"]` — `status="reviewed"` z
  `findings.count`, gdy recenzent czegoś nie potwierdził, `"verified"` przy
  czystym wyniku, `"unverified"` + `method_detail`, gdy recenzja się nie
  wykonała (nigdy fałszywe „verified”). Brak źródeł nie odmawia zatwierdzenia,
  tylko degraduje do `advisory_source_unavailable`. Rekruter dostaje trwały
  baner z liczbą uwag. Przy OBU flagach wyłączonych zostaje dotychczasowe
  `evidence_enforcement_off` bez żadnego wywołania modelu. Kontrole prywatności
  i struktury klienta działają w każdym wariancie. **`CV_SOURCE_EVIDENCE_ENFORCED`
  włączaj wyłącznie razem z `CV_GENERATION_PIPELINE=v10`** — to twarda bramka,
  a jej fałszywe alarmy zatrzymują pracę zespołu (10.09).
- **Raport „verified" z generacji zwalnia z drugiej recenzji** przy
  zatwierdzaniu NIEZMIENIONEGO CV (`cv_approval_provenance`,
  `unchanged_generation`) — świadome: ten sam recenzent i ta sama treść, więc
  druga płatna kontrola niczego by nie dodała.
- **Zachowane zachowania sprzed przebudowy (wiedz, zanim „naprawisz”):** pełny
  słownik klienta (także wpisy sprzed #1445) trafia do promptu i podmienia
  tekst we wszystkich polach; długie punkty są skracane z „…”; w trybie
  `polished`/`basic` nie ma pogrubień (tylko `tailored` pogrubia MUST/NICE
  Championa); brak branży w blind = „IT”; nagłówek lat zaokrągla sumę
  przedziałów; strony PDF będące samym obrazem są pomijane zamiast blokować.
  Ustawienia „wyróżnień” w regułach CV (0284) są w tym trybie nieaktywne.
- **Testy:** `conftest` przypina `v10` + ścisłe dowody dla dotychczasowych
  testów; domyślne zachowanie produkcyjne pilnuje
  `tests/test_cv_generator_legacy_v7.py`.
- **Generować CV może każdy (decyzja Artura, 10.09.2026).** #1448 dołożył
  wymóg członkostwa w zespole rekrutacji do `/generate`, `/generate-upload`
  i zrzutu zgody — cofnięty. Zostaje bramka roli (`CandidateWriteAccess`)
  i poprawność „etap musi należeć do kandydata” (404). Picker rekrutacji
  w generatorze (`/candidates/{id}/recruitments`) nie jest zawężany — to on
  decyduje, pod którą rekrutacją da się wygenerować CV.
  Istniejące CV (`_load_generated_document`): **autor zawsze**; cudzy dokument
  związany z rekrutacją wymaga odczytu tej rekrutacji (`ensure_job_read_access`
  — obejmuje Finanse, więc Finanse może też zatwierdzić/udostępnić cudze CV,
  jak przed 09.09); usunięcie nadal autor albo admin. Lista `/generated` to
  zakres odczytu **lub** własne CV. Podpięcie CV do etapu w pipeline
  (`candidate_stage_cv.py`) nadal wymaga członkostwa — to reguła sprzed #1448.
- **CV sprzed #1444 da się zatwierdzić.** Wiersze bez `docx_content` i
  `docx_sha256` (każde CV sprzed 10.09, 09:04) dostają DOCX renderowany raz
  z `render_payload` przy zatwierdzeniu, zapisany na wierszu
  (`docx_rendered_at_approval`). Stan częściowy (plik bez skrótu, skrót bez
  pliku, rozjazd) to nadal 409 integralności.
- **Zadania z kolejki przeżywają deploy.** `job_snapshot.py` przyjmuje snapshot
  bez pola, które ma wartość domyślną w dataclassie (np. `champion_profile`
  z #1477); nieznane pola i brak pól wymaganych dalej są odrzucane.
- **Wejścia generacji, która nie dała dokumentu, żyją 7 dni** (od 11.09.2026).
  `retire_unneeded_job_inputs` w pętli `cv_source_cleanup` (co 15 min, paczki
  `FOR UPDATE SKIP LOCKED`) bierze zadania zakończone porażką/przerwane bez
  gotowego dokumentu i zakończone podglądy reguł CV: klucz w magazynie zmienia
  na `purged/<id>`, a stary idzie do rejestru kasowań (to on kasuje plik,
  z ponowieniami). **Nie rusza** zadań w kolejce i w toku ani wejść pod gotowym
  dokumentem (przegląd zatwierdzenia i mapa wersji je czytają; ponowny render
  idzie z `render_payload`). Wyłącznik `CV_JOB_INPUT_RETENTION_ENABLED`, okres
  `CV_JOB_INPUT_RETENTION_DAYS`. Do 11.09 wgrane CV i notatki z nieudanych
  generacji leżały bez końca.
- **Limit 14 000 znaków dotyczy WYŁĄCZNIE miejsc, w których tekst czyta AI:**
  parser Championa (sprawdzany przed naliczeniem kwoty AI) i sekcja Championa
  w płatnym prompcie generatora CV (`cap_champion_prompt_section`, obie ścieżki —
  legacy i v10 — cięcie na granicy linii/słowa z ostrzeżeniem „Profil Championa
  przycięty…”). Odczyt tabel formularza Word v4 i zapisany profil nie są
  przycinane, a preflight uploadu podaje prawdziwy powód odmowy zamiast „nie
  można odczytać pliku DOCX”.
- **`CV_B2B_MAX_RETRIES` domyślnie 3** — łączny budżet 300 s dalej zatrzymuje
  nowe próby i backoffy po terminie. Jawna wartość w Coolify wygrywa.

### Zasada: AI w generatorze to dodatek, nigdy bramka (po 10–11.09.2026)

Trzy awarie w dwa dni miały jeden wspólny mechanizm: w ścieżkę, która działała
deterministycznie, wstawiono wywołanie modelu jako **warunek** wykonania
(#1444 — kontrola źródeł; #1477 — podgląd AI Championa w Kroku 2 generatora
i ponownie serwerowo w `generate-upload` dla trybu `tailored`). Model odpowiada
nierównomiernie, więc każda taka bramka to losowe „generator nie działa”.

- **Wgrany DOCX Championa jest przypinany PRZED podglądem AI** (#1490).
  Nieudany `/api/champion/preview` daje notkę informacyjną
  (`championPreviewNotice`, osobny stan od `championError`), a generacja czyta
  plik sama, deterministycznie (`parse_champion_from_docx_bytes`).
  W `generate-upload` 422/503 z `read_preview` = „brak zrecenzowanego profilu”,
  nie błąd. Regresja: `CVGeneratorStandaloneV2.test.tsx` („the AI champion
  preview is an aid, not a gate”).
- **Dokładając wywołanie AI do generatora, zaprojektuj jego awarię:** wynik
  modelu może wzbogacić dokument, podgląd albo audyt — ale ścieżka bez tego
  wyniku musi nadal oddać CV. Jeśli musi blokować (RODO, pieniądze), stoi za
  flagą domyślnie OFF (`CV_SOURCE_EVIDENCE_ENFORCED`, `CHAMPION_INTAKE_GATE_ENABLED`).

## Reguły CV per klient — pełna recepta Delivery Leada

`/settings/cv-rules` jest JEDYNYM ekranem polityki CV klienta (od 09.2026).
Warstwy reguły, w kolejności powstania: nazwa pliku i język (`0255`) →
instrukcje dla modelu (`0266`) → blokady dla rekrutera, polityka prezentacji
egzekwowana w kodzie, słownik, wersja + historia + CV próbne (`0267`).
Decyzje Artura z 02.09.2026: reguła per KLIENT (wspólna, nie per rekrutacja),
DL zatwierdza SAM dla DOWOLNEGO klienta, zapis tylko **DL + admin**, blind
bez zmian, jeden szablon DOCX, stawek w CV nigdy, notatka sourcingowa TEŻ idzie
do modelu.

- **`GET /api/settings/cv-rules` zwraca `{rules, unassigned_templates}`** —
  KAŻDĄ regułę w bazie plus szablony Championa bez wiersza. Tych drugich nie
  wolno ukryć: brak reguły wyglądałby identycznie jak jej nieistnienie.
- **Zapis i zatwierdzenie to JEDNO kliknięcie** („Zapisz i zatwierdź",
  `PUT … {confirm: true}`). Domyślny `PUT` zostawia propozycję, a edycja
  obowiązującej reguły tą ścieżką ZDEJMUJE zatwierdzenie. Blokady i polityka
  też czekają na zatwierdzenie — inaczej kopia z innego klienta zaczęłaby
  blokować rekruterów (`test_unconfirmed_recipe_is_invisible_to_the_generator`).
- **Bramka zapisu to `DeliveryLeadPlus`, NIE `TacPlus`.** TAC edytuje kartę
  klienta, reguł nie prowadzi. Front idzie po WŁASNEJ capability
  `cv_rule.manage` (lustro w `capabilities.test.ts`). Okno „Edytuj firmę"
  NIE ma już formularza reguł ani przełącznika interaktywnego CV — odsyła do
  `/settings/cv-rules?client=<id>` (deep link czytany efektem, nie
  inicjalizatorem: miękka nawigacja nie odmontowuje strony). Zapis nie jest
  zawężany do portfela DL — lustro `PATCH /api/clients/{id}`; „Tylko moi
  klienci" to filtr z `data_scope`, nie granica.
- **Wersja i historia.** Każdy zapis zmieniający TREŚĆ bumpuje
  `client_cv_rules.version` i zostawia wpis w `client_cv_rule_events` z diffem
  pól (`saved` / `saved_and_confirmed` / `confirmed` / `deleted` / `copied`).
  Sam ponowny zapis identycznej treści wersji nie zmienia: stempel na CV ma
  mówić o treści, nie o kliknięciach. Nowy wiersz po usunięciu startuje od
  `max(rule_version)+1` z historii, nie od 1 — dwie różne treści pod tym
  samym numerem zamieniłyby stempel w zgadywankę. Wygenerowane CV nosi
  `cv_generated_documents.client_rule_version` — bez tego reklamacja klienta
  jest nie do prześledzenia. FK historii idzie po KLIENCIE, nie po regule:
  usunięcie i ponowne założenie reguły nie kasuje historii.
- **Flagi karty klienta (`cv_content_mode_cap`, `cv_interactive_enabled`)
  są zapisywane NA `clients`, ale prowadzone z edytora reguły** — generator,
  publiczny link i sufit działają bez zmian, a DL ma jeden ekran. Kopia
  z innego klienta ich NIE przenosi (obietnice złożone konkretnemu klientowi).
- **Do promptu trafiają DWA bloki w wiadomości użytkownika, nie w systemowym
  prompcie** (ten jest jednym cache'owanym blokiem i musi zostać bajt w bajt
  ten sam): `<client_presentation_rules>` = klocki zrenderowane w języku
  dokumentu + wolny tekst (`generator_instructions`, dla EN wariant
  `generator_instructions_en`, gdy wpisany) oraz `<client_notes>` = notatka DL.
  Oba prompty systemowe (PL/EN) definiują semantykę i granicę: dobór i forma
  faktów obecnych w `<cv>`/`<screening_notes>`, NIGDY nowe fakty; „klient ceni
  bankowość" znaczy „pokaż bankowe projekty wyżej, jeśli są", nie „napisz, że
  są". Pominiętą instrukcję model zgłasza w `warnings` („Pominięto instrukcję
  klienta: …"). `<`/`>` neutralizowane, sufit 2000 znaków na pole. Test:
  `test_cv_generator_client_instructions.py` (system prompt identyczny
  z instrukcjami i bez).
- **Klocki są domykane W KODZIE, nie tylko proszone** (`apply_presentation_policy`
  PO bezpiecznikach, tuż przed snapshotem `render_payload`): `omit_sections`
  (education | certifications | languages | skills — `why_points` i
  `experience` celowo poza katalogiem), `max_roles`, `max_bullets_per_role`,
  `max_bullet_chars` (cięcie na granicy słowa + „…"), `why_points_max`,
  `glossary` (całe słowa, bez `\b`, który przy polskich znakach nie działa;
  `re.sub` z lambdą, bo `\` w celu wywalałby `re.error`). **Kolejność jest
  load-bearing:** `_fix_experience_years` i `_derivable_years` liczą lata
  z PEŁNEJ listy stanowisk — obcięcie do `max_roles` przed nimi zaniżało
  nagłówek „N lat doświadczenia" i flagowało poprawną liczbę jako brak
  pokrycia; słownik przed bezpiecznikiem podmieniał nazewnictwo, którego
  ten nie znajdował w źródle. **Format dat NIE idzie do promptu** — model
  posłuszny prośbie o `MM/YYYY` gubiłby miesiące bezpiecznikom, które parsują
  wyłącznie `MM.YYYY`; format nakłada kod na końcu (`apply_date_format`).
  Domknięcie czegokolwiek = ostrzeżenie „domknięto politykę prezentacji
  klienta w kodzie" — posłuszny model nie generuje żadnej uwagi. Testy:
  `test_cv_rule_presentation_policy.py` (klocki w izolacji) i
  `test_cv_generator_client_instructions.py::test_policy_runs_after_year_guards…`
  (kolejność w prawdziwym pipeline'ie).
- **Blokady.** `content_mode` + `content_mode_locked`: zablokowany tryb
  NADPISUJE żądanie na serwerze (`resolve_content_mode` PRZED sufitem, sufit
  nadal wygrywa); kafelki w generatorze wyłączone; tryb bez blokady = domyślny,
  zaznaczany RAZ przy zmianie klienta. Wymagane wejścia (`require_*`) dają 422
  z listą braków PRZED naliczeniem kwoty, tym samym kanałem co zrzut zgody
  u PKO BP; front pokazuje te same zdania przed kliknięciem (`notes_chars`
  w readiness rekrutacji). `auto_second_language`: druga wersja generowana
  w tle po pierwszej, jako OSOBNY wiersz z osobną kwotą — tylko przy
  „obie wersje" i bez wymuszonego języka; odmowa kwoty dopisuje uwagę do
  pierwszego wiersza zamiast padać. Drugi wiersz jest pełnoprawny: własny wpis
  `Activity` i mapa wymagań interaktywnego CV, a `rule_reminders` NIE każe
  wtedy „pamiętać o drugiej wersji".
- **Klient w trybie upload podpowiadany z procesu kandydata** (picker
  kandydata z bazy, wyłącznie po to). Dokładnie jeden klient w procesach =
  wybrany sam; kilku = przyciski; zero = ręcznie. Generacja BEZ klienta wymaga
  jawnego checkboxa „CV poza zleceniem" — to była największa dziura: bez
  klienta nie działa ŻADNA reguła.
- **Lint instrukcji (`POST …/cv-rule/lint`)** — tani model
  (`CLAUDE_MODEL_CV_BULK`), osobny klucz kwoty `aifeaturekey.cv_rule_lint`
  (enum + seed + lustro w entrypoincie; pilnuje
  `test_ai_feature_enum_entrypoint_mirror.py`). Opinia, nie bramka: pokazuje
  wcześniej granicę, której prompt generatora i tak pilnuje. Linie, których
  model nie ocenił, wracają jako `unclear`, nigdy jako `ok`.
- **CV próbne (`POST …/cv-rule/preview`)** — ten sam kandydat i rekrutacja
  U TEGO klienta (cudza rekrutacja → 422), z regułą ZAPISANĄ (także
  niezatwierdzoną) i bez, obok siebie. Gotowość rekrutacji sprawdzana PRZED
  kwotą (inaczej DL płaciłby dwie generacje za wiersz „failed"); dwie
  generacje = DWA obciążenia `cv_generator` naliczone przed kolejką; liczone
  w tle (2-3 min to więcej niż limit proxy), osobna tabela
  `client_cv_rule_previews` — nie `cv_generated_documents`, bo podgląd nie
  jest dokumentem do wysłania. `candidate_id` z **CASCADE** (wiersz niesie
  pełne CV — usunięcie osoby ma go zabrać), retencja 7 dni sprzątana przy
  następnym podglądzie, „processing" starsze niż 15 min raportowane jako
  awaria (Coolify zabija zadanie w tle przy każdym pushu), porażka zapisywana
  po `rollback()`. Id podglądu żyje w edytorze, nie w zakładce — przełączenie
  zakładki nie może zgubić wyniku, za który już zapłacono.
- **Sygnał zwrotny (`GET …/cv-rule/feedback`)** liczy z ostrzeżeń
  wygenerowanych CV pominięte instrukcje per tekst i domknięcia polityki;
  instrukcja pomijana w co drugim CV to instrukcja do przepisania.
- **Usuwanie bez `window.confirm`** — dwustopniowe potwierdzenie w edytorze
  i modal na liście. Natywny dialog zamraża automatyzację przeglądarki.

### Centralne reguły CV (`CV_CENTRAL_POLICIES_ENABLED`, 21.09.2026)

Katalog `backend/app/data/cv_policies.json` + `central_policies.py`, opis:
`docs/delivery/central-cv-policies.md`. Reguły, które łatwo cofnąć:

- **Tryb treści NIE jest blokowany.** Każdy klient (także Nordea) i polityka
  standardowa mają domyślnie „Pod rekrutację" (`content_mode` w katalogu —
  pole zostaje, żeby dało się przełączyć pojedynczego klienta). Rekruter może
  zmienić tryb; serwer honoruje żądanie (`resolve_mode`) w `/generate`
  i `/generate-upload`. `GET /api/cv-generator/policy` zwraca `default_mode`,
  `content_mode_locked=false` i `content_mode_notice`.
- **„Pod rekrutację" bez Championa = Redakcja + komunikat, nigdy 422.**
  Champion to kompletny profil rekrutacji (`job_supports_tailored` — JEDEN
  predykat dla domyślnego trybu i kontroli w ścieżce rekrutacji) albo
  WGRANY plik/podgląd Championa w uploadzie. Komunikat trafia do ostrzeżeń
  dokumentu (`source_warnings`). Sufit `cv_content_mode_cap` wygrywa zawsze.
- **Upload znowu używa wgranego Championa.** Pierwsza wersja centralnych
  reguł wyrzucała plik (`champion_bytes = None`) — udział CV „Pod rekrutację"
  spadł z 49% do 12%. Ręczne pola MUST/NICE (zasilały tylko kafelki
  interaktywnego CV) NIE są Championem.
- **Recepta centralna nie ustawia `why_points_max`.** „Najwyżej cztery
  punkty" jest w prompcie systemowym (`presentation_title.instructions`);
  powtórzone jako instrukcja klienta dawało fałszywe „Pominięto instrukcję
  klienta" w co trzecim CV.
- **Zmiana treści katalogu = podbij `version` wpisu.** `synchronize()`
  publikuje ponownie, gdy `managed_policy` (metadane wpisu) albo recepta się
  różni; `resolve()` do tego czasu daje 503 dla klienta. Klient niezgodny
  z katalogiem (inny `external_id`, ukryty, scalony) jest POMIJANY z logiem,
  a błąd synchronizacji nie zatrzymuje startu backendu (`main.py`).
- **Stary dokument drukuje „Rozważany na stanowisko" tylko, gdy różni się od
  nagłówka** (`considered_for_line`, porównanie bez wielkości liter i białych
  znaków) — DOCX, widok publiczny i eksport HTML.

## Profil Championa — sześć sekcji + karta klienta (przebudowa 09.2026)

Szablon skrócony do sześciu sekcji: **1. Podstawowe informacje · 2. Co wpisać
(search) · 3. Stack technologiczny · 4. O projekcie · 5. Pytania screeningowe ·
6. O kliencie**. Powód: Delivery Leadowie opisywali 80% starego profilu jako
szum. Sekcja 6 niesie WYŁĄCZNIE treść zależną od roli (co przekona kandydata
do tej oferty, insight konsultanta, historyczne pytania, branże). Standardy
klienta i dokumenty żyją w **karcie klienta** (`client_playbooks`, osobna
sekcja niżej), nie w profilu rekrutacji. Schemat `app/schemas/champion.py`
(nadal deklaruje siedem sekcji — patrz niżej), warstwa odczytu
`app/services/champion_view.py`, wzór Word `scripts/generate_champion_template.py`.

- **Skrócenie „O projekcie" do 2 zdań jest bezpieczne WYŁĄCZNIE dzięki sekcji 3.**
  Do 09.2026 jedynym maszynowym sygnałem wymagań dla oferty z Championem był
  `_extract_skills_from_champion` — regex po prozie, szukający 153 kanonicznych
  skilli i 277 aliasów. Im mniej tekstu, tym mniej trafień, więc samo skrócenie
  narracji byłoby regresem retrievalu (Champion ma zmierzony wpływ: P@5 +67%,
  R@20n +87%, 15.08). Strukturalny stack usuwa zgadywanie: `_extract_skills_from_champion`
  ma teraz **Tier 0**, który zwraca `stack.must` wprost i nie dotyka regexa.
  **Nie skracaj sekcji 4 w oderwaniu od wypełnionej sekcji 3.**
- **Nazwy spoza taksonomii przechodzą surowe.** Delivery Lead wpisujący technologię,
  której nie ma w alias mapie, opisuje realne wymaganie, nie literówkę — odsianie
  jej zamieniłoby jawnie podane wymaganie w ciszę.
- **`PUT .../champion-profile` synchronizuje stack do `Job.must_skills`/`nice_skills`.**
  Kolumny wygrywają wszędzie indziej (scoring, `requirement_map` = kafelki
  interaktywnego CV, filtry wyszukiwarki) i są puste na ~88% ofert. Stack wpisany
  i niezsynchronizowany byłby niewidoczny dla wszystkiego, co go naprawdę czyta.
- **Zapis z UI kasował 12 z 16 pól sparsowanego dokumentu** — do 09.2026
  `ChampionProfile` nie deklarowało kluczy zapisywanych przez parser, a Pydantic
  z domyślnym `extra="ignore"` wyrzucał je przy `model_dump()`. Ginęły m.in.
  `rate_value` (twardy sufit stawki w `dealbreaker_filters`) i `seniority_min_years`
  (kara seniority, zmierzona +4% P@5). Objaw był **niewidoczny**: profil dalej się
  otwierał, tylko dwa filtry cicho przestawały działać. Nowy schemat zna wszystkie
  te pola, a handler dodatkowo scala payload NA zapisanym profilu.
- **Migracja jest LENIWA, przy odczycie** (`model_validator(mode="before")`), nie
  jednorazowym przepisaniem JSONB. 949 ofert niesie stary kształt; przepisanie
  wsadowe jest odwracalne tylko z kopii, której off-site nie mamy.
- **Kolejność w `PUT` jest load-bearing: NAJPIERW normalizacja starego profilu,
  POTEM nałożenie payloadu.** Migracja uzupełnia PUSTE pole nowej sekcji wartością
  ze starego klucza — to jej sens. Gdyby scalać wprost na surowym profilu,
  wyczyszczenie frazy w edytorze nigdy by się nie zapisało, bo migracja wpisywałaby
  ją z powrotem z `sourcing.keywords`. Scalanie jest o jeden poziom w głąb: klient
  API wysyłający samo `{"basics": {"language": "EN"}}` nie może zgubić stawki.
- **Konsumenci czytają WYŁĄCZNIE przez `champion_view`** (scoring, `canonical_text`,
  `embedding_service`, generator CV, Talent Radar, uzasadnienia dopasowań,
  `champion_draft_service`). Odczyt wprost widzi jeden kształt — ten, którego akurat
  nie ma w bazie — i zwraca pustkę nie do odróżnienia od „nie ma takich danych".
- **`embedding_parts` jest CELOWO węższe niż `narrative_parts`.** Dla starego profilu
  zwraca dokładnie `about` + `responsibilities` + `selling_points`, czyli bit w bit
  to samo co przed przebudową: wektory 949 ofert nie drgnęły, indeks nie wymaga
  przeliczenia, a przebudowa formularza nie miesza się w pomiarze ze zmianą
  retrievalu. **Rozszerzenie tego zakresu (o pytania screeningowe, słowa kluczowe)
  jest osobną zmianą jakości wyszukiwania i wymaga własnego A/B** — pilnuje tego
  `test_embedding_text_for_legacy_profile_is_unchanged`.
- **Parser dokumentu rozpoznaje sekcje po NAZWACH nagłówków, nie po numeracji**
  (`_NUM` jest opcjonalne). Przenumerowanie jest bezpieczne, **przemianowanie nie**.
  Stare nagłówki ZOSTAJĄ obok nowych („Pytania od Delivery Leada" wystąpiło w 783
  z 1095 sparsowanych dokumentów, a po firmie krąży kilkaset kopii starego wzoru).
  Zdjęcie któregokolwiek zamieniłoby te pliki w CV bez sekcji — po cichu, bo brak
  sekcji jest u nas poprawnym wynikiem, nie błędem. Pilnuje tego
  `test_champion_template_agenda.py` czytający tytuły WPROST z generatora wzoru.
- **Prompt parsera to v6** (`champion_parse:v6:haiku-4.5`), opisuje TRZY układy
  (6 sekcji, 7 sekcji, stary) i NIE wydobywa pól karty klienta
  (`client.about/priority_rules/offlimit/contract_type/cv_language`, `documents`)
  — `build_champion_dict` emituje dla nich puste wartości, a kształt siedmiu
  kluczy JSONB zostaje (konsumenci czytają `.get()`, test kształtu tego pilnuje).
  `schemas/champion.py` CELOWO nadal deklaruje te pola: migracja leniwa starych
  profili i 949 wierszy produkcji. `ingest_parsed_profile` czyta skille
  z `stack.must` **oraz** z płaskiego `must_skills` — czytanie jednego kształtu
  zepsułoby albo każdy nowy dokument, albo każde ponowne przetworzenie starego,
  a objaw byłby ten sam i cichy.
- **Publiczna karta Championa dostaje WĄSKĄ projekcję**, nie surowy JSONB
  (`_public_champion_projection`). Do 09.2026 endpoint zwracał cały profil, więc
  każdy z linkiem miał w JSON-ie także NASZĄ stawkę dla kandydata, firmy docelowe,
  dyskwalifikatory i reguły priorytetu klienta — niewidoczne na ekranie, ale obecne
  w odpowiedzi, a odbiorcą linku jest strona trzecia.
- **Notatkę meetingową podpina do rekrutacji JEDNA bramka**
  (`services/note_job_link.ensure_note_linkable_to_job`, UAT M03-B13): „Powiąż
  + AI” i briefing DL odmawiają 422 notatki podpiętej do innej rekrutacji oraz
  notatki kandydata spoza pipeline'u tej rekrutacji. Bez tego rozmowa
  z kandydatem innego klienta trafiała do cudzego profilu Championa i do AI.
  Panel „Meetingi bez powiązania” pyta `GET /api/notes?unattached=true`.
- **Weryfikacja dwustronna, briefing DL i rekomendowane wyszukiwania NIE są
  sekcjami** — mają własne endpointy, są server-stamped i zwykły zapis profilu ich
  nie dotyka. Trzymanie ich poza siódemką jest decyzją produktową (19.08→09.2026),
  nie przeoczeniem.
- **Etykiety pól mówią to, co robi kod (rewizja 09.2026).** „Lokalizacja biura",
  nie „kandydata" — `scoring_service._score_location` porównuje
  `basics.candidate_location_pref` z miastem KANDYDATA, więc pole od zawsze
  znaczyło „dokąd trzeba dojechać", a stara etykieta mówiła coś odwrotnego.
  **Klucz w JSONB zostaje historyczny**: przemianowanie to migracja 949 profili
  i ośmiu konsumentów po to, żeby użytkownik zobaczył dokładnie to samo.
- **Dwa różne języki, dwa pola.** `basics.language` to JĘZYK PRACY wymagany od
  kandydata (zasila wektor oferty); `ClientCvRule.cv_language` to język
  DOKUMENTU CV — per klient i to jego słucha generator. W edytorze język CV jest
  **tylko do odczytu**, bo edytowalne pole obok reguły klienta byłoby drugim
  źródłem prawdy, które przy pierwszej zmianie zaczyna kłamać.
- **Wzór Word NIE ma ramki standardów ani sekcji „Dokumenty"** — wskazówka pod
  nagłówkiem sekcji 6 kieruje do karty klienta w NEXUSIE. Do 09.2026 ramka
  „Standardy tego klienta" i sekcja 7 niosły treść per klient kopiowaną do
  każdej rekrutacji; teraz ma ona jedno miejsce.
- **Wzór Word leży na SharePoincie, nie w repo** — NEXUS trzyma do niego wyłącznie
  link (`help_materials`). Jest JEDEN, ogólny; 14 wzorów per klient wycofano
  z Pomocy migracją 0272 (`is_published=false`; wiersze zostają, bo przegląd
  reguł CV linkuje je po slugu; pliki na SharePoincie zostają w bibliotece).
  Generator: `scripts/generate_champion_template.py --out-dir …` (bez
  `--client`/`--all`).
- **Treść kliencka dawnych wzorów żyje w `app/data/client_playbooks/seed.json`**
  — źródło seeda migracji 0272 i lustra w entrypoint. Dawny
  `scripts/champion_template_clients.json` został usunięty po jednorazowej
  konwersji skryptem `scripts/build_client_playbook_seed.py`, który sprawdza
  KOMPLETNOŚĆ: każda linia 14 wzorów musi trafić do karty (inaczej pada).
- **Walidacja szkicu v4 (#1477) jest doradcza: `CHAMPION_INTAKE_GATE_ENABLED`
  (domyślnie OFF, #1481).** Włączona blokuje search, handoff i generację CV
  (`enforce_operation` → 422 „Profil Championa wymaga poprawy przed
  użyciem”) dla profili ostemplowanych `policy_version=1` — a stempel dostaje
  każdy profil przy zapisie zmieniającym treść, klonowaniu oferty, imporcie
  z Traffita i akceptacji draftu AI. 10.09 zablokowało to pracę zespołu, stąd
  domyślne OFF.
- **Zapis profilu normalizuje TYLKO zmienione pola (od 11.09.2026).**
  `prepare_profile(previous=…)` porównuje z zapisanym profilem; pole, którego
  użytkownik nie ruszył, zostaje takie, jakie było. Do 11.09 każdy zapis
  (niezależnie od flagi bramki) zerował stawkę podaną zakresem i wycinał z
  `jobs.must_skills` pozycje MUST dłuższe niż 12 słów/120 znaków. Teraz:
  pozycje stacku nigdy nie znikają z powodu długości (tylko flaga), limit
  pozycji 500 znaków, dłuższa zostaje w `unresolved`.
  `requirement_contract.contract_names` przycina nazwę do 100 znaków — bez tego
  must-have dłuższy niż 100 znaków wywalał walidację KAŻDEGO wyszukiwania tej
  rekrutacji. `jobs.py` porównuje intake po normalizacji, więc zapis bez zmian
  nie robi zapisu ani powiadomienia.
- **Stawka: NIEZMIENIONA liczba nigdy nie jest wyliczana ponownie z tekstu**
  (`prepare_profile(previous=…)` porównuje ją jako liczbę, niezależnie od
  `rate_raw` w żądaniu): zostaje zapisana wartość, tekst i notatki. Kopia
  rekrutacji (`from_job_id`) przenosi stawkę tak, jak była zapisana. Bez tego
  „Uzgodnij profil i pola rekrutacji”, import dokumentu na rekrutację, która ma
  już stawkę, i kopia rekrutacji kasowały budżet profilom z importu 08.2026
  („140 zł netto/h” itp.), a przy zaznaczonej synchronizacji także
  `jobs.rate_budget_hourly` — z którego czytają dealbreaker stawki i scoring
  (przegląd adwersarialny drugiej rundy, 11.09).
- **Tekst ŚWIEŻEGO dokumentu jest źródłem prawdy o stawce** (`document_rate`,
  `pln_hourly_bounds` w `champion_intake.py`; parser AI, komórka formularza
  Word v4, tekst odesłany przez okno importu przy nietkniętej stawce
  z dokumentu): jedna wartość PLN/h → budżet; zakres „120–140 zł/h”, „120/140”,
  „od 120 do 140” albo „do 140” → GÓRNA granica z notatką w `intake.advisory`
  (pole to „Maksymalna stawka PLN/h”, a dealbreaker czyta je jako sufit —
  środek zakresu z parsera zaniżał budżet). Gramatyka przyjmuje netto/+VAT/
  „(netto, B2B)”, „zł/godz.”, „za godzinę”, „PLN 140/h”. Inna waluta, stawka za
  dzień/MD/miesiąc, brutto, brak jednostki → `unresolved` + `missing_budget`,
  budżet pusty. Liczba wpisana ręcznie (bez tekstu) jest budżetem bez notatki.
  Okno importu (`ChampionIntake.tsx`) odsyła `rate_raw` WYŁĄCZNIE przy imporcie
  dokumentu (`sourceIsDocument`), nigdy przy uzgadnianiu zapisanego szkicu.
- **Walidacja sprawdza profil tak, jak jest zapisany.** Wymagania odłożone do
  `intake.unresolved` wracają do stacku wyłącznie przy zapisie, który edytuje
  ten stack — `validation()` ich nie wskrzesza (wskrzeszanie dawało fałszywy
  konflikt z kolumnami rekrutacji, który przy włączonej bramce blokował search).
  Odłożony MUST, którego obecny normalizator nie przyjąłby (np. dłuższy niż
  limit pozycji), daje OSTRZEŻENIE — nigdy błąd ani blokadę. Konflikt kolumn
  NICE to ostrzeżenie, nie błąd.
- **Pusty ZAPISANY stack MUST/NICE dziedziczy kolumny rekrutacji** (17.09.2026,
  lustro `missing_role` → `job.title`): `validation()` czyta wtedy
  `effective_skill_names(job, key)` zamiast zgłaszać `missing_requirements`/
  `missing_must` na profilu, który po prostu jeszcze nie ma swojego stacku —
  `ineligible_must` liczy się wtedy na liście odziedziczonej, a
  `skill_column_conflict` pomija klucz, którego zapisana lista jest pusta
  (dziedziczenie nie jest konfliktem). `job_handoff_blockers`
  (`job_readiness.py`) dodatkowo pomija kody z `_MIRRORED_VALIDATION_CODES` —
  te same braki (rola, klient, kontekst, pytania, must-have, budżet, tryb
  pracy, dni/miasto biura) inaczej wychodziły DWA RAZY, raz jako zdanie
  briefu/rubryki, raz jako issue Championa; realne dodatki (`column_conflict`,
  `skill_column_conflict`, `unresolved_value`, `ineligible_must`, ...) zostają.
  `response_context()["job_values"]` niesie też `role_name` (= `job.title`) i
  `deadline` (ISO) — `fingerprint()` obejmuje `deadline`.

## Karta klienta (`client_playbooks`)

Jedno miejsce prawdy „jak pracujemy z tym klientem" (migracja `0272`, decyzje
Artura 03.09.2026). Tabela 1:1 z klientem + `client_playbook_events` (historia
z diffem pól). Pola: SLA w dniach roboczych, minimum kandydatów, limit CV na
proces, blokada kandydata (h), karencja między projektami (dni), polityka
stawek, „co powiedzieć kandydatowi o kliencie", reguły priorytetu, zasady
procesu (Markdown), onboarding po akceptacji (Markdown), dokumenty (nazwa +
link). API: `app/api/client_playbooks.py`.

- **Zapis = obowiązuje.** Bez `confirmed_at` jak w regułach CV: seed NIGDY nie
  nadpisuje istniejącego wiersza (`ON CONFLICT (client_id) DO NOTHING`), więc
  nie ma propozycji do odróżnienia od decyzji człowieka. `version` bumpuje się
  tylko przy realnym diffie; identyczny zapis nie zostawia wpisu w historii.
- **Tabela-siostra reguł CV, nie kolumny w `client_cv_rules`** — edycja
  obowiązującej reguły CV zdejmuje zatwierdzenie; adres biura na tym samym
  wierszu wyłączałby wymuszanie nazwy pliku do ponownego zatwierdzenia.
- **Bramki (lustro reguł CV po #1351):** zapis i historia = `DeliverySectionUser`
  (sekcja Delivery) + graf klienta `resolve_client_access` (admin org-wide,
  Delivery Lead tylko własny portfel). **Odczyt karty i przeglądu = `OperationalUser`,
  org-wide, bez grafu klienta** — świadome odstępstwo: karta zastępuje 14 wzorów
  Word w Pomocy, które czytał każdy zalogowany, a rekruter czyta ją PRZED
  przypisaniem do rekrutacji. `off_limits` (z `client_contract_terms`) jedzie
  w odpowiedzi tylko do ról z odczytem sekcji Delivery. `client_playbooks.router`
  NIE trafia na listę routerów Delivery w `test_section_access.py` (bramki per
  handler, jak `client_cv_rules.router`).
- **Trzy powierzchnie odczytu, jeden formularz:** profil klienta → „Zasady
  współpracy" (edycja w miejscu dla DL/admina), rekrutacja → sekcja 6 Championa
  (wariant compact; link „Pełna karta klienta →" prowadzi do Pomocy, bo `/clients/*`
  jest w middleware bramkowane sekcją Delivery), Pomoc → Klienci (procedura per
  klient generowana z karty, `?tab=clients&client=<id>`). Edycja także jako
  zakładka „Karta klienta" w `/settings/cv-rules?client=<id>&tab=playbook`.
  Formularz jest JEDEN (`ClientPlaybookForm`); capability `client_playbook.manage`
  = admin + delivery_lead z wymogiem sekcji Delivery/write.
- **Seed jest KOMPLETNY** (decyzja: „żeby nic nie uciekło z aktualnych plików"):
  każda linia standardów, opisu klienta i dokumentów z 14 wzorów trafia do karty,
  w tym linie o nazwie pliku/języku CV (dublują regułę CV — DL usuwa je z karty,
  gdy reguła CV jest zatwierdzona) i linie o pochodzeniu kandydata (przeniesione
  jak są). Liczby (SLA, limity) zasiano tylko tam, gdzie wzór podawał je WPROST.
  Wzorce dopasowania klienta są z 0255; wieloznaczne (np. `%bnp%` przy kilku
  klientach BNP) nie zasieją nic — DL zakłada kartę ręcznie z treści `seed.json`.
- **Trzy miejsca rejestracji modelu** (`models/__init__`, lokalne importy sondy
  startowej i lista probe tuples w `main.py`) i **lustro w `entrypoint.sh`**
  (DDL w `_COLUMN_STATEMENTS`, `_seed_client_playbooks(conn)` po procedurach,
  odpublikowanie wzorów w `_DATA_STATEMENTS` z markerem
  `0272_champion_client_templates_unpublished` w `app_settings`, który nie cofa
  ponownej publikacji przez admina). Prod alembic jest osierocony — entrypoint
  JEST wdrożeniem.
- **Nie przenoś na kartę `selling_points`/`consultant_insight`/`historical_questions`
  bez A/B** — zasilają wektor oferty i prompt generatora CV (949 ofert).
- Poza zakresem MVP: `DELETE`/`copy-from` karty, alerty z pól strukturalnych (SLA).
## Delivery Lead widzi kwoty własnego portfela (profil klienta + Analityka)

Kwoty JEDNEGO klienta redaguje wspólna reguła **`can_read_client_finance`
(`api/financial_access.py`)**, a **nie** samo `VIEW_FINANCE`. Widzą: role z tą
capability (admin, finance) **oraz Delivery Lead — wyłącznie u klienta ze
swojego portfela**. Trzy powierzchnie:

| Powierzchnia | Endpoint | Co odsłania |
|---|---|---|
| Profil → Obecni konsultanci / Archiwum | `GET /api/clients/{id}/profile` | stawki, marża, MRR/LTV, widełki otwartych rekrutacji |
| Zakładka Analityka | `GET /api/my-clients/{id}/dashboard` | przychód lifetime/aktywny, marża/mc, revenue per waluta |
| Lista „Moi klienci" | `GET /api/my-clients` | `total_revenue_all_time`, `active_revenue` |

**Reguła mieszka w JEDNYM miejscu i tak ma zostać.** Rozjazd kopii kończy się
ekranem, który sam sobie przeczy: te same kwoty tego samego klienta widoczne
w jednej zakładce i puste w sąsiedniej.

- **Dlaczego wyjątek, a nie capability.** „Obecni konsultanci" to obsada DL,
  a stawka kosztowa/przychodowa i marża to trzy z pięciu kolumn tej tabeli —
  bez tego rola, dla której ta zakładka powstała, widziała w nich wyłącznie „—"
  (zgłoszenie 01.09). Dopisanie `VIEW_FINANCE` roli `delivery_lead`
  w `ROLE_CAPABILITIES` otworzyłoby razem z tym 40+ innych powierzchni
  (eksport kontraktów, przychody w `/my-clients`, `/settings/clients-overview`,
  dashboardy zarządcze). To ten sam kompromis co `_can_see_finance` w module
  zamówień: wąska powierzchnia zamiast szerokiej capability.
- **Granicą jest portfel, nie rola.** `client_id` musi leżeć
  w `resolve_delivery_lead_client_ids(user)`. Trasy i tak odcinają obcego klienta
  (`assert_delivery_lead_client_visible` / `require_dl_assigned_or_admin` → 403),
  ale finanse nie mogą wisieć na tym, że wcześniejsza linijka nie rzuciła wyjątku.
- **Na LIŚCIE granicy nie sprawdza się per wiersz, tylko per gałąź.**
  `list_my_clients` ma dwie: organizacyjną (admin/HoR/finance — WSZYSCY klienci)
  i DL-ową (filtr po własnych przypisaniach). Flaga
  `rows_are_callers_own_portfolio` ustawiana w obu gałęziach jest tym, co wiąże
  kwoty z zakresem wierszy. Sam `has_role(delivery_lead)` rozdałby hybrydzie
  HoR+DL przychody całej firmy, bo ta wchodzi gałęzią organizacyjną.
- **`None` jako granica = brak finansów z tej ścieżki.** Tak wygląda odbiorca
  nierządzony personą DL: admin (i tak ma capability), rola nie-DL oraz
  **hybryda `head_of_recruitment + delivery_lead`** — ta ostatnia ma nadzór
  nieoskopowany, więc „własny portfel" nie miałby czego zawęzić, a repo
  konsekwentnie trzyma HoR poza finansami. Pilnuje tego
  `test_head_of_recruitment_with_dl_role_stays_redacted`.
- **`tac` i `head_of_recruitment` ZOSTAJĄ zredagowane i to nie jest przeoczenie**
  — TAC jest w zespole klienta i widzi konsultantów, ale obsady nie prowadzi
  (lustro decyzji z `_can_see_finance`); HoR przechodzi guardy klienta globalnie,
  bez przypisania. Macierz: `tests/test_client_access_matrix.py` (`financials`).
- **Redakcja jest całościowa albo żadna.** Częściowa rozjeżdża ten ekran ze sobą
  samym: kafel „Aktywne MRR" jest sumą kolumny „Marża" pod nim, a „Archiwum
  konsultantów" ma DOKŁADNIE te same trzy kolumny co zakładka obok.
- **Marża = przychodowa − kosztowa, po przewalutowaniu obu nóg na PLN osobno**
  (`_finance_rates_in_pln`), nigdy z kolumny `contracts.margin` — ta niesie
  kwotę z ostatniego ZAPISU kontraktu. `None` zostaje tylko wtedy, gdy brakuje
  danych źródłowych: stawki albo kursu FX dla waluty obcej.
- **Tabela konsultantów nie ma bramki front-endowej i mieć nie powinna** —
  `ConsultantsTable` rysuje wszystkie kolumny zawsze, a `null` renderuje jako
  „—". Decyduje wyłącznie backend.
- **Zakładka Analityka ma DRUGĄ bramkę, po stronie front-endu** — i o niej łatwo
  zapomnieć. `AnalyticsTab` sam decyduje, czy w ogóle wyrenderować kafle
  finansowe; przy samym `hasAnalyticsCapability(user, "view_finance")` chowała je
  przed DL nawet wtedy, gdy backend przysyłał już komplet liczb. Teraz woła
  `canViewClientFinance(user, clientId)` (`store/auth.ts`) — lustro reguły
  backendowej, liczone z `data_scope` z `GET /api/auth/me`, czyli z **tego
  samego** `resolve_dashboard_scope`, którego używa backend. Nie z roli:
  hybryda HoR+DL dostaje `recruitment_org` i kwot nie widzi po obu stronach.
- **Kwoty na LIŚCIE `/api/my-clients` nie mają dziś konsumenta w UI** —
  `my-clients/page.tsx` i `MyClientsTab.tsx` czytają tylko pola operacyjne.
  Reguła obejmuje je dla spójności kontraktu API; nie szukaj tam efektu wizualnego.
  Efekt widać w zakładce **Analityka** (karta z listy linkuje wprost tam).

## Analityka kontraktów: utylizacja i kafle sum (18.09.2026)

- **Mianownik utylizacji to POPULACJA KONSULTANTÓW, nie baza CV.** Jedna
  definicja: `services/consultant_population.py` (czytają ją
  `GET /api/contract-analytics/utilization` i `analytics/metrics.finance_summary`).
  Populacja = osoby z kontraktem `active`/`ending`/`ended` o starcie ≤ dziś,
  fałdowane po tożsamości (`contractor_identity`), więc scalenie duplikatów nie
  podbija wskaźnika. Endpoint liczył wcześniej `outerjoin(Contract)` BEZ filtra
  statusu: 0,8% zamiast 91,3% (**błąd 114×**) i 56 647 osób „na ławce" zamiast
  45 — przy czym `avg_bench_days` obok liczyło się już po tych 45, więc ekran
  przeczył sam sobie. `utilization_pct = None` gdy nie ma kogo liczyć: zero
  znaczyłoby „nikt z naszych konsultantów nie pracuje".
- **Sumy firmowe mają własny endpoint `GET /api/contract-analytics/margin-totals`.**
  Kafle „Miesięczna marża" i „Miesięczny przychód" liczyły się na froncie
  z `margin-by-client`, a ta trasa oddaje 20 wierszy przyciętych po MARŻY —
  klient o wysokim przychodzie i niskiej marży wypadał z kafla PRZYCHODU
  (12 555 483 zamiast 12 772 543 PLN, brakowało 217 060 zł). Podniesienie
  limitu byłoby tym samym błędem, tylko dalej: **suma nie może zależeć od tego,
  ilu klientów mieści się w rankingu obok**. Ranking i suma mają wspólne
  źródło (`_margin_by_client_rows`), ale osobne trasy i osobne stany ładowania.

## Indeks wektorowy: dryf, degradacja i pula ofert (18.09.2026)

- **Hasz indeksu zależy od TREŚCI i MODELU** (`index_outbox_service._desired_hash`).
  Był samym `sha256(text)`, więc zmiana `VOYAGE_MODEL` nie tworzyła dryfu i nic
  się nie przeindeksowywało — indeks cicho mieszałby wektory z dwóch przestrzeni,
  a podobieństwo między nimi nie znaczy nic. **Porównuj przez `hashes_match`,
  nigdy `!=`**: hasz sprzed tej daty nie niesie modelu i porównany dosłownie
  wyglądałby jak dryf na CAŁEJ bazie — reconciler zakolejkowałby ~60 tys.
  przeliczeń Voyage'a przy pierwszym tiku, płacąc za import jeszcze raz.
  `LEGACY_EMBEDDING_MODEL` to zapis historii, nie konfiguracja — nie zmieniaj
  go razem z `VOYAGE_MODEL`.
- **Reconciler dryfu jest WŁĄCZONY domyślnie i objęty heartbeatem.** Powód
  wyłączenia („przy `AI_INDEX_MAX_ATTEMPTS=5` awaria Voyage'a plus reconciler
  karmiący workera wypala backlog w wiersze `dead` za zielonym healthem") był
  słuszny i nie zniknął sam — zamyka go bramka `embedding_provider_down()`:
  przy `checks.voyage = unhealthy` tik nic nie zapisuje. `unknown` NIE jest
  awarią (inaczej po każdym deployu reconciler stałby do pierwszego
  niezwiązanego wywołania modelu). Zdjęty z `EXEMPT` w `loop_heartbeat`:
  pętla wykrywająca BRAK zapisu nie może sama milczeć niezauważona.
- **Import Traffita zapisuje intencję przeindeksowania OFERT** (`index_intents`
  w statystykach fazy `jobs`). `_UPSERT_JOB` nadpisuje `title`, a tytuł wchodzi
  do tekstu embeddingu, więc każda nocna zmiana zostawiała wektor nieaktualny
  na stałe: 128 z 307 opublikowanych rekrutacji (41,7%) bez wektora.
- **`degraded` znaczy AWARIA SILNIKA, nie „ktoś nie ma wektora".** Pula niesie
  dwie różne flagi: `semantic_unknown` (ten kandydat) i `semantic_engine_down`
  (dostawca). Do 18.09.2026 baner „tryb awaryjny" zapalał się na pierwszej
  z nich, więc wystarczył jeden kandydat dociągnięty przez BM25 i zaraz
  odfiltrowany: 20 z 21 losowych rekrutacji w „trybie awaryjnym" przy zdrowym
  Qdrancie i Voyage'u. Jedyny sygnał ostrzegający przed nieufnym rankingiem
  świecił non stop, więc realna awaria byłaby od normalnej pracy
  nieodróżnialna. `/ai-matches` liczy `degraded` **po przycięciu do
  `max_results`** (wiersz, którego rekruter nie zobaczy, nie zapala banera nad
  tym, co widzi) i dodatkowo, gdy NIC z widocznych nie zostało zmierzone.
- **Odznaka dopasowania na liście kandydatów nie zmyśla liczby.** Ta ścieżka
  nie ma `similarity_map` z Qdranta, więc świeżo policzony wynik ma warstwę
  wartą 60/100 punktów NIEZMIERZONĄ — stąd stałe 26,2 i „0 pasujących ofert"
  o każdym kandydacie w bazie przy progu 50, którego przy takim suficie nie da
  się przekroczyć. Teraz wiersze są oznaczane (`semantic_unavailable_ids`),
  a `summarize_match_stats` liczy WYŁĄCZNIE wyniki ze zmierzoną semantyką
  (`semantic_was_measured`) i oddaje `top_score = None`, gdy nie ma czego
  pokazać. `None` to „nie wiemy", nie „zero" — UI renderuje „Nie policzono".
  Cache czytamy dalej, więc para policzona wcześniej z prawdziwym kosinusem
  ma prawdziwą odznakę. Zapytanie o oferty dostało `ORDER BY` (bez niego
  `LIMIT` oddaje DOWOLNY wycinek), a `total_open` liczy wszystkie opublikowane,
  nie wielkość wycinka.
- **Pula ofert filtruje się PO STRONIE QDRANTA** (`search_jobs_semantic(statuses=…)`,
  `status` w payloadzie punktu). 95,4% wektorów ofert to rekrutacje ZAMKNIĘTE,
  a filtr nakładał się dopiero w SQL na pobraną pulę, więc `top_k=50` dawało
  ~9 rekomendacji. **Filtr jest `should` (OR) z `IsEmptyCondition`, nigdy
  twardym `must`**: punkty sprzed tej zmiany nie mają `status`, więc `must`
  odciąłby całą dzisiejszą kolekcję i zamienił ~9 rekomendacji w ZERO. Filtr
  staje się w pełni skuteczny w miarę przeindeksowywania ofert.

## Interaktywne CV (publiczny link do wygenerowanego CV)

Generator CV B2B ma ścieżkę do klienta: rekruter tworzy token-link
(`/cv/i/{token}`), hiring manager przełącza widok **classic** (HTML 1:1 z
`render_payload`) ↔ **interaktywny** (kafelki must/nice-have z
dowodami-cytatami + chat AI). Migracja `0217_cv_interactive_share` (+ lustro
w entrypoint.sh). Pełny opis: `docs/cv-interactive-share-completion-report.md`.

- **Jedno źródło prawdy client-safe**: `cv_generator_b2b/public_view.py::build_public_payload`
  (bez `warnings`, blind maskowany lustrem renderera DOCX). Ten sam payload
  renderuje widok classic, jest WEJŚCIEM generacji mapy wymagań i CAŁYM
  kontekstem chatu — model fizycznie nie widzi notatek/stawek/transkryptów.
- **WYŁĄCZONE od 21.09.2026 (decyzja Artura): `CV_INTERACTIVE_ENABLED=false`**
  (backend, sprawdzane w `interactive_client_enabled`, `ensure_requirement_map`
  i `execute_map`) + `CV_INTERACTIVE_UI_ENABLED=false` (`lib/cv-generator.ts`).
  Brak dodatkowego wywołania AI mapy wymagań (~28% kosztu generacji przy
  2 linkach użytych w historii), link `/cv/i/` i plik HTML pokazują widok
  klasyczny, czat zwraca 404, pola Must/Nice i checkbox klienta ukryte. Pola
  Must/Nice zasilały WYŁĄCZNIE kafelki, a serwer liczył je jako „jest
  Champion” — tryb dopasowany przechodził bez Championa w prompcie. Powrót =
  obie flagi na `true`; reszta opisu poniżej dotyczy stanu włączonego.
- **Kafelki = precompute**: 1 dodatkowy call Claude na końcu background-joba
  generacji. Źródło wymagań: mode="new" → Job (must/nice, fallback
  champion/JD); mode="upload" → ręczne pola `must_requirements`/
  `nice_requirements` (Form, przecinki/nowe linie) albo sekcje MUST/NICE
  wgranego pliku championa — bez żadnego źródła upload zostaje classic-only.
  Walidator odrzuca cytaty niebędące substringiem payloadu; „met" bez dowodów
  degraduje do „partial". Fail-open — kwota/błąd LLM nie psuje generacji CV.
  Publiczny endpoint serwuje wyłącznie cache. Uwaga: upload nie zna klienta,
  więc flaga `cv_interactive_enabled` go nie ogranicza (ta sama klasa luki co
  sufit content_mode w upload — świadoma).
- **Jeden plik HTML** (doprecyzowanie Artura — wersja do wysyłki mailem jak
  DOCX): `GET /api/cv-generator/generated/{id}/html` → samodzielny plik
  (style/dane/JS inline, offline) z układem szablonu firmowego + kafelkami +
  przełącznikiem; druk = czyste klasyczne CV. Renderer:
  `cv_generator_b2b/html_export.py` (wejście = ten sam client-safe payload;
  wszystko przez html.escape). DOCX nie wykonuje logiki, PDF z JS działa
  tylko w Acrobacie — stąd HTML. Chat NIE działa w pliku (wymaga serwera).
- **Chat**: `POST /api/public/cv-i/{token}/chat` — dzienny limit per link
  (`CV_INTERACTIVE_CHAT_DAILY_LIMIT`=30 → 429) + kwota
  `AIFeatureKey.cv_interactive_chat` (→ 503) + rate limit 5/min; injection →
  odmowa bez wywołania AI; historia server-side. Model default Haiku
  (`CV_INTERACTIVE_CHAT_MODEL`). Pytania logowane w `cv_share_chat_messages`.
- **Tokeny v2-only** (`cv_generated_share_tokens`): sekret raz, w DB tylko
  SHA-256, PK = revoke-key `v2$<hex>`, bez gałęzi legacy. Veto HM przy
  tworzeniu linku (jak w brandowanym CV).
- **Flaga per klient** `Client.cv_interactive_enabled` (default ON, checkbox w
  EditClientModal) — gasi kafelki+chat, link zostaje classic. Świadomie
  NIEZALEŻNA od `cv_content_mode_cap`.
- Dwa nowe klucze AI w Ustawieniach → AI: `cv_requirement_map`,
  `cv_interactive_chat` (0217 seeduje `ai_features`).

## Podsumowanie aktywności kandydata (AI)

Karta „Podsumowanie aktywności" w szynie „Podsumowanie AI" profilu kandydata
(`CandidateActivitySummaryCard.tsx`) — krótka notatka AI kondensująca historię
(wysyłki, feedbacki, preferencje, stawki, dostępność). PR #1003, migracja
`0204_candidate_activity_summaries`. Pełny opis:
`docs/candidate-activity-summary-completion-report.md`.

- **GET nigdy nie generuje** (`/api/candidates/{id}/activity-summary` = cache-only) —
  karta jest na domyślnej zakładce, auto-generacja przy 49k kandydatów = koszt.
  Pierwsza generacja i aktualizacja wyłącznie przyciskiem → `POST …/refresh`.
- **Refresh płaci tylko przy zmianie historii**: `input_hash` sekcji + wersji promptu
  + modelu (wzorzec match justification). Bez zmian → `refreshed=false`, FE toastuje
  „Podsumowanie jest aktualne". Bump wersji promptu `CANDIDATE_ACTIVITY_SUMMARY`
  inwaliduje wszystkie cache.
- **Kwoty**: `AIFeatureKey.candidate_summary` (slot zarezerwowany od 0085, teraz
  użyty) — liczy zużycie, niczego nie blokuje (NEXUS bez limitów AI). Oba endpointy za
  `OperationalUser`. Model override: env `CANDIDATE_SUMMARY_MODEL`.
- Wyjście plaintext (nie JSON) + `thinking={"type": "disabled"}` (trap truncacji
  Sonnet 5). Tabela ma lustro DDL w entrypoint.sh (jak każda zmiana schematu).

## Integracja COMPASS ↔ NEXUS (kontraktorzy + cykl życia)

Druga apka (COMPASS, HR, Next.js/Supabase) i NEXUS wymieniają dwie rzeczy poza
dniami roboczymi z D5. **Kod wdrożony (#1368), aktywacja częściowo credential-gated.**

**Dwa kierunki, dwa różne sekrety — łatwo pomylić:**

| Przepływ | Endpoint (źródło) | Uwierzytelnienie | Konsument |
|---|---|---|---|
| Kontraktorzy: **Compass ← NEXUS** | `GET /api/integrations/compass/contractors` | `X-API-Key` = klucz konta serwisowego scope `contractors:read` | cron Compassa |
| Cykl życia: **NEXUS ← Compass** | Compass `GET /api/internal/roster` | `Bearer` = `COMPASS_LIFECYCLE_SECRET` | pętla `compass_lifecycle_sync` |

- **`/api/integrations/compass/contractors`** (`app/api/integrations_compass.py`) —
  tożsamość + zaangażowanie, **BEZ kwot** (decyzja produktowa). Reużywa kształtu
  `contractors.list_contractors` minus stawki, więc NIE woła `effective_rate_fields`
  (brak pułapki `RATE_SCHEDULE_LOADS`). `lacks_current_order` = sygnał ławki (Etap 4).
  Ścieżka CELOWO pod `/api/integrations/…`, nie pod `/api/candidates|jobs|clients|users`
  — `test_key_cannot_reach_domain_data` wymaga tam 401 dla klucza. Moduł **bez**
  `from __future__ import annotations` (slowapi #579) i **na liście `_RATE_LIMITED_MODULES`**
  w `test_public_surface_hardening.py`.
- **Scope `contractors:read`** (`app/models/service_account.py`) — nazwa NIE może brzmieć
  `candidate:read`/`client:read` (`test_no_candidate_data_scope_exists` je zakazuje).
- **`compass_lifecycle_sync`** (`app/services/compass_lifecycle.py` + `app/tasks/`) —
  pętla tła, deaktywuje `users.is_active` osób ze statusem `exited` w Compassie.
  **Jednokierunkowa** (nigdy nie reaktywuje), **`offboarding` NIE deaktywuje**
  (offboarding trwa po ostatnim dniu pracy), **pusty roster = awaria, nie masowe
  odejście**. Nie rusza rankingów wypłacających nagrody (`competitions.py:194`
  zostaje). Domyślnie WYŁĄCZONA (`COMPASS_LIFECYCLE_ENABLED=false`).
  **Ręczne przywrócenie konta przez admina wygrywa — ale tylko w bieżącym
  epizodzie odejścia** (od 11.09.2026). Aktywne konto osoby `exited` jest
  deaktywowane, CHYBA ŻE ostatnia jawna decyzja admina to przywrócenie
  (Activity `active_changed` z `to=True`, `PUT /api/admin/users/{id}`) nowsze
  niż początek bieżącego epizodu. Początek epizodu = chwila, w której pętla
  zobaczyła zmianę statusu na `exited` (per osoba w
  `app_settings['compass_lifecycle_state']`, wersja 2); przy pierwszej
  obserwacji — ostatnie Activity `compass_lifecycle_deactivated`, a bez niego
  `now()`. Włączenie konta bez takiego Activity (logowanie SSO z grupą AAD,
  resync AAD) NIE liczy się — następny bieg wyłącza je znowu; stare,
  niezwiązane przywrócenie sprzed odejścia też nie. Do 11.09 każdy sync
  wyłączał wszystkich `exited`, więc przywrócenie przez admina znikało po ≤6 h;
  pierwsza wersja poprawki („tylko przy zmianie statusu”) zostawiała dostęp na
  zawsze po takim przywróceniu (przegląd adwersarialny 11.09). Stara pętla nie
  zostawiała śladu, więc konto przywrócone PRZED wdrożeniem zostanie wyłączone
  raz. Zapis stanu to upsert (dwa kontenery przy deployu); logi niosą liczby
  i ID, bez e-maili.
- **`GET /api/insights/reconciliation/placements`** (`app/api/insights_reconciliation.py`)
  — read-only raport uzgadniający placementy w OBU rodzinach atrybucji (FULL OUTER,
  LEFT JOIN na sieroty). Tłumaczy rozjazd 213/228/317/332, **nie usuwa go**; NIE
  rusza `VERIFIER_ANCHORED_CTE`. Nazwiska kandydatów tylko dla ról z odczytem
  kandydatów (`user_has_candidate_read`); pozostali dostają `candidate_id`
  i flagę `candidate_names_redacted`.
- **Sonda `checks.compass_workdays`** w `/api/health` (0276 `CompassWorkdaysSyncState`) —
  patrz sekcja o D5; `healthy` wymaga `last_status=='ok'`, nie samej świeżości.

**Env (Coolify, przez workflow „Coolify set env"):** `COMPASS_LIFECYCLE_ENABLED`,
`COMPASS_LIFECYCLE_URL` (`https://compass.dynaminds.pl/api/internal/roster`),
`COMPASS_LIFECYCLE_SECRET` (**= Compass `ROSTER_EXPORT_SECRET`**). Klucz konta
serwisowego wydaje admin przez Ustawienia → Konta serwisowe (mintuje żywe
poświadczenie — nie da się z CI: `coolify-ops.yml` świadomie nie ma `command`).

## CloudTalk (telefonia)

5-fazowa integracja zdeployowana w PR #157 (Fazy 1-5 razem). Dormant na prod do momentu provisioning secret + flipnięcia killswitcha.

- **Kill-switch:** `CLOUDTALK_ENABLED=false` default. Wszystkie `/api/cloudtalk/*` zwracają 503,
  webhook stoi w DRY-RUN, background loop `cloudtalk_sync` **kończy się przed pętlą** (do 28.07
  ten opis kłamał: pętla startowała zawsze i budziła się co 60 s, żeby sprawdzić tę samą flagę),
  a `/api/health` **nie raportuje już klucza `cloudtalk`** przy wyłączonej integracji — stały wpis
  „unconfigured" nie niósł informacji i uczył ignorować niezdrowe pozycje w `checks`.
- **Decyzja 28.07: nie używamy CloudTalka** (koszt). Integracja została zneutralizowana, nie usunięta —
  model `Call` i kolumny `calls.*`/`users.cloudtalk_agent_id` są niezależne od dostawcy i zostają jako
  punkt zaczepienia pod następną telefonię. Karta w Ustawieniach → Integracje zdjęta z widoku
  (komponent `CloudTalkSettingsCard.tsx` zachowany).
- **Aktywacja:**
  1. CloudTalk panel → Settings → API Keys → generate pair → secret pokazany RAZ
  2. `openssl rand -hex 32` → webhook signing secret
  3. Coolify env vault → `CLOUDTALK_API_KEY_ID`, `CLOUDTALK_API_KEY_SECRET`, `CLOUDTALK_WEBHOOK_SECRET` (runtime), na koniec `CLOUDTALK_ENABLED=true`
  4. CloudTalk panel → Integrations → Webhooks → URL **`https://api.nexus.dynaminds.pl/api/calls/webhook`** (BEZ tokena w ścieżce — patrz niżej), signing secret = ten sam co `CLOUDTALK_WEBHOOK_SECRET`, events: `call-ended`, `transcript-ready`, `recording-ready`. CloudTalk podpisuje **body** HMAC-SHA256 → nagłówek `X-CloudTalk-Signature`.
  5. Settings → Integracje → CloudTalk → **Synchronizuj** żeby zmapować agentów do userów (auto-match po email; ręcznie dropdown gdy email się różni)
- **⚠️ Zmiana bezpieczeństwa (M6-P0.12) — NIE ma już URL-token webhooka.** Wariant `POST /api/calls/webhook/{token}` (Workflow Automations, PR #160), który wkładał **signing secret w ścieżkę URL** (wyciek do access logów Cloudflare/Traefik — te obcinają query string, ale NIE segmenty ścieżki), został **usunięty**. Jedyny inbound route to HMAC-podpisany `POST /api/calls/webhook`. Jeśli chcesz karmić Nexusa z CloudTalk Workflow Automations, skonfiguruj to jako **natywny podpisany webhook** (Integrations → Webhooks), nie jako „API request" z sekretem w URL. Rejestrując webhook przy aktywacji użyj gołego URL `…/api/calls/webhook` (bez `/{token}`).
- **Replay protection (opcjonalna, zalecana):** jeśli Twój plan CloudTalk wysyła nagłówek `X-CloudTalk-Timestamp` (unix seconds) i podpisuje `hmac(secret, f"{timestamp}.{body}")`, ustaw `CLOUDTALK_WEBHOOK_REQUIRE_TIMESTAMP=true` — backend zwiąże timestamp z podpisem i odrzuci request spoza okna ±`CLOUDTALK_WEBHOOK_TOLERANCE_SECONDS` (default 300s), więc przechwycony request nie da się odtworzyć. **Najpierw potwierdź w dokumentacji CloudTalk realną nazwę nagłówka + schemat podpisu** — domyślnie flaga jest `false`, więc backend akceptuje też legacy body-only podpis (integracja nie pęka gdy CloudTalk timestampów nie wysyła). Bez timestampa idempotencja opiera się na `calls.cloudtalk_call_id` UNIQUE.
- **Inbound flow:** webhook → HMAC verify (`X-CloudTalk-Signature`, opcjonalnie freshness `X-CloudTalk-Timestamp`) → kandydat lookup po phone (last-9-digits z `dedup_service._normalize_phone`) → upsert `Call` po `cloudtalk_call_id` → jeśli `agent.id` mapowany → `Call.user_id` → jeśli transkrypt + active stage → Champion enrichment via `champion_draft_service.enrich_from_call`.
- **Outbound flow:** profil kandydata → `<CallButton>` → `POST /api/cloudtalk/initiate-call` (wymaga `current_user.cloudtalk_agent_id`) → CloudTalk rings softphone → stub `Call(status=initiated)` → webhook po zakończeniu UPDATE'uje row.
- **Backfill:** `app/tasks/cloudtalk_sync.py` co `CLOUDTALK_SYNC_INTERVAL_SECONDS` (1h, clamp >=300s) zapycha luki dla ostatnich `CLOUDTALK_HISTORICAL_BACKFILL_DAYS` (30d) — `GET /calls/index.json` paginowane.
- **UI surface:** `/candidates/[id]` → tab Rozmowy (`CallsTimeline` + `CallDetailsDialog` + `AudioPlayer`), Settings → Integracje (`CloudTalkSettingsCard` z agent mapping), Dashboard recruiter (`CallStatsWidget`).
- **DB:** `calls.cloudtalk_agent_id`, `calls.started_at`, `users.cloudtalk_agent_id` UNIQUE — migracja `0099_cloudtalk_agent_mapping` (na bazie `0098_merge_heads`).

## Traffit daily sync (scheduled import)

Migracja Traffit→Nexus z maja 2026 była **one-shot CLI** (`python -m app.cli.import_traffit`). Ten moduł dodaje **zaplanowany sync** żeby Nexus był kompletny i aktualny: codzienny delta + tygodniowy full reconcile. PR 2026-06-17. Pełny opis: `docs/traffit-daily-sync-completion-report.md`.

- **Loop:** `app/tasks/traffit_sync.py` → `traffit_daily_sync_loop` (zarejestrowany w `main.py` lifespan jako `traffit_sync`). Budzi się co `TRAFFIT_SYNC_CHECK_INTERVAL_SECONDS` (30 min, clamp >=300s) i decyduje z **persisted watermark** (`traffit_sync_state`), NIE z in-memory timera → restart-safe (Coolify rebuild na każdym pushu NIE re-triggeruje importu).
- **Kill-switch:** `TRAFFIT_SYNC_ENABLED` (default `false`). Off → loop exit, `POST /api/admin/traffit/sync` → 503.
- **Tryby:**
  - **delta** (codziennie ~`TRAFFIT_SYNC_HOUR_UTC`=02:00 UTC): `updated_at >= since` (kandydaci, joby) / `created_at >= since` (activities, pipelines, sources); `since = last_synced - TRAFFIT_SYNC_DELTA_LOOKBACK_HOURS` (48h overlap) lub `now - TRAFFIT_SYNC_INITIAL_BACKFILL_DAYS` (45d) dla pierwszego runu. Pierwszy run po włączeniu odpala się natychmiast (ignoruje godzinę).
  - **full** (tygodniowo `TRAFFIT_SYNC_FULL_WEEKDAY`=6 niedz.): full-scan reconcile, safety net. **Gdy kursor którejś fazy budżetowanej (`candidate_files`, `candidates_cv`, `candidates_enrich_names`) wciąż stoi, pełny bieg jest należny CO NOC**, aż sweep dobiegnie końca (`should_run_full(sweep_pending=...)` + `full_sweep_pending()`). Przy rytmie tygodniowym ogon szedł w tempie wycinka na TYDZIEŃ — ~57k kandydatów to ponad miesiąc nietkniętych niedziel, a Coolify restartuje kontener przy każdym pushu na main, więc taki sweep mógł nie dojść do ogona **nigdy** (tak właśnie luka w plikach przeżyła miesiące przy zielonym healthu). Warunek czyta KURSORY, nie kalendarz, więc jest samoograniczający: dodatkowe biegi znikają tej nocy, w której sweep kasuje kursor. Slot wyłącznie `delta` **nie** liczy się jako zaległy sweep (te fazy kursorują tylko w trybie full).
- **Delta filtr:** `TraffitClient.get_paginated(..., filter_=...)` → nagłówek `X-Request-Filter` (day-granular). Jeśli tenant odrzuci (HTTP 400) → fallback na full scan (upserty są idempotentne, więc bezpieczne).
- **Notatki (kluczowe — „no notatka missing"):** importer NIE pisał do `notes` (jednorazowo zrobiła to migracja `0077`). `TraffitImporter.promote_notes(since)` powtarza logikę `0077` na każdym syncu — promuje `activities` (`traffit:Notatka/Email/Reply/Rozmowa telefoniczna/Spotkanie`) → `notes` (stamp `source_ref='traffit:activity:<id>'`). Wołane wewnątrz `import_candidate_activities`. **Dedup idzie po `source_ref`, nie po `created_at`** — znacznik czasu nie identyfikuje wiersza źródłowego i mylił się w obie strony: aktywność dosyłana PÓŹNIEJ z tym samym `created_at` (odpowiedź zalogowana nazajutrz, wiersz z backfillu) wyglądała jak już obecna i przepadała **na zawsze** (nic się w niej już nie zmieni, więc żaden kolejny sync jej nie uratuje), a aktywność, której `created_at` ktoś w Traffit poprawił, przestawała pasować do własnej notatki i wjeżdżała drugi raz jako duplikat. W jednym biegu problem był niewidoczny, bo promocja to jeden `INSERT ... SELECT`, a `NOT EXISTS` czyta stan sprzed instrukcji. Gałąź `source_ref IS NULL AND created_at = ...` **zostaje** i nie jest zaszłością: migracja `0077` zapisała historyczny backlog **bez** `source_ref`, więc klucz wyłącznie po `source_ref` zduplikowałby każdą notatkę z 0077 przy najbliższym syncu (~49k kandydatów). Te wiersze pozostają dopasowywane po znaczniku czasu do czasu ewentualnego backfillu `source_ref`.
- **Pliki/CV (delta):** scope = kandydaci **dotknięci w tym runie** (faza candidates upsertuje Traffit-zmienionych → Nexus `updated_at >= run_start`), NIE 45-dniowe okno danych (bo edycje w samym Nexusie bumpują `updated_at` wszystkich 49k → 2.7h zbędnych calli `/files`). Per kandydat pobiera tylko `file_id` których jeszcze nie ma (po `external_id="<emp>-<file>"`) → nowe/podmienione CV bez re-downloadu.
- **Pliki/CV (full reconcile) — jedyna ścieżka domykania luki.** Do 2026-08-10 full brał wyłącznie kandydatów z **zerem** plików (`HAVING count=0`), więc „ma jakikolwiek plik" było **trwałym zwolnieniem** ze sweepu: kandydat, któremu migracja pobrała 2 z 5 plików (reszta padła na `/content` non-200 / timeout), nie był oglądany **nigdy więcej** — delta widzi tylko rekordy zmienione w Traffit, a historyczne się nie zmieniają. **To była przyczyna „w Nexusie mniej CV niż w Traffit"** i żaden codzienny sync nie mógł tego naprawić. Teraz full przemiata **wszystkich**, pobierając wyłącznie brakujące `file_id`. Bo pełny sweep to ~49k calli `/files` (~2.7h przy `TRAFFIT_THROTTLE_RPS=5`) — dłużej niż odstęp między redeployami Coolify — skan jest **budżetowany** (`TRAFFIT_SYNC_FULL_FILES_LIMIT`, default **25000**) i **wznawialny** kursorem `after_id` w `traffit_sync_state.cursor_payload` (wiersz `candidate_files`). Kolejne biegi kontynuują sweep; po przejściu całej bazy kursor jest kasowany i następny full startuje świeży przebieg. **Operator domyka zaległość szybciej odpalając `POST /api/admin/traffit/sync?mode=full` kilka razy** — każdy bieg przesuwa kursor o kolejny budżet (nie trzeba czekać tygodnia na slice).
- **Enrich names (faza `candidates_enrich_names`):** Traffit rekordy bez imienia i bez użytecznego emaila lądowały jako `name="?"` / `lastname="?"` (importer pobierał CV do object storage, ale go NIE parsował). Ta faza (po `candidate_files`) czyta zapisane CV → `cv_text_extractor` → `parse_cv` (Claude→Ollama→regex) → `_apply_cv_enrichment`, fallback na imię z **nazwy pliku CV** (`name_from_filename`, konserwatywny — zgaduje tylko gdy 2 czyste tokeny / camelCase). Delta: scope `since=files_since` (świeże „?"); full reconcile: wszystkie pozostałe „?". **Idempotentny + bezpieczny** — wypełnia tylko puste/placeholder pola (`?`/`Nieznane` traktowane jako blank), nigdy nie nadpisuje realnej wartości. Logika współdzielona: `app/services/cv_backfill.py` + helpery `app/services/cv_enrichment.py` (wyniesione z `candidates.py`, re-eksport zachowany). **Backfill istniejących:** `POST /api/admin/candidates/backfill-names?limit=&prefer_llm=` (background, admin) + `GET .../backfill-names/status`. **Full reconcile jest budżetowany** (`TRAFFIT_SYNC_ENRICH_NAMES_LIMIT`, default 500 — każdy wiersz to call LLM) **i wznawialny** kursorem `after_id`: zbiór „?" NIE kurczy się sam (CV bez imienia zostaje „?"), więc bieg bez limitu w kółko płacił za ten sam prefiks `ORDER BY id` i nigdy nie docierał do ogona. Błędy per wiersz są **atrybutowalne** (`enrich candidate_name id=<nexus_id>`) — wcześniej `progress.errors` było przypisywane z pominięciem `add_error`, więc jeden trwale nieparsowalny CV zamrażał **globalny** watermark dzienny bezterminowo, a kwarantanna nie miała czego zaparkować.
- **Aktywacja:** Coolify env vault (secrety `TRAFFIT_TENANT/CLIENT_ID/CLIENT_SECRET` już ustawione z migracji) → `TRAFFIT_SYNC_ENABLED=true` → `POST /api/admin/traffit/sync?mode=delta` (admin) żeby odpalić pierwszy run; `GET /api/admin/traffit/sync/status` pokazuje watermark + per-phase stats.
- **Wznawialność (kursory) — bo Coolify restartuje kontener przy KAŻDYM pushu na main, a pełne biegi trwają godziny.** Faza bez kursora startuje po restarcie od zera i przy deployach częstszych niż tydzień może **nigdy** nie dojść do ogona. Kursory ma dziś: `candidates`, `candidate_activities` i `pipelines` (po numerze strony, `get_pages(start_page=)`), oraz `candidate_files`, `candidates_cv`, `candidates_enrich_names` (po `after_id` + budżet). **`candidate_sources` świadomie NIE ma kursora** — ta faza agreguje wszystkie wiersze w pamięci i zapisuje dopiero na końcu, więc kursor na stronie N pomijałby strony 1..N-1, których dane nigdy nie zostały zapisane; kursor wymagałby wcześniej inkrementalnego zapisu. Zamiast tego strony gubione przez `skip_on_5xx` (znany server-side bug `/sources/`) są liczone do `skipped_pages` i widoczne w `/sync/status` — celowo NIE jako `add_error`, bo nieatrybutowalny błąd przypiąłby `degraded` na stałe. Kursor siedzi w `traffit_sync_state.cursor_payload` na wierszu **fazy z `_phase_plan`** (nie `PhaseProgress.phase` — te bywają różne, np. `candidate_files` vs `candidates_files`; pomyłka zakłada widmowy wiersz w `/sync/status`). **Sloty są per tryb** (`{"delta": {...}, "full": {...}}`): numery stron delty są filtrowane po `since`, fulla nie, więc wspólny slot powodował, że nocna delta najpierw nadpisywała, a potem kasowała zaparkowaną pozycję fulla — wznawianie fulla było mechanicznie obecne i praktycznie martwe. Stary płaski kształt jest migrowany przy odczycie. Po HTTP 400 na filtrze klient zdejmuje filtr i restartuje od strony 1 → `saw_fallback` wstrzymuje zapis kursora (numery stron przestają odpowiadać `since`).
- **Faza `workflows` (szablony pipeline'ów) — zapis wsadowy pod SET-WIDE unique.** `pipeline_stage_defs` ma dwa ograniczenia obejmujące CAŁY szablon (`uq_stage_order_in_template (template_id, "order")` i `uq_stage_name_in_template (template_id, name)`), a wiersze pisane są **po jednym**, kluczem `(external_source, external_id)`. Przepisanie zbioru wiersz po wierszu pod ograniczeniem zbiorowym działa tylko wtedy, gdy żaden stan POŚREDNI nie koliduje — a zamiana kolejności w Traffit gwarantuje kolizję (stan B bierze pozycję 3, którą wciąż trzyma jeszcze nieprzepisany stan A). Cyklicznej zamiany nie da się rozwiązać kolejnością zapisów. Żadne z ograniczeń **nie jest DEFERRABLE** (entrypoint.sh obchodzi tę samą krawędź trikiem z przesunięciem), więc `_rewrite_template_stage_defs` najpierw **parkuje** wszystkie wiersze szablonu na `("order" = -id, name = '~<id>')` — unikalne per wiersz, bo `id` to PK, a ujemne pozycje nigdy nie spotkają docelowego układu (wszystkie ≥ 0) — i dopiero potem kładzie właściwy układ, już w dowolnej kolejności. **Stany, których Traffit przestał wysyłać, NIE są kasowane** (`candidate_stages.stage_def_id` na nie wskazuje — dlatego importer dawno porzucił DELETE+INSERT); dostają pozycje **za** żywymi, z zachowaniem względnej kolejności i nazw, a jeśli żywy stan zabrał nazwę wycofanego — ustępuje wycofany (żywy jest bieżącą prawdą). Każdy workflow siedzi w **SAVEPOINCIE**: stary handler wołał `db.rollback()`, czyli rollback SESJI, a faza commituje raz na końcu — jeden zepsuty workflow kasował wszystkie zapisane wcześniej w tym biegu. Na prodzie `processed: 2, updated: 2, errors: 1` nie znaczyło „1 z 2 padł", tylko „0 z 2 zapisanych", 23 biegi z rzędu.
- **Nagrobki (`candidates.external_deleted_at`, migracja `0221`).** 404/410 z Traffita było wcześniej wyłącznie **liczone** (`gone_upstream`), a licznik żyje tyle co statystyki biegu — więc informacja „tej osoby już u źródła nie ma" nie docierała nigdzie: rekruter widział zwykły profil, `reconcile` pokazywał rozjazd bez wyjaśnienia, a każdy kolejny sweep pytał o tego samego nieistniejącego kandydata. Trzy rzeczy, których ten mechanizm **celowo nie robi**: (1) **nie kasuje wiersza** — profil w Nexusie ma własną wartość niezależną od Traffita (notatki, etapy, ślady RODO), więc usunięcie u źródła nie jest zgodą na usunięcie NASZYCH danych; (2) **nie stawia nagrobka za brakujący PLIK** — 404 na `/employees/{id}/files` to odpowiedź o osobie, 404 na pobraniu pliku tylko o pliku, a pomylenie tych poziomów oznaczałoby oznaczanie profili jako usunięte z powodu jednego nieudanego załącznika; (3) **nie utrwala pomyłki** — upsert kandydata czyści znacznik, więc powrót w żywym feedzie `/employees/` kasuje nagrobek (bez tego pojedyncze 404 przy chwilowej awarii Traffita zostawiałoby trwałe kłamstwo). Warunek `external_deleted_at IS NULL` w UPDATE sprawia, że znacznik zapamiętuje **pierwszą** obserwację zniknięcia — inaczej data mówiłaby „kiedy ostatnio sprawdzaliśmy", a licznik `tombstoned` rósłby w nieskończoność zamiast odpowiadać, czy zniknęło coś **nowego**.
- **Ochrona dopisana do JEDNEJ ścieżki zapisu kandydata nie działa** (18.09.2026). Importer ma dwie gałęzie: `_UPSERT_CANDIDATE` (po `(external_source, external_id)`) i `_UPDATE_CANDIDATE_ADOPT` (po MAILU). **Produkcja chodzi drugą** — `email_to_id` jest budowane BEZ filtra `external_source`, więc kandydat już zaimportowany dopasowuje się sam do siebie po mailu. Czyszczenie nagrobka i lepka blacklista były wyłącznie w upsercie, więc: raz postawiony nagrobek nie znikał NIGDY (74 wiersze, w tym DWÓCH pracujących konsultantów niewidocznych dla automatu zamówień z maila — ten filtruje `external_deleted_at IS NULL`, więc jednemu założyłby drugiego kandydata i drugi kontrakt, a drugiemu podpiąłby zamówienie pod imiennika), a blacklista założona w NEXUSIE byłaby zdejmowana przy najbliższym syncu. Obie gałęzie mają teraz obie ochrony; pilnuje tego `test_traffit_adopt_path_protections.py`. **Dokładając cokolwiek do jednej z nich, sprawdź drugą.** Znany, nienaprawiony dług tej samej klasy: adopt przepisuje `cv_extracted_data.legacy_source` na `'traffit'` przy każdym biegu, niszcząc atrybucję pochodzenia, którą deklaruje zachowywać.
- **Health:** `/api/health.checks.traffit` = `unconfigured` (off) / `misconfigured` (brak secretów) / `degraded` (włączony, brak świeżego runu / errors) / `healthy` (ostatni `__daily__` < 36h, status ok). **To sonda ŚWIEŻOŚCI, nie kompletności** — `healthy` nie znaczy, że dane się zgadzają z Traffitem (tak właśnie luka w plikach/CV żyła miesiącami przy zielonym healthu).
- **Błędy WIERSZY faz wzbogacania są doradcze (od 11.09.2026):**
  `candidates_enrich_names`, `candidates_cv_fields` i `cortex` — błąd pojedynczego
  kandydata (`add_error`) nie wstrzymuje już watermarku `__daily__`, ale zostaje
  widoczny na wierszu fazy i w próbkach `/sync/status` (z klasą wyjątku, np.
  „backfill failed (ValueError)”). Powód: od 08.09 jeden trwale nieparsowalny
  kandydat zamroził `__daily__` i health pokazywał `degraded` przez dni, choć
  import działał. **Wywrotka CAŁEJ fazy (np. padnięty commit) nadal wstrzymuje
  watermark** — `candidates_cv_fields` nie jest objęta pełnym przebiegiem, więc
  bez przytrzymania kandydaci z tego biegu nigdy nie dostaliby pól z CV.
  Fazy importu rdzenia wstrzymują watermark jak dotąd.
- **DB:** `traffit_sync_state` (PK `phase` + markery `__daily__`/`__full__`) — migracja `0136_traffit_sync_state` (na bazie `0135`).
- **„Rekrutacja prowadzona w NEXUSIE" — `jobs.managed_in_nexus`** (migracja `0325`
  + lustro w `_COLUMN_STATEMENTS`, decyzja Artura 17.09.2026). Powód: tablica czyta
  NAJNOWSZY wiersz `candidate_stages` per (kandydat, oferta), a nocny import dopisuje
  etapy każdej rekrutacji z Traffita — ruch zrobiony w NEXUSIE przegrywał nazajutrz
  (131 z 32 872 ruchów w 90 dniach = 0,4 % powstało w NEXUSIE). Flaga PER OFERTA,
  przełączana ręcznie, żeby przenosić zespół falami:
  - faza `pipelines` pomija ruchy ofert z flagą (lookup `_build_managed_job_ids` RAZ
    na fazę, pominięcie PO mapperze i PRZED `dry_run`), licznik `skipped_managed`
    — osobny od `skipped` i obecny w OBU whitelistach statystyk (`PhaseProgress.as_dict`
    + `_summarize`); `GET /api/admin/traffit/sync/status` niesie
    `managed_in_nexus_jobs`;
  - `_UPSERT_JOB` nie nadpisuje `title`/`status`/`closed_at` przełączonej oferty
    (CASE jak `recruiter_id`↔`is_open`) i nie unieważnia wtedy wymagań (tytuł się nie
    zmienia). `deadline`/`opened_at`/`client_id`… nadal DOPEŁNIAJĄ puste pola
    (COALESCE), `custom_fields` scala JSONB. Kolumny flagi są w `NEXUS_OWNED`;
  - `POST /api/jobs/{id}/manage-in-nexus` (`TacPlus` + członkostwo sprawdzane PO
    odczycie oferty — brak oferty = 404; wyłączenie tylko admin / Delivery Lead = 403
    dla reszty; rekrutacja spoza Traffita = 409; idempotentne) — OSOBNA trasa, nie
    pole w PATCH: każda realna zmiana zostawia `activities.action='managed_in_nexus_changed'`
    z poprzednią wartością, a formularz edycji nie przełączy „przy okazji";
  - UI: `components/v2/jobs/ManagedInNexusSwitch.tsx` — baner nad tablicą dla
    nieprzełączonych rekrutacji z Traffita (ruch dozwolony, przycisk „Przełącz do
    NEXUSA") i chip „Prowadzona w NEXUSIE od …" w nagłówku (powrót do Traffita z chipu);
  - `rejection_backfill` nietknięty — aktualizuje tylko powód/notatki, nie zmienia etapu.

## Self-service registration (email/password — alternatywa dla Microsoft SSO)

Rejestracja bez logowania przez Microsoft, ograniczona do domen z whitelisty
`SSO_ALLOWED_DOMAINS` (te same co SSO, np. `b2bnetwork.pl`). Nowe konta są
**Recruiterem** (`UserRole.recruiter`) i zaczynają z dwiema zamkniętymi bramami:
`email_verified=false` do kliknięcia linku aktywacyjnego oraz
`profile_completed=false` do ukończenia obowiązkowego onboardingu Recruitera.
Najpierw użytkownik weryfikuje email, następnie po pierwszym loginie aplikacja
kieruje go na `/onboarding`; dopiero ukończenie onboardingu odblokowuje shell i
powierzchnie kandydatów/RODO. Legacy `UserRole.user` jest wycofywany przez
migrację 0210 i nie może być już nadawany. Pełny opis pierwotnego mechanizmu:
`docs/self-registration-completion-report.md`; aktualny cutover:
`docs/role-dashboard-rbac-cutover.md`.

- **Kill-switch:** `SELF_REGISTRATION_ENABLED` (default `false`). Off → `POST /api/auth/register` zwraca 503, strona `/register` pokazuje "rejestracja wyłączona".
- **Endpoint `POST /api/auth/register`** (`app/api/auth.py`): gate → domain whitelist (fail-closed, pusta lista = reject-all) → rola **wymuszona `recruiter`** server-side (`SelfRegisterRequest` NIE ma pola `role`) i `profile_completed=false` → `email_verified=False` → token + mail. **Anti-enumeration:** zawsze generyczne `201` (nigdy `409`), bcrypt liczony na obu ścieżkach (no timing leak); duplikat na niezweryfikowanym koncie re-wysyła link, na zweryfikowanym — cicho no-op.
- **`POST /api/auth/verify-email`** — jednorazowy 64-hex token (SHA-256 hash, TTL 24 h) → `email_verified=True`. **`POST /api/auth/resend-verification`** — anti-enum (zawsze 200).
- **Login + onboarding gate:** `login` blokuje konta z `email_verified=False` (czytelny komunikat PL). Po weryfikacji Recruiter może się zalogować, ale `profile_completed=false` kieruje go na `/onboarding` i blokuje domenowe endpointy do chwili ukończenia formularza. Istniejący userzy email/hasło + SSO mają `email_verified=True` (backfill migracji + SSO ustawia), więc **nie są dotknięci bramą emailową**.
- **Frontend:** `/register` (formularz) + `/register/verify` (auto-verify on mount) + link na `/login`; `/register` w `PUBLIC_PATHS` (`middleware.ts`).
- **DB:** `users.email_verified` (BOOLEAN NOT NULL DEFAULT true) + tabela `email_verification_tokens` (bliźniacza do `password_reset_tokens`) — migracja `0139_email_verification` (na bazie `0138_candidate_expected_hourly_rate`; aplikowana przez `alembic upgrade heads`).
- **Aktywacja na prod:** Coolify → `SSO_ALLOWED_DOMAINS` zawiera `b2bnetwork.pl` (już z SSO) + `SMTP_ENABLED=true` (+ SMTP creds, żeby mail aktywacyjny wyszedł) + `SELF_REGISTRATION_ENABLED=true`.

## Competence Categories (5 CC — podział profili, filtr, badge wszędzie)

Backbone CC istniał od `0033`/`0041` (5 kategorii zaseedowane w entrypoint `_DATA_STATEMENTS`:
`infrastructure_operations`, `software_development`, `data_ai`, `security_quality`,
`management_delivery`). Ten moduł go **odsłania**: filtr w głównej liście + backfill 49k +
badge wszędzie. Decyzja: **5 głównych** (podkategorie = Faza 2), **primary + do 2 pobocznych**.
Pełny opis: `docs/competence-categories-completion-report.md`.

- **Jedno źródło zapisu:** `app/services/candidate_cc_assignment.py::apply_candidate_cc_scores`
  pisze M2M `candidate_competence_categories` (1 primary + do 2 secondary, `confidence` +
  `source` band: `ai_auto` ≥0.80 / `ai_suggested`) I synchronizuje legacy `competence_category`
  (slug) + `competence_category_id` (FK). **Manual-safe:** kandydat z jakimkolwiek wpisem
  `source='manual'` nie jest ruszany. `overwrite=False` = uzupełnij tylko gdy puste. Używają go
  OBIE ścieżki auto (`_auto_assign_primary_cc` w `candidates.py` na wgraniu CV + `public_share.py`
  invite-apply) oraz backfill.
- **Filtr listy:** `GET /api/candidates?competence_category_id=<id>` (repeat = OR), match primary
  LUB secondary (M2M) OR legacy FK. FE: `lib/url-filters.ts` (`competenceCategoryIds`, URL `cc`) +
  sekcja „Kategoria kompetencji" w panelu `CandidatesListV2` (reuse `CompetenceCategoryMultiSelect`)
  + chip w `ActiveFilterChips`.
- **Badge:** `components/v2/CompetenceCategoryBadge.tsx` (token-owy, slug→`name_pl` z cache
  `GET /api/competence-categories`) — w wierszu listy, kafelkach, quick-view, nagłówku profilu.
- **Backfill 49k (aktywacja):** `POST /api/admin/candidates/backfill-cc` (+ `/status`), admin,
  background, resumable, `only_missing=true` domyślnie (tylko `competence_category_id IS NULL` →
  zero nadpisania). To ścieżka prodowa (brak SSH/DB). CLI: `python -m scripts.backfill_candidate_cc
  --dry-run|--commit [--all]`. **Bez migracji** — schemat już jest.

## Talent Radar (wklejasz request → ranking bazy, bez zakładania rekrutacji)

Sekcja `/talent-radar` + `POST /api/talent-radar/search`. Rekruter wybiera
klienta, wkleja treść requestu i dostaje ranking kandydatów. **Nie tworzy
oferty** — to przeszukanie bazy, nie krok pipeline'u. PR-y: #1115 (silnik),
#1116 (rename źródła), #1119 (UI).

- **Nazwa kolidowała i kolizja została rozstrzygnięta na korzyść modułu.**
  `talent_radar` funkcjonował od maja jako *legacy źródło importu* z Supabase.
  Migracja `0222` przepisała je na `tr_legacy` (15 wierszy — nie 40 745, ta
  liczba z docstringu importera opisuje rekordy POBIERANE, a importer scala).
  Ograniczenia `CHECK` **nadal akceptują starą wartość** (widen-then-migrate),
  a typ we froncie ma obie — dlatego zmiana niczego nie zerwała. Trasy techniczne
  zostają: `/api/admin/import-talent-radar` to wciąż tamten import.
- **`client_id` jest WYMAGANY, nie opcjonalny.** Filtr dopuszczalności sprawdza
  względem niego blacklistę klienta, NDA, konflikty konkurencyjne i weto hiring
  managera. Opcjonalny klient dałby listę, w której te kontrole cicho nie
  zaszły — dokładnie defekt naprawiony w `/ai-matches` (#1109). Dlatego UI ma
  **własny picker** (`TalentRadarClientPicker`), a nie `ContractsClientPicker`:
  tamten oferuje „Wszyscy klienci (lista globalna)" jako wybór, co tutaj jest
  zaproszeniem do czegoś, co z definicji nie może zadziałać.
- **`meta.degraded` MUSI renderować się jako awaria, nigdy jako pusty stan.**
  Gdy Qdrant albo Voyage milczy, backend zwraca zero wyników z tą flagą.
  „Brak dopasowań" byłoby wtedy kłamstwem w najgorszą stronę — rekruter uznałby,
  że w bazie nie ma nikogo takiego. Harness `/preview/talent-radar` (publiczny,
  same mocki, zero wywołań API) pokazuje te stany obok siebie właśnie po to,
  żeby różnica nie zniknęła przy kolejnej zmianie.
- **Ranking bez cache'u.** `rank_candidates_for_job`, NIE `bulk_get_or_compute`:
  klucz cache'u to `(kandydat, oferta, profil)`, a ta oferta nie ma `id`, więc
  cache albo kolidowałby między niezwiązanymi wyszukiwaniami, albo wywracał się
  na pustym kluczu. Z tego samego powodu `build_ephemeral_job` ma **`id=None`
  jako rzecz znaczącą, nie zaślepkę** — `build_job_scoring_context` filtruje
  `CandidateStage.job_id == job.id`, więc puste id oznacza brak historii
  pipeline'u, co dla wyszukiwania ad hoc jest poprawne.
- **`SimpleNamespace`, nie nieprzypisany `Job`.** Instancja ORM niesie deskryptory
  relacji, które przy dostępie do atrybutu potrafią odpalić lazy load — w async
  SQLAlchemy to `MissingGreenlet`, nie wartość domyślna. Test wychodzi wymagane
  atrybuty **AST-em po źródle** `scoring_service`/`embedding_service`/
  `pipeline_eligibility`, a nie z ręcznej listy, bo ręczna lista przechodzi
  dalej w dniu, w którym scoring zacznie czytać nowe pole.
- **Wyniki niosą tożsamość węższą niż profil** — bez e-maila, telefonu i stawki.
  Lista rankingowa służy do decyzji KOGO otworzyć; kontakt jest za kliknięciem.
  Warstwa wynagrodzenia jest wygaszana (`status: "not_applicable"`), bo radar
  nie ma widełek i surowe zero czytałoby się jako „nie pasuje finansowo".
- **Role: KAŻDA zalogowana** (decyzja produktowa Artura 19.08 — poszła po
  zrzucie 403 od Head of Recruitment; wcześniej `require_candidate_write` bez
  HoR). PIĘĆ lustrzanych miejsc: backend oba endpointy na `CurrentUser`,
  middleware BEZ wpisu `/talent-radar` (brak wpisu = brak zawężenia ról, sam
  login wymagany), sidebar bez `roles`, `nav.talent_radar = ALL_ROLES` w
  `CAPABILITY_ROLES` (paleta ⌘K czyta stamtąd) oraz SAM `page.tsx` BEZ
  `RequireRole` — piąta kopia starej listy ról (in-page `RequireRole` z
  fallbackiem „Brak uprawnień") przeżyła otwarcie #1212 i wyszła dopiero ze
  zrzutu użytkownika, zdjęta w follow-upie. Test kontraktowy pilnuje, że
  guard rolowy (`_check`) NIE wróci na trasy radaru cichym refaktorem.
  **Granice, które ZOSTAJĄ**: wyniki niosą tożsamość węższą niż profil (bez
  kontaktu i stawek), a „Otwórz profil" renderuje się tylko dla ról z
  `nav.candidates` — po decyzji z 19.08 (finance = pełny dostęp operacyjny)
  poza tą capability jest już wyłącznie viewer `user`.
- **Pułapka przy dokładaniu endpointów**: moduł z `@limiter.limit` nie może mieć
  `from __future__ import annotations` (PEP 563 + slowapi #579 → body ląduje jako
  parametr Query). Pilnuje tego test czytający AST, nie treść pliku — docstring
  wspomina ten import, żeby przed nim ostrzec, więc szukanie stringu wywalało
  się na własnym ostrzeżeniu.

### Pełny przegląd bazy (#1428): retencja, cykl życia, bramka must-have (10.09.2026)

Od #1428 Radar i „cała baza” w rekrutacji oceniają CAŁĄ populację (~60 tys.)
w trwałym przeglądzie (`candidate_search_runs` + wiersz na kandydata
w `candidate_search_results`, ~100–130 MB na przegląd). Worker działa w procesie
web — jeden przegląd naraz, ~3 min.

- **Retencja (decyzja 10.09):** pętla `candidate_search_retention` kasuje
  zakończone przeglądy (`complete`/`partial`/`failed`) starsze niż
  `CANDIDATE_SEARCH_RETENTION_DAYS` (7), ale najnowszy przegląd z wynikami
  zostaje dłużej — na (autor, OTWARTA rekrutacja), a bez rekrutacji jeden na
  autora — najwyżej `CANDIDATE_SEARCH_RETENTION_PROTECT_MAX_DAYS` (90).
  **Nie chroń per odcisk requestu ani bez limitu czasu:** każda nowa treść
  requestu i każdy bump wersji polityki dawałyby nową, wiecznie chronioną
  partycję, a tabela rosłaby z liczbą par zamiast z czasem (przegląd
  adwersarialny 10.09). Kill-switch `CANDIDATE_SEARCH_RETENTION_ENABLED`
  (pętla kończy się przed `while True`). Indeksy z migracji 0305 (`completed_at`
  przeglądu, `candidate_id` wyników) mają lustro w `_INDEX_STATEMENTS`.
  Rozmiar tabeli widać w `GET /api/admin/index-coverage` (blok `candidate_search`).
- **Stan `failed`:** przejęcie przeglądu zwiększa `metrics.claims` w tym samym
  UPDATE; zgłoszona porażka od trzeciego przejęcia (`MAX_FAILED_ATTEMPTS`)
  kończy przegląd jako `failed`, a przejęcia bez raportu — proces zabity
  w trakcie, u nas zwykle deploy — mają szerszy budżet (`MAX_CLAIMS` = 8).
  Reaper kończy przejęte przeglądy bez postępu od 30 min. Do 10.09 przegląd,
  który padł, był podejmowany na nowo w nieskończoność i trwale zajmował jeden
  z dwóch slotów autora. `failed` nie liczy się do limitu; front pokazuje
  „Uruchom ponownie”. Odpytywanie staje tylko po błędzie OSTATECZNYM
  (409/404/403 — `searchErrorIsFinal`); chwilowa awaria (sieć, 5xx, deploy)
  odpytuje dalej co 5 s i trzyma blokadę przycisku startu, żeby nikt nie
  odpalił drugiego trzyminutowego skanu. „Spróbuj ponownie” czyta przegląd,
  a nie odpala nowego skanu.
- **RODO:** twarde usunięcie kandydata kasuje jego wiersze wyników, a aktywne
  przeglądy z tą osobą kończy jako `failed` (`candidate_erased`) —
  `finish_run` wymaga rozliczenia całej migawki.
- **Bramka must-have (decyzja 10.09): `requirement_contract.search_dealbreaker_inputs`
  to JEDNO miejsce polityki dla wszystkich powierzchni.** Polityka `review`
  (domyślna) ukrywa kandydata, którego ZNANE umiejętności nie obejmują
  must-have rozpoznanego jako technologia; kandydat bez danych przechodzi;
  proza nigdy nie bramkuje. `exclude` dokłada ukrywanie braku dowodu. Po #1428
  do 10.09 `review` zdejmowało bramkę w całości (nikt nie był ukrywany).
  `MUST_GATE_POLICY_VERSION` jest częścią odcisku requestu — zmiana znaczenia
  polityki = bump, inaczej stare rankingi udają aktualne. Kill-switch
  `RUBRIC_DEALBREAKERS_ENABLED` działa raz, w `apply_dealbreakers`.
- **„Przekaż do searchu” liczy must-have podane prozą jako podane**
  (`must_skills or must_skills_ignored` w `job_readiness.py`). Do 10.09 rekrutacja
  z samą prozą dostawała 422, choć dok gotowości pokazywał ✓.
- **Podobieństwo liczy Qdrant, nie Python (od 11.09.2026).**
  `full_search_measurement.measure_candidates` robi JEDNO wyszukiwanie dokładne
  z filtrem po ID (`HasIdCondition`, `SearchParams(exact=True)`, kwantyzacja
  ignorowana) i ściąga tylko payload pochodzenia (`content_hash`,
  `embedding_model`). Wcześniej przegląd ściągał 256×1024 liczby na paczkę jako
  JSON i liczył cosinus w Pythonie (1,48 s → 0,08 s na 3000 kandydatów; parytet
  do 4e-8). **Odpowiedź 4xx i dokładne 0.0 wracają na ścieżkę referencyjną**
  `_measure_by_retrieval` — zerowy wektor też punktuje 0.0, a zepsuty wektor nie
  może udawać zmierzonego zera. Pętle CPU (`canonical_fit`,
  `full_candidate_scan`, pomiar) oddają pętlę zdarzeń co 32 elementy, bo worker
  żyje w procesie web.
- **Konsumenci kanonicznego fitu pytają pulę bez rerankera**
  (`retrieve_candidate_pool(use_rerank=False)`: `/ai-matches`, rekomendacje,
  propozycje, digest). Pula = `final_top_k`, więc reranker zmieniał wyłącznie
  kolejność, którą i tak nadpisuje sortowanie po `fit_score` — był czystym
  kosztem (wywołanie Voyage i SELECT puli). `None` = `RERANKER_ENABLED`.
- **Higiena indeksu: `GET/POST /api/admin/index-cleanup`** (admin JWT). GET to
  plan tylko do odczytu z odciskiem: punkty kandydatów bez wiersza (sieroty)
  i oferty bez punktu lub stempla `embedding_id`. POST z odciskiem i licznikami
  kolejkuje DOKŁADNIE ten plan w outboxie indeksu (plan się zmienił → 409).
  Kasowania sierot niosą `desired_hash="orphan-point"` i worker przy wykonaniu
  sprawdza, że wiersza kandydata nadal nie ma — tą ścieżką nie da się skasować
  punktu istniejącego kandydata. Plan czyta najpierw indeks, potem SQL, więc
  kandydat dodany w trakcie nie wygląda na sierotę. Odcisk obejmuje tylko części
  wykonawcze (sieroty, oferty do embeddingu) — globalne liczniki są w odpowiedzi,
  ale nie w odcisku, inaczej każdy niezwiązany embedding między GET a POST
  dawałby 409.
- **Kolumna dopasowania w wyszukiwarce ręcznej i pierścień „Dopasowanie” to
  kanoniczny fit** (ten sam, co na ekranach C2), a nie `CandidateJobMatchScore`
  — żaden ekran go już nie czyta. `/api/search/candidates/scores` liczy na
  żądanie najwyżej 20 ID (422 powyżej), limit 60/min **per zalogowany
  użytkownik** (`user_or_ip_key` — biuro za jednym NAT-em nie dzieli kubełka;
  ten sam klucz ma ocena opisu „Dopasowanie”), **za tą samą bramką co
  pełny przegląd (`_authorized_job` z `candidate_search.py`)** — rekruter,
  sourcer i TAC spoza zespołu widzą ten sam wynik na ekranach C2, więc kolumna
  nie może być ostrzejsza (pierwsza wersja z `ensure_job_read_access` chowała go
  im bez słowa); stawki redagowane bez `view_finance`. Front pyta tylko
  o wiersze na ekranie (`useVisibleMatchScores`, anulowanie AbortControllerem,
  cache per `profile_key` z odpowiedzi): niezmierzony = „Ocena niepełna”,
  403 = „brak dostępu”, inny błąd = „nie policzono — ponów” (429 ponawia sam
  z backoffem — jedna runda dla WSZYSTKICH wierszy czekających na ponowienie,
  także z kilku równoległych paczek) — nigdy puste pole ani 0. Modal porównania pokazuje błąd
  z „Ponów”, nie „Brak kryteriów”.
- **Pierścień „Dopasowanie” liczy się we własnej sesji** (`display_fit`, tylko
  do odczytu, nigdy nie rzuca): wcześniej wyjątek w nim robił rollback sesji
  requestu, wygaszał `current_user` i zakładka kończyła się 500
  (`MissingGreenlet`), a współdzielona instancja kandydata przestawiała stare
  rozbicie i hash opisu (płatne regeneracje). **Opis AI nie podaje liczby
  punktów** (`MATCH_JUSTIFICATION` v2 bez `{score}`) — liczbę pokazuje pierścień,
  a opis tłumaczy mocne strony i luki. Zapisane opisy odświeżają się leniwie
  przy następnym otwarciu (wersja promptu jest w hashu).
- **Telemetria jest podpięta.** Strona wyników pełnego przeglądu zapisuje
  impresje obsłużonych wierszy jednym INSERT-em (`match_impressions`, `run_id`
  = id przeglądu). Dodanie do pipeline'u (`proposals_bulk`) przypina outcome
  `add_to_pipeline` WYŁĄCZNIE do przeglądu, który klient zadeklarował (`run_id`
  + `source`), i tylko gdy to przegląd tej osoby, tej rekrutacji i z impresją
  tego kandydata — w innym wypadku `run_id` = NULL. Żadnego zgadywania po
  „ostatnio widzianym” (to zawyżało pozytywy C2 dodaniami z wyszukiwarki
  ręcznej). `source` (`full_search` | `manual_search` | `historical` |
  `quick_add` — każdy ekran dodawania wysyła swój) żyje w
  `match_outcomes.reason_code` (stały słownik, bez migracji). Zapis we własnej sesji po commicie, nigdy nie rzuca, najwyżej 100
  wierszy. Tabele nie mają FK do kandydatów (celowo: analityka, pseudonimy,
  rozbicie wyłącznie liczbowe) ani jeszcze retencji — świadomy dług.
- **Eval: nigdy nie porównuj metryk między scorerami.**
  `scripts/eval_matching.py --scorer canonical` domyślnie maskuje dowody wymagań
  zweryfikowane przez rekruterów (wyciek etykiety, jak `champion_fit`);
  `--include-reviewed-evidence` je przywraca. `weekly_eval` mierzy canonical
  i porównuje tylko biegi tego samego scorera (bieg bez klucza `scorer` =
  legacy), więc pierwszy bieg canonical to `baseline: "scorer_changed"`, nie
  regresja. A/B na prodzie: `coolify-ops.yml` `action=eval-ab-scorer` (legacy to
  ramię kontrolne, ma odtworzyć baseline 18.08). `--pool full` nie ma sensu:
  pełny przegląd ukrywa kandydatów już w rekrutacji, czyli wszystkie pozytywy.
- **Komenda zadania Coolify ma najwyżej 255 znaków** (`scheduled_tasks.command`
  = VARCHAR(255) — dłuższa kończy `POST /scheduled-tasks` gołym HTTP 500). Oba
  kanały A/B wysyłają więc tylko `python -m scripts.eval_ab_run …`, a ramiona,
  zamrożoną listę ofert i sekcje raportu liczy skrypt; workflow pilnuje długości
  przed wysłaniem. Do 11.09 komenda A/B miała ~1,6 tys. znaków (dwie listy 50
  ofert w YAML-u) i żaden bieg nie mógł wystartować. Długie zadanie potrzebuje
  też jawnego `timeout` (Coolify od 11.2025 ubija po domyślnych 300 s). Każdy
  nowy kanał operacyjny: logika w `scripts/`, w komendzie tylko argumenty.
- **Surowy SQL (`text()`) musi przejść `PREPARE`** — `= ANY(:ids)`, nie
  rozwijane `IN :ids` (strażnik `test_raw_sql_prepares`).

## Audyt manualny Codexa 13–15.09.2026 — reguły, które łatwo cofnąć

Raport naprawczy: `docs/manual-audit-2026-09-13-remediation-report.md`.

- **Budżet PLN/h rekrutacji ma JEDNO pole do wyświetlania:
  `JobResponse.effective_budget_hourly`** (`resolve_job_budget_hourly` — jawne
  pole albo stawka Championa, ta sama funkcja co filtr). Nagłówek, pasek AI
  Matching i dok oferty czytają je przez `lib/job-budget.ts`. Pole jest
  redagowane dla viewera i zdejmowane z listy rekrutacji (wyliczane także ze
  stawki Championa). `budget_max_at_move` w doku to migawka MIESIĘCZNYCH
  widełek z chwili ruchu — podpisana jako taka, nigdy jako budżet (B62/B72).
- **Akceptacja szkicu Championa synchronizuje kolumny rekrutacji** jak zapis
  z edytora (`_sync_job_columns_from_applied_sections`): stack → `must_skills`/
  `nice_skills`, podstawy → `rate_budget_hourly` itd. (FILL_EMPTY).
- **„W procesie” w AI Matching = `countInProcess` z kanbana** (bez odrzuconych).
  `pipeline_candidate_ids` obejmuje też etapy końcowe i służy wyłącznie
  plakietce „już w pipeline” (B71).
- **Prep kit opisuje stack z wymagań roli** (`job_skill_requirements`), nie
  z `ClientKnowledge.tech_stack`; pytania z poziomów 1–3 (podobne rekrutacje,
  wiedza klienta) o technologie spoza wymagań odpadają (`_fits_job`) (B70).
- **Rekrutacje klienta `hidden` albo `deleted_at` nie trafiają do rejestru,
  dashboardu procesów ani dashboardu Delivery** (`job_client_listed_clause`,
  EXISTS z `correlate_except(Client)`). Świadomie BEZ `archived_at` —
  archiwalny prawdziwy klient ma historyczne rekrutacje (B73).
- **Edycja kandydata edytuje wyłącznie tagi-napisy** (`lib/candidate-tags.ts`);
  obiekty importu (`traffit_source`) wracają do zapisu nietknięte, a
  niezmienione tagi w ogóle nie jadą w PATCH (backend zastępuje listę) (B60).
- **Kolumna „Stawka” listy kandydatów = stawka z profilu**
  (`expected_rate_hourly`, ta, po której filtruje lista); `last_rate` z etapu
  to druga linia „w procesie” (B58).
- **Powody niepewności odczytu PDF zamówień są po polsku**: prompt v7 +
  `_polish_model_reason` przy parsowaniu i `polish_gate_reason` przy
  wyświetlaniu zapisanych `gate_reasons` (stare dokumenty) (B77).
- **Karta M365 pokazuje `last_error_code`** (`services/m365/error_codes.py`,
  klasyfikacja przy odczycie, bez migracji); surowy `last_error` tylko
  w „Szczegółach technicznych” (B61).
- **`Button asChild` renderuje sam `Slot` z jednym dzieckiem** — loader obok
  children rzucał wyjątek Radix (B74).
- **Pasek boczny: pionowe wymiary identyczne w obu stanach**
  (`SIDEBAR_VERTICAL_LAYOUT`), a rozwinięcie pod kursorem to nakładka nad
  treścią. Nie przywracaj nagłówka sekcji zależnego od stanu ani różnych
  `space-y` — klik trafiał w sąsiedni link (B57).

## Rekrutacja v3: lista `/jobs` i „Więcej" w pasku bocznym

Decyzje właściciela: pulpit i topbar bez zmian, **nic nie znika** — zmienia się
miejsce, nie zbiór funkcji.

- **Klik w wiersz listy OTWIERA rekrutację** (`router.push`, Ctrl/⌘ = nowa
  karta; tytuł zostaje linkiem). Dok gotowości (`JobReadinessDock`, wariant
  `list`) otwiera ikona **„Podgląd"** w wierszu i na kafelku (`aria-label`
  „Podgląd: {tytuł}", `aria-pressed`), zamyka „Zamknij podgląd". Dok nie
  otwiera się sam, a wiersz `can_open === false` nie ma ani nawigacji, ani
  podglądu (dok pytałby o detal → 403). Gałąź kafelka z `pointer-events-none`
  + `aria-disabled` czyta test backendu — nie ruszaj jej.
- **Domyślny zakres zależy od ROLI** — jedna czysta reguła
  `defaultMineForUser` (`lib/jobs-url-filters.ts`, semantyka `hasRole`):
  recruiter, sourcer, tac, talent_community_manager, delivery_lead → „Moje"
  (także konto wielorolowe z którąkolwiek z nich); admin, head_of_recruitment,
  finance i viewer `user` → „Wszystkie". Jawne `mine=0/1` w adresie ZAWSZE
  wygrywa; do adresu trafia tylko zakres INNY niż domyślny roli (czyste `/jobs`
  znaczy więc co innego u rekrutera i u admina — link „dla kolegi" wysyłaj
  z jawnym zakresem). Stan to NADPISANIA (`mineOverride`/`sortOverride`,
  `null` = bez wyboru), bo rolę znamy dopiero po hydratacji store'u; zapytanie
  listy ma `enabled: hydrated`. „Wyczyść" = `null` = domyślny roli. Pusty
  zakres „Moje" ma własny komunikat z „Pokaż wszystkie" — to nie pusta baza.
  Zakres NIE liczy się do „Filtry (N)". Licznik „Wszystkie" to pole `all`
  z `/api/jobs/quick-counts`.
- **Sortowanie domyślne zależy od zakresu** (`defaultSortForScope`):
  „Moje" → `sort=attention` („Wymaga uwagi"), „Wszystkie" → `newest`. Do
  adresu trafia tylko sortowanie INNE niż domyślne zakresu. Zmiana zakresu
  przestawia sortowanie wyłącznie wtedy, gdy nie było wybrane jawnie.
- **Kolumna filtrów jest zwijana** (`store/ui.ts` v7, `jobsFiltersCollapsed`):
  `null` = brak wyboru → rozwinięta od `2xl`, zwinięta poniżej — liczone
  CSS-em (`hidden 2xl:block`), bez migotania przy hydracji. W trybie `null`
  otwarty dok chowa filtry (trzy kolumny ucinały tabeli termin i akcje).
- **Kolumny:** „Etapy" = sześć liczb z `stage_columns`, grupowanych TĄ SAMĄ
  funkcją co lejek (`buildStageFunnel`; tooltip `funnelGroupStages` wymienia
  pełne nazwy etapów szablonu), „Wymaga ruchu" = `needs_action_count`
  (0 = wyszarzone „na bieżąco", 1–4 ostrzeżenie, 5+ czerwone; brak pola =
  kreska, nie zero) i „+N propozycji" (`open_proposals_count`, ukryte przy 0)
  → `/jobs/{id}?tab=people&seg=proposals`. Komórki: `v2/jobs/JobListCells.tsx`.
- **Słownik tego ekranu:** „Moje rekrutacje", „Brak opiekuna TAC"
  (`tac_id IS NULL`; celowo NIE „Brak właściciela" — kolumna „Właściciel"
  pokazuje `primary_owner`, więc wiersz mówiłby „Marta K." i „brak
  właściciela" naraz). „Potrzebny search", „Priority Work"
  i nazwy techniczne zostają.
- **Klucze react-query listy buduje `jobsListQueryKey` /
  `jobsQuickCountsQueryKey`** — harness `/preview/jobs-list-v3` zasiewa cache
  tymi samymi funkcjami, a zapytania doku odcina interceptorem (zero sieci).
- **Pasek boczny = szyna w GRUPACH z nagłówkami + „Więcej" (21.09.2026).**
  `placement` w `lib/nav-registry.ts` jest PER WPIS, niezależne od roli (kto
  co widzi, rozstrzyga wyłącznie bramka widoczności). Szyna to
  `NAV_PRIMARY_GROUPS`: **„Praca"** (Dashboard, Rekrutacje, Kandydaci,
  Kalendarz) · **„Klienci i umowy"** (Klienci, Kontrakty, Zamówienia z maila)
  · **„Firma"** (Finanse, Insights); `NAV_PRIMARY_ORDER` jest ich
  spłaszczeniem, `visiblePrimaryGroups` zwraca grupy danej roli i odrzuca
  PUSTE (rekruter nie widzi nagłówka „Klienci i umowy"). Reszta w grupach
  `NAV_MORE_GROUPS`. Nowy wpis `more` MUSI mieć `moreGroup`, nowy `primary` —
  miejsce w dokładnie jednej grupie szyny (pilnuje `nav-registry.test.ts`).
  **Wyszukiwarka i Talent Radar NIE stoją w menu** — to tryby ekranu
  „Kandydaci" (`/candidates?mode=search`, `?mode=request`); oba wpisy mają
  `inSidebar: false` i żyją w palecie ⌘K („Wyszukiwarka kandydatów",
  „Szukaj z treści requestu (Talent Radar)", słowa kluczowe „radar",
  „wyszukiwarka"). Radar jest dla KAŻDEJ roli (19.08), a /candidates tylko dla
  `nav.candidates`, więc `resolveHref` radaru daje `/talent-radar` (strona
  samodzielna) roli bez `nav.candidates` (np. viewer `user`). Nagłówek grupy
  (`SidebarNavGroup`/`SidebarGroupHeading` w `SidebarMore.tsx`) siedzi
  w stałym slocie `SIDEBAR_VERTICAL_LAYOUT.sectionSlot` w OBU stanach:
  rozwinięta szyna — tekst, zwinięta — kreska `aria-hidden` tej samej
  wysokości, a tekst zostaje jako `sr-only`, bo `role="group"` jest nazwane
  przez `aria-labelledby`. Stałe B57 żyją w `SidebarMore.tsx` (czyta je też
  szuflada), `SidebarV2` je re-eksportuje. „Kto co widzi" testuj przez
  `visibleNavHrefs` (szyna + „Więcej"); `visibleNavSections` zostaje widokiem
  sekcjami całego menu. Paleta ⌘K nadal listuje wszystko.
- **„Więcej"** (`v2/shell/SidebarMore.tsx`): Radix Popover w trybie modalnym
  (pułapka fokusu, Esc, fokus wraca na przycisk, strzałki chodzą po linkach),
  licznik = SUMA liczników w środku, bieżąca strona spod „Więcej" zapala
  przycisk. Przycisk używa `navItemClassName` (ta sama wysokość co linki) i
  stoi za stałym slotem z kreską — inwariant `SIDEBAR_VERTICAL_LAYOUT` (B57)
  zmierzony: pozycje Y identyczne przy 60 i 240 px. Przy otwartym panelu
  `mouseleave` szyny jest ignorowany, a zamknięcie zdejmuje hover. Szuflada
  mobilna renderuje grupy w linii (`SidebarMoreInline`), bez nakładki.

## Kanban bez bramek (decyzja Artura, 17.09.2026)

Tylko 0,4 % ruchów w pipeline powstawało w NEXUSIE (131 z 32 872 w 90 dniach —
reszta z nocnego importu Traffita), a bramki zniechęcały do przeciągania kart.
Decyzja: **żadna bramka nie blokuje przepływu** — ostrzeżenia i odznaki zamiast
blokad. Razem z przełącznikiem „Rekrutacja prowadzona w NEXUSIE" (sekcja
Traffit) to warunek przenoszenia zespołu z Traffita falami. Nie przywracaj
żadnej z bramek bez decyzji właściciela.

- **Brak karty „Oczekuje".** Bramka jest USUNIĘTA z kodu (18.09.2026; do tego
  dnia wyłączała ją flaga — nazwa w raportach z 17.09.2026, #1593; stara
  zmienna w Coolify jest nieszkodliwa, `Settings` ignoruje nieznane env).
  Ruch na „Zweryfikowany" daje `active`, stawka jest
  OPCJONALNA (jej brak to 200, nie 422), a korekta stawki
  (`update_latest_expected_rate`) NIGDY nie ustawia `pending` i sama aktywuje
  stary wiersz `pending`. `budget_max_at_move` zostaje jako snapshot. Kredyt
  KPI pierwszego weryfikatora trafia od razu przy ruchu. **Tras kolejki
  akceptacji nie ma** (`/pending-verifications`, `accept-verification`,
  `reject-verification`) — pilnuje tego test czytający `app.routes`, nie HTTP
  404. Stare wiersze zalicza jednorazowo `pending_verification_promotion.py`
  (blok w `entrypoint.sh`, nie ma osobnej migracji) — idempotentny, zostaje na
  potrzeby świeżej instalacji i odtworzenia bazy. W bazie zostaje wartość
  `pending` w enumie `verificationstatus` (`ALTER TYPE … DROP VALUE`
  w Postgresie nie istnieje) i typ powiadomienia `pending_verification` —
  historycznych wierszy i powiadomień nikt nie kasuje, a `/pending-verifications`
  nadal przekierowuje na `/jobs`. Żaden writer ich już nie tworzy.
- **„Ponad budżet" to odznaka, nie stan.** Liczona na froncie
  (`lib/rate-to-hourly.ts`) ze stawki na karcie względem
  `effective_budget_hourly` rekrutacji (dzień ÷ 8, miesiąc ÷ 168, waluta ≠ PLN
  = brak porównania). Okno „Zweryfikowany" podpowiada stawkę z profilu
  kandydata (`candidate_expected_rate_hourly` w payloadzie tablicy) i ma
  „Pomiń stawkę".
- **Globalna czarna lista / weto HM = ostrzeżenie z potwierdzeniem.**
  (Konflikty z klientem — czarna lista klienta, NDA, konkurent — od #1589 nie
  blokują w ogóle, tylko plakietka; sekcja „Konflikty kandydat↔klient".)
  `check_candidate_move_eligibility` (`services/pipeline_eligibility.py`): bez
  `acknowledge_eligibility` → 409 ze strukturalnym `detail`
  (`code: "ELIGIBILITY_WARNING"`, `reason_code`, `reason`, `message`,
  `can_acknowledge`); z flagą ruch przechodzi i zostaje
  `Activity(action="eligibility_acknowledged")`. Front: okno „Przenieś mimo to"
  (`lib/pipeline-eligibility-warning.ts`; tablica i warsztat screeningu mają je
  wbudowane, „Wysyłka CV” i „Rozmowy” przez
  `components/v2/jobs/useEligibilityWarning.tsx` — każdy nowy ekran wysyłający
  `/move` musi obsłużyć to ostrzeżenie, inaczej wraca bramka w postaci toastu
  błędu). **`/bulk-move` i wejścia dodające kandydata
  (`assert_candidate_move_eligible`) zostają twarde** — nie ma tam UI do
  potwierdzenia. `moveBlockedReason` blokuje już wyłącznie `readOnly`.
- **„Zatrudniony": szkic kontraktu nie cofa ruchu.** `ensure_b2b_employment_draft`
  biegnie w savepoincie; 409/404 serwisu = zatrudnienie zostaje,
  `Activity(contract_draft_skipped)` + powiadomienie „Nie założono szkicu
  kontraktu" dla Delivery klienta (`emit`, dedup dzienny).
- **Podpis umowy offline.** `services/signing/pipeline_hook.py` usunięty —
  wysyłka, „oznacz jako wysłane" i powrót podpisanego PDF nie przesuwają kart;
  `confirm-fully-signed` w Generatorze B2B ma `ensure_hired=False`. Kolumny
  „Umowa wysłana"/„Umowa podpisana" są ręczne.
- **Mail odrzucenia OPT-IN.** Serwer planuje wyłącznie przy
  `send_rejection_email is True`; checkbox w `RejectionV2` domyślnie odznaczony.
- **Po ruchu nie otwierają się arkusze.** Payload tablicy niesie
  `screening_done`/`scorecard_done` (`_sheet_filled` — `{"answers": []}` to NIE
  wypełniony arkusz); karta pokazuje „Uzupełnij screening" / „Scorecard".
- **Podpowiedź „komplet obsady"** idzie do `list_job_member_ids` (zespół +
  admini), nie do każdego DL/TAC w firmie.

## Pipeline rekrutacji — bramka ruchu, przekazanie CV, spójność ekranów (11.09.2026)

Poprawki z przeglądu kodu spoza Codexa. Wspólny mianownik: ekran mówił co
innego niż serwer albo nadpisywał cudzą pracę.

- **Frontendowa bramka ruchu to WYŁĄCZNIE `moveBlockedReason`**
  (`lib/pipeline-flow.ts`). **Od 17.09.2026 blokuje tylko `readOnly`** — karta
  „Oczekuje” nie powstaje, a weto HM jest ostrzeżeniem serwera (sekcja
  „Kanban bez bramek”); akapit niżej opisuje stan z 11.09.
  Były cztery kopie tej reguły (w tym `InterviewDecisionDock`) i żadna nie
  zgadzała się z serwerem. Nie dokładaj kopii — przeciąganie, przyciski i doki
  wołają tę jedną funkcję. **Główny przycisk „dalej” w doku
  (`primaryForwardMove`) zatrzymuje się na pierwszym etapie objętym wetem** i
  pokazuje go wyłączonego z powodem — wcześniej przeskakiwał „CV Wysłane” na
  następny etap (w „Default B2B” to „Preparation Meeting”, spotkanie u klienta,
  którego serwerowe weto — kluczowane legacy enumem — nie zna).
- **Przekazanie CV klientowi: ruch → link → stawka.** Odmowa ruchu nie tworzy
  linku. Link celuje w etap SPRZED ruchu (tam leży brandowane CV); gdy link padnie
  po udanym ruchu, workbench pokazuje „Utwórz link ponownie”. Brak odpowiedzi
  albo 5xx przy ruchu to „nie wiadomo, czy ruch się zapisał — odśwież kartę”,
  nie „nic nie zostało zmienione” (`isDefiniteRefusal` — tylko 4xx jest pewną
  odmową); ponowienie mogłoby dodać drugi wpis „CV Wysłane”.
- **Link jednorazowy tylko przez `OneTimeLinkField` + wynik `lib/clipboard.ts`** —
  URL zostaje na ekranie, a toast „skopiowano” pojawia się tylko po udanym
  kopiowaniu (link Championa, interview z klientem). Link przeżywa przemontowanie
  karty po zapisie werdyktu.
- **Po ruchu kanban unieważnia OBA klucze** (`["kanban", String(id)]`
  i `["kanban", id]`; przy operacjach zbiorczych raz, po pętli). Zapisy Championa
  idą przez `invalidateChampionDependents` (`lib/champion-cache.ts`), który
  odświeża też `["job-readiness", id]`. Edycja samej rekrutacji (tytuł, klient,
  rubryki) jeszcze tego nie robi — znany dług.
- **Dok kandydata porównuje stawkę po przeliczeniu na miesięczną**
  (`normalizeRateToMonthly`); waluta inna niż PLN albo nieznana jednostka =
  „nie do porównania”, nie fałszywe „powyżej widełek”.
- **Werdykt HM** (`api/hiring_manager_feedback.py`): odczyt za
  `ensure_job_read_access` (także Finanse); cudzy werdykt nadpisuje autor,
  KAŻDY Delivery Lead (DL omija członkostwo w zespole), Head of Recruitment
  albo admin — inaczej 403
  z nazwiskiem autora. GET zwraca `{can_record, items}`: `can_record` liczy
  DOKŁADNIE te same warunki co POST (impersonacja, zapis sekcji pipeline, role
  RecruiterPlus, członkostwo z obejściem DL), a formularz renderuje się tylko przy
  `can_record === true` — Finanse spoza zespołu widzą werdykt tylko do odczytu
  zamiast przycisku kończącego się 403. Wiersze niosą `author_id`,
  `author_name`, `can_edit`. HoR od 17.09.2026 zapisuje i nadpisuje cudze
  werdykty (decyzja Artura: parytet z rekruterem + nadzór jak DL).
- **Shortlista nie nadpisuje zmiany kolegi i nie gubi wpisanego tekstu:**
  `ServerSyncedInput` (`JobShortlist.tsx`) — wersja bazowa idzie za serwerem do
  pierwszej zmiany użytkownika, potem zamarza; brak zapisu przy niezmienionym
  blur. 409: tekst zostaje w polu; jeśli kolega zmienił INNE pole, zapis ponawia
  się raz na nowej wersji, a jeśli to samo — toast o konflikcie i przyjęcie nowej
  wersji, więc następny zapis nadpisuje świadomie. Backend najpierw sprawdza
  członkostwo w zespole, potem blokuje wiersz (`with_for_update()`) i dopiero
  wtedy porównuje wersję — dwa równoczesne zapisy nie przejdą oba, a osoba spoza
  zespołu nie założy blokady na cudzy wpis.
- **ATLAS — firmy z historii kandydata** (`api/integrations_companies.py`
  + `_past_company_predicate` w `api/candidates.py`): `via_us` =
  `placed_contract_clause()` — kontrakty `active`/`ending`/`ended` oraz
  `draft`/`ready_for_signature` z aktywnym zamówieniem u tego klienta albo
  z bieżącym etapem „hired” u niego (zatrudnienie i obsada linii MD zakładają
  kontrakt jako szkic, więc bez tego pracujący konsultant znikał z odpowiedzi).
  Aktywny konflikt = firma obecna, nieaktywny = przeszła. Data końca
  „present/current/obecnie/teraz” (`services/experience_end.py`, po przycięciu
  WSZYSTKICH białych znaków — SQL `btrim(…, E' \t\r\n')` jak Python `.strip()`)
  = praca OBECNA we wszystkich predykatach (lista kandydatów i ATLAS). Pusty
  `end` też, z jednym historycznym wyjątkiem: w filtrze „Poprzednia firma” wpis
  bez daty dalej niż na pierwszej pozycji liczy się jako przeszły. Każde zapytanie ma
  sufit 2000 WIERSZY (`truncated`) i lokalny timeout 8 s (→ 503
  `lookup_timeout`). Surowy alias idzie do `LIKE` tylko, gdy jego forma
  kanoniczna ma co najmniej 3 znaki (koniec z „IT” → `LIKE '%it%'`). Filtr listy
  `_worked_at_client_predicate` nadal liczy szkice i unieważnione kontrakty —
  znany dług.
- **Delivery Lead zakładający rekrutację staje się jej `delivery_lead_id`**
  (17.09.2026, `create_job`): pierwszeństwo jawne `delivery_lead_id` > head DL
  klienta (`resolve_default_owners`) > twórca — zawsze WYŁĄCZNIE gdy pole
  zostaje puste po obu wcześniejszych krokach. `recruiter_id`/`/claim`
  nietknięte, to zmiana ownera, nie autorstwa. `delivery_lead_job_pairs`
  zwraca `None` dla roli DL, więc bramka zakresu klienta nie gryzie własnej
  rekrutacji świeżo utworzonej bez zespołu. 403 przy próbie ustawienia widełek
  wynagrodzenia przez DL/TCM jest teraz po polsku: „Widełki wynagrodzenia może
  ustawić tylko admin lub TAC”.
- **Tworzenie rekrutacji = krótki modal + reszta w doku** (17.09.2026).
  `CreateJobModal` (`components/v2/modals/`) ma 9 pól: tytuł, klient
  (`ClientSinglePicker`), typ, opis (z „Generuj AI”), must-have, miasto, tryb,
  dni w biurze, budżet PLN/h; widełki PLN/mies. tylko dla `canManageRecruitmentBudget`
  (klucz NIEOBECNY dla DL/TCM, nie `null` — backend liczy `fields_set`). Nie
  wysyła statusu, priorytetu, deadline'u, TAC/DL/rekrutera/HM/szablonu/kategorii.
  Po zapisie ląduje na `/jobs/{id}?tab=champion` (+`&intake=1`, gdy jest opis —
  panel AI otwarty z opisem); `?tab=champion-profile` zostaje aliasem
  (`JOB_DETAIL_TAB_ALIASES` w `app/jobs/[id]/page.tsx`). Szkic formularza w `localStorage`
  (`nexus:jobDraft:v1:<userId>`), Escape przy brudnym formularzu pyta.
  `EditJobModal`/`JobFormFields` ZOSTAJĄ w `AppShell.tsx` jako pełna edycja
  (testy źródłowe czytają tam literały `FieldGroup`). TAC, DL, szablon,
  kategoria, Program/Train, priorytet i deadline edytuje `JobSettingsPanel`
  w zakładce „Zespół” doku gotowości. Zakładka „Zlecenie i Champion”: spis
  sekcji tylko od `2xl`, na `xl` dwie kolumny (edytor + dok) — przy 1440 px
  edytor miał 251 px; dok zwijany do 44 px wyłącznie od `xl`
  (`nexus:jobChampionDockCollapsed:v1`), szyna „Otwarte karty” domyślnie
  zwinięta (`nexus.jobTabsRail.collapsed.v2`). Sekcja 1 Championa startuje
  z pól rekrutacji per pole (`lib/champion-job-seed.ts`), nietknięte klucze nie
  jadą w PUT; okno „Uzgodnij profil i pola rekrutacji” dostaje widoczny `draft`
  (pusty stack + „Uzgodnij też pole” czyściłby `must_skills`).

## Konflikty z klientem (blacklist / NDA / konkurent) są OSTRZEŻENIEM, nie blokadą (decyzja Artura, 17.09.2026)

Rejestr `candidate_conflicts` (widżet „Konflikty" na profilu kandydata) do
17.09 ukrywał kandydata w wyszukiwaniu AI pod rekrutację u danego klienta
i odmawiał 409 przy dodaniu do pipeline'u. Od 17.09 aktywny, niewygasły
konflikt typu `blacklist` / `nda` / `competitor` **ostrzega**: kandydat jest
widoczny (Talent Radar, `/ai-matches`, rekomendacje, „podobne rekrutacje",
digest, ręczna wyszukiwarka), przypisywalny, z bursztynową plakietką
i polskim powodem.

| Sygnał | Widoczność | Przypisanie |
|---|---|---|
| globalna `blacklisted` (status kandydata) | ukryty | blokada |
| już w tej rekrutacji | ukryty | blokada (dedup) |
| weto hiring managera | widoczny, `severity=hard` | blokada |
| konflikt klienta, obecne zatrudnienie, wykluczenie przez kandydata | widoczny, `severity=warning` | dozwolone |

- **Jedno źródło prawdy:** `services/candidate_job_eligibility.py`. Kolejność
  bramek: globalna blacklista → duplikat → weto HM → dominujący sygnał miękki
  (`blacklist > nda > competitor > current_employment > excluded`, reszta
  w `secondary_reasons`). `override_allowed` jest ZAWSZE `False` — pole zostaje
  dla kształtu API, endpointu nadpisania nie ma i nie ma już czego nadpisywać.
- **Plakietka: `services/eligibility_annotation.py`**, dla KAŻDEGO
  `reason_code != eligible`. Do 17.09 helper zwracał `None` dla decyzji
  `eligible=True` bez sygnałów pobocznych, więc czyste „obecne zatrudnienie"
  nie miało plakietki — a po zmianie zniknęłaby też plakietka NDA.
- **Zwolnione z dealbreakerów w `/ai-matches` jest tylko weto HM**
  (`severity=hard ∧ visibility=warn`). Kandydat z NDA ponad budżet chowa się
  do `over_budget` jak każdy inny — świadomie. Testy, które potrzebują „widoczny,
  ale zablokowany", seedują weto HM (`tests.test_manager_rejection_gate`), nie NDA.
- **Scoring nie zeruje za konflikt ani `client_excluded`** — trafiają do
  `breakdown.warnings`; zeruje wyłącznie globalna `blacklist`. Zero trzymałoby
  kandydata pod `RECOMMENDATION_MIN_SCORE` i decyzja byłaby niewidoczna.
  Stare wiersze cache z tymi kodami w `penalties` unieważnia instrukcja
  w `_DATA_STATEMENTS` entrypointu (samoograniczająca: `stale = false`),
  a dodanie i dezaktywacja konfliktu wołają `mark_stale_for_candidate`.
- **`/seeking-contractors`:** ostrzeżenie o konflikcie klienta NIE jest
  wyłączalne checkboxem `industry_blocklist` (on steruje tylko obecnym
  zatrudnieniem — M2-SEC-03). `FilterStats.dropped_blocklist` jest zawsze 0
  i zostaje dla kształtu odpowiedzi.
- **Bulk-add:** `client_blacklist`/`client_nda`/`client_competitor` są
  w `warnings[]`, nie `skipped[]` — lustro w `candidate-search-api.ts`
  i `bulk-result-summary.ts`.
- **Obecne zatrudnienie wynika też z umów** (`services/current_employment.py`):
  `status ∈ {active, ending}` ∧ (`start_date` puste albo ≤ dziś); koniec
  rozstrzyga status, nie `end_date` (umowa B2B bezterminowa). Ręczne wiersze
  `current_employment` zostają dla pracodawców spoza naszych umów.
  `_derive_employment` w `candidates.py` celowo nietknięte.
- **Ręczna wyszukiwarka** (`POST /api/search/candidates`) niesie `eligibility`
  wyłącznie przy `exclude_in_job_id` i wyłącznie dla osoby z dostępem do tej
  rekrutacji (`ensure_job_read_access`) — plakietka ujawnia weto hiring
  managera. Bez dostępu wyniki przychodzą normalnie, bez plakietek.
- **`pipeline_eligibility` czyta konflikty KOLUMNAMI, nie encją** — gorąca
  ścieżka każdego ruchu nie może zależeć od kolumn audytu z 0321 (na prodzie
  wprowadza je safety-net z `lock_timeout`; pominięty ALTER = 500 na ruchu).
- **Rejestr (`api/candidate_conflicts.py`, migracje 0321–0322):** jeden
  AKTYWNY wpis na (kandydat, klient, **typ**); precedencja typów
  w `models/candidate_conflict.py` (`CONFLICT_TYPE_PRECEDENCE`,
  `dominant_conflict_type`, `active_unexpired_clause`). NDA wymaga daty
  wygaśnięcia. Wygaśnięcie NIE przełącza `active=false` — stan `expired`
  liczony przy odczycie, a skaner DL wystawia jednorazową kartę
  „Konflikt z kandydatem wygasł". Wygasły wpis nadal zajmuje indeks
  unikalności, więc nowy wpis tego samego typu ZAMYKA go („Zastąpiony nowym
  wpisem po wygaśnięciu") zamiast odmawiać 409. Dezaktywacja wymaga powodu
  i zostawia `Activity` (`conflict_added` / `conflict_deactivated`, same ID —
  wolny tekst powodu zostaje na wierszu konfliktu). Formularz w widżecie
  widzą tylko role z prawem zapisu (admin, Delivery Lead z zapisem Sourcing
  lub Pipeline); pozostałe widzą listę.
  Odczyt: `CandidateSearchAccess` — do 17.09 lista stała za bramką Finance
  i Delivery Lead, który mógł konflikt dodać, dostawał 403 przy jej odczycie.
  `GET /api/conflicts` zasila sekcję „Konflikty z kandydatami" na profilu
  klienta i zakładkę Ustawienia → Konflikty. Tabela nie miała wcześniej
  żadnego lustra w `entrypoint.sh` — teraz ma (kolumny, indeksy, CHECK alertu).

## Konta serwisowe / klucze API (`X-API-Key`)

Druga klasa poświadczeń obok JWT użytkownika — dla automatyzacji (cron, CI, skrypty
operacyjne). Powstało, bo jedyną alternatywą było podszywanie się pod rekrutera tokenem
z przeglądarki albo podniesienie `ACCESS_TOKEN_EXPIRE_MINUTES`, które jest **globalne**
i osłabia sesje wszystkim. Migracja `0220_service_accounts` (+ lustro w `entrypoint.sh`).

- **Nagłówek `X-API-Key`, NIE `Authorization: Bearer`.** Na `Authorization` jadą już trzy
  poświadczenia (access JWT, refresh JWT, token OAuth klienta) rozróżniane claimem `type`
  **po** zdekodowaniu; klucz nie jest JWT, więc czwarty typ zmuszałby parser do zgadywania
  kształtu przed weryfikacją. Do tego front dokleja `Authorization` do KAŻDEGO wywołania
  (interceptor w `lib/api.ts`), więc klucz, który tam wyląduje, byłby wysyłany wszędzie.
  Precedens w repo: `X-Snapshot-Token` w `/api/admin/snapshot` — ten mechanizm jest jego
  uogólnieniem (tamten to jeden globalny sekret z env-a: bez terminu, rotacji, rewokacji
  i bez możliwości ustalenia, kto go użył).
- **Format `nxs_v2_<24 hex>_<sekret>`** — jawne id + sekret. SELECT idzie po jawnym id
  (więc wolno je logować → audyt „którym kluczem" w ogóle istnieje), a skróty porównuje
  `hmac.compare_digest`. Prefiks `nxs_` jest grepowalny — jest reguła w `.gitleaks.toml`.
- **SHA-256, świadomie NIE bcrypt jak `oauth_clients`.** Tam hash liczy się raz na godzinę
  przy wymianie na token, tu przy KAŻDYM requeście: bcrypt (~100 ms) byłby podatkiem na
  każde wywołanie i darmowym DoS-em. Rozciąganie chroni sekrety o niskiej entropii, a tu
  sekret ma 256 bitów.
- **Dwie tabele, bo rotacja.** `service_accounts` (tożsamość + scope'y) osobno od
  `service_account_keys` (N kluczy na konto): wydaj drugi → wdroż → rewokuj pierwszy,
  bez okna bez działającej automatyzacji i bez rozdwojenia tożsamości w audycie.
- **Uprawnienia własne, ZERO dziedziczenia roli właściciela.** Konto serwisowe nie jest
  wierszem w `users` (wyciekłoby do list userów, KPI, powiadomień, eksportów RODO) i nie ma
  `role` — żaden guard rolowy go nie przepuści. Dziedziczenie roli oznaczałoby ciche
  zyskiwanie uprawnień przy awansie właściciela i śmierć klucza przy jego odejściu, a rola
  `admin` = „wszystko", więc wykluczałoby najmniejsze uprawnienia z definicji.
- **Scope'y są własnym, wąskim słownikiem** (`ServiceScope`): `traffit:sync`, `traffit:read`,
  `ops:snapshot`. Świadomie NIE `OAuthScope` — tamten jest kontraktem zgodności dla integracji
  migrujących z Traffita i opisuje dane domenowe (`candidate:read`). **Nie ma scope'u na dane
  kandydatów**, więc klucz do syncu nie ma jak ich dotknąć; powierzchnie domenowe i tak wiszą
  na `get_current_user`, dla którego `X-API-Key` jest nieznanym nagłówkiem (→ 401).
- **Uprawnienia czytane z konta przy każdym requeście**, nie zapiekane w poświadczeniu —
  odebranie scope'u i rewokacja działają NATYCHMIAST. Tym różni się od `oauth_clients`, gdzie
  wystawiony JWT niesie scope'y ze sobą i żyje jeszcze godzinę po odebraniu dostępu.
- **`expires_at` NOT NULL** (domyślnie 90 dni, sufit `SERVICE_ACCOUNT_KEY_MAX_TTL_DAYS`=365;
  żądanie ponad sufit jest przycinane, nie odrzucane) — klucz bez terminu nie jest nigdy
  oglądany ponownie. `last_used_at` stemplowany z **dławieniem** (60 s), bo zapis przy każdym
  requeście robi z odczytu zapis do jednego gorącego wiersza; licznika wywołań świadomie brak
  (zdławiony kłamałby — od liczenia są logi).
- **Konto serwisowe NIE MOŻE impersonować** — `X-API-Key` + `X-Impersonate-User-Id` → 403.
  Połączenie poświadczenia bez wygasania sesji z cudzymi oczami znosiłoby sens scope'ów.
- **Kluczem nie da się zarządzać kontami serwisowymi** (CRUD za `AdminUser`) — inaczej klucz
  o wąskim scope'ie wydałby sobie szerszy.
- **Wpięte:** `POST /api/admin/traffit/sync` (`traffit:sync`), `GET .../sync/status`
  (`traffit:read`) oraz `GET /api/admin/snapshot` (`ops:snapshot`). Admin z JWT nadal działa —
  `require_service_scope(..., allow_admin_jwt=True)`, więc to nie jest zmiana zrywająca.
  W snapshotcie klucz jest sprawdzany **przed** legacy `X-Snapshot-Token` (w trakcie migracji
  lecą oba nagłówki naraz); `auth_mode` w odpowiedzi ma teraz trzecią wartość
  `service_account`. CRUD: `/api/settings/service-accounts` (+ `/scopes`, `/config`,
  `/{id}/keys`, `/{id}/keys/{key_id}/revoke`).
- **`SNAPSHOT_TOKEN` jest do wycofania**, nie do rozbudowy — jeden globalny sekret bez
  terminu, rotacji, rewokacji i atrybucji. Zostaje, dopóki cron i ops-skille (`.claude/commands/
  ops-snapshot.md`) nie przejdą na klucz ze scope'em `ops:snapshot`.
- **Env:** `SERVICE_ACCOUNTS_ENABLED` (default `true` — przy pustej tabeli powierzchnia
  ataku jest zerowa; flaga to awaryjne odcięcie CAŁEJ klasy poświadczeń),
  `SERVICE_ACCOUNT_KEY_DEFAULT_TTL_DAYS`, `SERVICE_ACCOUNT_KEY_MAX_TTL_DAYS`,
  `SERVICE_ACCOUNT_LAST_USED_THROTTLE_SECONDS`, `SERVICE_ACCOUNT_RATE_LIMIT`.
- **Uwaga przy dokładaniu endpointów:** moduł z `@limiter.limit` **nie może** mieć
  `from __future__ import annotations` (PEP 563 + slowapi #579 → `Annotated` guardy lądują
  jako wymagane parametry QUERY, 422 na poprawnym body). Ten sam trap co
  w `candidate_activity_summary.py`.

## Zamówienia z maila `zamowienia@b2bnetwork.pl` — czytnik app-only, skrzynka współdzielona

`zamowienia@b2bnetwork.pl` NIE jest skrzynką na hostingu, tylko **listą
dystrybucyjną w Exchange Online** (właścicielka i jedyna osoba: Marta
Kozarzewska; nadawcy zewnętrzni dozwoleni). Kopię zamówień robi więc sama
lista: jej członkiem jest skrzynka współdzielona **`nexus-zamowienia@b2bnetwork.pl`**
(bez licencji, bez logowania, zero kont z hasłem). Hosting `hosting.b2bnetwork.pl`
nie ma żadnej reguły do utrzymania.

- **Czytnik pracuje app-only** (`ORDER_MAIL_AUTH_MODE=app`): client_credentials
  rejestracji **„NEXUS ATS - Mailbox and Login"** (`b5be7c77-…`, tenant
  `e277180c-…`) — tej samej, którą rekruterzy łączą delegowanie. Dołożone
  APPLICATION `Mail.Read` ze zgodą administratora (02.09.2026) i **Application
  Access Policy** `RestrictAccess` na grupę `NEXUS-OrderMail-Scope`
  (`nexus-ordermail-scope@b2bnetwork.pl`, mail-enabled security group, ukryta
  w GAL, jedyny członek: skrzynka zamówień). `Test-ApplicationAccessPolicy`:
  skrzynka zamówień → Granted, dowolna inna → Denied. **Skrzynka współdzielona
  NIE może być zakresem polityki wprost** („not a security principal") — stąd
  grupa. Bez tej polityki uprawnienie aplikacyjne czytałoby każdą skrzynkę
  w firmie; jej brak to błąd konfiguracji, nie „szerszy dostęp".
- **`AppGraphClient`** (`services/m365/app_graph_client.py`) to subklasa
  `GraphClient`: ta sama pętla retry/throttle, nadpisane tylko konstruktor,
  bramka `_authorize` (brak właściciela do rewalidacji) i `_refresh_and_persist`
  (nowy token klienta, nic do zapisania). Graph nie ma `/me` bez użytkownika,
  więc `mailbox_prefix()` daje `/users/{ORDER_MAIL_UPN}`; wiersz
  `order_mail_documents.connection_id` zostaje NULL (kolumna NULL-owalna od 0264).
- **Tryb delegowany zostaje** (`ORDER_MAIL_AUTH_MODE=delegated`, domyślny w kodzie)
  — wymaga konta-bota z licencją, hasłem i OAuth; na prodzie nieużywany.
- Health: `checks.order_mail = misconfigured`, gdy tryb `app` nie ma
  `M365_CLIENT_ID/SECRET` albo realnego tenanta w `M365_MAIL_TENANT_ID`
  (`M365_TENANT_ID` bywa `common`, a client_credentials z `common` nie działa).
  Status: `GET /api/admin/order-mail/status` → `auth_mode`, `app_only_ready`.
- Env na prodzie (workflow „Coolify set env", `redeploy=false`, potem jeden
  zwykły deploy): `ORDER_MAIL_AUTH_MODE=app`, `ORDER_MAIL_UPN=nexus-zamowienia@b2bnetwork.pl`,
  `M365_MAIL_TENANT_ID=<GUID tenanta>`, `ORDER_MAIL_INGEST_ENABLED=true`.
- **Odczyt awaryjny (bez AI) jest ponawiany sam** (`retry_ai_fallback_documents`,
  bieg skrzynki po ponownej weryfikacji): wpis `needs_review` z
  `extraction.source == "regex"` dostaje ponowny odczyt AI z zachowanego PDF-a,
  najwyżej `MAX_AI_RETRY_ATTEMPTS` (3) razy (`document_meta.ai_retry_*`,
  przeżywa „Przelicz plan"). Model idzie POZA blokadą wiersza, zapis po
  ponownym sprawdzeniu pod `FOR UPDATE` (`populate_existing`). Udany odczyt =
  ścieżka nowego maila (reguły, rodzaj stawki) + `replan_and_apply`. Powód
  porażki AI (`OrderExtraction.ai_failure`: klasa błędu / HTTP, bez treści)
  jest na wpisie i w powodzie bramki „Odczyt awaryjny (AI: …)". Do 09.2026
  szedł tylko do logu kontenera, który znika przy deployu (PKO BP, 14.09:
  mail odczytany w trakcie deployu). Bez klucza albo przy
  `ORDER_EXTRACTION_ENABLED=false` ponowienie nic nie robi.
- **Skrzynka jest sprawdzana co godzinę, nie w slotach.** Do 03.09.2026 pętla
  miała dwa sloty dobowe (08:00/15:00 Europe/Warsaw): zamówienie VeloBank
  przyszło o 08:37 i czekałoby do 15:00. Teraz bieg jest należny, gdy od KOŃCA
  ostatniego minęło `ORDER_MAIL_POLL_INTERVAL_MINUTES` (default 60, podłoga 5;
  `ORDER_MAIL_SLOTS_LOCAL` nie istnieje). Odstęp liczony od końca ma dwie
  konsekwencje, na których stoi ticket: bieg ręczny przesuwa zegar (nie ma
  dwóch biegów tuż po sobie), a bieg przerwany restartem końca NIE zapisuje,
  więc po deployu skrzynka jest sprawdzana od razu, nie za godzinę.
- **„Pobierz zamówienia z maila" jest w kolejce `/order-mail`**, nie tylko
  w API admina: `POST /api/order-mail/sync` (admin / finance / delivery_lead —
  bramka ROLOWA, bo dotyczy całej skrzynki, nie dokumentu; TCM ma sam odczyt)
  i `GET /api/order-mail/sync/status` (każda rola kolejki; TCM bez treści
  błędów, bo te cytują nazwy załączników). Bieg idzie w tle, front odpytuje
  stan co 2 s i uznaje koniec po ZMIANIE `finished_at` z serwera, nigdy po
  zegarze przeglądarki (`lib/order-mail-sync.ts`). 409 = bieg już trwa, front
  dołącza do niego. Liczby w pasku (nowe wiadomości / zapisane automatycznie /
  do weryfikacji) dotyczą CAŁEJ skrzynki — kolejka DL jest zawężona do
  portfela, więc „1 do weryfikacji" i pusta lista to nie sprzeczność.
- **Wynik biegu żyje w `order_mail_sync_state.stats` jako rekord** (`reason`,
  `started_at`, `finished_at`, `status`, `error` + liczniki), bo wiersz stanu ma
  jedną parę start/koniec, a bieg, który właśnie trwa, nadpisuje start.
  `last_status='running'` bez blokady w procesie = bieg PRZERWANY (deploy
  w trakcie — u nas kilka razy dziennie) i tak jest pokazywany
  (`interrupted`), a health traktuje `running` jako brak informacji, nie awarię
  (degraduje po 3 odstępach albo na `error`). Trzy rzeczy, które trzymają ten
  stan uczciwym: bieg z requestu startuje przez `start_ingest_task` (trzymana
  referencja — zebrane zadanie nie zapisuje końca), padnięte powiadomienie DL
  robi `rollback()` (bez niego zapis końca leci na `PendingRollbackError`),
  a watermark nigdy się nie cofa (backfill `since_days` oglądał starsze maile
  i przesuwał okno wstecz).
### Godzinowa ponowna weryfikacja wstrzymanych wpisów (0316, 16.09.2026)

- **Bieg AUTOMATYCZNY rusza tylko 8:00–18:00** (`ORDER_MAIL_RECHECK_START_HOUR_LOCAL`
  .. `_END_HOUR_LOCAL`, `BUSINESS_TZ`, półotwarte — ostatni bieg o 17:xx;
  wyrównane godziny = okno wyłączone, escape hatch bez deployu). Bramka siedzi
  na wejściu `run_recheck`, PRZED `_candidate_ids`, i czyta `trigger`: bieg
  RĘCZNY („Pobierz zamówienia z maila") okna nie pyta i zapisuje wiersz zawsze.
  **Zawężenie dotyczy WYŁĄCZNIE recheku** — pobieranie poczty
  (`ORDER_MAIL_POLL_INTERVAL_MINUTES`) i sonda `checks.order_mail` zostają
  dobowe. Nie zamykaj na noc całego `run_order_mail_ingest`: zamówienie
  przysłane o 18:30 czekałoby do rana, a sonda zdrowia (`stale_after =
  max(3 × poll_interval, 180)` min) degradowałaby co noc.
- **Wiersz historii powstaje TYLKO przy zmianie** (09.2026). Do tego dnia
  kolejka rzadko bywała pusta, więc tabela dostawała 24 wiersze dziennie,
  w większości identyczne. `outcome_fingerprint(details)` liczy odcisk STANU
  wstrzymanych zamówień (`document_id`, `outcome`, `category`, `reasons`,
  `alerted`, `order_number`, `people`; posortowane po `document_id`, bo rotacja
  `last_at NULLS FIRST` tasuje kolejność); `changed = trigger == "manual" or
  applied > 0 or odcisk != poprzedni`. Bieg bez zmian przesuwa tylko znacznik
  `app_settings['order_mail_recheck_state']` (`last_checked_at`,
  `last_change_at`, `fingerprint`, `unchanged_runs`; upsert scaleniem `||`, bez
  migracji — to stan pętli, nie konfiguracja). **Poza oknem marker NIE jest
  przesuwany** — „sprawdzone ostatnio 17:05" ma zostać prawdą przez całą noc.
  `GET /recheck-runs` zwraca marker i okno obok `items`; są GLOBALNE (opisują
  mechanizm, nie dokument klienta), więc nie podlegają zawężeniu po portfelu
  ani redakcji TCM. Front: zdanie „Sprawdzone ostatnio: …" nad tabelą i pusty
  stan „Tu trafiają tylko te sprawdzenia, które coś zmieniły".
- **Pominięty wiersz NIE pomija stempla `last_at`, licznika prób ani karty DL.**
  Karta wychodzi po trzeciej próbie z rzędu, więc gdyby licznik wisiał na
  zapisie wiersza, przestałaby wychodzić dokładnie wtedy, gdy nic się nie
  zmienia. Retencja (`_prune_history`) też jest wołana w KAŻDYM biegu — inaczej
  tydzień bez zmian to tydzień bez sprzątania.
- **Próg bezpiecznika alertu jest WYPROWADZONY z okna**
  (`order_mail_recheck_reasons.alert_after_hours()` =
  `max(ORDER_MAIL_RECHECK_ALERT_AFTER_HOURS, godziny_zamknięcia + 2)`, domyślnie
  16 h). Nie wołaj `should_alert` z surową wartością z konfiguracji: recheck
  stoi w nocy, więc o 01:00 stempel `last_at` KAŻDEGO wstrzymanego wpisu ma
  ~14 h i sześciogodzinny próg kazałby dobowemu `rule_order_mail_review`
  wystawić kartę całej kolejce — a `dl_alerts_loop` chodzi co 24 h od startu
  kontenera, więc trafienie w noc jest kwestią godziny ostatniego deployu.
- **W testach okno jest WYŁĄCZONE** (autouse `_open_the_order_mail_recheck_window`
  w `conftest.py`): zegar w suicie jest prawdziwy, więc bramka zamieniłaby każdy
  test recheku w test „czy jest teraz dzień". Testy okna włączają je jawnie
  i podróżują zegarem — ale NIE o lata w przód: retencja liczy się od `now()`,
  więc skasowałyby wiersze innych testów na wspólnej bazie.

- **Wstrzymany wpis nie wracał sam.** Jedyne automatyczne przeliczenie
  (`replan_outdated_documents`, USUNIĘTE) odpalało się tylko po zmianie
  `rule_version`. Przyczyna wstrzymania znika najczęściej GDZIE INDZIEJ:
  po podpisaniu umowy B2B nowego kontraktora albo po uzupełnieniu NIP-u
  u klienta. Teraz `order_mail_recheck.run_recheck` przelicza KAŻDY wstrzymany
  wpis w każdym biegu skrzynki — lokalnie i przed Graphem, więc także przy
  awarii skrzynki. Bez nowej pętli: ta sama kadencja, jeden heartbeat, jedna oś
  czasu w historii.
- **Dwie ścieżki.** `needs_review` (ma klienta i odczyt) → `replan_and_apply`,
  bez modelu AI. `unrecognized_client` → SAMO ponowne rozpoznanie klienta
  (tekst z PDF-a + rejestr NIP-ów); dopiero rozpoznany klient przechodzi na
  pierwszą ścieżkę. **Nie wołaj tu `process_pdf_bytes`** — ta funkcja czyta
  modelem PRZED sprawdzeniem klienta, więc płaciłaby za AI w każdym biegu.
- **Kody powodów, nie proza** (`order_mail_gate.CODE_*`, kolumna
  `order_mail_documents.gate_reason_codes`, równoległa do `gate_reasons`).
  KAŻDE dopisanie powodu MUSI nieść kod — pilnuje tego test czytający AST
  bramki. Powody wstrzykiwane poza bramką idą przez `set_gate_hold`.
- **Cicha jest WYŁĄCZNIE kategoria „czeka na podpis" (i wpis bez klienta).**
  `config` (wyłącznik automatu globalny albo per klient) **eskaluje jak każda
  inna przyczyna**: wyłącznik gasi tylko zapis automatyczny — ręczne
  „Zastosuj" go nie czyta — więc taki dokument zapisze WYŁĄCZNIE człowiek.
  Wyciszenie tej kategorii znaczyłoby, że przestawienie
  `ORDER_MAIL_AUTOAPPLY_ENABLED` kasuje alarmowanie całej kolejki i zamyka
  karty już wystawione.
- **„Czeka na podpis umowy" = `classify_hold` zwraca `awaiting_contract`**:
  WSZYSTKIE kody dokumentu należą do `{person_decision_new,
  person_known_elsewhere_idle}`, czyli osoby nie ma na rosterze klienta i nie ma
  żywej umowy NIGDZIE w systemie. Taki wpis czeka bezterminowo, licznik prób
  stoi na zerze i **nie wysyła karty do DL nigdy**. Jeden dodatkowy powód
  (stawka poza pasmem, niepewny odczyt) przesuwa dokument do `other` — to
  bezpieczny kierunek pomyłki. Świadomie NIE są `awaiting_contract`: zakończona
  współpraca u tego klienta, imiennicy i osoba z otwartą umową u INNEGO klienta
  (to pytanie o zdublowany rekord klienta, nie o podpis).
- **Karta DL wychodzi dopiero po TRZECH nieudanych próbach z rzędu**
  (`document_meta["recheck"] = {attempts, category, last_at}`; zmiana kategorii
  zeruje licznik). Do 0316 `notify_review` wołane z `_process_message`
  wystawiało kartę przy PIERWSZYM wstrzymaniu — to wywołanie zniknęło.
  Regułę ma JEDNO miejsce: `should_alert` — czyta ją i recheck, i dobowy
  `rule_order_mail_review` (dwie kopie rozjechałyby się, a skaner wystawiałby
  nazajutrz karty, które recheck wyciszył). Bezpiecznik: dokument bez ustalonej
  kategorii (pętla nigdy go nie widziała) **albo ze stemplem `last_at`
  starszym niż okno** (pętla przestała go widzieć) alarmuje po
  `ORDER_MAIL_RECHECK_ALERT_AFTER_HOURS` (6 h). Bez DRUGIEGO przypadku pętla
  zatrzymana po pierwszej próbie zamrażała dokument na `attempts = 1` na
  zawsze, a dobowy skaner — nie widząc go w `live` — zamykał nawet kartę
  wystawioną wcześniej. Udany zapis kasuje ślad i zamyka kartę od razu
  (`resolve_entity_alerts`).
- **KAŻDY dokument, który zjadł budżet biegu, MUSI dostać stempel `last_at`
  i trafić do `details` biegu** — także ten, którego nie da się przeliczyć,
  i ten, na którym bieg padł (stempel idzie wtedy osobną transakcją PO
  rollbacku). Czy `details` staną się WIERSZEM historii, rozstrzyga odcisk
  (wyżej) — ale stempel i tak musi paść.
  Sortowanie `last_at NULLS FIRST` jest rotacją tylko pod tym warunkiem: wpis
  bez stempla wraca na czoło w każdym biegu, a sto takich wierszy zatrzymuje
  całą funkcję — niewidzialnie, bo historia pokazuje wtedy bieg „sprawdzono 0".
- **`_replannable` ODPOWIADA „nie da się", nie rzuca.** Helper magazynu
  (`get_order_mail_attachment_path`) rzuca `FileNotFoundError` dla ścieżki,
  której nie ma; bez przechwycenia recheck wywracał się na takim wpisie
  w każdym biegu, licznik prób stał w miejscu i karta nie wychodziła nigdy.
- **Historia: `order_mail_recheck_runs`** (`GET /api/order-mail/recheck-runs`,
  sekcja na dole `/order-mail`). `details` są ZDENORMALIZOWANE — historia
  pokazuje powód z chwili biegu, nie dzisiejszy stan dokumentu. DL widzi wpisy
  swojego portfela, a **liczniki są przeliczane z widocznych wpisów** (globalne
  „sprawdzono 12" nad listą z jednym wierszem to ekran, który sam sobie
  przeczy). Retencja `ORDER_MAIL_RECHECK_HISTORY_DAYS` (30 dni) — po niej znikną
  też bezzmianowe wiersze sprzed 09.2026, więc nie ma czego czyścić ręcznie.
- **Sufit `ORDER_MAIL_RECHECK_MAX_DOCS` (100) i rotacja po `last_at NULLS
  FIRST`** — każdy recheck to ekstrakcja tekstu z PDF-a, a skan idzie przez OCR.
  Wpisy `unrecognized_client` starsze niż
  `ORDER_MAIL_RECHECK_UNRECOGNIZED_DAYS` (90) odpadają: znikają z kolejki tylko
  ręcznie, więc bez sufitu OCR-owalibyśmy je co godzinę bez końca.
- **Test na wspólnej bazie MUSI asertować po WŁASNYM dokumencie** — bieg
  przegląda każdy wstrzymany wpis, a baza testowa nie jest czyszczona, więc
  globalne liczniki i globalny mock `notify_review` mierzą cudze wiersze.
- **`ORDER_MAIL_AUTOAPPLY_ENABLED` jest żywym wyłącznikiem (od 10.09.2026).**
  #1472 zrobił z niej flagę „legacy” — bramka jej nie czytała, a status zwracał
  na sztywno `true`. Teraz działa w jednym miejscu,
  `hold_when_autoapply_disabled` (`order_mail_ingest.py`), przy TRZECH zapisach
  bez człowieka: odczyt maila, „Przelicz plan” i jednorazowe czyszczenie
  kolejki. Wyłączona flaga zostawia werdykt „auto” w kolejce z powodem
  „Automatyczny zapis jest wyłączony…”. `evaluate()` jej NIE czyta (zostaje
  czyste), a ręczne „Zastosuj” ją ignoruje.
- **Powrót po przerwie = NOWE zamówienie (decyzja Artura, 10.09.2026).** Do
  10.09 automat „reaktywował” zakończone zamówienie: przepisywał w nim tytuł,
  okres, stawkę, koszt i PDF — tak w nocy 9/10.09 nadpisał PFRON 507–509.
  Teraz powrót idzie tą samą ścieżką co nowe zamówienie, a zakończone jest
  tylko czytane (`FOR SHARE`, ponowne sprawdzenie warunków planera). Link do
  poprzedniego żyje w Activity `order_mail_renewal` (`renewal_of_order_id`,
  `gap_days`, `previous_end_date`) — NIE w `notes` (tam jest znacznik
  idempotencji porównywany dosłownie) i NIE w `predecessor_order_id` (to
  zamiana kontraktora na linii grupy MD). Linie grup MD nigdy nie są
  „poprzednim zamówieniem”. Nowe zamówienie dziedziczy z poprzedniego pola,
  których PDF nie niesie: `project_part` (bez niej e-Zdrowie nie przejdzie
  walidacji), `framework_contract_id`, `job_id`, `billing_hours_per_month`,
  `description` — reaktywacja w miejscu zostawiała je w wierszu.
- **Mail nie wskrzesza wypowiedzianej umowy — ale tylko poza jej okresem.**
  `termination_allows` (w `order_mail_signature.py`, przed sprawdzeniem
  podpisu, także w `complete_signed_mail_drafts`): przy umowie z
  `terminated_at`/`termination_reason` zamówienie z maila aktywuje się tylko
  wtedy, gdy CAŁY jego okres mieści się przed bieżącą `end_date` umowy;
  wychodzące poza nią zostaje szkicem. `terminated_at` NIE jest czyszczone przy
  aneksie ani przywróceniu (`reopen_contract`), więc reguła czyta bieżącą datę
  końca: aneks przesuwa okres, a umowa przywrócona bezterminowo (`end_date`
  pusta) wraca do zwykłych zasad. Bez tego jedno wypowiedzenie blokowałoby
  automat dla tej osoby na zawsze (przegląd adwersarialny 10.09).
- **Jedyny imiennik w bazie wymaga człowieka.** Nowa osoba z maila jest
  szukana po nazwisku ze zwiniętymi polskimi znakami po obu stronach. Jeden
  imiennik bez umowy u tego klienta zostaje dopięty tylko przy ręcznym
  „Zastosuj”; automat odsyła dokument do kolejki (samo nazwisko to za mało,
  żeby dać komuś cudze zamówienie). **Blokadę zdejmuje `confirmed_by_human`,
  nie `actor_user_id`** — „Przelicz plan” podaje klikającego wyłącznie do
  audytu (`apply_document(actor_user_id=…, confirmed_by_human=False)`), więc
  imiennik i dopasowanie niedokładne nadal wracają do kolejki, a wyłącznik
  automatu dalej działa.
- **Zamówienie nadpisane w miejscu da się odtworzyć z historii.** Activity
  `order_mail_reactivate` niesie `before` (stan sprzed nadpisania), `message`
  i `created_at` = chwila nadpisania; `before` NIE zapisuje `rate_unit`.
  Jednorazowa korekta PFRON 507–509 (migracja `0306_pfron_renewal_split_repair`,
  SQL w `services/pfron_renewal_split_repair.py`, lustro w `entrypoint.sh`):
  nowy okres 01.09–30.11 przechodzi do NOWEGO wiersza, oryginał wraca do stanu
  z `before` (koszt z harmonogramu umowy na ostatni dzień okresu), a konsumpcje,
  alerty i dokument maila od 09.2026 idą za nowym wierszem. Każde zamówienie
  jest przypięte tożsamością biznesową i pomijane z powodem, gdy stan produkcji
  się nie zgadza — w tym gdy po T0 ktoś je edytował (`edited_after_incident`:
  PATCH/PDF/anulowanie/zakończenie), gdy tytuł albo jednostka różni się od planu
  z maila, i gdy TA SAMA OSOBA ma u klienta inne zamówienie na którykolwiek
  z dwóch okresów, także na innej umowie („Nowy kontraktor / zamówienie” zakłada
  nową umowę). Blok ma `lock_timeout` 15 s i blokuje wiersz klienta jak writer
  maila; po timeoucie nic nie zapisuje i ponawia przy następnym starcie.
  Harmonogram przychodu umów domyka krok `pfron_revenue_resync` (entrypoint, tuż
  po korekcie) przez `resync_contract` — ten sam kod co zwykły zapis zamówienia.
  **Dwa klucze w `app_settings`:** paragon `0306_pfron_renewal_split_repair`
  (liczniki, ID, daty, powody — czyta go `coolify-ops` `migration-receipts`,
  którego log jest PUBLICZNY) i szczegóły `repair_details_0306_…` (migawki,
  tytuły, stawki, notatki, ścieżki — do ręcznego odwrócenia; kształt klucza
  sprawia, że workflow ich nie wydrukuje). Wynik weryfikuje Delivery Lead.
  **Nowy paragon naprawy danych = tylko liczniki i ID pod kluczem `NNNN_…`**;
  wszystko z kwotą, tytułem albo nazwiskiem idzie pod klucz innego kształtu.
- **Dedup alertów wygasania = (odbiorca, obiekt, próg, data końca)**
  (`dl_portal_expiry_scanner.py`, także umowy ramowe). Data pochodzi z treści
  komunikatu („kończy się/wygasa RRRR-MM-DD”), którą alerty niosą od maja —
  **nie zmieniaj tego sformułowania bez `_end_phrase`**, bo stare powiadomienia
  przestaną się deduplikować. Przedłużona umowa z nową datą końca dostaje nowy
  alert; do 11.09 próg raz wysłany milczał przy każdej kolejnej dacie.
- **Pierwszy szkic z maila u klienta bez DL** dostaje alert z dziennego
  backstopu (`dl_alerts.py`), gdy tylko DL zostanie przypisany — ten sam klucz
  co zapis, więc bez duplikatów. Do adminów świadomie nie idzie (jak #1394).
- **Migracja uruchamiana przez `text()` nie może zawierać `:słowo`** (SQLAlchemy
  zrobi z tego parametr) — czas przez `make_timestamptz(...)`, nie literał.

## Finanse → „Zamówienia PDF" (21.09.2026)

`/finance?view=order-pdfs`: miesiąc startu → klient → PDF-y do pobrania.
Serwis `services/finance_order_pdfs.py`, trasy `/api/finance/order-pdfs*`
(bramka sekcji Finance, jak cały moduł — roli „Finanse admin" nie ma).

- **Liczone przy odczycie, bez tabeli i migracji** — historia jest objęta od
  razu, nowe zamówienie z PDF-em pojawia się samo. Nie dokładaj tabeli-wykazu.
- **Trzy źródła:** `client_orders.file_path` (okres `COALESCE(linia, grupa)`),
  `client_order_groups.file_path`, aneks `extension` z `document_id` (start =
  `old_values.end_date` + 1). Anulowane zamówienia i kopie PDF-u grupy
  w dokumentach kontraktu (`source_order_group_id`) są pomijane.
- **Nazwisko z przypisania, nigdy z PDF-a;** PDF grupy dostaje nazwisko tylko
  przy DOKŁADNIE jednej osobie. Nazwa pliku: `build_download_name`
  (`<oryginał>_<Nazwisko>_DD.MM.RRRR-DD.MM.RRRR`, brak końca = `-bezterminowo`);
  lista i pobranie liczą ją tą samą funkcją (`find_entry`).
- Klucze URL `pdfMonth`/`pdfClient` (nie `month` — ten należy do „Zmian").

## Usunięcie zamówienia przecenia historię — dialog musi to powiedzieć (18.09.2026)

- **`ContractClientRate.source_order_id` ma `ondelete=CASCADE`.** Komentarz przy
  kolumnie zawęża intencję do SZKICU, ale `delete_order` kasuje od #1594
  w KAŻDYM statusie, więc razem z zamówieniem znika krok harmonogramu stawki
  klienta. `Contract._resolve_scheduled_rate` przy braku kroku obowiązującego
  sięga po NAJBLIŻSZY PRZYSZŁY — miesiące historyczne dostają wtedy stawkę,
  której wtedy nie było. Na produkcji: 99 zamówień ma własny krok, 31
  kontraktów ma ich więcej niż jeden, 5 z różnymi kwotami (kontrakt 167:
  usunięcie zamówienia 351 przecenia III–VIII z 185,00 na 178,00 zł/h).
- **Skutki liczy SERWER** (`GET /api/clients/{c}/orders/{o}/delete-preview`,
  wyłącznie odczyt) — front nie zgaduje, bo reguła wyboru stawki zastępczej
  żyje w modelu kontraktu i rozjechałaby się przy pierwszej jej zmianie.
  Kwoty redagowane jak wszędzie w module (`_can_see_finance`): rola bez
  finansów widzi, ŻE okres się przeceni, i od kiedy — bez kwot.
- **Dialog zamiast `window.confirm`** (`components/orders/DeleteOrderDialog.tsx`,
  zdania w `lib/order-delete-consequences.ts`). Stary tekst obiecywał „umowa
  tej osoby nie zmieni się" i był nieprawdą; przy okazji natywny dialog
  ZAMRAŻA automatyzację przeglądarki, więc tej ścieżki nie dało się przeklikać.
  Zdanie „nic się nie zmieni" pada wyłącznie wtedy, gdy lista skutków jest
  pusta. Dopóki podgląd się nie wczytał, przycisk „Usuń" jest wyłączony:
  „nie wiem" nie jest tym samym co „nic się nie stanie".
- Rozliczenia nadal blokują usunięcie (409, `settlement_blockers`) — dialog
  tylko mówi to WCZEŚNIEJ i nazywa, co by przepadło.

## Zamówienia wielo-konsultantowe (BIK / Polkomtel / BNP) + import zużycia MD

Klienci rozliczani w T&M na MD przysyłają JEDNO zamówienie („nr 445") obejmujące
kilku konsultantów, każdego z własną stawką kosztową, przychodową i budżetem MD,
który topnieje wraz z miesięcznymi raportami z Finansów. Migracja `0227`.

- **Zamówienie wielo-konsultantowe to GRUPA nad istniejącymi `client_orders`, a nie
  „wiele osób w jednym wierszu".** Odruchowe rozwiązanie — zdjąć `NOT NULL`
  z `client_orders.contract_id` i przenieść konsultanta do tabeli linii — psuje
  siedemnaście ścieżek, bo CAŁY system czyta zamówienie przez jego kontrakt:
  `dl_portal_expiry_scanner` robi INNER JOIN po `contract_id` (zamówienie bez kontraktu
  przestaje ostrzegać na 30/14/7 dni, a `_promote_statuses` i tak przestempluje je na
  `completed` — wygasa bez ostrzeżenia), sync terminacji w `contracts.py` domyka zamówienia
  po `contract_id` (osierocone biegłyby po zakończeniu współpracy w nieskończoność),
  zgrupowana lista iteruje po `Contract.client_orders` (osierocone ZNIKA z widoku),
  a `ClientOrderRead.contract_id: int` wywala walidację przy pierwszym odczycie.
  Grupa kosztuje jedną tabelę i zero ryzyka: linia = zwykłe `ClientOrder` ze swoim
  kontraktem, więc wszystkie te ścieżki działają bez zmian. Zamówienia pozostałych
  klientów mają `order_group_id IS NULL` i nie zmienia się dla nich nic.
- **Bramka po `client_id` z ENV, nie po nazwie i nie w bundlu.** `MULTI_CONSULTANT_ORDER_CLIENT_IDS`
  (CSV, Coolify) — dopisanie klienta bez deployu. Nazwa odpada z tego samego powodu co
  przy e-Zdrowiu: Traffit nadpisuje `Client.name`, a „BNP" to RODZINA rekordów.
  **Front NIE trzyma kopii listy** (inaczej niż `lib/ezdrowie.ts`, gdzie jedno stałe ID
  jest zduplikowane po obu stronach) — lista jest zmienną środowiskową, więc kopia
  w bundlu byłaby nieaktualna od pierwszej zmiany w Coolify. Zamiast tego
  `ClientSafeResponse` wystawia wyliczone `multi_consultant_orders_enabled`.
  **Pusta lista = funkcja wyłączona dla wszystkich** (fail-closed).
- **Bramka stoi przy KAŻDEJ operacji, nie tylko przy renderowaniu.** Ukryty przycisk nie jest
  zabezpieczeniem; wywołane wprost API założyłoby zamówienie u klienta, którego zakładka
  nigdy go nie pokaże — dane nie do zobaczenia i nie do poprawienia z interfejsu.
  Wyjątek: **ODCZYT u klienta spoza listy zwraca pustą listę, nie 403** — 403 renderuje się
  jak awaria, a tutaj naprawdę nie ma czego pokazać.
- **Stawki MD mają WŁASNE kolumny** (`md_rate_cost`/`md_rate_revenue`), nie nadpisują
  `rate_client`/`Contract.rate_candidate`. Tamte są interpretowane przez `Contract.rate_unit`
  (h/dzień/mc) i zasilają marżę miesięczną w widokach jednoosobowych — wpisanie tam stawki
  dziennej dałoby cichy, 22-krotny błąd marży u trzech klientów. `_compute_monthly_margin`
  jest CELOWO nietknięte.
- **`md_remaining` jest WYLICZANE** (`md_total − Σ konsumpcji + md_manual_adjustment`),
  przeliczane od zera przy każdej zmianie. To jest mechanizm idempotencji importu, razem
  z UNIQUE `(order_id, period_month)`: powtórka miesiąca NADPISUJE wiersz konsumpcji.
  **Korekta ręczna siedzi w osobnej kolumnie**, nie nadpisuje `md_remaining` — nadpisanie
  przeżyłoby dokładnie do najbliższego importu, który przelicza pozostałość od `md_total`.
- **Pozostałość może zejść poniżej zera** — przekroczony budżet jest faktem handlowym.
  UI sygnalizuje kolorem, nic nie blokuje i nic nie ścina (także przy zamianie kontraktora).
- **Zamiana kontraktora zachowuje wartość w PLN**: `md_nowe × stawka_nowa = md_pozostałe ×
  stawka_stara`, wyłącznie od dnia zamiany w przód. Domknięcie starej linii jest lustrem
  syncu terminacji z `contracts.py`: data zawsze, status `completed` dopiero gdy dzień
  zamiany nadszedł — zamiana zaplanowana na przyszłość NIE może wyłączyć pracującego
  konsultanta. Obie stawki, obie liczby MD i data lądują w `payload` zdarzenia; bez nich
  nie da się rozliczyć faktury za miesiąc zamiany (MD sprzed zamiany idą po stawce poprzednika).
- **Precyzja:** `NUMERIC(16, 6)`. „Bez zaokrąglenia" jest nieosiągalne w typie
  stałoprzecinkowym (`kwota / stawka` bywa ułamkiem nieskończonym); sześć miejsc to cztery
  zapasu ponad prezentację (2 miejsca), więc kolejne importy nie kumulują widocznego błędu.
- **Import MD dopasowuje WYŁĄCZNIE po imieniu i nazwisku** (arkusz nie ma numeru zamówienia).
  Jedno trafienie → zastosuj; zero → „Brak aktywnego zamówienia"; **więcej niż jedno →
  „Wymaga przypisania" i system NIE zgaduje** — trafienie w złe zamówienie odejmuje MD nie
  temu klientowi i wychodzi dopiero na fakturze. Wiersz importu ŻYJE DALEJ w bazie, bo bez
  trwałego wiersza niejednoznaczność przepadłaby razem z odpowiedzią HTTP.
  Tokeny nazwiska są **zbiorem** (nie listą) — arkusze piszą raz „Jan Kowalski", raz
  „Kowalski Jan". Normalizacja z `candidate_identity_quarantine.normalize_person_name_part`.
- **Parser XLSX szuka nagłówka po synonimach** i przemiata wszystkie arkusze (raporty często
  zaczynają się arkuszem tytułowym). Miesiąc wybiera OPERATOR — nazwy plików kłamią dokładnie
  wtedy, gdy import dotyczy okresu zaległego. Wiersze nieczytelne trafiają do `skipped_rows`,
  nigdy nie znikają po cichu.
- **Uprawnienia — obsadę zamówienia prowadzi DELIVERY, nie tylko admin.** Stawki linii MD
  ustawia admin albo Delivery Lead **przypisany do tego klienta** (`_manages_md_lines`).
  Zakres jest wąski i trzeba go pilnować: dotyczy WYŁĄCZNIE kolumn `md_rate_*` na tej
  powierzchni — legacy `rate_client`/`rate_candidate`/`total_value` w module zamówień
  zostają **admin-only** (`_ORDER_FINANCE_WRITE_FIELDS`), a `head_of_recruitment` jest poza
  (przechodzi `DlAssignedOrAdmin` globalnie, bez przypisania, a repo konsekwentnie trzyma go
  z dala od powierzchni finansowych — patrz `/settings/clients-overview`). Rola `finance`
  też nie: jest odcinana od powierzchni kandydackich, a ta niesie nazwisko konsultanta.
  **Odczyt i zapis są wyliczane z JEDNEJ funkcji** — rozdzielenie ich dałoby rolę, która
  zapisuje stawkę i widzi w jej miejscu „—", czyli formularz bez możliwości sprawdzenia
  własnej pracy. `VIEW_FINANCE` NIE zostało dodane roli DL globalnie: to zmieniłoby eksport
  kontraktów, `/settings/clients-overview` i panel admina. **Profil klienta ORAZ portal DL
  (`/my-clients`, zakładka Analityka) są od 01.09 wyjątkiem zrobionym tą samą metodą,
  nie capability** — patrz „Delivery Lead widzi kwoty własnego portfela
  (profil klienta + Analityka)".
  Liczby MD są **operacyjne**, nie finansowe — pasek zużycia działa bez uprawnień do stawek,
  a same stawki renderują się jako „—" (znikająca kolumna czytałaby się jak brak danych, nie
  jak brak uprawnień). Import: `FinanceManageUser` (admin + Finanse) z wąską projekcją
  wierszy — bez identyfikatorów kandydatów i kontraktów.
- **Picker konsultanta pokazuje DWA źródła w jednej liście** (`ConsultantPicker`,
  `GET …/order-groups/consultant-options`): osoby z kontraktem u tego klienta
  („Rekrutacja u klienta") i pozostałych aktywnych konsultantów z bazy
  („Baza Nexus"). Wcześniej był tu `<select>` wyłącznie z kontraktami u klienta,
  więc konsultanta kończącego projekt u jednego klienta nie dało się wpisać na
  zamówienie u drugiego. Reguły, które trzymają tę listę uczciwą: dedup po
  OSOBIE, nie po kontrakcie (kto jest w źródle A, nie pojawia się w B, a osoba
  z dwoma żywymi kontraktami u tego klienta ma jeden wiersz — ten o najpóźniejszym
  starcie); „aktywny" to `active` + **`ending`** (kontrakt < 30 dni do końca to
  wciąż ktoś, kto pracuje, i najbardziej oczywisty kandydat na obsadę); sortowanie
  i wyszukiwanie idą po kluczu bez diakrytyków **w Pythonie**, bo prod nie ma
  `unaccent`; zapytanie jest AND-em po tokenach dopasowywanych PREFIKSEM, więc
  „Jan Kowalski" zwraca jedną osobę, a nie wszystkich Janów i wszystkich
  Kowalskich (równość byłaby pułapką — „Anna Kowal" w trakcie pisania nie
  zwracałoby nic, a pustka czyta się jak „nie ma jej w bazie" i kończy duplikatem).
  Odpowiedź niesie `total`, bo lista bez licznika przycięta limitem czyta się jako
  komplet. **Nazwa klienta, u którego dana osoba pracuje teraz, NIE wychodzi** —
  odbiorcą listy jest zespół jednego klienta. Harness wizualny (publiczny, same
  mocki): `/preview/order-consultant-picker`.
- **Osoba z bazy Nexus jedzie jako `candidate_id`, a serwer zakłada jej kontrakt
  w statusie `draft`.** `client_orders.contract_id` jest NOT NULL i czyta go
  kilkanaście ścieżek (skaner wygasania, sync terminacji, MRR), więc linia musi
  wisieć na kontrakcie u TEGO klienta — zdjęcie NOT NULL jest wykluczone (patrz
  wyżej). `draft`, nie `active`: aktywacja ma własny walidowany cykl życia
  (`contract_lifecycle.activate_contract`), a formularz obsady o umowie nie pyta,
  więc nie może wpychać ludzi do MRR i alertów wygasania. Kontrakt już istniejący
  jest REUŻYWANY (zero drugich, równoległych kontraktów u tego samego klienta).
  `OrderLineCreate` wymaga DOKŁADNIE JEDNEGO z pól `contract_id`/`candidate_id`:
  przy dwóch trzeba by rozstrzygać, które wygrywa, a każde rozstrzygnięcie po
  cichu wpisuje na zamówienie kogoś innego, niż widział operator. Fakt założenia
  kontraktu ląduje w historii zamówienia (`payload.contract_created`).
  **Zamiana kontraktora (`SwapConsultantModal`) świadomie ZOSTAJE przy starej,
  wąskiej liście** — ticket dotyczył dodawania do zamówienia.
- **Pułapka UI, którą złapał dopiero test w przeglądarce:** gałąź pustego stanu MUSI wisieć na
  `isSuccess`, nie na `!isLoading`. W przerwie między ponowieniami react-query ma
  `isLoading === false`, `isError === false` i puste `data`, więc warunek na `isLoading`
  przepuszczał ten stan do pustego stanu i ekran twierdził „brak zamówień", zanim cokolwiek
  było wiadomo. Dotyczy trzech miejsc: listy zamówień, historii zamówienia i historii importów.
- **Aktywacja na prodzie:** ustaw `MULTI_CONSULTANT_ORDER_CLIENT_IDS` w Coolify (ID z
  `SELECT id, name FROM clients WHERE name ILIKE '%BIK%' OR name ILIKE '%Polkomtel%' OR
  name ILIKE '%BNP%'`). Do tego czasu wszystko stoi bezczynnie i zakładka „Zamówienia"
  renderuje dotychczasowy widok jednoosobowy dla każdego klienta.

## Zamówienie MD i zamówienie okresowe to DWA niezależne byty

Kontrakt (`Contract`) opisuje parę *osoba × klient*, a nie pojedyncze
zamówienie. U klientów wielo-konsultantowych ta sama osoba bywa więc opisana
dwa razy: linią grupy MD/kosztowej (`ClientOrder.order_group_id IS NOT NULL`)
i samodzielnym zamówieniem okresowym. Zgłoszenie z sierpnia 2026
(BNP / Polkomtel / BIK / Lotte Wedel): zakończenie tego drugiego kasowało
budżet MD tej samej osoby. Migracja `0262_separate_md_periodic`.

- **Przyczyna była DWUCZĘŚCIOWA i obie połowy trzeba było zamknąć.** Hook
  zatrudnienia (`_ensure_open_order`) zakłada szkic-zaślepkę „(bez numeru)"
  **zanim** Delivery obsadzi osobę na zamówieniu MD, więc bramka przy tworzeniu
  zamówienia nie miała czego odrzucić. Teraz: hook nie tworzy nic, gdy żywa
  linia grupowa już jest, a wejście na linię grupy **kasuje** zostawioną
  zaślepkę (`absorb_auto_draft_shells`). Kasujemy WYŁĄCZNIE wiersz, który na
  pewno niczego nie niesie (szkic, tytuł-zaślepka, bez pliku PO, bez budżetu MD,
  bez `filled_at`) — usunięcie szkicu kasuje też jego plik, a bywa on jedyną
  kopią dokumentu.
- **Ręczne założenie zamówienia okresowego obok żywej linii MD → 409**
  (`assert_no_open_group_line`). Ścieżki AUTOMATYCZNE pytają predykatem i po
  cichu odpuszczają: zatrudnienie nie może się wywrócić dlatego, że ktoś jest
  już na zamówieniu MD. Reguły odwrotnej („nie dodawaj linii MD, gdy jest
  okresowe") świadomie NIE ma — linia grupy powstaje zawsze decyzją operatora.
- **„Zakończ zamówienie" ≠ „Zakończ współpracę" i to są dwa różne przyciski.**
  `POST /api/clients/{c}/orders/{o}/close` domyka JEDEN wiersz i nie dotyka ani
  umowy, ani sąsiednich zamówień. Wypowiedzenie umowy (`/contracts/{id}/terminate`)
  zostaje bez zmian — domyka wszystkie zamówienia kontraktu i otwiera sprawy
  offboardingowe MD, bo umowa opisuje CAŁĄ współpracę u klienta. Zawężenie jej
  po cichu zabiłoby workflow decyzji Delivery Leada.
- **Linia grupy jest z nowego endpointu odrzucana (409)** — grupa ma własne
  zakończenie (`POST /order-groups/{id}/close`), które prowadzi budżet, historię
  i sprawy offboardingowe. Dwie drogi do jednego wiersza rozjechałyby się przy
  pierwszej zmianie którejkolwiek.
- **Data w przyszłości zapisuje się, ale nie wyłącza zamówienia** — lustro
  `close_order_group` i syncu terminacji umowy. Resztę materializuje dzienny
  `dl_portal_expiry_scanner`.
- **`flush` + `refresh` PRZED commitem w `close_order`.** `updated_at` ma
  serwerowy `onupdate`, więc po UPDATE atrybut jest wygasły niezależnie od
  `expire_on_commit=False`; sięgnięcie po niego przy budowaniu odpowiedzi to
  w sesji async `MissingGreenlet`, czyli 500 bez CORS („Network Error").
- **Kontrakt NIE dziedziczy daty końca zamówienia.** Szkic zakładany przy
  obsadzie linii (`_contract_for_candidate`) kopiował `end_date` linii/grupy,
  więc umowa B2B, która ma być bezterminowa, dostawała datę, której nikt nie
  zadeklarował — a nocny `_promote_statuses` przestawiał ją na „Kończąca się",
  potem „Zakończona". Kopiujemy wyłącznie datę ROZPOCZĘCIA. Datę zakończenia
  umowy ustawia człowiek (rejestr umów albo `/terminate`).
  `sync_contract_to_live_order` **zostaje** jako mechanizm wskrzeszania
  („Przedłużenie zamówienia wskrzesza zakończony kontrakt"), ale od 09.2026
  wskrzeszony kontrakt jest BEZTERMINOWY — nie dziedziczy już daty końca
  zamówienia (patrz „Zakładka „Zakończeni" — decyduje umowa, nie okres
  zamówienia").
- **Zakończenie u jednego klienta nie sięga do drugiego.**
  `client_orders.client_id` to WŁASNA kolumna, a baza nie ma więzu wiążącego ją
  z klientem kontraktu (rozjazd zna też `contract_merge`). Kaskada offboardingu
  bierze teraz wyłącznie zamówienia, dla których `ClientOrder.client_id ==
  Contract.client_id`; wiersz rozjechany zostaje nietknięty i widać go
  w `GET /api/admin/engagement-inventory` (checki `order_client_mismatch`
  i `periodic_duplicates_group_line`). Cicha zmiana czyjegoś stanu na podstawie
  niespójnych danych jest gorsza niż jej brak — dlatego audyt, nie automat.
- **Naprawa danych: migracja `0262` + lustro w `entrypoint.sh`** (prod alembic
  bywa osierocony, a ta naprawa jest treścią ticketu). SQL ma JEDNO źródło:
  `app/services/order_separation_repair.py`. Jest jednorazowy (advisory lock +
  marker w `app_settings`) i regułowy — **ani jednego `client_id` w SQL-u**.
  Czterej klienci ze zgłoszenia są przypadkiem reguły, nie jej definicją.
  Krok A kasuje puste zaślepki i ANULUJE (nie kasuje) pozostałe duplikaty;
  krok B czyści datę końca umowy i przywraca `active` tylko tam, gdzie widać,
  że nikt współpracy nie zakończył (brak `terminated_at`, brak powodu, brak
  aneksu `early_termination`, żywa linia grupowa obejmująca dziś). Paragon
  w `app_settings`.
- **Karta kontraktora znika, gdy zostaje po niej wyłącznie martwy duplikat**
  (`filterMaterializedContractorShells` — warunkiem jest brak ŻYWEGO zamówienia
  samodzielnego, nie brak zamówień w ogóle). Osoba z realnym, otwartym
  zamówieniem okresowym obok linii MD nadal ma obie pozycje: to dwa różne
  zaangażowania i o ich rozdzielenie w tym tickecie chodzi.

## Okno „Nowe zamówienie" — jeden odczyt PDF-a, karty wszystkich osób (09.2026)

„Nowe zamówienie" (MD/kosztowe) i „Uzupełnij zamówienie" połączone w JEDNO okno
(`OrderGroupFormModal` w trybie nowego zamówienia): PDF → **„Zczytaj i uzupełnij całe
zamówienie"** (`POST /api/clients/{id}/order-groups/extract`) → karta na każdą osobę
z dokumentu (`OrderPlanLineCard`, logika w `lib/order-plan.ts`) → JEDNO
`POST /order-groups` z `lines` (atomowo — endpoint od zawsze przyjmował linie).
Tryb edycji istniejącego zamówienia zostaje przy starym „Zczytaj dane z dokumentu".

- **Typy bez blokady per klient.** `order_types.allowed_order_types` zwraca wszystkie
  trzy typy dla każdego klienta (dawne `_PINNED_ALLOWED_ORDER_TYPES`: BNP/BIK tylko MD,
  Polkomtel/Wedel MD+kosztowe — ZNIESIONE). Mapa czterech klientów przetrwała
  wyłącznie jako **interpretacja legacy `NULL`** (`_LEGACY_NULL_ORDER_TYPES` →
  `ClientSafeResponse.legacy_null_order_type`) — bez niej historyczne karty MD
  przeskoczyłyby do sekcji „Okresowe". Front: `MultiConsultantOrdersTab` ma stałe
  `ALL_ORDER_TYPES`, a propsy `costOrdersEnabled`/`periodicOrdersEnabled` zniknęły.
  Konsekwencja zamierzona: jednorazowa korekta sierpniowa (`nexus_data_correction`)
  jest teraz zablokowana `order_type_runtime_policy_drift` — jej przesłanka („te typy
  są niedozwolone") przestała obowiązywać, a ponowne uruchomienie skasowałoby
  poprawne zamówienia. Nie „naprawiaj" tego blokera.
- **Domyślny typ = NAJCZĘSTSZY u klienta** (`most_common_order_type`: grupy +
  samodzielne bez anulowanych; remis → ostatni typ; brak historii → typ legacy).
  Zasila `OrderGroupListResponse.suggested_order_type`. Automaty (szkic po zatrudnieniu,
  poczta) nadal biorą OSTATNI typ (`suggested_order_type`) — świadomie nie ruszone.
- **Odczyt = ten sam pipeline co poczta zamówień**: `extract_order_text` → polityki →
  `parse_order_document(all_rows=True)` (dokument jednoosobowy BNP → tryb zwykły, jedna
  karta bez osoby) → `apply_policies` → `apply_rate_kind`. Pola dokumentu (stawka/MD
  z nagłówka) zastępują brak w wierszu TYLKO przy jednej osobie. Nic nie zapisuje.
- **Dopasowanie osoby do KONTRAKTU — `order_consultant_match`, NIE `order_mail_resolver`.**
  Resolver poczty toleruje odmianę i literówkę (trafia do kolejki), tu trafienie
  zapisałoby cudzą stawkę jednym kliknięciem. Reguła z ticketu: rdzeń = od
  przedostatniego wyrazu z wielkiej litery do końca, wcześniej dopisek („Active",
  „UR –", „Projekt 2"); tolerowane tylko dopisek, polskie znaki, wielkość liter,
  myślnik/spacja. `auto` = identyczne; `confirm` = dopisek / odwrotna kolejność
  (jedno kliknięcie DL); `inactive` = jedyny pasujący kontrakt jest ZAKOŃCZONY —
  karta mówi to wprost i każe wybrać: zapis historyczny / wznów / zastąp / usuń
  (od 09.2026; wcześniej był to cichy `confirm`, którego zapis wznawiał kontrakt);
  `ambiguous` = >1 RÓŻNA osoba w puli
  (także gdy jedna ma kontrakt aktywny, a druga szkic ALBO zakończony — powrót po
  przerwie) albo ta sama osoba z >1 żywym
  kontraktem; `none` = reszta. Pula: żywe + szkice (+ `ready_for_signature`); dopiero
  bez nich — zakończone (powrót osoby). `nearest_names` (difflib ≥ 0,75) to WYŁĄCZNIE
  podpowiedź tekstowa, nigdy wybór.
- **Osoba nieaktywna/nieznaleziona — JEDEN mechanizm na trzech ścieżkach (ticket B,
  09.2026, reguła ogólna dla zamówień MD i kosztowych każdego klienta).** Komunikat
  ma jedno źródło: `inactive_consultant_reason` / `unknown_consultant_reason`
  (`order_consultant_match`). Czytają go: karta okna „Nowe zamówienie", ten sam
  odczyt w „Uzupełnij zamówienie" (tryb edycji `OrderGroupFormModal` od 09.2026
  czyta PDF przez `/order-groups/extract`, karty tylko dla osób spoza zamówienia —
  `splitPlanForGroup`, zapis `POST …/lines/batch`, razem albo wcale), planer poczty
  i kontrakty zakończone na liście „kilka osób" (`OrderPlanContractRead.inactive_reason`
  — wybór zakończonego kontraktu przechodzi w pytanie zostaw / wznów / zastąp /
  usuń, a nie w ciche wznowienie). **Poczta: `ACTION_DECIDE_PERSON`** dla wierszy
  `order_type ∈ {md, cost}`, gdy osoby nie ma u klienta albo jej jedyny kontrakt
  do zapisu jest `ended` — nieautomatyczna akcja, „Zastosuj" wyłączone. Kolejka
  prowadzi przyciskiem **„Rozstrzygnij w oknie zamówienia"** do
  `/clients/{id}?tab=zamowienia&orderMailDoc={doc}`: zakładka pobiera PDF
  (`GET /order-mail/queue/{id}/order-target` + `/file`), otwiera „Uzupełnij
  zamówienie" dla otwartej grupy o tym numerze (`titles_collide`) albo „Nowe
  zamówienie", czyta PDF sama, a po zapisie `POST …/resolved-in-order` zdejmuje
  dokument z kolejki (`outcome=applied`, `proposal.resolved_in_order`). Świadomie
  BEZ `applied_order_id`: to pole czyta `complete_signed_mail_drafts`, który
  aktywuje szkice z maila po podpisie — linii grupy dotykać nie może. PDF z maila
  przy grupie, która MA już plik, domyślnie służy tylko do odczytu (podmiana
  pliku = checkbox). **Zamówienie okresowe zostaje przy decyzji z 10.09**: powrót
  po przerwie = nowe zamówienie (nie wskrzeszenie zakończonego).
- **Osoby spoza rostera klienta automat NIE zakłada — na ŻADNYM typie
  zamówienia** (zgłoszenie 09.2026, Nordea, umowa 1506/2026). Kontraktor rodzi
  się z podpisanej umowy B2B, nie z PDF-a klienta: zamówienie, które przyszło
  wcześniej, **czeka**. Rozstrzyga BRAMKA, nie planer — `match_kind == "none"`
  zawsze daje powód (`CODE_PERSON_NEW_TO_SYSTEM`, gdy osoby nie ma też w bazie;
  `_known_elsewhere_code` z #1561, gdy jest). Oba kody są
  w `AWAITING_CONTRACT_CODES`, więc wpis wisi **cicho**: bez licznika prób,
  bez karty dla Delivery Leada, z godzinową ponowną weryfikacją. Gdy ktoś
  oznaczy umowę „podpisana obustronnie", `confirm-fully-signed` zakłada kontrakt
  (`active`) i najbliższy recheck dopisze zamówienie sam. **Plan ZOSTAJE przy
  `ACTION_NEW_DRAFT`** (poza MD/kosztowymi, gdzie planer i tak daje
  `ACTION_DECIDE_PERSON`): ręczne „Zastosuj" bramki nie czyta, więc DL zachowuje
  drogę dla kontraktora bez umowy B2B (UoP, zlecenie, klient spoza generatora).
  Do 09.2026 zamówienie okresowe na nieznaną osobę jechało automatem i zakładało
  kandydata + szkic kontraktu + zamówienie — tak powstał kontrakt #657.
  `DECIDE_PERSON_ORDER_TYPES` **nie jest** listą typów, dla których nowa osoba
  jedzie automatem; opisuje wyłącznie, gdzie decyzję podejmuje się w oknie
  zamówienia.
- **Wiersze modelu weryfikowane regułą klienta.** Gdy aktywna polityka ma
  `extract_rows` (deterministyczny regex tabeli), wartość z tabeli wygrywa z modelem
  (`_reconcile_with_evidence`; lustro `order_mail_gate._row_evidence_reasons`),
  a rozbieżność i brak osoby w tabeli są ostrzeżeniem na karcie. Orlen (`requires_target`,
  więc tu jego polityka się nie odpala): MD z PDF-a zawsze pomijane, wiersze on/off-site
  tej samej stawki zlewane. Bank Pocztowy: linia MD dostaje oryginalne `rate_client_md`,
  nie godzinówkę ×8 (zaokrąglenie w górę zawyżałoby stawkę). Dokument wieloosobowy
  bez wierszy NIE tworzy karty z pól nagłówka — tylko jednoosobowy BNP. Brak jednostki
  stawki blokuje kartę (`revenueUnit: null`), a nie domyślnie „MD".
- **Stawka kosztowa z TEGO kontraktu** (`client_order_lines.contract_cost_rate`,
  wyciągnięte z `_rate_suggestion` — ta sama arytmetyka co picker), nie z „najnowszego
  żywego" osoby. Kwoty redagowane jak na liście (`_can_see_finance`); MD operacyjne.
- **Źródło każdej wartości** jedzie z odpowiedzi (`position_label` = numer pozycji
  tabeli PDF-a, szukany deterministycznie nad linią z nazwiskiem, nigdy wyżej niż linia
  poprzedniej osoby; brak pewności → „N. osoba w dokumencie"). Ręczna poprawka na karcie
  przestawia źródło na „wpisano ręcznie" — opis nie może twierdzić „z PDF", gdy liczbę
  wpisał człowiek.
- **Nowe MD jest domyślnie „Aktywne"** (dotąd wyłącznie „Draft"). `create_order_group`
  przy `status="active"` + `md_budget_mode` waliduje jak aktywacja szkicu (PATCH):
  per osoba — ≥1 linia i każda z `input_value > 0`; wspólna pula — `md_budget_total > 0`.
- **Zmiana typu na „Okresowe" przenosi wgrany PDF** do `NewContractorOrderDialog`
  (`initialFile`) i z powrotem — formularze są różne, plik ten sam.
- Harness wizualny (publiczny, zero zapytań): `/preview/order-new-from-pdf`.

## Eksport zamówień do Excela pokazuje stan NA DZIŚ

`POST /api/clients/{id}/orders/export` bierze wyłącznie zamówienia
OBOWIĄZUJĄCE w dniu pobrania i **dokładnie jedno na konsultanta**.

- Reguła jest JEDNA i mieszka po obu stronach: `is_current_order_period`
  (`order_excel_export.py`) oraz `isCurrentOrder` (`lib/client-order-list.ts`).
  Brak daty końca = bezterminowo; brak daty startu = już obowiązuje (rekordy
  historyczne nagminnie nie mają startu). Status `completed`/`cancelled`
  odpada niezależnie od dat — linia domknięta bez daty przechodzi test okresu.
- **Zamówienie „kończące się" JEST aktualne** — dopóki data nie minęła,
  konsultant pracuje.
- **Deduplikacja idzie po KONTRAKCIE, nie po imieniu**: imiona się powtarzają,
  a ta sama osoba u tego samego klienta ma dokładnie jeden kontrakt. Obejmuje
  też linie grup, więc konsultant nie pojawi się raz w grupie i raz jako karta.
- **Filtr linii grupy czyta okres LINII, a w jego braku okres GRUPY.** Linie
  zwykle nie niosą własnych dat (arkusz renderuje je z okresu zamówienia), więc
  filtr patrzący tylko na kolumny linii przepuszczałby całą obsadę zamówienia
  zakończonego rok temu.
- Wiersz zbiorczy grupy („Całe zamówienie…") zostaje niezależnie od filtra —
  opisuje zamówienie, nie osobę.

## Domyślny widok modułu Kontrakty: Aktywne **i** Kończące się

`/contracts` bez parametrów pokazuje `["active", "ending"]`
(`DEFAULT_CONTRACT_STATUS_FILTER`). „Kończący się" to `active` z bliskim końcem,
a nie osobny etap życia umowy — konsultant nadal pracuje, więc domyślne
`["active"]` chowało dokładnie te umowy, którymi trzeba się zająć najpilniej.
Etykieta licznika („N kontraktorów / M aktywnych kontraktów") liczy teraz
**cały zbiór obowiązujących**, nie tylko dokładnie jeden status — inaczej
domyślne wejście do modułu cofało ją do generycznego „osób / kontraktów".
Filtrowanie do pojedynczego statusu i sentinel `status=all` działają bez zmian.

## Cykl życia zamówienia, zamówienia kosztowe i powiadomienia Delivery Leada

Migracja `0233`. Trzy obszary, jedna rewizja — spotykają się na jednym wierszu
`client_order_groups`. Pełny opis: `docs/order-lifecycle-cost-and-dl-alerts-completion-report.md`.

- **Zakładka „Zamówienia" renderuje DWA różne widoki i tickety dzielą się między nie
  czysto.** `MultiConsultantOrdersTab` dla klientów z `MULTI_CONSULTANT_ORDER_CLIENT_IDS`
  (BIK/Polkomtel/BNP), `OrdersAndContractsTab` dla wszystkich pozostałych
  ([page.tsx:945](frontend/src/app/clients/[id]/page.tsx)). Zanim cokolwiek dodasz do
  „zamówień", ustal, o którym widoku mowa — pole dołożone do złego jest **martwe**, bo
  jego klienci tego ekranu nigdy nie widzą (dokładnie dlatego „Liczba MD" NIE trafiła do
  `ExtendOrderDialog`).
- **Cykl życia grupy jest STANEM, nie datą.** `status` ∈ `active | completed | exhausted`.
  Data nie odróżnia zamówienia domkniętego świadomie od takiego, któremu minął termin,
  a to dwie różne decyzje. `exhausted` dochodzi automatycznie przy zerowym budżecie
  i **nie da się go cofnąć** przywróceniem (409) — tam problemem nie jest data, tylko
  brak pieniędzy, więc właściwą akcją jest korekta kwoty albo nowe zamówienie.
- **Zakończenie jest LUSTREM syncu terminacji kontraktu** ([contracts.py:2918](backend/app/api/contracts.py)):
  data zapisuje się zawsze, ale `completed` dostają tylko linie, których dzień już
  nadszedł. Bez tego zakończenie zaplanowane w przód wyłączałoby kogoś, kto dziś pracuje.
  **Import MD/kosztowy rozlicza taką grupę do daty zakończenia** (od 10.09.2026):
  grupa ma `completed` od razu, a jej linie są aktywne, więc
  `active_md_lines`/`active_cost_lines`/`active_shared_md_lines` przyjmują grupę
  `completed` z `closure_date ≥` pierwszy dzień importowanego miesiąca
  (`group_settles_in_month`). Ta sama reguła MUSI być w walidacji po blokadach
  (`md_consumption._ordinary_locked_target_is_valid`) — bez niej cała partia
  kosztowa lub wspólnej puli dostaje 409.
- **Usunięcie zamówienia kasuje WYŁĄCZNIE to zamówienie** (ticket 09.2026, decyzja:
  bez efektów ubocznych). `DELETE …/order-groups/{g}/lines/{l}` i kasowanie całej
  grupy wołają `_delete_line_row` — twarde `db.delete`, nigdy odpięcie. Do tej zmiany
  aktywna linia była odpinana (`order_group_id=NULL`) i wracała na liście jako NOWE
  zamówienie okresowe osoby, a linia z rozliczeniami dostawała `completed` + wpis
  `removed_from_order` (`_keep_consumed_line_as_history`, usunięte), co czytało się
  jak zamknięty projekt. `DELETE /api/clients/{c}/orders/{o}` na zamówieniu
  samodzielnym kasuje trwale w KAŻDYM statusie (dawniej aktywne → `cancelled`);
  linia grupy wołana tą trasą zachowuje starą regułę (szkic znika, reszta anulowana).
  **Rozliczenia blokują (409)** — `services/order_settlements.py`
  (`settlement_blockers`, wspólne z `_assert_group_is_disposable`): kaskada
  zabrałaby MD i faktury z importu Finansów. Front wyszarza kosz linii przy
  `lineHasSettlements` (`lib/order-line-usage.ts`). Status kontraktu, inne zamówienia
  i sprawy offboardingu nie są ruszane; `commit_order_write` tylko przelicza okres
  i stawki kontraktu z tego, co zostało. Pliki PO kasowane są PO commicie.
  Wpisy `removed_from_order` sprzed zmiany są dalej czytane (`_apply_line_history`,
  `sync_md_line_status`, `order_facts`), ale nie powstają nowe. Kasowanie linii
  zabiera jej `dodanie_konsultanta`; `zamiana_kontraktora` ZOSTAJE. Bieżące
  zamówienie na karcie kontraktora ma własny przycisk „Usuń zamówienie", a
  „Zakończ współpracę" (wypowiedzenie umowy, domyka WSZYSTKIE zamówienia osoby) nie
  ma już ikony kosza — to ona była „kaskadowym usuwaniem" ze zgłoszenia.
- **Historia osoby na zamówieniu** (`_apply_line_history`, jedno zapytanie o dziennik):
  `origin` (`document` = z PDF-a / `manual`), `added_by_name`/`added_at` (autor
  zdarzenia `dodanie_konsultanta`/`zamiana_kontraktora`), `replaces_name`,
  `removed_from_order`, `cooperation_ended_on`, `md_used`, `history_kept_*`.
  Pochodzenie zapisuje front (`document_name` / `replaces_name` w `OrderLineCreate`);
  linie sprzed tej ewidencji dodane > 2 min po utworzeniu grupy liczą się jako
  `manual`, wcześniejsze — `null` (bez odznaki). **Zapis historyczny**
  (`historical: true`): osoba z ZAKOŃCZONYM kontraktem zostaje na zamówieniu jako
  linia `completed` z datą końca udziału ≤ dziś, wyłącznie dla kontraktu
  w statusie `ended` (`terminated_at` przeżywa wznowienie, więc nie wystarcza);
  nie wznawia kontraktu (`_sync_contract_after_live_group_line` pomija
  `completed`, `sync_md_line_status` nie wskrzesza linii, której kontrakt jest
  `ended`) i nie przepisuje go (`skip_sync_for_contract` — bez tego sync
  przestawiłby zakończonej umowie jednostkę i dopisał krok przychodu po jej końcu).
  `POST …/lines/{id}/keep-history` = decyzja „Zostaw jako historię" (wpis w dzienniku
  z autorem; sprawa offboardingu MD `pending` → 409). PDF zamówienia trafia do
  profilu każdej osoby na zamówieniu przez `_sync_group_pdf_documents` (add_line,
  swap, upload pliku) — zastępca dodany później też go dostaje.
  Pod osobą spoza aktywnej obsady karta zamówienia pisze jedno zdanie dla MD
  i kosztowych: „[osoba] wykorzystał(a) X zł / Y MD na tym zamówieniu przed
  zakończeniem współpracy — ta kwota nie wraca do puli" (`lib/order-line-usage.ts`;
  kwota tylko przy `rate_revenue` z odpowiedzi, czyli z dostępem do finansów).
- **Wyczerpanie MD (BIK, Polkomtel) pomija osoby z zakończoną współpracą**
  (rozstrzygnięcie otwartego pytania z ticketu 09.2026): linia `completed`
  z niewykorzystanym limitem nie trzyma zamówienia otwartego; zamówienie kończy się,
  gdy ktoś NAPRAWDĘ wyczerpał limit, a nikt na obsadzie nie ma już MD. WYJĄTEK:
  nierozstrzygnięta sprawa offboardingu MD w grupie trzyma zamówienie otwarte —
  po zamknięciu „przywróć" i „przenieś" nie miałyby dokąd wrócić.
  **Dane testowe:** od 09.2026 skasowanie grupy i usunięcie linii kasują linie
  trwale (patrz „Usunięcie zamówienia kasuje WYŁĄCZNIE to zamówienie"). Osierocone
  wiersze `client_orders` po kasowaniu grup sprzed tej zmiany usuwasz
  `DELETE /orders/{id}` (samodzielne zamówienie jest kasowane w każdym statusie) —
  najpierw linia-następca, potem poprzednik, bo `predecessor_order_id` wskazuje wstecz.
- **Przedłużenie to NOWA grupa** z `predecessor_group_id`, nie edycja poprzedniej:
  poprzednia musi zostać taka, jaka była, bo na jej podstawie rozliczono już faktury.
  Typ rozliczenia DZIEDZICZY się po poprzedniku.
- **Zamówienie kosztowe (`is_cost_based`) — kwota mieszka na GRUPIE, nie na linii.**
  To jedna pula dzielona przez kilku konsultantów; trzymanie jej per osoba wymagałoby
  podziału z góry, czego nikt nie robi. Linia kosztowa ma obie stawki i **puste pola MD** —
  dlatego 0233 rozluźnia `ck_client_orders_md_coherence`: budżet nadal wymaga dodatniej
  stawki przychodowej, ale stawka bez budżetu jest legalna (do 0233 taka linia w ogóle
  nie dawała się zapisać).
- **Trzy liczby, nie jedna.** Ticket nazywa „zużyciem" wartość, która MALEJE — czyli
  resztę. UI pokazuje `budget_amount` / `budget_used` / `budget_remaining` + pasek, bo
  jedno pole podpisane „zużycie", a pokazujące resztę, myli w rozmowie o pieniądzach.
- **Rozliczenie przelicza się od zera przy każdej zmianie** (`cost_orders.settle_group`),
  po `(period_month, order_id)`. To jest mechanizm idempotencji importu razem z UNIQUE
  `(order_id, period_month)`, a stała kolejność jest tym, co sprawia, że odpowiedź na
  pytanie „której osobie zabrakło budżetu" nie zmienia się między odczytami.
  `settled_amount`/`unsettled_amount` są ZAPISANE, nie liczone przy odczycie.
- **Reszta nie schodzi poniżej zera**, a nadwyżka ląduje jako `unsettled_amount` na
  konkretnej linii — „budżet przekroczony o X" bez wskazania osoby nie daje się rozliczyć
  z klientem. `budget_manual_adjustment` jest osobną kolumną (jak `md_manual_adjustment`):
  korekta nadpisująca resztę wprost przeżyłaby do najbliższego importu.
- **Import kosztowy to DRUGA, niezależna ścieżka w „Import zużycia MD"** (`/finance?view=md`),
  nie w „Wynikach miesięcznych" — tamten moduł świadomie nie przechowuje „Uwag" i ta
  decyzja zostaje. Numer wybierany jest przez KONFRONTACJĘ z istniejącymi zamówieniami
  (`extract_order_number_candidates`), nie heurystyką „najdłuższy ciąg cyfr": obok numeru
  stoi często rok albo numer transzy. Wiersz wchodzi na tę ścieżkę tylko gdy ma **numer
  i kwotę** — bez kwoty nie ma czego odjąć, więc czerwień byłaby fałszywym alarmem.
  `cost_status` jest OSOBNĄ kolumną od `status`: jeden wiersz bywa MD-dopasowany po
  nazwisku i kosztowo-niedopasowany po numerze.
- **Parser MD wyklucza nagłówki stawkowe** (`_MD_ANTI_HEADERS`). Realny arkusz z Finansów
  ma obok siebie „Średnia Stawka MD" i „Ilość MD"; bez tego wygrywała pierwsza z brzegu
  i system odejmował 1000 „dni" zamiast 15 — błąd CICHY, bo liczba jest poprawna
  arytmetycznie, tylko opisuje co innego.
- **`dl_alerts` to OSOBNA tabela, nie `notifications`.** Tamta zna wyłącznie `is_read`:
  nie wie kto i kiedy sprawę załatwił, więc nie ma czasu reakcji, czyli nie ma czego
  wyeksportować. Ma też dobowy indeks dedupu, który tłumiłby powtórki, i fail-closed
  filtr widoczności, przez który rola Finanse i tak by tych wpisów nie zobaczyła.
- **Powtórka co 7 dni jest NOWYM wierszem**, nie aktualizacją — raport ma pokazywać, ile
  tygodni sprawa czekała. Numer okna wchodzi w `dedupe_key`; okno liczy się od daty
  PIERWSZEGO alertu tej sprawy, nie od poniedziałku (inaczej wszystkie alerty
  zsynchronizowałyby się w jeden dzień). Powtórki ustają po `handled` **albo** gdy warunek
  ustąpi. Wpisy nie są kasowane — log JEST raportem.
- **Uprawnienia cyklu życia są SZERSZE niż uprawnienia do stawek i to jest świadome.**
  `_ORDER_LIFECYCLE_ROLES` = admin + head_of_recruitment + delivery_lead (przypisany)
  + finance; `_has_md_line_management_role` (stawki) zostaje przy admin + DL. Dwie
  konsekwencje do zapamiętania: **HoR dostaje te akcje u WSZYSTKICH klientów** (przechodzi
  guardy globalnie, bez przypisania), a **rola `finance` widzi tu nazwiska konsultantów**,
  od czego repo konsekwentnie ją odcina. Test `test_rate_gate_did_not_leak_to_lifecycle_roles`
  broni granicy przed „uproszczeniem" obu list do jednej.
  **Uwaga:** `finance` nie ma dziś ŻADNEGO wejścia nawigacyjnego do modułu Klienci
  (`nav.clients` = role operacyjne), więc w praktyce przyciski klikną admin, HoR
  i przypisany DL. Otwarcie modułu dla Finansów to osobna zmiana RBAC.
- **Kontraktor bez zamówienia w widoku jednoosobowym** ma teraz edytowalne numer, okres
  i obie stawki; pierwszy zapis zakłada szkic `ClientOrder`. To była przyczyna zgłoszenia
  „u Banku Pocztowego nie da się nic wpisać" — u Aliora pola działały wyłącznie dlatego,
  że jego zamówienia zostały kiedyś zaimportowane. Różnica DANYCH, nie konfiguracji.
- **Odczyt PDF ma DWIE polityki nadpisywania i nie wolno ich ujednolicać:** widok MD pyta
  „Tak/Nie" przy rozbieżności z ręcznym wpisem, widok jednoosobowy nadpisuje po cichu.
  Oba wymogi są w ticketach wprost. Wspólna warstwa: `lib/order-extraction.ts`.
- **Zamiana kontraktora DZIAŁA na zamówieniu kosztowym i nie rusza puli.** Guard był
  pisany wyłącznie pod tryb MD (`md_total is None` → 422), a linia kosztowa ma `md_total`
  puste **z definicji** — więc przycisk renderował się aktywny i gwarantowanie kończył się
  błędem „Linia nie ma budżetu MD do przeniesienia", czyli komunikatem o danych do
  uzupełnienia w stanie, którego nie da się usunąć. W trybie kosztowym nie ma czego
  przenosić: zmienia się osoba i jej stawki, a nowa linia dostaje **komplet NULL-i** w
  polach MD (`ck_client_orders_md_coherence` dopuszcza tylko wszystko albo nic).
  `settle_group` nie filtruje po statusie linii, więc domknięcie poprzednika **nie
  odsłania wydanych już pieniędzy** — dlatego zamiana nie wymaga przeliczenia budżetu.
  Przejście potwierdzone na produkcji end-to-end (Polkomtel, 2026-08-18, zamówienie
  testowe usunięte po weryfikacji): nowa linia ma komplet NULL-i w polach MD, poprzednik
  `completed` z datą zamiany, `budget_remaining` bez zmian, a wpis w historii brzmi
  „Zamiana kontraktora … (zamówienie kosztowe): … Kwota zamówienia zostaje wspólna dla
  całej grupy" — bez arytmetyki MD.
- **Weryfikując te ekrany przeglądarką: akcje destrukcyjne wołają natywny `window.confirm`,
  który ZAMRAŻA automatyzację.** `Input.dispatchMouseEvent` leci w timeout, screenshot
  zwraca „Script injection timed out", klawiatura nie pomaga (dialog jest poza stroną),
  a `navigate` co prawda odmraża kartę, ale **odrzuca** dialog, czyli akcja się nie
  wykonuje. Usuwanie/zakończenie testuj przez API (`fetch` z Bearer w zalogowanej karcie);
  przez interfejs weryfikuj to, co nie kończy się natywnym dialogiem.
- **Centrum e-Zdrowia a „kontraktor bez zamówienia":** `POST /orders` wymaga tam części
  umowy (`validate_project_part(..., require=True)`), a select renderował się wyłącznie
  przy istniejącym `activeOrder` — u TEGO klienta objaw „nie da się nic wpisać" przeżywał
  więc poprawkę T6, i to jako surowe 422. Teraz część umowy jest **polem, które zakłada
  szkic**: renderuje się bez zamówienia, a próba zapisu czegokolwiek innego bez niej
  odmawia po polsku, po stronie przeglądarki, zamiast lecieć po odpowiedź serwera.
- **`?tab=` na profilu klienta jest LOAD-BEARING.** Trzy źródła powiadomień linkują wprost
  do zakładki ze sprawą (`dl_alerts_scanner.py`, `dl_portal_expiry_scanner.py`,
  `pipeline.py` — wszystkie `/clients/{id}?tab=zamowienia`), a strona trzymała `useState`
  na stałe `"profil"` i parametru nie czytała. Kliknięcie powiadomienia lądowało na
  Profilu i kazało odbiorcy szukać samodzielnie.
  **Sam inicjalizator `useState` NIE wystarcza** — odpala się raz na cykl życia
  komponentu, a użytkownik już na `/clients/1` klikający powiadomienie do
  `/clients/1?tab=zamowienia` dostaje MIĘKKĄ nawigację App Routera: adres się zmienia,
  komponent się nie odmontowuje, stan zostaje. Dla Delivery Leada siedzącego na profilu
  klienta to scenariusz codzienny, nie brzegowy. Logika mieszka w
  `frontend/src/lib/client-tab.ts` (`useClientTab`) właśnie po to, żeby dała się
  przetestować bez montowania całego ciężkiego profilu — efekt zależy od WARTOŚCI
  parametru, nie od tożsamości `searchParams`, więc ręczne kliknięcie w inną zakładkę
  nie jest cofane przy najbliższym renderze.
  **Klucze `?tab=` w backendzie muszą pochodzić z `client-tab.ts`** — pilnuje tego
  `tests/test_client_tab_links.py`. Do 10.09 alert nowego szkicu z maila linkował
  do `?tab=orders`, a alerty umów ramowych do `?tab=framework-contracts`; oba
  klucze nie istnieją, więc odbiorca lądował na Profilu.
- **Aktywacja na prodzie: `COST_ORDER_CLIENT_IDS=15` (Polkomtel) USTAWIONE 2026-08-18.**
  Nie panelem i nie po SSH (klucze martwe, hasła do panelu nie znamy) — workflow
  **„Coolify set env"** (`.github/workflows/coolify-set-env.yml`, `workflow_dispatch`);
  to jest droga do każdej przyszłej zmiany env na prodzie. Zweryfikowane na żywym API:
  `cost_orders_enabled` = `true` u Polkomtela i `false` u BIK/BNP, mimo że wszyscy trzej
  są wielo-konsultantowi. `DL_ALERTS_ENABLED` domyślnie `true` (wyłączenie kończy pętlę
  skanera PRZED nią, nie budzi procesu co 24 h).
  **Uwaga:** sama zmienna to połowa aktywacji — checkbox renderuje się dopiero, gdy
  `GET /api/clients/{id}` zwraca `cost_orders_enabled`. To pole było zaplanowane,
  udokumentowane i konsumowane przez front, a mimo to nigdy nie powstało (PR #1196);
  wyszło z odpytania produkcji, nie z zielonych testów.
  **Od 09.2026 `cost_orders_enabled` NIE bramkuje już UI** — typ kosztowy jest
  dostępny u każdego klienta (patrz „Okno „Nowe zamówienie"…"). Flaga zostaje jako
  informacja dla automatów (np. brak auto-szkicu po zatrudnieniu).

## Panel „Moi klienci" na dashboardzie Delivery Leada (09.2026, migracja 0310)

Sprawy zamówień i kontraktów klientów mają osobny kanał od „Moje zadania →
Powiadomienia". Widget „Moje zadania" na pulpicie **Delivery Leada**
(`recruitmentNotificationsOnly`) pyta `GET /api/notifications?exclude_section=delivery`
(filtr działa na listę **i** `unread_count`). Inne pulpity i dzwonek widzą
wszystko jak dotąd — nie mają panelu, a sekcja delivery obejmuje też podpisy
i zwroty sprzętu, dla których kart nie ma. Panel `MyClientsAlertsPanel` (`preset === "delivery-lead"`, zaraz pod
„Moje zadania") czyta `GET /api/dl-alerts/cards`. Migracja 0310 + lustro w `entrypoint.sh`.

- **Karta = sprawa = `dl_alerts.event_key`** (`{typ}:{encja}:{odbiorca}`,
  `dedupe_key` bez okna). Powtórki zostają osobnymi wierszami (raport), serwer
  składa je w kartę (priorytet = najwyższy w sprawie). `POST /{id}/handled`
  zamyka **wszystkie** otwarte wiersze sprawy i pisze `Activity`
  `dl_alert_handled` na zamówieniu/grupie/kontrakcie/dokumencie.
- **`stage` w `emit`** nazywa próg (`t14`, `t7`, `high`) zamiast numeru tygodnia;
  bez `stage` klucz zostaje numeryczny jak dotąd (stare klucze się nie zmieniają).
  `email=True` → `payload.email`, wysyła `send_pending_alert_emails` PO commicie
  skanu (claim + stempel jak w `job_deadline_alerts`, ponowne sprawdzenie odbiorcy).
- **`status='resolved'`** = przyczyna ustąpiła (przedłużenie, uzupełniony szkic,
  zweryfikowany mail) — `handled_by_user_id` pusty, to NIE odhaczenie DL. Każda
  reguła stanowa kończy się `resolve_stale(live_event_keys)`; `entity_prefix`
  zawęża, gdy typ ma kilka ścieżek emisji (`order:` vs `mail-draft:`). Resolve
  kończy EPIZOD wspólnym stemplem `episode_closed_at` na WSZYSTKICH wierszach
  sprawy — także odhaczonych. Bez stempla na odhaczonych sprawa odhaczona raz
  (np. pula MD) nie alarmowałaby już nigdy, nawet po uzupełnieniu i ponownym
  spadku. Powrót warunku alarmuje z prefiksem `e{n}` w kluczu (bez tego
  `ON CONFLICT` zdusiłby pierwsze przypomnienie). `_episode_state` porównuje
  stemple, nie `created_at` (dwa zegary). Odhaczenie blokuje sprawę do końca
  epizodu — **także etapy t14/t7/high** (ticket: „zatrzymuje dalsze
  przypomnienia"). Karta mail-review zamyka się od razu przy apply/dismiss.
- **Cykl datowy** (`date_cycle_stage`): okno 30 dni z ZAKRESU dat, nie równości
  (dzień bez skanera nie gubi progu) → **pierwszy wiersz sprawy = mail** → co 7
  dni bez maila → T-14 mail → T-7 high + mail.
  Encja niesie datę końca (`order:{id}:end:{data}`), więc przedłużenie = nowy cykl.
  Dotyczy zamówień okresowych (`order_group_id IS NULL`), umów ramowych
  i kontraktów (kontrakt, którego zamówienie okresowe kończy się tego samego
  dnia, nie dostaje drugiej karty).
- **Klienci z rozszerzonymi alertami zamówień: `EXTENDED_ORDER_ALERT_CLIENT_IDS`**
  (CSV, fail-closed, dziś BNP — `services/order_alert_policy.py`). Jedna lista,
  DWA niezależne sygnały o tym samym zamówieniu, nigdy łączone w jedną kartę
  (ticket 09.2026):
  1. **`rule_periodic_order_ending` obejmuje u nich także LINIE zamówień
     wielo-konsultantowych** (`or_(order_group_id IS NULL, client_id IN …)`
     + wymóg `ClientOrderGroup.status == active`). U pozostałych klientów te
     linie zostają pominięte, bo tam zamówienie kończy wyczerpanie budżetu, nie
     kalendarz. Dzwonek (`_scan_orders`) widział je od zawsze — linia dziedziczy
     `end_date` grupy — ale daje jeden sygnał na próg; maila przy pierwszym
     wierszu i powtórkę co 7 dni ma wyłącznie karta w panelu.
  2. **`md_base_usage_high`** — zużycie PODSTAWY MD (`md_total`) ≥
     `DL_ALERT_MD_BASE_USAGE_PERCENT` (80%), per konsultant. Zakres opcjonalny
     NIE wchodzi ani do licznika, ani do mianownika. Zużycie liczone z SUMY
     ZEJŚĆ (`client_order_md_consumptions`), nie z `md_remaining` — ta niesie też
     `md_manual_adjustment`, czyli korektę BUDŻETU, więc wyprowadzenie z niej
     przesunęłoby próg. Podział podstawa/opcja przez `split_md_usage` (te same
     liczby co paski `MdScopeBars`). **Bez eskalacji i bez maila** — wysoki
     priorytet ma `md_budget_low`; w paśmie, gdzie oba warunki są spełnione, DL
     widzi dwie karty i to jest zamierzone.
- **`DL_ALERT_MD_THRESHOLD=21` zostaje GLOBALNY i bezwzględny** — `md_base_usage_high`
  go nie zastępuje ani nie konfiguruje per klient. „Mało MD" ma znaczyć to samo
  w każdym raporcie (pilnuje `test_md_threshold_is_global_not_per_client`);
  próg procentowy to OSOBNY typ alertu i osobna karta, nie wariant tamtego.
- **Pusta lista = zero zmian dla wszystkich.** `client_id.in_(frozenset())` daje
  `IN ()` = fałsz, a `rule_md_base_usage_high` kończy się przed zapytaniem.
  Aktywacja na prodzie = jedna zmienna przez workflow „Coolify set env"; id
  ustala się NA PRODUKCJI (`/api/admin/client-mixups`), bo „BNP" to RODZINA
  rekordów klienta (oddział vs bank vs Cardif) i zaszycie `12` na ślepo mogłoby
  włączyć alerty złej spółce.
- **Miesięczne uprzedzenie mailem to `email_on_first` w `emit`, NIE etap `t30`**
  (09.2026, decyzja Artura: mail + dzwonek, progi 14/7 zostają). Mail idzie przy
  pierwszym wierszu sprawy — `first_seen is None`, liczone PER ODBIORCA, więc
  nowy DL przypisany w połowie okna dostaje swój pierwszy mail, a pozostali nie
  dostają drugiego. Osobny etap `t30` zjadłby powtórki tygodniowe w paśmie
  30→15 dni (etap i numer okna to ta sama pozycja `dedupe_key`), wysłałby zaraz
  po wdrożeniu mail każdej sprawie już wiszącej w oknie i **nie objąłby
  zamówienia wpisanego 20 dni przed końcem** — próg 30-dniowy już by minął.
  `date_cycle_stage` zostaje nietknięte.
- **Dzwonek (`dl_portal_expiry_scanner`) liczy progi z ZAKRESU, nie z równości**
  (09.2026). Do tej zmiany pytał `end_date == today + N` dla `N ∈ (30, 14, 7)`,
  więc jeden dzień bez biegu — albo zamówienie wpisane/przedłużone na mniej niż
  30 dni — gubił próg 30-dniowy BEZPOWROTNIE i pierwszy dzwonek wypadał na 14
  dni. Teraz `_threshold_bucket(days_left)` wybiera najciaśniejszy pasujący próg
  (jeden na encję na bieg), dedup po `_end_phrase` zostaje bez zmian, a zegar to
  `business_today()` jak w `_promote_statuses` (koniec rozjazdu UTC/Warszawa).
  Tytuł niesie FAKTYCZNĄ liczbę dni (`_lead_phrase`), bo próg 30 bywa wysłany
  przy 22 dniach; `message` nietknięty — to on jest kluczem dedupu.
  `contract_alerts` (90/60/30/14/7 na kontraktach) bez zmian.
- **MD** start `DL_ALERT_MD_THRESHOLD=21` (`<=`), **kosztowe** start
  `DL_ALERT_COST_BUDGET_THRESHOLD=10000` (treść bez kwot — panel widzą też
  hybrydy bez finansów). Wysoki priorytet + mail: pozostałość ≤ tempo ×
  `DL_ALERT_HIGH_PRIORITY_WORKDAYS` (7). Tempo liczy czysty
  `services/order_burn_rate.py`: suma miesięcznych raportów (MD albo
  `invoice_amount`) ÷ dni robocze (polskie święta) od startu zamówienia do końca
  ostatniego raportowanego miesiąca. MD bez raportów = szacunek 1 MD/dzień na
  osobę; kosztowe bez faktur = brak etapu `high`.
- **Nowy kontraktor**: `_ensure_open_order` (ścieżka podpisu z Generatora) emituje
  `new_contractor_draft` w savepoincie, fail-soft; skaner powtarza, dopóki brakuje
  stawki przychodowej / okresu / numeru (tytuł-zaślepka albo „Imię — rekrutacja").
  Takie szkice są WYŁĄCZONE z `draft_consultant_unassigned` (jedna karta, nie dwie).
- **`notify_review`** bierze odbiorców z `dl_user_ids_for_client` (rola + sekcja
  Delivery; wcześniej surowe przypisania), fallback admini zostaje; treść niesie
  klienta i osoby z odczytu.
- **Deep linki**: `?order=` (linia grupy → jej grupa, zamówienie okresowe → karta
  kontraktora, szkic → od razu „Uzupełnij zamówienie"), `?group=`, `?framework=`.
  Rozwiązuje `resolveOrderFocus` (`lib/client-order-list.ts`); zakładka zdejmuje
  filtry, przewija i podświetla, potem strona usuwa parametry z adresu. Cel
  niewidoczny = toast, nigdy cisza.
- **Harness `/preview/dl-alerts`** renderuje panel z `refetchIntervalMs={false}`
  i cache z `updatedAt` w przyszłości — zero zapytań (401 przerzuciłby na /login).
  Checkbox w harnessie woła API — nie klikaj go w podglądzie.

## Decyzja Delivery Leada po zakończeniu współpracy konsultanta MD

Terminacja kontraktu domyka linię MD (`completed`, `end_date` ucięta do dnia
terminacji) i zakłada sprawę `client_order_offboarding_cases` w stanie
`pending`. Rozstrzygnięcie ma TRZY wartości (migracja `0253`, + lustro DDL
w `entrypoint.sh` — CREATE TABLE dotyczy tylko instalacji od zera, więc
poszerzenie CHECK-a na prodzie WYMAGA jawnego DROP+ADD):

| Decyzja | Co robi z pulą | Co robi z linią |
|---|---|---|
| `remove` | pula per linia przepada (`_reduce_legacy_md_budget`) | osoba znika z aktywnej obsady |
| `transfer` | pula przeliczona na innego konsultanta | jw. + budżet rośnie odbiorcy |
| `restore` | **pula NIETKNIĘTA** | linia wraca na `active`, kontrakt wraca do aktywnych |

- **`restore` powstał, bo bez niego jedynym wyjściem ze sprawy było zapisanie
  decyzji, która się nie wydarzyła.** Zgłoszone przypadki (Płonka 90 MD, Dynek
  120 MD, Krawczyk 85 MD) to współpraca, która trwa dalej — ani nie oddano
  puli, ani jej nikomu nie przekazano.
- **Gałąź `restore` MUSI omijać `_reduce_legacy_md_budget`.** Zdjęcie
  niewykorzystanych MD z wartości zamówienia byłoby zapisaniem faktu, który się
  nie wydarzył, i zabraniem konsultantowi budżetu, na którym właśnie pracuje.
- **Przywrócenie wskrzesza KONTRAKT** (`sync_contract_to_live_order`). Bez tego
  decyzja kasuje samą siebie: konsultant zostaje w „Zakończonych" mimo aktywnej
  linii, a nocny cron widzi `end_date < today`, stawia `ended` i domyka linię
  z powrotem — bez nowej sprawy i bez alertu, bo `_ensure_md_case` trafia
  w istniejący wiersz.
- **Data zakończenia jest DECYZJĄ, nie odtworzeniem.** Oryginalna `end_date`
  linii przepadła przy offboardingu (sprawa snapshotuje pulę, stawki i numer
  zamówienia — nie okres), więc serwer nie ma jej skąd wziąć. Przy zamówieniu
  z datą końca pole jest WYMAGANE i ograniczone do okresu zamówienia; przy
  bezterminowym puste znaczy „bezterminowo". Data z przeszłości jest odrzucana:
  linia ze WSPÓLNEJ puli ma `md_total IS NULL`, więc nie chroni jej
  `sync_md_line_status`, a `dl_portal_expiry_scanner._promote_statuses` domyka
  dokładnie takie linie.
- **Osobny typ zdarzenia `przywrocenie_konsultanta`**, świadomie różny od
  `przywrocenie` (= przywrócenie CAŁEGO zamówienia, `reopen_order_group`).
  Wspólny slug zlałby w historii dwie operacje na dwóch różnych poziomach.
- **Osobny CHECK `ck_..._restore_target`**: dwa istniejące guardy używają
  `IS DISTINCT FROM`, więc trzecia wartość omijała OBA i mogłaby nieść
  `target_order_id`/`rate_basis` bez żadnego ograniczenia.

## Zapis zamówienia: „Network Error" znaczy nieobsłużone 500

`UnhandledErrorMiddleware` (`app/main.py`) jest dodane jako PIERWSZE, czyli
NAJGŁĘBIEJ w stosie — pod `CORSMiddleware`. Bez niego wyjątek z handlera leci
ponad całym stosem do starlette'owego `ServerErrorMiddleware`, które odpowiada
gołym 500 bez `Access-Control-Allow-Origin`; przeglądarka blokuje odpowiedź
i użytkownik widzi wyłącznie „Network Error" — bez statusu, bez treści, bez
śladu w zgłoszeniu. Kolejność `add_middleware` jest tu load-bearing.

Warstwa wyżej: `commit_order_write` (`services/order_write_errors.py`) zamienia
znane naruszenia więzów modułu zamówień na 409 z komunikatem po polsku.
Dopisując CHECK w migracji, dopisz tam zdanie — inaczej operator dostanie
komunikat ogólny i nie będzie wiedział, którego pola dotyczy.

Cztery odtworzone ścieżki, które kończyły się „Network Error" (wszystkie
naprawione, każda ma test w `test_order_write_unhandled_500.py`):
`POST /orders` z `md_quantity` (brak `md_remaining` → CHECK; regresja
PR #1276), nazwa pliku PDF > 255 znaków, nieistniejące `job_id` /
`framework_contract_id` w PATCH, przepełnienie `Numeric(12,3)` przy
relabelingu stawek w materializerze.

## Aktywacja umowy: `end_date` NIE jest wymagane (umowa bezterminowa)

`ACTIVATION_REQUIRED_FIELDS` (`contract_service.py`) to `start_date`,
`rate_candidate`, `rate_client`, `contract_type` — **bez daty
zakończenia**. Umowa bezterminowa jest w body-leasingu normalnym stanem
docelowym, a nie brakiem danych: rejestr renderuje ją jako „bezterminowo”,
`_status_after_end_date_change` leczy z niej `ended`/`ending` na `active`,
a `ending_soon_clause` jej nie łapie. Wymaganie daty w bramce dawało **stan
bez wyjścia** — taka umowa nie wychodziła z Draftu żadną ścieżką (objaw: 409
przy każdym zapisie na „Aktywny”). PR #1260 obszedł skutek w UI; ten PR usunął
przyczynę. Lustro po stronie zamówień: `_order_has_required_activation_data`.

- **Bramka rozpoznaje stawkę z HARMONOGRAMU**, nie tylko z kolumny cache’u
  (`_has_activation_value` + `inspect(..., raiseerr=False)`, bo woła się ją
  także na wierszach bez eager-loadowanych relacji — inaczej `MissingGreenlet`).
- **W `PATCH /api/contracts/{id}` harmonogramy są wyprowadzane PRZED przejściem
  stanu.** `POST` zawsze miał tę kolejność; `PATCH` ją odwracał, więc bramka
  oglądała pustą kolumnę i odmawiała `missing: rate_candidate` dla stawki
  przysłanej w tym samym żądaniu.
- **„Kończący się” WYMAGA daty końca** (409 `ending_requires_end_date`) — bez
  niej `_status_after_end_date_change` i nocny cron cofają status na `active`,
  więc zapis zwracałby 200 i nie robił nic. Odmowa idzie PO pełnej liście
  braków, żeby nie odsyłać operatora po kolejną odmowę.
- FE ma trzy lustra tej bramki: `DraftCompletionModal`, walidacja „Nowy
  kontrakt” i `extractErrorMsg` (`CONTRACT_FIELD_LABELS`).

## Przedłużenie zamówienia wskrzesza zakończony kontrakt

`POST /clients/{id}/orders` to TRZECIA ścieżka przedłużania współpracy i do
sierpnia 2026 jedyna, która nie dotykała statusu kontraktu (aneks
i `/bulk-extend` wołają `reopen_contract`). Skutek: przedłużenie dodane
kontraktorowi z zakładki „Zakończeni” zostawiało go tam, bo pigułki czytają
`contract_status` — i razem z pigułką milczały MRR, rejestr umów i skaner
wygasania.

Reguła żyje w `contract_lifecycle.sync_contract_to_live_order` i zależy
WYŁĄCZNIE od dat, nie od zakładki: zamówienie obejmujące dziś (`start <= dziś`
i `end IS NULL OR end >= dziś`) wskrzesza kontrakt, przyszłe nie zmienia nic,
`draft`/`cancelled` nie liczą się wcale. **Wskrzeszony kontrakt jest
BEZTERMINOWY** (od 09.2026; do tego czasu dostawał datę końca zamówienia,
a gdy jej okres mijał, cron kończył umowę ponownie — patrz sekcja o zakładce
„Zakończeni"). Nocny `_promote_statuses` pomija `end_date IS NULL`, więc nie
demotuje go „tej samej nocy". Data z zamówienia ma swoje miejsce w „Końcu
zamówienia u klienta" (`client_order_end_date` — od 09.2026 okres zamówienia zawsze z najnowszego uzupełnionego zamówienia, patrz „Synchronizacja kontrakt ↔ zamówienia"). Historię
leczy migracja `0243` (reguła ogólna, zero ID w SQL-u).

**Każdy writer aktywnego zamówienia musi wołać tę samą regułę.** Po 0243
zostały pominięte: PATCH uzupełniający draft, import CSV Nordea oraz aktywne
linie grupowe (create/add/swap i materializacja `scheduled`). Skutek wrócił dla
Contract 327/order 285493 i Contract 165/order 285623. Runtime obsługuje teraz
wszystkie te ścieżki; migracja `0250` koryguje dwa jawnie wskazane rekordy po
pełnych kluczach biznesowych i zapisuje read-only audyt analogicznych przypadków
innych klientów w `app_settings['0250_live_order_contract_repair']`.

## Zakładka „Zakończeni" — decyduje umowa, nie okres zamówienia

Zgłoszenie (VeloBank, 09.2026): 11 osób miało to samo zamówienie do 31.08,
a po jego upływie do „Zakończonych" trafiły dokładnie te 4, którym umowa
miała wpisaną datę końca 30.06 — przepisaną przy zakładaniu kontraktu
z pierwszego okresu zamówienia, bez wypowiedzenia. Reszta (umowy
bezterminowe) została w „Aktywnych". Jedna reguła w trzech miejscach:

- **Zakładka czyta WYŁĄCZNIE umowę** (`contractClosed` w
  `lib/client-order-list.ts`, jedyne źródło pigułek dla obu rejestrów):
  „Zakończeni" = status końcowy ORAZ `contract_end_date < dziś`. Do daty
  końca włącznie osoba jest w „Aktywnych", od następnego dnia przechodzi
  sama (nocny cron `contract_alerts._promote_statuses`). Upływ okresu
  zamówienia nie przenosi nikogo — osoba zostaje w „Aktywnych" z dopiskiem
  **„Brak aktywnego zamówienia"** (`lacksCurrentOrder`: żadne zamówienie
  nie obejmuje dziś ani nie zaczyna się później).
- **Data końca umowy rządzi zamówieniem, nie odwrotnie.** PATCH daty końca
  w Kontraktach (`update_contract`) woła `_sync_client_orders_to_contract_end`
  (ten sam co `/terminate`): otwarte zamówienia dostają tę datę, zaczynające
  się później są anulowane, `completed` dopiero gdy dzień nadejdzie. Wyłącznie
  SKRACANIE — zamówienie to PO klienta, przedłużenie umowy go nie wydłuża;
  wyczyszczenie daty (bezterminowa) nie rusza zamówień.
  W drugą stronę zamówienie NIGDY nie ustawia daty końca umowy:
  `sync_contract_to_live_order` wskrzesza kontrakt jako bezterminowy.
- **Korekta danych (migracja `0274` + lustro w `entrypoint.sh`, SQL w
  `services/contract_ended_tab_repair.py`)**: wskazany w tickecie Contract 469
  (Piotr Klimczak, VeloBank) wraca na `active` po pełnych kluczach
  biznesowych; klasa „zakończona bez wypowiedzenia, a zamówienie trwało po
  dacie końca umowy" jest tylko AUDYTOWANA do `app_settings` — masowe
  wskrzeszenie wciągnęłoby do MRR osoby, które faktycznie odeszły
  (dwie z trzech u VeloBanku nie są na nowym zamówieniu).

## Umowa B2B jest bezterminowa, dopóki ktoś jej ręcznie nie zakończy (11.09.2026)

Data zakończenia umów B2B była przepisywana z końca ZAMÓWIENIA (pole
„Contract end" w oknie „Nowy kontraktor / zamówienie", aneks „Przedłuż",
scalanie duplikatów), a nocny cron kończył potem umowę, choć współpraca
trwała. Reguła ma jedno źródło: `app/services/b2b_contract_end_date.py`
(front: `lib/contract-end-date.ts`).

- **Umowa B2B w statusie innym niż „Zakończony"/„Anulowany" nie ma daty
  zakończenia, chyba że ktoś ją ręcznie zakończył** — `/terminate`
  („Zakończ współpracę": `terminated_at` + `termination_reason`, data także
  przyszła) albo aneksem `early_termination`. Umowy zlecenie i o pracę bez
  zmian — tam data końca jest częścią umowy.
- **API odmawia 422 (`reason: b2b_end_date_requires_termination`), nie
  zeruje po cichu:** tworzenie (`POST /contracts` — datę niesie tylko wpis
  umowy już zakończonej), edycja (`PATCH` — sprawdzana wyłącznie ZMIANA daty
  albo typu, więc zapis innego pola z nieruszaną datą przechodzi; status
  liczony wynikowy), aneks `extension`, `contract-with-order`
  (`contract_end_date` wycofane z formularza). `/bulk-extend` pomija takie
  umowy. Wyczyszczenie daty jest zawsze dozwolone.
- **Przywrócenie umowy B2B z „Zakończony"/„Kończący się" na „Aktywny"
  w rejestrze czyści datę** (jak wskrzeszenie zamówieniem) — ze starą datą
  cron kończyłby ją następnej nocy.
- **Scalanie duplikatów** (`contract_merge.merge_field_plan`) zostawia żywą
  umowę B2B bez wypowiedzenia bezterminową zamiast brać „najpóźniejszą datę".
- **„Kto i dlaczego" żyje w `termination_lessons`** (pole tekstowe dialogu
  „Zakończ współpracę", format „[Kto] — [Powód]"); `termination_reason` to
  słownik analityki odejść (inicjatywa konsultanta = rezygnacja). Karta
  „Zaplanowane zakończenie współpracy" na szczegółach kontraktu pokazuje je
  od chwili wypowiedzenia, nie dopiero w dniu końca (dyskryminator: umowa
  przywrócona ma `terminated_at`, ale `end_date IS NULL`).
- **Zakończenie z datą przyszłą NIE daje dziś statusu „Zakończony"** (P0.7):
  umowa pracuje do tej daty („Aktywny", w oknie 30 dni „Kończący się"),
  cron domyka ją dzień po dacie — inaczej osoba znikałaby z MRR przed czasem.
- **Jednorazowa korekta:** `app/services/b2b_end_date_repair.py`, blok
  w `entrypoint.sh`, marker `0307_b2b_indefinite_end_date` (paragon: liczby,
  ID, daty) + `repair_details_0307_…` (treść wpisów, poprzednie wartości —
  klucz innego kształtu, publiczny workflow `migration-receipts` go nie
  drukuje). Najpierw zakończenia osób ze zgłoszenia — **po trójkach
  ID (kontrakt, kandydat, klient), bez nazwisk w repo**; niezgodna trójka =
  pominięcie z kodem powodu. Potem każda umowa B2B „Aktywny"/„Kończący się"
  z datą i bez ręcznego zakończenia → bezterminowa („Kończący się" →
  „Aktywny"). Szkice świadomie poza korektą (wyczyszczona data wpuściłaby
  martwy szkic do MRR przy najbliższej aktywacji). Test
  `test_ticket_lists_all_sixteen_people…` trzyma CI na czerwono, dopóki
  lista nie jest kompletna — marker jest jednorazowy.

## Kontakt do konsultanta na umowie (09.2026, migracja 0320)

Karta „Informacje o kontrakcie" pokazuje e-mail i telefon konsultanta w jednym
wierszu pod „Typ kontraktu". Reguła kolejności źródeł ma JEDNO miejsce:
`services/contract_candidate_contact.py` (front renderuje gotowy wynik, nie
powtarza reguły).

- **`contracts.candidate_email` / `candidate_phone` to NADPISANIE, nie migawka.**
  Wartość trafia tam z „Danych Partnera" generatora B2B albo z ręcznej edycji
  w widoku kontraktu. Pusta kolumna znaczy „weź z profilu kandydata", a fallback
  liczy się przy ODCZYCIE — poprawiony w profilu telefon jest na umowie widoczny
  od razu. Materializacja profilu przy backfillu dałaby umowy z kontaktem
  starzejącym się w ciszy, dlatego korekta 0320 kopiuje **wyłącznie poziom
  pierwszy** (dane z generatora).
- **Wyczyszczenie pola przywraca fallback.** Pusty string i jawny `null` w PATCH
  normalizują się do `NULL` (`_normalize_candidate_contact_updates`). Gdyby pusty
  string zapisywał się dosłownie, „usunąłem wartość" znaczyłoby „zablokowałem
  profil na zawsze", a pusta komórka obok wypełnionego profilu czyta się jak
  utrata danych. Wartość dłuższa niż kolumna jest ODRZUCANA (422), nie przycinana
  — przycięty numer telefonu wygląda na poprawny.
- **Odpowiedź szczegółów niesie trzy pary pól** (`candidate_email`,
  `candidate_email_effective`, `candidate_email_source` i analogicznie telefon).
  Bez `*_source` nie da się oznaczyć „z profilu" ani wytłumaczyć, czemu
  wyczyszczone pole nadal coś pokazuje. Lista kontraktów tego nie dostaje.
- **Zapis na umowę jest FILL-ONLY na wszystkich ścieżkach**
  (`fill_candidate_contact` w `b2b_contract_automation`): podpis obustronny
  (`confirm-fully-signed`, także z `keep_existing_terms`) i `POST /render`, gdy
  para (kandydat, rekrutacja) ma DOKŁADNIE JEDEN nie-`void` kontrakt. Zero
  trafień albo więcej niż jedno = pominięcie: wpisanie kontaktu w zgadniętą
  umowę jest gorsze niż jego brak. Stempel z `/render` jest fail-soft — awaria
  nie może zabrać wygenerowanego DOCX-a.
- **Twarde usunięcie kandydata ZERUJE obie kolumny** (`api/candidates.py`, art. 17
  RODO). Wiersz umowy celowo zostaje (podpisy, faktury), ale kontakt do usuniętej
  osoby przeżyłby w ciszy — żaden ekran nie mówi, że umowa trzyma własną kopię.
- **Edycja w miejscu reużywa `InlineText`** z `components/orders/InlineOrderFields`;
  bramka to istniejące `canEditContract` (admin + DL + zapis sekcji Delivery) —
  to samo, co odsłania przycisk „Edytuj". Bez nowej capability.
- **Raport braków: `GET /api/contracts/candidate-contact-report`** (Admin, bez
  przycisku w UI — jak `order-sync-report`). 409 przed wykonaniem korekty. Do
  arkusza „Braki" trafia kontrakt, dla którego **rozstrzygnięty** e-mail lub
  telefon jest pusty, czyli ani umowa, ani profil nic nie dają — zapytanie
  o samą pustą kolumnę wysyłałoby zespół do przepisywania danych, które i tak
  widać. Paragon korekty (`0320_contract_candidate_contact`) niesie liczniki
  i ID; wartości (PII) leżą pod `repair_details_…`, którego publiczny
  `show_migration_receipts` nie wydrukuje.
- **`render_payload` starych dokumentów zostaje nietknięty** — korekta go czyta,
  nie czyści. Kontakt w podpisanym dokumencie jest zapisem tego, co strony
  podpisały.

## Data rozpoczęcia umowy ≠ start zamówienia (korekta 21.09.2026)

`contracts.start_date` to dzień, od którego obowiązuje UMOWA z konsultantem —
nie początek bieżącego zamówienia (ten żyje w `client_order_start_date`).
Import rejestrów 23–26.06.2026 wpisał w nią start zamówienia/zaślepkę (291
z 475 kontraktów błędnych); korekta z arkusza działu:
`services/contract_start_date_repair.py` + blok `repair-contract-start-dates`
w `entrypoint.sh` (marker `0334_contract_start_date_correction`, przypięta do
trójki ID i stanu z 21.09). Raport: `docs/contract-start-date-correction-completion-report.md`.

- **Żaden import ani automat nie wypełnia `start_date` okresem zamówienia**
  przy istniejącym kontrakcie. Zmierzone przed korektą: w 30 dziennych zrzutach
  nic poza ludźmi tej daty nie zmieniało — tak ma zostać.
- Formularz edycji odsyła datę przy KAŻDYM zapisie; dziennik „updated" niesie
  `previous_start_date` tylko przy realnej zmianie — po nim szukaj, kto zmienił datę.
- „Start date" w profilu klienta czyta `contracts.start_date` wprost; nie
  dokładaj tam drugiego źródła.

## Synchronizacja kontrakt ↔ zamówienia (09.2026, migracja 0304)

Zgłoszenie: kontrakt Bartosza Czapelki (Alior) stał jako „Szkic" (120 zł/h,
bez przychodu i okresu zamówienia), choć zamówienie OIT/0189/2026/ITVM miało
okres 15.09–31.12.2026 i 1340 PLN/MD. Serwis: `services/contract_order_sync.py`.
Każda strona jest źródłem prawdy dla SWOICH pól:

- **Podpis obustronny w Generatorze B2B = kontrakt AKTYWNY od razu**
  (`confirm-fully-signed` → `contract_lifecycle.activate_without_revenue_gate`,
  `source="b2b_signed_agreement"`): start z umowy → bezterminowo, stawka
  kosztowa godzinowa z umowy. Bramka kompletności wymaga obu stawek, a
  przychodowa przychodzi dopiero z zamówienia — dlatego osobne przejście
  z DWOMA dozwolonymi źródłami (drugie: jednorazowa korekta). Wymaga daty startu.
  Rusza też `ready_for_signature` (podpis obustronny zamyka tor QES).
- **Zamówienie → kontrakt** (każdy zapis zamówienia): z najnowszego
  „uzupełnionego" zamówienia (status ≠ cancelled, jest `start_date` I dodatnia
  stawka przychodowa — auto-szkic z podpisu ma start umowy i PUSTĄ stawkę, więc
  nie udaje okresu) kontrakt dostaje **okres zamówienia** w OSOBNYCH polach
  `client_order_start_date`/`client_order_end_date` (nigdy `start_date`/
  `end_date`; kolejne zamówienie nadpisuje poprzednie) oraz **stawkę
  przychodową** jako krok `client_rate_schedule` od daty startu zamówienia
  (`source_order_id` — krok z zamówienia vs krok ręczny/z aneksu; przyszła
  stawka obowiązuje od swojej daty). **Jednostka kontraktu = jednostka
  najnowszego zamówienia, ALE NIGDY MD** (`contract_unit_for_order`, ticket
  „Ujednolicenie stawek w module Kontrakty", 14.09.2026): zamówienie w MD daje
  kontrakt w zł/h (MD ÷ 8), ryczałt i stawka godzinowa przechodzą bez zmian.
  Przełączenie przelicza KAŻDĄ kwotę kontraktu (obie stawki + harmonogramy,
  ramowa, widełki) z precyzją 6 miejsc (`CONTRACT_RATE_SCALE`, kolumny
  `NUMERIC(16,6)` od 0309 — 1001,55 zł/MD = 125,19375 zł/h; zamówienia zostają
  przy 3 miejscach). Zamówienie w MD ustawia kontraktowi **176 h/mc** (22 MD ×
  8 h): czytniki pieniędzy liczą MD × 22, a godziny × `billing_hours_per_month`,
  więc MRR/marża miesięczna są takie jak przy dawnym kontrakcie w MD. Jawnie
  wybrana jednostka w PATCH (`follow_order_unit=False`) zostawia też godziny.
  **Zamówienie nie jest ruszane** — zostaje w MD, koszt wraca do niego ×8 bez
  zmiany kwoty. Wszystkie inne zapisy kontraktu też nie dają MD
  (`apply_contract_hourly_policy`): POST `/api/contracts`, `contract-with-order`
  i szkic z maila przeliczają kontrakt podany w MD; PATCH/aneks przejścia NA MD
  odmawiają 422 (`contract_rates_are_hourly`), a zapis kontraktu wciąż w MD
  przelicza go w całości. Formularze Kontraktów nie mają opcji „Dziennie".
  Jednorazowo `contract_hourly_rate_repair.py` (blok w `entrypoint.sh`, marker
  `0309_contract_hourly_rates`): każdy kontrakt `daily` → zł/h + 176 h/mc,
  kontrola odwrotności (×8 == dawna kwota) i miesięcznego ekwiwalentu, suma
  kontrolna `client_orders` przed/po (różnica = rollback); czeka na poszerzone
  kolumny, bez nich nie stawia markera. DDL 0309 zdejmuje i zakłada ponownie
  trigger walut `trg_contract_rate_currencies_legacy_sync` (ma `margin`
  w `UPDATE OF`, Postgres inaczej odmawia zmiany typu).
  Szkic z kompletem danych przechodzi na `active` przez zwykłą bramkę
  (`auto_activate_complete_draft`) — ale nie szkic, którego `end_date` minęło.
- **Kontrakt → zamówienie: stawka kosztowa.** Kontrakt jest JEDYNYM źródłem:
  ręczny koszt w zamówieniu przegrywa przy zapisie (UI: pole tylko do odczytu,
  „z kontraktu", gdy kontrakt ma stawkę). Zamówienie niesie jedną liczbę, więc
  dostaje stawkę z harmonogramu na „dziś przycięte do okresu zamówienia"
  (`cost_reference_day`), a przebieg dobowy (`run_daily_order_cost_sync` w cyklu
  `contract_alerts`) wprowadza każdą zaplanowaną podwyżkę w jej dniu. Zakończone
  i anulowane zamówienia są historią — nietknięte.
- **Linie zamówień zbiorczych MD/kosztowych (`order_group_id`) są POZA
  kierunkiem kosztowym — świadomie.** Ich stawkę kosztową prowadzi per linia DL
  (patrz „Zamówienia wielo-konsultantowe"), a kontrakty tych osób bywają szkicami
  z obsady bez stawki albo ze stawką sprzed lat — nadpisanie przestawiłoby
  rozliczenia BIK/Polkomtela/BNP pierwszej nocy. Kierunek zamówienie → kontrakt
  (okres, przychód, jednostka) je obejmuje.
- **Hak jest JEDEN: `order_write_errors.commit_order_write`** (22 wywołania).
  Listener `after_flush` na `Session` zbiera `contract_id` ruszonych zamówień
  w `session.info`, a `sync_pending_order_contracts` synchronizuje je przed
  commitem — w savepoincie, fail-soft (awaria = log, zamówienie i tak zapisane).
  Writery spoza routerów wołają go jawnie: auto-zapis z maila
  (`order_mail_apply.apply_document`), import Nordea (`admin_import`). Nowy
  writer spoza tych ścieżek MUSI zrobić to samo.
- **Po synchronizacji `_refresh_expired` doczytuje TYLKO wygasłe atrybuty.**
  Sync zmienia zamówienie, które handler już `refresh`-ował, więc serwerowe
  `updated_at` wygasa → `MissingGreenlet` przy serializacji. `refresh` całego
  obiektu wygasiłby relacje (harmonogramy) — dlatego lista atrybutów.
- **PATCH kontraktu**: jawna `rate_unit`/waluta w tym zapisie wygrywa z
  zamówieniem (`follow_order_unit`/`follow_order_currency=False`); ręczna
  stawka przychodowa przy istniejącym harmonogramie dopisuje krok od dziś
  (`apply_manual_client_rate`) — ale TYLKO przy realnej zmianie, bo formularz
  wysyła całą stawkę także nieruszaną, a krok z niezmienioną wartością
  przykryłby późniejszą korektę w zamówieniu.
- **Cała synchronizacja czeka na marker jednorazowej korekty**
  (`sync_enabled`): padnięty blok w entrypoincie (loguje i idzie dalej) nie
  może pozwolić zapisom zamówień zatrzeć niezgodności przed migawką. Ścieżki
  kontraktu (PATCH, aneksy, `/bulk-extend`, `/bulk-mark-ended`, `/terminate`,
  potwierdzenie podpisu) wołają `resync_contract_safely` — savepoint + log;
  błąd projekcji nie cofa zapisu użytkownika. Przedłużenie/zakończenie MUSI
  resyncować: `_synced_client_order_end` wpisałby datę końca UMOWY w okres
  zamówienia.
- **Alert kontraktowy „koniec zamówienia u klienta" pomija okres prowadzony
  synchronizacją** (`client_order_start_date IS NOT NULL`) — o końcu zamówienia
  ostrzega już skaner zamówień; dwa alerty nie deduplikują się (inne encje).
- **Jednorazowo (`contract_order_sync_repair.py`, blok w `entrypoint.sh`,
  marker `0304_contract_order_sync_repair`)**: NAJPIERW migawka raportu zgodności
  zamówienie ↔ kontrakt (stan sprzed wdrożenia — potem sync by go zatarł), POTEM
  szkice: zwykły → `active` (z okresem i przychodem, gdy osoba ma uzupełnione
  zamówienie); minione `end_date` + trwające zamówienie → bezterminowy
  `active` (aktywny z minioną datą zakończyłby cron razem z zamówieniami
  i sprawami offboardingu MD); minione bez zamówienia → `ended` bez
  offboardingu; **duplikat żywego kontraktu tej osoby u klienta → ZOSTAJE
  szkicem** (aktywny podwoiłby MRR; decyzja w raporcie). Przebieg dobowy kosztów
  rusza dopiero po markerze i odświeża też cache `rate_client` kontraktów,
  którym wszedł krok (formularz odsyła kolumnę). Excel:
  `GET /api/contracts/order-sync-report` (Admin, bez przycisku w UI) — arkusze
  „Przed wdrożeniem", „Poprawione szkice", „Stan bieżący".

## Polityki odczytu PDF per klient — jeden wzorzec, bramka per klient

Każda polityka jest DETERMINISTYCZNA i stosowana PO odpowiedzi LLM (model
wybiera interpretację, nie stosuje reguł), bramkowana CSV `client_id` z env,
fail-closed:

| Klient | Env | Reguła |
|---|---|---|
| Nordea | `NORDEA_ORDER_NUMBER_CLIENT_IDS` | numer tylko z „Call Off Agreement number”; zawsze netto/h bez ÷1,23; Quantity/MD ignorowane; summary pomijane przed modelem i planem |
| Bank Pocztowy | `BANK_POCZTOWY_ORDER_EXTRACTION_CLIENT_IDS` | numer pisma; netto MD ÷ 8 (w górę) |
| Credit Agricole | `CREDIT_AGRICOLE_ORDER_EXTRACTION_CLIENT_IDS` | stawka tylko z „Wynagrodzenie za 1MD (8h)”, MD tylko z „Szacowana ilość MD” |
| BNP | `BNP_ORDER_EXTRACTION_CLIENT_IDS` | dokument JEDNOOSOBOWY; „Cena netto” → stawka za 1 MD, „Szt.” → liczba MD, „MM-RRRR do MM-RRRR” → pierwszy/ostatni dzień miesiąca |
| Erste Bank Polska | `ERSTE_GROSS_RATE_CLIENT_IDS` | brutto ÷ 1,23 → netto (half-up, 2 miejsca) |
| Orlen | `ORLEN_ORDER_EXTRACTION_CLIENT_IDS` (+ kanoniczne ID 35) | wspólna stawka on/off-site tej samej osoby; MD z PDF zawsze pomijane |
| PFRON | `PFRON_ORDER_EXTRACTION_CLIENT_IDS` (+ kanoniczne ID 122) | okres wyłącznie z jawnej daty końca usług; brutto → netto |
| BIK | `BIK_ORDER_CLIENT_IDS` (+ kanoniczne ID 18) | numer/data z „Numer/data zamówienia” (start = data, koniec = bezterminowo); każda „Poz.” = osoba z własnym limitem MD („Ilość zamów.”, SZT) i stawką PLN/MD („Cena jednostk.”); wartości netto tylko do kontroli |
| Polkomtel | `POLKOMTEL_ORDER_EXTRACTION_CLIENT_IDS` (+ kanoniczne ID 15) | „Zlecenie wykonawcze": numer = skrót + numer po „nr" do ukośnika („SAP 4500123456"); start z „zawarte w dniu …", koniec zawsze bezterminowo; reguły działają WYŁĄCZNIE na dokumencie z nagłówkiem „ZLECENIE WYKONAWCZE nr" (inny szablon = odczyt ogólny + uwaga); tabela „Cena netto 1MD po upuście \| Cena total \| Konsultant" czytana jako STRUMIEŃ KOMÓREK (PDF: wiersz w linii, komórka scalona osobno; DOCX: komórka = linia, scalona powtórzona), kolejność kolumn z nagłówka (kotwicą „Cena netto", nagłówek osoby = całe słowo „Konsultant"); dwie kwoty w wierszu = stawka + kwota osoby TYLKO z dowodem (każdy wiersz ma parę, kwota osoby > stawki, suma = „na kwotę"), inaczej wiersz niepewny — nigdy zgadywanie; odczyt modelu jest drugim, niezależnym czytelnikiem (inna stawka tej osoby albo osoba spoza tabeli → do sprawdzenia); stawka zawsze netto za MD; „na kwotę …"/„Cena total" = kwota CAŁEGO zlecenia; MD: kolumna przy osobie albo jedna liczba („pracochłonność … MD"); brak MD w kosztowym = poprawny odczyt; `closes_on_md_exhaustion` |
| Cyfrowy Polsat | `CYFROWY_POLSAT_ORDER_EXTRACTION_CLIENT_IDS` (+ kanoniczne ID 38339) | wyłącznie numer tą samą regułą („CP 1234"); okres i stawki — odczyt ogólny (CP ma też zamówienia okresowe) |
| Alior | `ALIOR_ORDER_EXTRACTION_CLIENT_IDS` | tylko 4 pola: „Zamówienie nr:”, nazwisko z kolumny konsultanta, okres z nawiasu pod nazwiskiem (inaczej „Moment wejścia w życie” / „czas oznaczony”), stawka z „Razem stawka dla Banku” za MD; zawsze netto, jawne „brutto” w tabeli → weryfikacja bez ÷1,23; Roboczodni/Stawka bazowa/Marża/Total ignorowane |
| PKO BP | `PKO_BP_ORDER_EXTRACTION_CLIENT_IDS` | numer z „Zamówienie nr”; tabela Wykonawców: nazwisko WYŁĄCZNIE z kolumny osoby — profil jednoliniowy („Tester Middle”) pdfplumber wstawia w linię wiersza między nazwisko a daty i jest odcinany słownikiem słów profilu (granica niepewna = wiersz do sprawdzenia; nazwisko sklejone w odczycie modelu/zapisanym prostowane do tabeli przy „Przelicz plan”, `reapply_on_refresh`); okres z „Początek/Planowany Koniec Zaangażowania”; stawka z „Stawka PLN/MD netto” zawsze netto (bez ÷1,23 i bez pytania brutto/netto; „brutto” łącznej wartości nie ma wpływu), jawne „PLN/MD brutto” w nagłówku → weryfikacja; gwiazdka „stawka negocjowana” pomijana |

- **„Brak liczby MD" nie jest zastrzeżeniem ODCZYTU — o wymaganych polach decyduje
  typ zamówienia** (ticket Polkomtel 09.2026). Model czyta PDF bez wiedzy o typie
  i przy zamówieniu kosztowym zgłaszał „brak informacji o liczbie MD". Trzy warstwy:
  prompt v6 („MISSING MAN-DAYS" — brak MD nie jest niepewnością i nie zeruje stawki
  wiersza); `drop_md_absence_reasons` w obu endpointach formularzy (formularz sam wie,
  czy dla typu i wariantu MD czegoś brakuje; `md_scope` = `per_consultant` / `order`
  ustawia „Budżet MD na całe zamówienie"); bramka poczty zdejmuje takie powody tylko
  gdy są nieistotne dla typu, a MD bez liczby w ŻADNYM wariancie oraz wspólna pula
  przy kilku osobach idą do kolejki (automat nie dzieli puli). `is_md_absence_reason`
  NIGDY nie łapie powodu, który mówi też o stawce, kwocie, dacie, numerze, nazwisku
  albo sprzeczności.
- **BIK: tekst z SAP-a jest SKLEJONY** — pdfplumber oddaje
  „ProfilUR-JanKowalski”, „4500012345/20260903”, a etykieta „Numer/data”
  stoi linię nad adresem, nie nad wartością. Nazwisko jest kotwiczone na linii
  „Profil”, z myślnikiem albo bez (`_split_glued` rozcina granice mała→wielka
  litera); istniejąca linia „Profil” jest WIĄŻĄCA — nieczytelna nie przełącza
  na szukanie „dwóch wyrazów z wielkiej litery” gdzie indziej, bo opis pozycji
  („Rozwój Strumienia Detalicznego”) wygląda dokładnie jak imię i nazwisko.
  Niejednoznaczna osoba = puste `consultant_name` + powód z numerem pozycji →
  bramka maila odsyła do kolejki, writer odmawia założenia osoby bez nazwiska.
  „Termin dostawy” jest ignorowany (to po nim model zgadywał datę końca).
  Netto dowodzi nagłówek „Wart.netto”, a iloczyn ilość × cena ≠ wartość netto
  pozycji to powód do weryfikacji, nigdy korekta. Polityka ma trzy flagi
  rejestru: `open_ended_period` (bramka maila nie żąda daty końca, front
  dostaje `open_ended` i czyści pole „do”), `exposes_consultant_rows` (ręczny
  odczyt oddaje tabelę osób z limitem MD) i `closes_on_md_exhaustion`
  (patrz niżej). Kanoniczne ID 18 jest odpinane w testach autouse fixturą
  `_detach_bik_canonical_client` — serial `clients.id` inaczej zamienia
  osiemnastego klienta testowego w BIK.
- **BIK: zamówienie kończy wyczerpanie limitów MD WSZYSTKICH osób**
  (`services/order_md_exhaustion.py`). Linie MD kończyły się same już wcześniej,
  ale grupa zostawała `active` bez ani jednej aktywnej osoby. Teraz
  `recompute_remaining` (jedyny writer `md_remaining`, wołany przez import
  zużycia z Finansów) woła `sync_md_group_exhaustion`: grupa per osoba przechodzi
  na `completed` z `closure_reason` „Wszyscy konsultanci wyczerpali limit MD”
  i bez autora, gdy każda nieanulowana linia ma limit i `md_remaining <= 0`.
  Osoba bez limitu trzyma zamówienie otwarte. Świadomie `completed`, nie
  `exhausted` (ticket: „Zakończone”; `exhausted` = pula WSPÓLNA z własnymi
  alertami). Korekta przywracająca komuś MD wskrzesza grupę automatycznie —
  tylko zakończoną automatycznie; ręczne „Przywróć” takiej grupy daje 409
  z instrukcją. Siatka: dobowy skaner i `GET …/order-groups` (reconcile).
- **Nordea i Alior mają tabelę osób jako źródło prawdy** (`table_authoritative`
  w rejestrze): formularze czytają wszystkie osoby tak jak mail (parser
  all-rows, osobę wybiera polityka), a „Przelicz plan” stosuje regułę ponownie
  na zapisanym odczycie. U Aliora wiersz kotwiczy MARŻA (token z „%”), kwoty
  mają spację jako separator tysięcy, a nazwisko to słowa bloku wiersza bez
  słownika kompetencji. Model czyta osoby niezależnie: rozbieżność nazwiska,
  stawki albo okresu z tabelą idzie do weryfikacji — także PUSTA stawka/okres
  w odczycie modelu (prompt każe je zostawić puste, gdy model nie umie ich
  powiązać z osobą, więc brak to nie zgoda).
- **Alior porównuje tabelę z ZAPISANYM odczytem modelu** —
  `OrderExtraction.model_rows`, utrwalane w `order_mail_documents.extraction`
  i odtwarzane przez `restore_extraction`. Powody są budowane od zera przy
  każdym zastosowaniu. Bez tego „Przelicz plan” porównywałby tabelę z własnym
  wynikiem (`consultant_rows` po pierwszym zastosowaniu SĄ wierszami tabeli)
  i każda rozbieżność znikałaby po jednym kliknięciu. Zapis sprzed tej reguły
  nie ma `model_rows`; gdy dokument ma wiersze w starym kształcie
  (`_LEGACY_ROW_RE` — stara reguła mogła podstawić tabelę za odczyt modelu),
  nie potwierdza osób i idzie do człowieka. `model_rows` niesie kwoty, więc
  kolejka redaguje je jak `consultant_rows`.
- **U Aliora żadna pozycja nie znika po cichu**: osoba z odczytu modelu bez
  odczytanego wiersza w tabeli (druga pozycja tej samej osoby, wiersz
  w nietypowym układzie na kolejnej stronie) zostaje w wynikach jako niepewna.
  Pomijane jest wyłącznie powtórzenie z IDENTYCZNĄ stawką i okresem.
  Formularz z osobą (`target_consultant`) wybiera wiersz wspólnym ścisłym
  matcherem `_name_match_score` — nie „wszystkie człony w bloku”, bo
  „Anna Nowak” zawiera się w „Anna Nowak-Kowalska”.
- **Szkic, który niesie już zamówienie, nie jest nadpisywany dokumentem na
  rozłączny okres** (planer: `from_order_mail` z Activity `order_mail_*` albo
  `has_file`): Alior przysyła wrzesień i październik–grudzień osobnymi mailami,
  a szkic nie aktywuje się przed podpisem umowy. Ten sam numer albo nachodzący
  okres (korekta dokumentu) nadal uzupełnia ten sam szkic; szkic linii grupy
  zostaje przy `ACTION_GROUP` (osobne zamówienie obok linii MD rozdwoiłoby
  współpracę). Szkic wypełniony ręcznie bez pliku nadal jest „pusty” — znane
  ograniczenie, instrukcja każe dołączyć PDF.
- **Zmieniasz regułę klienta → PODBIJ `rule_version` w rejestrze.** Dokument
  zapamiętuje wersje reguł, którymi go przeczytano
  (`document_meta["rule_versions"]`) i stempluje je przy każdym przeliczeniu.
  Od 0316 wersja NIE jest już warunkiem przeliczenia — wstrzymany wpis wraca
  w każdym biegu (niżej) — ale stempel zostaje: mówi, którą regułą czytano
  zapisany odczyt. Wersja `None` = reguła bez wersjonowania.
- **Domniemanie netto bez reguły klienta** (`_document_marks_only_net`,
  UAT M07-B04): stawka bez oznaczenia przy kwocie jest netto tylko wtedy, gdy
  „netto” stoi przy etykiecie stawki/kwoty W TEJ SAMEJ LINII („Stawka netto
  za MD”, „kwota … PLN netto”), a dokument nigdzie nie mówi „brutto” ani
  o kwotach „z VAT”. Samo „Wartość netto razem” w podsumowaniu nie wystarcza —
  reguła działa też w bramce automatu poczty, więc luźniejsze dopasowanie
  zapisałoby stawkę z VAT jako pewną.
- **Erste stosuje się OSTATNIA** — przelicza kwotę ustaloną przez polityki
  wyżej. Odwrotna kolejność po cichu nie przeliczyłaby nic.
- **Credit Agricole odmawia zamiast zgadywać**, gdy obie etykiety stoją
  w jednym wierszu (nagłówek tabeli): bez wyrównania kolumn „pierwsza liczba
  za etykietą” trafia w liczbę porządkową. Zła stawka zapisana jako pewna jest
  gorsza niż puste pole — wychodzi dopiero na fakturze.
- **`total_value` NIE jest przeliczane** u Erste (ticket mówi o stawce).
- **BNP omija matcher konsultanta, i to jest cała jego istota.** PDF-y tego
  klienta NIE zawierają imienia ani nazwiska — niosą wyłącznie numer ID
  konsultanta. Generyczny matcher (`apply_consultant_row_match` +
  `enforce_consultant_policy_safety`) jest fail-closed po nazwisku, więc dla
  takiego dokumentu KAŻDY odczyt kończył się wyczyszczeniem stawki i liczby
  MD — to jest zgłoszona awaria, nie błąd modelu. Dla BNP parser dostaje sam
  tekst (bez `consultant_name`), a bramka bezpieczeństwa matchera jest
  pomijana; tożsamość rozstrzyga karta, z której operator uruchomił odczyt.
- **Odczytany numer ID NIE jest nigdzie zapisywany.** Nexus nie przechowuje
  identyfikatorów nadanych przez klienta (`candidates.external_id` to ID
  z Traffita, objęte unikalnością per źródło i nadpisywane przy każdym syncu),
  więc numer jedzie wyłącznie w odpowiedzi odczytu jako `consultant_ref` i
  służy WZROKOWEMU potwierdzeniu. Nie jest kwotą, więc przeżywa redakcję
  finansową — rola bez `VIEW_FINANCE` też musi wiedzieć, czyjego zamówienia
  dotyczy plik.
- **BNP jest klientem WIELO-KONSULTANTOWYM**, więc jego zamówienia obsługuje
  `ConsultantLineModal` / `OrderGroupFormModal` / `ExtendOrderGroupModal`, a nie
  widok jednoosobowy. Pole odczytu dołożone tylko do `EditOrderDialog` byłoby
  dla realnego użytkownika BNP MARTWE (ta sama pułapka co przy „Dwóch widokach
  zamówień” wyżej).
- **Brak etykiety u BNP NIE czyści pola** (inaczej niż w Credit Agricole).
  Tam kasowanie było odpowiedzią na udokumentowaną pomyłkę dwóch sąsiednich
  etykiet; tu takiego incydentu nie ma, a wyczyszczenie zostawiłoby operatora
  z pustym formularzem, czyli z tym, na co się skarży. Wartość modelu zostaje,
  ale zawsze z komunikatem „sprawdź”.
- **Dwie rzeczy w wyrażeniu ilości są obroną, nie kosmetyką**: `[^\S\n]*`
  zamiast `\s*` (zwykłe `\s*` przechodzi przez nową linię, więc kwota
  z wiersza wyżej sklejała się z „Szt.” z wiersza niżej i do liczby MD
  trafiała STAWKA) oraz brak spacji w klasie cyfr (separator tysięcy sklejał
  numer porządkowy z ilością: „1 105 szt.” → 1105 zamiast 105).

## Odczyt PDF w formularzu NOWEGO zamówienia

„Zczytaj dane z dokumentu" działa też w „Nowy kontraktor / zamówienie"
(`NewContractorOrderDialog`), dla KAŻDEGO klienta. Ten sam endpoint i te same
reguły klientowe co w „Uzupełnij zamówienie" — bez osobnej konfiguracji.

- **Klient wynika z profilu**, z którego formularz otwarto, i nigdy nie jest
  czytany z dokumentu: endpoint dostaje `clientId` z trasy.
- **Dwie polityki nadpisywania w jednym formularzu, obie świadome.** Odczyt
  AUTOMATYCZNY po wgraniu pliku uzupełnia wyłącznie PUSTE pola — formularz
  startuje pusty, więc jest to skrót, a nie kasowanie cudzej pracy. Przycisk
  „Zczytaj dane z dokumentu" NADPISUJE, bo to świadoma prośba o ponowny odczyt.
  Reguła repo „dodanie pliku samo z siebie nie zmienia pól" broni ręcznych
  wpisów i tutaj jest spełniona wariantem „tylko puste".
- **PDF zapisuje się DRUGIM żądaniem.** `contract-with-order` jest atomowym
  zapisem JSON, więc plik idzie po nim (`PUT …/orders/{id}/file`). Nieudany
  upload NIE cofa utworzonego kontraktu — mówimy o tym wprost w toaście,
  zamiast udawać, że nic się nie stało.
- **Stawka KOSZTOWA nie pochodzi z dokumentu.** PDF opisuje pozycję
  przychodową klienta; kwota, którą płacimy kontraktorowi, nie wynika z niego
  i zostaje do wpisania ręcznie.

### `client_policy` — brak reguł klientowych ma być WIDOCZNY

Odpowiedź odczytu niesie `client_policy`: nazwę zastosowanej reguły klientowej
albo `null`. To nie jest kosmetyka — bramki są fail-closed i sterowane env-em,
więc **niewłączona bramka nie daje żadnego objawu poza cichą zmianą wyniku**.
Zgłoszenie „Nordea nadal bierze numer z Frame Agreement" jest dokładnie tym
trybem awarii: odczyt „działa" (model coś wypełnia), a numer przychodzi
z niewłaściwego pola. Pusta nazwa jest w interfejsie zdaniem, a nie ciszą.

Uwaga na wording: brak reguł NIE znaczy „odczyt niedostępny" — odczyt ogólny
(sam model) działa u każdego klienta i pola wypełnia. Komunikat mówi więc
„nie ma jeszcze własnych reguł, sprawdź pola", bo tak jest naprawdę.

### Etykieta Nordei nie ma jednego zapisu

`Call Off` / `Call-Off` / `Calloff`, a po niej `number` / `no.` / `nr` / `#`
albo nic. Wąskie wyrażenie wypadało na każdym wariancie poza pierwszym, a
polityka jest fail-closed: nierozpoznana etykieta CZYŚCI numer. Przy
niewłączonej bramce zostawał wtedy numer wybrany przez model — czyli zwykle
`Frame Agreement number`, bo stoi w dokumencie wyżej i wygląda równie
oficjalnie (prompt dopuszcza „a similar document reference"). Test negatywny
`test_frame_agreement_number_never_becomes_the_order_number` pilnuje, że numer
UMOWY RAMOWEJ nigdy nie wygrywa — także wtedy, gdy stoi przed właściwą etykietą.

## Instrukcja zamówień w Pomocy — przestempluj po ZMIANIE LOGIKI ZAMÓWIEŃ

Pomoc → Procedury zawiera „Zamówienia — instrukcja dla Delivery Leada"
(`backend/app/data/procedures/zamowienia-instrukcja-delivery-lead.md`). Opisuje
ZACHOWANIE SYSTEMU — który przelicznik stosuje się u którego klienta, ile dni
przed końcem przyjdzie alert, co wypełni się samo z PDF-a. Taka treść psuje się
nie wtedy, gdy zmieni się proces w firmie, tylko wtedy, gdy ktoś zmieni parser
albo próg — a wtedy nikt nie ma powodu wchodzić do modułu Pomoc.

**Zmieniasz cokolwiek w logice zamówień → przejrzyj instrukcję i przestempluj:**

```bash
cd backend && python scripts/stamp_orders_procedure.py
```

`tests/test_orders_procedure_freshness.py` trzyma CI na czerwono, dopóki tego nie
zrobisz, i wypisuje po polsku, które pliki się zmieniły. Lista obserwowanych
plików (36 pozycji, backend + ekrany) siedzi w `app/data/procedures/__init__.py`.
Przegląd zakończony wnioskiem „ta zmiana nie dotyczy instrukcji" jest w pełni
poprawny i też kończy się przestemplowaniem — to nie jest obejście.

- **Treść jest w repo, nie tylko w bazie.** Jedno źródło (`.md`) czytają OBA
  kanały zasiewu: migracja `0254_orders_procedure_seed` i `_seed_repo_procedures`
  w `entrypoint.sh` (prod alembic bywa osierocony). Nie przepisuj treści do
  migracji — 40 KB w trzech miejscach rozjeżdża się przy pierwszej poprawce.
- **Zasiew jest UPSERT-em z warunkiem `procedures.updated_by IS NULL`.** Wdrożenie
  odświeża wiersz tak długo, jak nikt nie tknął go w aplikacji; edycja przez
  `PUT /api/procedures/{id}` stempluje autora i od tej chwili wiersz zostaje
  taki, jaki zapisał człowiek. Sama instrukcja mówi o tym czytelnikowi wprost.
- **Data w treści i w stemplu muszą być równe** — test to sprawdza, a skrypt
  ustawia obie naraz. Ta data jest jedynym sygnałem świeżości, jaki widzi
  Delivery Lead.
- **Spis treści w module Pomoc** powstaje z DOM-u (`lib/procedure-headings.ts`),
  nie z parsowania Markdownu — parser po naszej stronie musiałby powtórzyć
  zachowanie `react-markdown` co do joty, a każdy rozjazd to link prowadzący
  w złe miejsce. Harness wizualny: `/preview/procedure-help`.

## Finanse → Zmiany w zamówieniach
(Zmiany · Wejścia · Zejścia · Kończące się zamówienia · Braki, 0308)

Comiesięczny audyt zamówień dla działu finansowego (`/finance?view=order-changes`,
`GET /api/finance/order-changes?year&month&q&client_id&date_from&date_to`
+ `/export?…&tab=`, bramka sekcji Finance).
Decyzje Artura 14.09.2026: zmiany do miesiąca WPROWADZENIA; Brakiem nie jest
wypowiedziana umowa, szkic następnego zamówienia ani decyzja offboardingu MD /
„zostaw jako historię"; DL dostaje alert DL + dzwonek. Pełny opis:
`docs/finance-order-changes-completion-report.md`.

- **Zakładka nazywa się tak, jak to, co w niej jest (korekty 16.09 i 20.09.2026).**
  Do 16.09 Wejścia zbierały KAŻDE zamówienie startujące w miesiącu, a Zejścia
  pokazywały wiersze z werdyktem „Kontynuacja". Do 20.09 Wejścia nadal brały za
  nową osobę każdego, kto nie miał wcześniejszego WIERSZA ZAMÓWIENIA, a Zejścia
  mieszały „kończy się zamówienie" z „kończy się współpraca". Finanse czytają te
  listy jako „kto doszedł" i „kogo zdjąć z rozliczeń", więc obie kłamały.
  Stan docelowy: **Wejścia** = pierwsza współpraca (dowód: zamówienie ALBO
  umowa); **Zejścia** = zapisany koniec współpracy; **Kończące się zamówienia**
  = zamówienie bez kolejnego przy żywej współpracy; **Zmiany** = wszystko, co
  dzieje się w trwającej współpracy; **Braki** bez zmian.
- **Rejestr zamówień jest MŁODSZY niż współpraca, którą opisuje** — i to była
  przyczyna zgłoszenia z 09.2026 (konsultantka z umową bezterminową od grudnia,
  pierwszy wiersz zamówienia z września, w Wejściach jako „Nowy konsultant").
  Zmierzone na produkcji: z 63 zamówień startujących we wrześniu 2026 **38 ma
  umowę starszą niż własne zamówienie**, a 11 z nich nie miało ŻADNEGO
  wcześniejszego zamówienia. Dlatego `_classify_by_engagement` czyta
  `contracts` (bez `draft` i `void`) i dokłada szczebel tuż przed `new`.
  **Próg to pierwszy dzień MIESIĄCA, nie dzień startu zamówienia**: osobie
  faktycznie nowej zakłada się umowę razem z pierwszym zamówieniem, często
  z datą o kilka dni wcześniejszą, więc próg „ściśle przed startem" opróżniłby
  zakładkę (pilnuje tego
  `test_contract_starting_in_the_same_month_still_counts_as_an_entry`).
- **Klasyfikacja wejścia: `_classify_entries`, pierwsze trafienie wygrywa** —
  `additional_project` (trwające zamówienie u INNEGO klienta w dniu startu) →
  `order_continuation` (`previous_of`: poprzednie zamówienie u TEGO klienta
  ≤31 dni przed startem — reguła nietknięta) → `client_change` /
  `order_continuation` po kliencie OSTATNIEGO wcześniejszego zamówienia osoby
  (powrót po przerwie, przejście do innego klienta) → **ta sama drabinka na
  UMOWACH** (`_classify_by_engagement`) → `new` (jedyna klasa w Wejściach).
  Dowody z zamówień idą pierwsze, bo są dokładniejsze (niosą klienta, okres
  i numer). Wszystko poza `new` to wiersze syntetyczne w Zmianach, liczone przy
  odczycie — **bez migracji**: CHECK na `order_change_events.field` i dziennik
  zostają nietknięte. Zamówienie zaczynające się PÓŹNIEJ nie czyni z osoby „już
  współpracującej"; dwa zamówienia tego samego dnia u dwóch klientów rozstrzyga
  niższe `order_id` (`_precedes`), żeby osoba naprawdę nowa pokazała się
  w Wejściach raz, a nie zniknęła z nich całkiem.
- **Kontynuacja z UMOWY nie ma poprzedniego numeru zamówienia** — niesie
  `engagement_since` (data startu umowy) i obie warstwy renderują „współpraca
  od DD.MM.RRRR". Puste „—" czytałoby się jak utrata danych, nie jak inny
  rodzaj dowodu. `EntryClass` niesie pola PREZENTACYJNE
  (`running_client_names`, `previous_client_name`), nie surowe `OrderFact`y:
  dowodu z umowy nie da się w nie włożyć.
- **„Zmiana klienta" to konsultant przechodzący do innego klienta, nie zmiana
  pola.** `ClientOrderUpdate` nie ma `client_id` — zamówienia nie da się
  przepiąć z UI, więc literalna zmiana pola nie istnieje i nie ma czego
  zapisywać w dzienniku.
- **Zejście liczy się z FAKTÓW, nie z napisu werdyktu:** wiersz odpada, gdy
  `fact.works_until_md_exhausted or successor is not None`. Warunek stoi PRZED
  drabinką werdyktów, bo intencja zakończenia jest w niej sprawdzana pierwsza —
  rzadkie „wypowiedzenie + żywy następca" zostawałoby inaczej w Zejściach mimo
  tego, że osoba pracuje dalej. `ExitVerdict` nie ma już `continuation`, a
  `OrderExitItem` pól o następcy (zawsze puste).
- **Zejście wymaga ZAPISANEGO końca współpracy** (`load_ending_intents`,
  werdykt `ended_intent`). **Decyzja Artura 20.09.2026: wszystkie pięć rodzajów
  intencji zostaje w Zejściach** — wypowiedziana/zakończona umowa, zamiana
  kontraktora, decyzja DL po offboardingu MD, usunięcie z zamówienia,
  „zostaw jako historia". Wspólny mianownik: człowiek świadomie zapisał, że ta
  osoba schodzi. Nie zawężaj tego do samego `INTENT_CONTRACT_ENDED`.
  Zakres następcy per (osoba, klient) ZOSTAJE: przejście konsultanta do innego
  klienta JEST zejściem z punktu widzenia rozliczeń klienta A.
- **`ending_pending` i `no_successor` to „Kończące się zamówienia"** — osobna
  zakładka (`?sub=ending`, `?tab=ending`), ten sam `OrderExitItem` i ten sam
  render co Zejścia. Bliźniaczy typ różniący się wyłącznie nazwą byłby drugim
  miejscem do rozjechania; rozstrzyga WERDYKT. Wrzesień 2026 na produkcji: do
  87 zamówień kończących się przy żywej umowie stało w Zejściach obok ~13
  faktycznych zakończeń. `_exits` zwraca obie listy z JEDNEGO przebiegu — dwa
  osobne rozjechałyby się przy pierwszej poprawce drabinki i ta sama osoba
  potrafiłaby stać w obu zakładkach albo w żadnej.
- **Zmiany stawek NIE mają progu** — do Zmian trafia każda różnica stawki
  kosztowej i przychodowej. Jedyny filtr jest w `order_change_audit` (pierwsze
  wpisanie stawki to nie zmiana, szkice i anulowane się nie liczą).
- **Filtry (szukaj / klient / zakres dat) liczy SERWER, jedną funkcją
  `apply_filters` na gotowych listach** — ten sam kod obsługuje ekran
  i eksport, więc plik nie może pokazać czego innego niż lista. Data znaczy
  w każdej zakładce co innego (zmiana / start / koniec / dzień wykrycia braku),
  więc etykieta pola zmienia się z zakładką. Liczniki przy podzakładkach liczą
  się z długości list, czyli po filtrach — badge nie obiecuje wierszy, których
  pod nim nie ma. Wiersz BEZ daty nie mieści się w żadnym zakresie.
  `open_gaps_total` zostaje globalne (baner o całej historii).
- **Eksport bierze aktywną podzakładkę** (`?tab=`) z tymi samymi filtrami;
  `tab` pominięty = cały audyt (pięć arkuszy), zgodność wstecz. Tytuł
  arkusza musi zmieścić się w 31 znakach Excela — stąd „Kończące się zam.".
  `OrderChangesPanel` NIE odpytuje API sam — picker klienta wchodzi slotem
  `filters.clientPicker`, bo ten sam komponent renderuje publiczny harness
  `/preview/finance-order-changes`, który musi robić ZERO zapytań.
- **Pustka po filtrach ma własny komunikat** („Żaden wiersz nie pasuje do
  ustawionych filtrów") — pustka pod nagłówkiem miesiąca czyta się jak utrata
  danych. Odwrócony zakres dat nie jedzie do serwera (byłoby 422 w trakcie
  wpisywania drugiej daty), tylko wyświetla prośbę o poprawę.
- **Filtry żyją w adresie** (`q`, `client`, `clientName`, `from`, `to` obok
  `sub`/`month`); `ORDER_CHANGES_URL_KEYS` jest lustrem listy czyszczonej przy
  wyjściu z widoku w `app/finance/page.tsx`. Nazwa klienta jedzie obok id, żeby
  po odświeżeniu chip nie mówił „Klient: 18".

- **Stara wartość istnieje TYLKO w `order_change_events`.** Jedna zmiana na
  TRANSAKCJĘ (`services/order_change_audit.py`): `before_flush` zapamiętuje
  pierwszą starą wartość z `committed_state` (po flushu jest pusty;
  `get_history` zgłasza starą `None` jako brak historii, a `None → data` końca
  to zmiana), a wiersze powstają w `before_commit` jako różnica początek →
  koniec. Zapis per flush rejestrował stan pośredni: PATCH kosztu, który
  synchronizacja z umową cofa przed commitem, dawał dwie „zmiany" autora.
  Bez leniwego doczytywania (`MissingGreenlet`). Filtr szumu: pomija
  zamówienia, które na początku transakcji były szkicem/anulowane, i pierwsze
  wpisanie stawki. Linia grupy → `md_rate_*`; samodzielne → `rate_*` +
  `rate_unit` (tam `md_rate_revenue` to lustro, liczone raz). Historia
  zaczyna się od wdrożenia — widok mówi to wprost.
- **Autor = `session.info` stemplowane w `deps.get_authenticated_user`**
  (prawdziwe konto, nie podglądane). Zapis bez zalogowanej osoby (pętle,
  poczta, sync kosztu z umowy w tle) ma `source="system"`.
- **Jedna reguła następcy dla Zejść i Braków: `services/order_facts.py`.**
  Okres = `COALESCE(linia, grupa)`; następca = inne nieanulowane zamówienie tej
  samej OSOBY (`contracts.candidate_id`, nie kontrakt) u tego samego klienta,
  trwające po końcu (szkic się liczy; zakończone bez daty — nie). Świadomy
  koniec (`load_ending_intents`): umowa `ended`/`void` albo wypowiedziana
  z datą końca ≤ końca zamówienia, `predecessor_order_id` (zamiana),
  offboarding MD `remove`/`transfer`, zdarzenie `zakonczenie_konsultanta`
  z `removed_from_order`/`keep_history`.
- **Osoba z Zejść nie stoi w Brakach** (ticket 09.2026, filtr PRZY ODCZYCIE):
  `_gaps` pomija brak, którego zamówienie ma DZIŚ intencję zakończenia
  (`order_gaps.gap_orders_with_ending_intent` — ta sama `load_ending_intents`
  co Zejścia; typowo DL wypowiada umowę dopiero PO wykryciu braku), oraz brak
  współpracy (`sibling_key`) stojącej w Zejściach tego miesiąca. Wpis w bazie
  zostaje; `open_gaps_total` liczy bez takich wpisów, a `remind_open_gaps`
  zamyka ich karty DL (`handled_by_user_id` puste) zamiast przypominać.
- **Braki (`order_gaps`) nigdy nie są kasowane.** Wykrycie: pętla `order_gaps`
  (00:30 Warszawa + start), `detected_on = koniec + 1`, od
  `ORDER_GAP_TRACKING_START` (domyślnie 2026-08-01) i najwyżej
  `ORDER_GAP_LOOKBACK_DAYS` (45) wstecz — zamknięty miesiąc nie dostaje po
  tygodniach nowych braków. Następca utworzony do końca dnia wykrycia jest NA
  CZAS (decyzja 15.09.2026, UAT B69): brak nie powstaje, a brak założony rano
  i uzupełniony tego samego dnia zostaje w bazie, ale raport Finansów go nie
  pokazuje (`delay_days == 0`). Następca z kolejnego dnia = `filled_late`. **Aktywna linia MD z niewyczerpanym budżetem nie kończy
  się datą** (skaner wygasania też jej nie domyka) — nie jest brakiem, a
  w Zejściach ma werdykt „trwa do wyczerpania budżetu MD". Każdy brak w
  osobnym savepoincie (awaria powiadomienia nie cofa przebiegu). Dzwonek tylko
  dla braków sprzed ≤ 2 dni (pierwszy bieg po wdrożeniu nie zasypuje DL).
  Zamknięcie: `commit_order_write` ORAZ `order_mail_apply` wołają
  `refresh_order_gaps_safely` dla kontraktów ruszonych zamówień (savepoint,
  zawężenie w SQL) i oznaczają alerty DL `handled`. Kontrakt bez osoby jest
  współpracą sam w sobie (`sibling_key`). GET widoku niczego nie zapisuje.
- **Alert `order_missing_successor`** — lustro CHECK `ck_dl_alerts_type`
  w migracji, modelu i OBU definicjach w `entrypoint.sh`; powtórka co
  `DL_ALERT_REPEAT_DAYS` przez regułę w `dl_alerts_scanner`. Dzwonek:
  `NotificationType.order_missing_successor` (enum w `_ENUM_STATEMENTS`),
  jedno powiadomienie na brak. `DlAlertsSection` jest znowu montowana
  w `RoleDashboard` dla presetu `delivery-lead` (od #1304 nie była nigdzie).
- **Dodatkowy projekt** liczony przy odczycie: zamówienie startujące w miesiącu,
  gdy osoba ma w dniu startu trwające (nie szkic) zamówienie u INNEGO klienta.
- Harness wizualny (publiczny, zero zapytań): `/preview/finance-order-changes`.

## Audyt pomylonych klientów — `GET /api/admin/client-mixups`

Read-only raport (admin) rodzin klientów o wspólnym rdzeniu nazwy wraz z ich
kontraktami i umowami B2B; przy każdym wierszu NIP obu stron, klient
REKRUTACJI i flaga `job_client_mismatch`. Powstał po DWÓCH niezależnych
zgłoszeniach tej samej pomyłki (BNP Paribas Cardif ↔ CARDIF - ASSURANCES…).

- **Rodzinę wyznacza wspólny TOKEN nazwy, nie podciąg** — „BNP” jako podciąg
  wciąga „BNP Paribas Bank Polska”, odrębnego prawdziwego klienta.
- **Formy prawne odsiane** („SPÓŁKA AKCYJNA”, „ODDZIAŁ W POLSCE”), inaczej pół
  bazy to jedna rodzina. **`ł` trzeba transliterować ręcznie** — NFKD go nie
  rozkłada, więc „SPÓŁKA” tnie się na „spo” + „ka”.
- **Zero mutacji.** Podobna nazwa bywa naprawdę innym klientem; rozstrzyga
  człowiek. Uwaga: `ContractUpdate` NIE ma `client_id`, więc przepięcia
  kontraktu na innego klienta nie da się dziś zrobić z interfejsu w ogóle.

## Jednorazowe czyszczenie „Nieaktywnych klientów" (migracja 0303)

Admin w zakładce „Nieaktywni klienci" → **„Czyszczenie listy"**: podgląd
(tylko odczyt) → zgoda → wykonanie → raport. Trasy
`/api/clients/directory/inactive-cleanup` (+ `/preview`, `/execute`),
wszystkie `AdminUser`. Ocena: `services/inactive_client_cleanup.py` (czyta),
wykonanie i raport: `services/inactive_client_cleanup_run.py`. Pełny opis:
`docs/inactive-clients-cleanup-completion-report.md`.

- **Trzy werdykty.** Niepuste którekolwiek z 8 źródeł (rekrutacje aktywne/
  zamknięte, kontrakty `ended`, zamówienia wszystkich etapów + grupy +
  offboarding, kontrakty/umowy ramowe/B2B w dowolnym statusie,
  `clients.notes`, one-pagery + warunki umowy, przejścia pipeline'u i historia
  DynaReportera) → **zostaje bez zmian**. Osiem pustych, ale inne dane →
  **lista B** (wstrzymany, z opisem). Nic → **lista A** (usunięty trwale).
- **„Inne dane" NIE są listą ręczną** — każdy FK do `clients.id` jest czytany
  z `pg_catalog` w chwili uruchomienia, więc tabela dopisana w przyszłości nie
  zostanie cicho skaskadowana. Pomijane są tylko wpisy katalogu: zakres
  portfela, aliasy, wiersz audytu manifestu. Poza FK lista B łapie też:
  dziennik (`activities`) z akcją spoza technicznych (import manifestu,
  założenie, edycja, przesunięcie zakładki), zakres w innej zakładce, NDA,
  wskazanie klienta w env `*_CLIENT_IDS` i w stałych kodu (e-Zdrowie,
  Polkomtel, Wedel, Cyfrowy Polsat, kanoniczne ID polityk PDF), klienta
  zakładanego przy starcie („Ministerstwo Sprawiedliwości") oraz nazwę
  pasującą do wzorca zasiewu karty klienta (usunięcie duplikatu zmieniłoby
  licznik „dokładnie jeden" i następny start założyłby kartę komuś innemu).
  FK zadeklarowane w modelach, a nieobecne w bazie, są liczone mimo to.
- **Ślady PO NAZWIE** (`services/inactive_client_cleanup_signals.py`):
  `dr_clients` (DynaReporter ma WŁASNĄ tabelę klientów — MRR i placementy
  nie wskazują na `clients`), `dr_board_placement_clients`,
  `finance_monthly_results` i `b2b_generated_contracts` z pustym `client_id`
  (umowa wygenerowana bez rekrutacji) zatrzymują klienta; leady/oferty
  sprzedażowe DynaReportera → lista B. Klucz nazwy zdejmuje formy prawne —
  fałszywe trafienie może klienta tylko zatrzymać. Okres umowy przypięty do
  zakresu portfela (`contract_*_override`) liczy się jako umowa.
- **Pusta lista nie wykonuje niczego** (422) — inaczej zapis raportu bez
  usunięć zużyłby jednorazową operację przed rozstrzygnięciem listy B.
- **Usuwane jest wyłącznie przecięcie** listy zatwierdzonej w podglądzie
  z klientami, którzy w chwili wykonania NADAL się kwalifikują (blokada FOR
  UPDATE na wierszach klientów przed ponowną oceną). Kto zakwalifikował się po
  podglądzie, trafia na listę B — nikt go nie widział.
- **Jednorazowe:** UNIQUE(`client_cleanup_runs.kind`) + sprawdzenie pod
  blokadą doradczą → drugie wykonanie i podgląd po wykonaniu = 409. Nic
  w kodzie nie woła tego automatycznie.
- **Nagrobek jest load-bearing.** Faza `clients` syncu Traffita robi pełny
  skan co noc i upsertuje po `external_id`, więc bez `purged_clients` usunięty
  klient wracałby następnej nocy. `import_clients` pomija te id (`skipped`).
  `purged_clients.run_id` ma RESTRICT, nie CASCADE — skasowanie raportu nie
  może zdjąć nagrobków.
- **Manifest portfela:** usunięcie klienta zeruje (SET NULL) jego powiązanie
  w `client_import_rows`, a inwariant `get_client_portfolio_import_health`
  porównuje żywe zakresy z liczbą wierszy audytu. Stąd `purged_at` na wierszu
  (stawiany PRZED usunięciem) i `retained_audit_rows = audit_rows -
  purged_rows`. Bez tego każde usunięcie klienta z manifestu = `/api/health/
  deep` 503. Brak kolumny `purged_at` (lustro DDL przegrało blokadę) liczy
  się jako zero, nie wywraca `--apply-once` pod `set -e`.
- **Rollback zaaplikowanego manifestu jest po czyszczeniu niedostępny —
  świadomie.** Manifest ma wiersz audytu dla KAŻDEGO klienta (arkusz
  „NEXUS-only"), więc po usunięciu choćby jednego run ma wiersze `purged_at`
  i rollback odmawia (`rows_purged_by_inactive_client_cleanup`) zamiast
  przywracać stan klientów, których nie ma. Reconcile Traffita pokaże stały
  rozjazd liczby klientów o liczbę nagrobków (tylko raport).
- **Nowy manifest (nowy digest) odtworzyłby usuniętych klientów**, jeśli
  nadal ich wymienia — first-apply dopasowuje po nazwie i nie czyta nagrobków.
  Świadomie poza zakresem (to decyzja przy przygotowaniu nowego pliku).

## Usuwanie klienta z profilu + Historia zdarzeń (migracja 0307)

Przycisk **„Usuń klienta"** w profilu klienta (dowolny status) i ogólnosystemowa
sekcja **Ustawienia → Historia zdarzeń**. Kod: `api/client_deletion.py`,
`services/client_deletion.py`, `services/critical_events.py`,
`api/event_history.py`; front: `components/client-profile/DeleteClientDialog.tsx`,
`components/settings/EventHistoryTab.tsx`. Pełny opis:
`docs/client-deletion-event-history-completion-report.md`.

- **Uprawnienie jest IMIENNE, nie rolowe:** `users.can_delete_clients`
  (domyślnie `false` dla wszystkich). Macierz akcji RBAC daje administratorowi
  każdą akcję automatycznie, więc nie da się nią wyrazić „tylko te cztery
  osoby" z ticketu — dlatego osobna flaga, której **admin też nie ma**, dopóki
  ktoś jej nie zaznaczy w edycji użytkownika („Może usuwać klientów").
  Nadanie i odebranie trafia do Historii zdarzeń. Osoby z ticketu NIE są
  zaszyte w kodzie ani migracji (repo jest publiczne) — flagę nadaje admin
  w Ustawieniach → Administracja. W trybie „podgląd jako" usuwanie jest
  zablokowane (403), a przycisk ukryty.
- **Nadane uprawnienie działa od następnego załadowania aplikacji, nie od
  ponownego logowania** (16.09.2026). Profil siedzi w `nexus_user`
  w localStorage i do tej daty odświeżał go WYŁĄCZNIE login: cztery osoby
  z ticketu dostały flagę i nadal nie widziały przycisku. `AppShellV2` raz na
  załadowanie dociąga `GET /api/auth/me` i wpisuje go przez `syncUser`
  (`store/auth.ts`) — bez tokena (strony publiczne) i w trybie podglądu nie
  strzela, przy identycznym profilu nie zapisuje (nowa referencja
  przerenderowałaby cały shell), a innego `user.id` niż zapamiętany nie
  przyjmuje. Dotyczy tak samo roli i `allowed_sections`, w obie strony:
  odebrane uprawnienie też znika bez wylogowania.
- **Router bez bramki ZAPISU Delivery** (`DELIVERY_SECTION_DEPENDENCIES`),
  tylko odczyt Delivery: flagę może dostać np. osoba z Finansów, a Finanse
  mają Delivery do odczytu. Stary `DELETE /api/clients/{id}` z `clients.py`
  (admin, jedno żądanie, kaskada, bez nagrobka) usunięty — trasa żyje teraz
  w `client_deletion.py` i wymaga `?confirmation=0`.
- **Blokada twarda patrzy na FAKTY, nie na `clients.status`:** otwarte
  zamówienia okresowe (`draft`/`active`/`paused`, także przez kontrakt
  klienta), otwarte zamówienia MD/kosztowe (`draft`/`active`/`scheduled`),
  żywe kontrakty (`active`/`ending`/`ready_for_signature`) i kandydaci
  w niezamkniętych rekrutacjach. Szkic kontraktu bez zamówienia NIE blokuje
  (to nie pracujący kontraktor). **Linie zamówień MD/kosztowych są sprawdzane
  SAME, niezależnie od statusu grupy** — zamknięcie z datą w przyszłości daje
  grupę `completed` z liniami nadal `active`, wyczerpanie puli przestawia
  wyłącznie grupę, a osoba obsadzona z bazy ma kontrakt-szkic, więc blokada
  kontraktorów by jej nie złapała. Kliknięcie „Usuń klienta" to już próba —
  zablokowana trafia do Historii zdarzeń; wykonanie liczy ocenę od nowa pod
  `FOR UPDATE` na wierszu klienta i przy blokadzie zwraca 409 jako
  `JSONResponse` (NIE `HTTPException` — wyjątek wycofałby sesję razem z wpisem).
- **Pusty vs z historią = ta sama ocena co czyszczenie 0303**
  (`evaluate_candidates` + `load_client_candidates` — dowolna zakładka, zakres
  portfela w KAŻDEJ kategorii to wpis katalogu). Werdykt `delete` → trwale,
  przez `purge_client(run=None)` z nagrobkiem (`purged_clients.run_id` jest od
  0307 NULL-owalne), znacznikiem w manifeście portfela i wszystkimi pułapkami
  z 0303. Każdy inny → **usunięcie z zachowaniem historii**: `deleted_at` +
  `archived_at`, wiersz zostaje (kontrakty, zamówienia, umowy nadal na niego
  wskazują). `visible_client_predicates` dostało `deleted_at IS NULL`, bo import
  portfela potrafi cofnąć `archived_at`. Zakresów portfela NIE archiwizujemy —
  inwariant manifestu liczy żywe zakresy.
- **`critical_events` nie ma żadnego FK** — wpis przeżywa usunięcie obiektu
  i konta (nazwy zdenormalizowane), a zapis zablokowanej próby z OSOBNEJ sesji
  (`record_blocked`) nigdy nie czeka na blokady trzymane przez odmawiające
  żądanie. Wykonane operacje idą do sesji operacji (`record_executed`, wspólny
  commit). `audited_deletion` owija istniejące DELETE-y: 403/409/422/423
  z wnętrza bloku = zablokowana próba, 404/5xx = nic.
- **Wpisy NIE niosą imion i nazwisk kontraktorów/kandydatów** — przeżywają
  usunięcie osoby (art. 17 RODO), a API nie pozwala ich edytować. Etykiety to
  numery: `Kontrakt #id`, `Zamówienie #id`, `Konsultant (linia #id) —
  zamówienie X`, `Umowa B2B {numer}`; zablokowana próba usunięcia klienta
  zapisuje rodzaj i liczbę blokad bez pozycji (okno pokazuje nazwiska na żywo).
  Nazwy firm i kont pracowników zostają.
- **Usunięty klient nie ma profilu ani zapisów:** `get_client`/`profile`,
  `_assert_client` w zamówieniach, grupach i umowach ramowych oraz lista
  Pomoc → Klienci odrzucają `deleted_at` — obok list filtrowanych predykatem.
  Odmowy „brak uprawnienia" są zapisywane raz na 10 min na osobę i klienta.
- **Na start w Historii:** usunięcie klienta, kandydata/kontraktora
  (`DELETE /api/candidates/{id}` — BEZ imienia i nazwiska, tylko `Kandydat #id`
  + pseudonim `subject_ref`, bo to usunięcie z art. 17), konsultanta
  z zamówienia MD/kosztowego, kontraktu (także wymuszone przy podpisanej B2B),
  umowy ramowej, wygenerowanej umowy B2B, zamówienia okresowego (anulowanie =
  wpis z opisem) i zamówienia MD/kosztowego, plus zmiany uprawnienia do
  usuwania. Nowa krytyczna operacja = `audited_deletion` / `record_executed` +
  etykieta w `EVENT_TYPE_LABELS`.
- **Odczyt:** `GET /api/settings/event-history` (`FinanceModuleUser` = Admin
  + Finanse), filtry obiekt/wynik/tekst/daty, stronicowanie. Brak API do
  edycji i kasowania wpisów — świadomie.

## Insights (`/insights`) — parytet z DynaReporterem na danych NEXUSA

`/insights` odtwarza raporty DynaReportera (`infrareporter.onrender.com`)
**licząc je od zera z operacyjnych danych NEXUSA**, a nie z wchłoniętych tabel
`dr_*` (te są zamrożone: `dr_*` stanęły na tygodniu 21/2026, `clients-mrr` jest
puste, a finanse zarządu mają `0.0` we wszystkich 36 miesiącach). Zakres:
Rekrutacja · Liga Mistrzów · Delivery Lead · Klienci/MRR · Zarząd. **Poza
zakresem świadomie:** Sales, AI Analytics, Przetargi, Premie (moduł sprzedaży).
Decyzje D1–D7 i pełna specyfikacja: `docs/insights-dynareporter-migration-plan.md`
§0 oraz `docs/insights-etap0-specs.md`.

- **DWIE zakładki od 21.09.2026: `body-leasing` (3 rozdziały w `?ch=`) i
  `rada`** (makiety: https://claude.ai/artifact/3JijNAob8Vc1d53NgBGMJb, runda F).
  Dawne Rekrutacja i Delivery Lead zlane w **Body Leasing** — jeden rozdział
  widać naraz (`BodyLeasingPanel.tsx`, pliki w `components/insights/chapters/`):
  **Rywalizacja** (domyślny; kampania, Liga, wyścigi, ścieżka rozwoju jako
  tablica Junior / Senior / Expert, Hall of Fame — BEZ paska okresu),
  **Wyniki** (Wynik · Dziś i w miesiącu · Zespół · Praca w toku · Dopływ
  kandydatów; miesiąc) i **Klienci** (portfele DL — jedna tabela, DL jako
  nagłówek grupy; rok). **Rada** (rok do roku NA GÓRZE jako karty metryk, pod
  nimi kokpit i ranking klientów) widzą WYŁĄCZNIE admin, Finanse i HoR —
  `RADA_ROLES` we froncie i `BoardReader` na `/api/insights/board`,
  `/board/yoy`, `/clients/ranking`. **Usunięte z UI:** Power Calling, LinkedIn
  (endpointy zostają bez konsumenta) oraz cztery sekcje DL zastąpione
  portfelami. Z pulpitu przeszły: aktywność dnia/miesiąca
  (`RecruitmentActivityDashboard showNextSteps={false}`, tylko z dostępem do
  sekcji Rekrutacje), obłożenie (`AllocationWorkloadBoard`, tylko admin/HoR —
  endpoint `HeadOfRecruitmentOnly`) i kompetencje jako agregat
  (`/api/insights/recruitment/competence-matrix`). Dokładając sekcję, zacznij
  od pytania, na czyje pytanie odpowiada — nie od tego, gdzie jest wolne miejsce.
- **Tabele rok-do-roku Rady (`GET /api/insights/board/yoy`)** — dwanaście
  miesięcy × trzy lata, z deltą i kolumną „Ocena". Endpoint świadomie NIE
  przyjmuje paska okresu: patrzy na pełne lata kalendarzowe, a wpuszczenie tam
  `period`/`offset` dałoby siatkę „ostatnie 12 miesięcy" podpisaną nazwami
  miesięcy, czyli dwie różne rzeczy pod jedną etykietą. Okno wybiera się
  latami (`end_year`, `years`; 2–5, domyślnie 3).
  - **Backend zwraca WYŁĄCZNIE liczby.** Delta, „Ocena" i wiersz podsumowania
    to czysta arytmetyka w `frontend/src/lib/insights-yoy.ts` — testowana na
    wartościach, nie na zrzucie ekranu.
  - **Każda metryka niesie `aggregate`** (`sum` przepływy, `avg` stany,
    `ratio` wskaźniki, `distinct` liczności zbioru) oraz `lower_is_better`.
    Bez pierwszego widok potrzebuje własnej listy „co się sumuje", czyli
    drugiego lustra tej wiedzy — w DynaReporterze go nie było i wiersz „Suma"
    pod kolumną procentów pokazywał 874%. Bez drugiego wzrost zejść i kosztów
    dostaje zieloną strzałkę w górę, czyli komunikat odwrotny do prawdy.
  - **Wskaźnik za rok liczy się OD NOWA: Σlicznik / Σmianownik** (od 18.09.2026).
    Średnia dwunastu miesięcznych procentów to ŚREDNIA ILORAZÓW, a mianowniki
    miesięcy różnią się pięciokrotnie — miesiąc z 9 zamkniętymi rekrutacjami
    ważył tyle samo co miesiąc z 200. Zmierzone na produkcji: hit ratio 2024
    pokazywane 14,57% przy realnych 17,4% (134/770), 2025 — 16,58% przy
    realnych 14,5% (195/1342); delta zmieniała ZNAK (+2,0 pp „Lepiej" zamiast
    −2,9 pp „Gorzej"). Dlatego `ratio` niesie `components` (klucze licznika
    i mianownika), a odpowiedź osobne `component_series` — to NIE są wiersze
    tabeli. Nowy wskaźnik bez składowych = błąd kontraktu, nie brak danych
    (`test_insights_board_yoy.py`).
  - **Liczności zbioru (`unique_clients`) nie da się złożyć z miesięcy żadnym
    działaniem** — klient obsłużony w marcu i w lipcu to jeden klient.
    DynaReporter pokazywał 4,33 / 6,75 / 8,63 przy realnych 18 / 23 / 25.
    Rok przychodzi gotowy w `yearly`; wiersze miesięcy zostają miesięczne,
    bo to prawda o miesiącu. Porównania YTD ta metryka NIE ma — rok jest rokiem.
  - **Miesiąc PRZYSZŁY to `null`, miesiąc BIEŻĄCY jest oznaczony**
    (`partial_month`). Zera w kolumnie bieżącego roku czytają się jak awaria,
    a siedem dni danych — jak załamanie wyniku.
  - **Podsumowanie roku niepełnego porównuje się z TYMI SAMYMI miesiącami**
    roku poprzedniego (YTD). To jedyne miejsce, gdzie mianownik porównania jest
    inny niż liczba w komórce obok — i dlatego wiersz to mówi. **Trwający
    miesiąc nie wchodzi do YTD w żadnym z lat** (od 11.09.2026): 1 lutego YTD
    porównuje jeden pełny miesiąc, w styczniu pokazuje „—”, a wiersz „(trwa)”
    nie ma delty ani oceny. Wcześniej kilka dni bieżącego miesiąca stawało
    naprzeciw pełnego miesiąca roku poprzedniego i dawało fałszywy spadek.
  - **Pieniądze liczy `insights_board_money.fold_money`, ta sama funkcja co
    kafle** — wyniesiona z `insights_board.py` w chwili, gdy pojawił się drugi
    konsument. Kopia przechodziłaby każdy test wartości do dnia, w którym ktoś
    poprawi jedną z nich; wtedy kafel „Marża / mc" i komórka „Marża" w tabeli
    obok pokazują dwie różne kwoty pod jedną nazwą, na jednym ekranie.
    Pilnuje tego test TOŻSAMOŚCI obiektu funkcji, nie zachowania.
    **Kwoty kontraktu są zaokrąglane do pełnych złotych PRZED sumowaniem**
    (`to_whole_pln`, UAT M06-B04) — tak samo w rankingu klientów, profilu,
    portalu DL i przeglądzie admina; suma zaokrągleń ≠ zaokrąglenie sumy,
    a różnica wychodzi między kaflem a rankingiem na jednej zakładce.
    Pilnuje `test_margin_rounding_parity.py`.
  - **Rezygnacje to PODZBIÓR zejść** (`consultant_resigned`, `better_offer`,
    `personal_reasons`); `poached_by_client` świadomie poza — to klient zabiera
    człowieka, inne zjawisko i inny wniosek. Data zejścia to
    `COALESCE(terminated_at, end_date)`, jak w `contract_analytics`.
  - **Marża na godzinę wyklucza ryczałt z LICZNIKA i MIANOWNIKA naraz.**
    Kwota miesięczna nie niesie godzin, a podstawienie 160 zamieniłoby
    wskaźnik w marżę podzieloną przez wymyśloną stałą.
  - **EWIDENCJA KONTRAKTÓW JEST MŁODSZA NIŻ FIRMA — i bez tego tabela kłamie.**
    Zmierzone na produkcji 08.09.2026: styczeń 2024 → **17** wycenionych
    kontraktów, sierpień 2026 → **452**, przy realnej liczbie ~320 konsultantów
    w 2024 (dane DynaReportera). Placementy przyszły z importu Traffita
    i sięgają lat wstecz; kontrakty zaczęły powstawać w NEXUSIE później i nie
    zostały uzupełnione wstecz. Pierwsze wydanie pokazywało to jako **+935%
    wzrostu przychodu** — liczbę arytmetycznie poprawną i semantycznie
    fałszywą. Dlatego każda metryka niesie `basis` (`contracts` | `pipeline`),
    odpowiedź niesie `coverage.contracts_by_year`, a widok stawia ostrzeżenie
    PRZY grupach liczonych z kontraktów. **Nie usuwaj tego ostrzeżenia „bo
    brzydkie" — usuń je dopiero, gdy historia kontraktów zostanie uzupełniona
    wstecz.** Ostrzeżenie stoi przy grupach, a nie jednym banerem na górze:
    Dywersyfikacja i hit ratio liczą się z pipeline'u i są porównywalne, więc
    baner zbiorczy podważałby także je, a ostrzeżenie podważające wszystko
    uczy ignorować ostrzeżenia.
  - **Poza zakresem świadomie: „Zysk" (marża − pozostałe koszty)** — NEXUS nie
    zna „pozostałych kosztów", a w DynaReporterze ta tabela była pusta we
    wszystkich 36 miesiącach. Tabela rok-do-roku NIE wchodzi też do eksportu
    CSV zakładki: tamten jest przycinany oknem z paska, a ta siatka jest
    latami — jeden plik pod jedną nazwą oznaczałby dwa różne zakresy.
- **Stare identyfikatory zakładek i kotwic ŻYJĄ jako aliasy**
  (`LEGACY_TAB_ALIASES`, `LEGACY_ANCHOR_CHAPTER` w `InsightsView.tsx`):
  `rekrutacja` → Body Leasing / Wyniki, `delivery-lead` i `klienci` → Body
  Leasing / Klienci, `zarzad` → Rada; stara kotwica (`#liga`, `#zrodla`…)
  wybiera rozdział dokładniej niż alias. Nie kasuj ich: te linki są
  w zakładkach przeglądarki, w zapisanych powiadomieniach i w przekierowaniach
  `/dynareporter/*`. Rozstrzygają czyste `resolveInsightsTab`
  i `resolveChapter` (testowalne bez montowania widoku).
- **Każdy rozdział ma własny domyślny okres i zmiana rozdziału go zeruje**
  (Wyniki: poprzedni miesiąc, Klienci: rok, Rada: kwartał). Klienci stoją na
  roku, bo hit ratio stoi na rekrutacjach ZAMKNIĘTYCH w oknie, a tych
  w miesiącu jest kilkanaście na cały zespół — wskaźnik z takiej próbki
  skacze o dziesiątki punktów i czyta się jak awaria.
- **Portfele DL (`/api/insights/delivery-leads/portfolio`) liczą nagłówek DL
  i wiersze klientów TĄ SAMĄ definicją co `/delivery-leads`** — suma wierszy
  zgadza się z nagłówkiem. Nie mieszaj z `/clients/hit-ratio` (inna definicja
  hit ratio, bez filtra body_leasing).
- **Sekcje mają kotwice** (`InsightsSection` + `InsightsSectionNav`): tablica
  `SECTIONS` w panelu jest jednocześnie spisem treści i kontraktem `id`.
  Dokładając sekcję, dopisz ją do tablicy — inaczej pasek sekcji obiecuje
  komplet, którego nie ma. `scroll-mt` w `InsightsSection` jest load-bearing:
  bez niego kotwica chowa nagłówek pod paskiem aplikacji.

- **`/api/insights/*` jest ODDZIELNĄ powierzchnią od `/api/reports/*`
  i `/api/admin/*`.** Tamte trasy są współdzielone z innymi stronami, więc
  poszerzenie ich guardu (D7) albo zmiana semantyki okresu zmieniałaby po cichu
  liczby i widoczność gdzie indziej. Kopiowanie SQL-a też nie: logika wspólna
  z zakładką Klienci mieszka w `services/insights_clients.py`.
- **Placement = D2: PIERWSZE `hired` dla pary (kandydat, oferta)**, czytane
  z widoku `analytics_first_milestones`. `candidate_stages` nie ma unikalności
  na `(candidate_id, job_id, stage)`, a import Traffita dopisuje wiersz na każde
  zdarzenie — liczenie surowych wierszy dubluje powroty na etap.
- **`analytics_first_milestones` niesie DOKŁADNIE SZEŚĆ etapów**
  (`verified`, `cv_sent`, `interview`, `client_interview`, `acceptance`,
  `hired`). Reszta lejka idzie z `candidate_stages`. Lejek trzyma **dwie
  niezależne flagi** (`in_milestones`, `mapped_from_traffit`), bo mylą się
  w obie strony: `new`/`screening` NIE są w widoku, ale są mapowane z Traffita,
  a `acceptance`/`client_interview` są w widoku i z Traffita nie przychodzą.
  Test porównujący dwa pola TEJ SAMEJ odpowiedzi przechodzi niezależnie od tego,
  czy odpowiedź jest prawdziwa — tak ten defekt przeżył pierwsze podejście.
- **Zero mianownika to `None`, nigdy `0.0`, i nigdy nie przycinamy do 100%.**
  „Nie da się policzyć" i „policzone, wyszło zero" to dwa różne zdania
  o zespole; konwersja powyżej stu procent jest sygnałem o kolejności etapów
  w imporcie, a sufit osi go chowa.
- **Awaria NIE MOŻE renderować się jako pustka** (`resolveViewState`
  z `isSuccess`). Bez tego przerwa między ponowieniami react-query pokazuje
  awarię jako „brak danych". Dotyczy też 403: pustka czyta się jak utrata
  danych, nie jak brak uprawnień.
- **D7: `/insights` widzi KAŻDA zalogowana rola — poza zakładką Rada
  (21.09.2026, patrz wyżej).** Guard rolowy zdjęty
  z sześciu luster; `ROLE_CAPABILITIES` i middleware nietknięte. Poszerzone do
  `CurrentUser`: `/api/competitions/current`, `/monthly-races` oraz `/history`
  (ta ostatnia dopiero wtedy, gdy zyskała konsumenta — sekcję „Hall of Fame").
  Zapisy zostają wąskie: CRUD kampanii i nadawanie plakietek to `AdminUser`.
- **Ścieżka rozwoju (D6) liczy się PRZY ODCZYCIE, zero mutacji w GET.** Każdy
  poziom ma DWA alternatywne progi połączone przez LUB („6 placementów w 6
  miesięcy **lub** 12 w 12"), a **zegar eksperta jest kotwiczony na dacie awansu
  na seniora** — bez tej kotwicy jedna dobra passa kupuje oba awanse naraz
  i „ścieżka" staje się jednym progiem z dwiema nazwami. Poziom jest ZAPADKĄ:
  cichy kwartał go nie odbiera. Progi są konfigurowalne
  (`insights_scoring_config`), więc żyją w TRZECH kopiach — kod, migracje
  (`0256` + `0260`), lustro w `entrypoint.sh` — pilnowanych przez
  `test_insights_scoring_config.py`.
- **Dni robocze (D5) idą z COMPASSA** (`nexus_workdays_export` →
  `/api/internal/workdays` → `user_workday_periods`). Metryka to **dni robocze
  minus zatwierdzony urlop**, NIE „dni przepracowane" — chorobowego w źródle nie
  ma (trigger B2B go blokuje). Bez sekretów (`WORKDAYS_EXPORT_SECRET`,
  `COMPASS_WORKDAYS_*`) endpoint zwraca 503, a Power Calling raportuje
  `not_assessable` — mówi wprost, że nie wie, zamiast dzielić przez zmyśloną
  stałą (usunięte `POWER_CALLING_WORKDAYS = 5` stawiało osoby na urlopie
  na imiennej liście „poniżej progu").
- **Plakietki wygaszamy, nie kasujemy** (`user_performance_flags`, 0258):
  `is_active=false` + data i autor. Jedna AKTYWNA plakietka danego typu na osobę
  — częściowy UNIQUE `WHERE is_active`, bo pełny zablokowałby historię.
  Kontrolka admina renderuje się TAKŻE przy zerze plakietek; inaczej pierwszego
  ostrzeżenia nie da się nadać nikomu.
- **Kampania: brak kampanii → baner renderuje NIC**, nie pustą ramkę „0/0"
  (ta twierdziłaby, że kampania trwa i idzie fatalnie). Okno odwrócone odbija
  CHECK `ck_recruitment_campaigns_window` — pusty przedział dałby „0 z N"
  i „0 dni do końca", czyli liczby poprawne arytmetycznie, opisujące
  nieistniejącą kampanię.
- **Domyślny okres to `offset = -1` (poprzedni pełny miesiąc)**, nie bieżący.
  Pierwszego dnia miesiąca `offset=0` znaczy jeden dzień danych i cały ekran
  pokazuje zera, które wyglądają jak awaria.
- **Kampania: `active`/`ending` liczą się jako rezygnacja DOPIERO od dnia,
  w którym ich data końca nadeszła** (`ended` — zawsze, bo status jest
  stwierdzeniem faktu). Te dwa statusy są w katalogu po to, żeby złapać
  kontrakty przed nocnym `_promote_statuses`; bez sufitu ta sama reguła
  wciągała każdą PRZYSZŁĄ datę końca w oknie, więc trzymiesięczna kampania
  miała pierwszego dnia policzone odejścia z miesiąca drugiego i trzeciego.
  Sufit to `business_today()`, nie `CURRENT_DATE`, i wchodzi w klucz cache'u.
  Slug definicji zbumpowany do `..._v2` — baner drukuje notatkę DOSŁOWNIE,
  więc definicja, która zmieniła znaczenie pod tym samym kluczem, byłaby
  niewykrywalna dla konsumenta.
- **Hall of Fame liczy TAK SAMO jak „Analiza placementów" (D2), ale INACZEJ
  niż wyścigi, które płacą.** Od 2026-09-01 `competitions.hall_of_fame` czyta
  `analytics_first_milestones.first_moved_by` — pierwsze wejście pary
  (kandydat, oferta) na etap „Zatrudniony", przypisane osobie, która ten etap
  przesunęła. `monthly_most_placements` i mistrzowie kwartału ZOSTAJĄ przy
  `_rank_recruiters_by_stage` (verifier-anchored): wypłacają 1500 zł i
  10 000 zł, mają zamrożoną historię, a ich docstring mówi wprost, po co ta
  atrybucja istnieje — „pozwalało osobie klikającej końcowy etap przejąć
  credit pierwszego verifiera". **Nie reużywaj `_rank_recruiters_by_stage`
  w Hall of Fame i nie ruszaj `VERIFIER_ANCHORED_CTE` „przy okazji"** — to
  jedyne dwie ścieżki, którymi ta zmiana mogłaby ruszyć pieniądze. Hall of
  Fame ich nie rusza: `_prize_for` daje mu 0, autofreeze go nie zna
  (`competition_autofreeze.py` mrozi cztery inne typy), żaden ekran nie woła
  `POST /freeze`, a `competition_winners` dla `hall_of_fame` jest puste
  (sprawdzone na produkcji 2026-09-01).
- **Zakres ról jest tym, co oddziela „kto dowiózł" od „kto kliknął".**
  `HALL_OF_FAME_ROLES` = sourcer, tac, recruiter, delivery_lead,
  head_of_recruitment — świadomie SZERSZY niż w wyścigach (te trzymają się
  sourcer/tac/recruiter i nie wolno ich zlać w jedną listę). Konta `admin`
  zostają poza rankingiem, bo w ostatnim roku pięć z nich zebrało **147 z 314
  placementów przy CZTERECH weryfikacjach łącznie** — to podpis masowego
  domykania pipeline'u. Delivery w tym samym oknie: 69 placementów przy 2186
  weryfikacjach, czyli praca, którą wąski filtr wyścigów by wyciął.
  Odpowiedź niesie `scope` (ile w rankingu, ile poza nim), bo TOP 5 bez tej
  liczby czyta się jako całość bazy.
- **Kod definicji jest DOKŁADNIE ten sam string** co w `/placement-analysis`,
  `/insights/board` i banerze kampanii: `first_hired_per_candidate_job`.
  Własny wariant („..._by_mover") wygląda precyzyjniej, a daje maszynowo
  „różne" tam, gdzie reguła jest identyczna — czyli odwrotność tego, do czego
  to pole służy. Dwie powierzchnie liczą to jednak DWOMA osobnymi
  zapytaniami, więc wspólny kod jest tylko obietnicą: pilnuje jej test, który
  porównuje obie odpowiedzi liczba po liczbie
  (`test_hall_of_fame_agrees_with_placement_analysis_number_by_number`).
- **Hall of Fame NIE filtruje `is_active`.** Ranking wszech czasów mówi, co
  ktoś osiągnął — odejście z firmy tego nie cofa. Byli pracownicy zostają
  z chipem, tak jak w tabeli „Performance per osoba" na tym samym ekranie.
  `is_active` jedzie w `extras` i przez `CompetitionRankingEntry`, żeby dało
  się ich OZNACZYĆ zamiast ukryć.
- **Testy jednostkowe `hall_of_fame` mockują `db.execute` i asertują KSZTAŁT
  SQL-a — nigdy go nie uruchamiają.** Literówka w nazwie kolumny przeszłaby
  przez nie na zielono, a 500 zobaczyłby użytkownik. Dlatego
  `test_insights_competitions_open.py` ma test, który przechodzi całą ścieżkę
  router → serwis → Postgres.
- **`/api/admin/schema-drift` robi `rollback()` w każdej gałęzi błędu** —
  zabezpieczenie ścieżki TIMEOUTU, gdzie `asyncio.wait_for` anuluje zapytanie
  w locie i zostawia sesję w zepsutej transakcji. Uwaga na zakres dowodu:
  po usunięciu wszystkich rollbacków test kontraktowy nadal przechodzi
  (`get_db` commituje taką sesję bez `PendingRollbackError`), więc guard broni
  KSZTAŁTU ODPOWIEDZI (200 + `error` + `alembic`), a nie tych linijek.
- **Fixture'y testowe nie mogą stać na stałym roku.** Baza testowa jest wspólna
  dla przebiegu i NIE jest czyszczona, więc rok zajęty przez sąsiedni plik wraca
  jako „regresja" w kodzie, którym nikt nie ruszał. Zanim wybierzesz rok:
  `grep -rhoE 'datetime\((1[89][0-9]{2}|20[0-9]{2})|date\((1[89][0-9]{2}|20[0-9]{2})|"(1[89][0-9]{2}|20[0-9]{2})-' backend/tests/ | grep -oE '(1[89][0-9]{2}|20[0-9]{2})' | sort -u`

## Autonomiczny przepływ CV (17.09.2026)

Raport: `docs/cv-autonomous-flow-completion-report.md`. Trzy reguły, które łatwo cofnąć:

- **Każde wejście CV kończy się `cv_ingest_service.finish_cv_ingest`**: pola →
  języki → indeks technologii → kategoria → wektor → cache → kolejka
  auto-dopasowania. Do 17.09 sześć miejsc robiło po odczycie co innego (CV z maila
  nie trafiało do wektora). Skan AST w `test_cv_ingest_service.py` pilnuje, że
  poza tym modułem `_apply_cv_enrichment` wołają tylko dwa biegi masowe
  (`cv_backfill`, `cv_field_backfill`) — świadomie bez auto-dopasowania, bo nocny
  sync Traffita dodawałby do pipeline'ów tysiące historycznych osób.
- **Pełny profil (prompt `cv_enrichment` v7) tylko dla nowych/odświeżonych CV**
  (decyzja: bez backfillu 49 tys.). Znacznik `cv_extracted_data._profile_schema = 2`
  odróżnia profil v7; frontend pokazuje certyfikaty, projekty i oś technologii
  WYŁĄCZNIE przy nim (pusta sekcja twierdziłaby, że CV ich nie ma). Oś
  (`skill_timeline`, tabela `candidate_skill_usage`) liczy Python z dat stanowisk
  i projektów — model jej nie pisze. Tekst embeddingu dla profili bez schematu 2
  musi zostać bajt w bajt taki sam (inaczej reindeks całej bazy), a próg
  „ostatnich lat" liczy się od daty odczytu CV, nie od zegara. Opis stanowiska
  z CV ma `source: "cv"` i NIE blokuje nadpisania historii nowym CV; opis
  z importu Traffita blokuje jak dotąd. Waga świeżości skilli w scoringu:
  `AI_SCORING_SKILL_RECENCY` (domyślnie OFF do pomiaru `eval_matching.py`).
- **Auto-dopasowanie** (`auto_match_service`, worker `candidate_auto_match`,
  tabele `candidate_match_outbox` + `candidate_auto_match_log`): nowe CV →
  opublikowane rekrutacje, publikacja/istotna zmiana rekrutacji → CV odczytane
  w ostatnich `AUTO_MATCH_JOB_LOOKBACK_DAYS`. Dodaje przez
  `proposals_bulk.add_candidates_to_job` (te same bramki co rekruter) na etap
  `posting` z tagiem `auto-match` i dzwonkiem `auto_match` (dedup po wierszu
  etapu; typ musi być w `NOTIFICATION_SECTION_BY_TYPE`, inaczej rekruter go
  nie widzi). Pula to wyszukiwanie w Qdrancie ZAWĘŻONE filtrem po id do
  opublikowanych rekrutacji albo profili v7 z okna — nie „najbliższe z całej
  bazy". Częściowy UNIQUE kolejki obejmuje `pending`/`processing`/`failed`
  (bez `failed` przejęcie paczki łapało konflikt unikalności i stawało na
  zawsze). Dziennik decyzji jest dedupem (kandydat × rekrutacja × wersja CV):
  `added` blokuje zawsze, `dry_run` nigdy, reszta do zmiany rekrutacji — i
  podglądem w Ustawieniach → AI. Reguła progu jest JEDNA z importerem JJIT
  (`auto_match_rules.is_good_match`). **Tryb rozstrzyga `AUTO_MATCH_MODE`
  (od 21.09.2026, domyślnie `propose`)** — patrz „Automaty rekrutacji v3";
  `AUTO_MATCH_DRY_RUN` został aliasem (true → `dry_run`, false → `add`)
  czytanym tylko, gdy `AUTO_MATCH_MODE` jest puste.
  **Konflikt z klientem (`active_conflict`) i wykluczenie klienta
  (`client_excluded`) BLOKUJĄ automat**, choć od #1589 rekruterowi tylko
  ostrzegają: ostrzeżenie czyta człowiek, a automat nie ma kogo ostrzec
  (`auto_match_service._BLOCKING_WARNINGS` → decyzja `penalized`).
- **CV z maila od nadawcy spoza bazy** (`attachment_handler.try_create_candidate_from_cv`):
  tożsamość z TREŚCI CV (rekruterzy przesyłają CV dalej). E-mail/telefon/LinkedIn
  pasuje → mail podpięty (`EmailMatchMethod.cv_identity`); pasuje samo imię
  i nazwisko → nic (`possible_duplicate_name`); CV bez imienia, nazwiska albo
  kontaktu → nic (`identity_insufficient`). Tylko poczta z ostatnich
  `M365_AUTO_CREATE_LOOKBACK_DAYS` (14). Wyłącznik `M365_AUTO_CREATE_CANDIDATE_FROM_CV`.

## Automaty rekrutacji v3 (21.09.2026, migracja 0335)

Cztery automaty, wszystkie WŁĄCZONE domyślnie, każdy za wyłącznikiem env,
którego stan OFF = zachowanie sprzed 21.09. **Nic zewnętrznego ani
nieodwracalnego nie dzieje się bez kliknięcia człowieka**: żaden automat nie
wysyła nic do klienta, nie przesuwa karty i nie dodaje nikogo do pipeline'u
(wyjątek: jawnie ustawione `AUTO_MATCH_MODE=add`). Zdarzenia automatów lądują
w `Activity(entity_type="job_automation", entity_id=<job_id>)` — osobny typ
encji, żeby nie mieszać się z historią rekrutacji — i czyta je
`GET /api/jobs/{id}/background-events` (zakładka „Praca w tle", bramka jak
skrzynka „Propozycje"; nazwisko kandydata tylko dla ról z odczytem kandydatów,
stan auto-CV czytany NA ŻYWO z wiersza dokumentu).

| Automat | Wyłącznik | Kod |
|---|---|---|
| A. nocny pełny przegląd bazy → „Propozycje" (`full_base`) | `AUTO_FULL_REVIEW_ENABLED` | `services/auto_full_review.py`, `tasks/auto_full_review.py` |
| B. nowe CV → „Propozycje" (`new_cv`) | `AUTO_MATCH_MODE=dry_run` | `services/auto_match_service.py` |
| C. auto-CV po ruchu na „Zweryfikowany" | `CV_AUTO_GENERATE_ON_VERIFIED` | `services/cv_auto_generate.py` |
| D. podpowiedź stawki/dostępności w arkuszu screeningu | brak (czysty odczyt) | `services/screening_suggestions.py` |

- **A. Sygnałem jest ZDARZENIE rekrutacji, nie „każda opublikowana".** Nocna
  pętla (okno `AUTO_FULL_REVIEW_WINDOW_START/END_HOUR` = 1–5 w `BUSINESS_TZ`,
  tick co 60 s, heartbeat `auto_full_review`) bierze rekrutacje opublikowane,
  które mają w `candidate_match_outbox` zdarzenie nowsze niż ich ostatni
  przegląd automatyczny (okno `AUTO_FULL_REVIEW_EVENT_LOOKBACK_DAYS` = 14).
  Przegląd to ~100–130 MB wierszy — przemiatanie wszystkich otwartych
  rekrutacji zapchałoby wolumen bazy. Zdarzenie zapisują: publikacja, PATCH
  z `_SIGNIFICANT_FIELDS` **albo `_AUTO_REVIEW_EXTRA_FIELDS`** (budżet, tryb
  pracy, dni w biurze — osobna lista, żeby nie wywoływać rescanów Targu) oraz
  zapis Championa. `enqueue_job` pisze też przy `AUTO_MATCH_ENABLED=false`
  (`job_events_enabled`) — wtedy od razu jako `skipped`, bo `pending` bez
  workera wisiałby bez końca i częściowy UNIQUE połykałby kolejne zmiany.
- **A. Limity:** najwyżej jeden przegląd na rekrutację na noc (także nieudany),
  `AUTO_FULL_REVIEW_MAX_PER_NIGHT` (20) łącznie, jeden nowy przegląd na tick,
  odcisk requestu równy ostatniemu nie-nieudanemu przeglądowi automatycznemu =
  pominięcie. **Automat ustępuje ludziom**: nie startuje, gdy JAKIKOLWIEK
  przegląd jest w kolejce/w toku, a worker i tak bierze ręczne pierwsze.
  Wywrotka jednej rekrutacji nie blokuje następnej (`_skipped_tonight`).
- **A. `version_trace.origin = "auto"`** (`candidate_search_store.is_auto_run`,
  `auto_origin_clause`; w `version_trace`, bo `metrics` nadpisuje telemetria):
  autor = `recruiter_id` albo `tac_id` (brak obu = pominięcie), ale taki
  przegląd **nie zajmuje żadnego z dwóch slotów autora** (`start_search`),
  **nie jest chroniony przez retencję** (filtr stoi WEWNĄTRZ rankingu
  `protected_run_ids` — inaczej zdjąłby ochronę z ręcznego przeglądu tej samej
  osoby), **nie dzwoni autorowi** i **czyta go każdy, kto przejdzie bramkę
  rekrutacji** (`owned_run` → `shared_auto_run`; cudzy RĘCZNY przegląd zostaje
  404). Policzony profilem punktacji BEZ użytkownika (globalny/klienta), więc
  odczyt też porównuje odcisk tym profilem — osobisty profil oglądającego nie
  daje 409.
- **A. Publikacja:** w transakcji kończącej przegląd, w savepoincie
  (`publish_on_finish`, nigdy nie rzuca): top `AUTO_FULL_REVIEW_TOP_K` (60)
  wierszy `eligible ∧ measured ∧ fit_score ≥ AUTO_FULL_REVIEW_MIN_SCORE`
  (osobny próg — przegląd punktuje kanonicznym fitem, auto-match starszym
  scoringiem), które
  przechodzą `is_good_match` → `upsert_proposals(source="full_base")` z wersją
  CV i dowodami przez `sanitize_evidence` (same nazwy wymagań). Znacznik
  `metrics.auto_proposals`; `reconcile_unpublished` domyka przeglądy bez niego.
- **B. `AUTO_MATCH_MODE = dry_run | propose | add`** (`auto_match_outbox.auto_match_mode`
  — JEDNO miejsce; puste = `propose`, literówka = `dry_run`). W `propose`
  dobry wynik daje decyzję `proposed` w dzienniku i wiersz `job_proposals`
  (`new_cv`, `cv_revision = profile_revision`) **w tej samej transakcji** —
  do pipeline'u nie wchodzi nikt. `proposed` blokuje ponowną ocenę jak inne
  decyzje (do zmiany rekrutacji), `_BLOCKING_WARNINGS` nadal dają `penalized`,
  sufity `AUTO_MATCH_MAX_*` obowiązują. Powiadomienie:
  `NotificationType.auto_match_proposals` — JEDEN dzienny digest na
  (rekrutacja, odbiorca), link `/jobs/{id}?tab=similar`; kolejne propozycje
  tego dnia PODBIJAJĄ licznik w tym samym wpisie i odznaczają „przeczytane".
- **C. Jedna ścieżka walidacji z kliknięciem rekrutera:**
  `api.cv_generator_b2b.enqueue_candidate_generation` (wyjęta z `POST /generate`;
  kontrakt kwoty w `test_cv_generator_ai_master_toggle.py`). Automat nie ma
  łagodniejszej kopii, więc **nie wygeneruje dokumentu łamiącego zatwierdzoną
  regułę klienta**: wymagany zrzut zgody RODO (PKO BP) = pominięcie PRZED
  wołaniem generatora (`consent_screenshot_required`), każde 422 ze wspólnej
  ścieżki (notatki, numer projektu, Champion, język) = `client_rule_inputs_missing`
  z komunikatem. Pominięcie = `Activity(cv_auto_generate_skipped, reason)`,
  bez naliczenia kwoty. Tryb = domyślny z reguły klienta (inaczej `polished`),
  język = wymuszony regułą (inaczej `pl`), nigdy blind, `project_ref` puste.
  **Pod centralnymi regułami CV (`CV_CENTRAL_POLICIES_ENABLED`, 0331)** język
  ustala wspólna ścieżka (język polityki), a tryb — od #1647 — serwer bierze
  z żądania (`central_policies.resolve_mode`: bez kompletnego Championa
  „Pod rekrutację" schodzi do Redakcji z komunikatem w ostrzeżeniach dokumentu,
  nigdy 422; sufit klienta wygrywa). Automat prosi więc o tryb z katalogu
  polityk (`policy_content_mode`, domyślnie „Pod rekrutację") — ten sam, który
  formularz zaznacza domyślnie. Wiersz dostaje ten sam stempel `central_policy`
  co po kliknięciu.
  Centralny przepływ NIE odmawia przy generacji braku zgody ani numeru projektu
  (sprawdza je gotowość pakietu), a obie rzeczy zapadają przy generacji — więc
  automat sam pomija: zgoda = `consent_screenshot_required`, numer projektu z
  `managed_policy.require_project_ref` (Energa, Orlen) =
  `client_rule_inputs_missing`; polityka czekająca na synchronizację (503) =
  `generation_unavailable`, nie „awaria".
  **Klient dwujęzyczny (Alior, BIK, BNP, Santander): automat robi JEDNĄ wersję**
  (decyzja właściciela 21.09.2026) — `enqueue_candidate_generation(languages=
  "primary_only")`, worker pomija drugą wersję TYLKO w pierwszym przebiegu.
  Drugą dorabia rekruter jednym kliknięciem: ponowienie pakietu odpala to samo
  zadanie gałęzią „pierwszy dokument gotowy" i tam druga wersja powstaje.
  Pakiet pokazuje „Brak wygenerowanej wersji EN." (brak wiersza, nie `failed`),
  `can_retry = true`. Ręczna ścieżka bez zmian (pola nie ma w snapshotcie).
  `position_fallback` = tytuł rekrutacji, tylko z automatu: potoki używają go,
  gdy ani `presentation_position`, ani stanowisko z CV nic nie dają
  (`Candidate` nie ma kolumny `current_position` — `getattr` w `/generate`
  zawsze daje `None`, stanowisko wiersza ustala dopiero finalizacja). Testy:
  `test_cv_auto_generate_central_policies.py` (prawdziwa wspólna ścieżka).
- **C. Odpalenie:** wyłącznie `move_candidate`, PO commicie, przez `_spawn`
  (własna sesja; wyjątek przy odpalaniu jest połykany — ruch zawsze 200).
  `/bulk-move` nie przyjmuje `verified`, importy tędy nie idą. Kwota AI
  i autorstwo (`created_by`) idą na osobę, która przesunęła kartę.
  Idempotencja: `cv_generated_documents.origin='auto'` + `stage_id` +
  `source_cv_revision` z częściowym UNIQUE (0335, lustro w `entrypoint.sh`) —
  ten sam etap z tym samym CV nie generuje drugi raz; nowe CV = nowy dokument.
  W testach automat jest WYŁĄCZONY autouse-fixturą w `conftest.py` (zadanie
  przeżywałoby test, który je odpalił).
- **C. Auto-CV jest odnajdywalne tam, gdzie rekruter wysyła CV.** Istniejący
  przepływ warsztatu: lista `GET /api/cv-generator/generated?candidate_id&job_id`
  → „Zastąp szkic i otwórz edytor" (`select-generated` = SZKIC brandowanego CV
  etapu) → `finalize` (zatwierdzenie, człowiek). Automat robi tylko pierwszy
  krok i tylko bezpiecznie: `attach_as_stage_draft` podpina gotowy dokument
  jako szkic WYŁĄCZNIE, gdy etap nie ma jeszcze żadnego (`branded_status ==
  "none"`, pod blokadą wiersza; wspólna funkcja `apply_generated_to_stage_cv`)
  — istniejącego szkicu nie nadpisuje i NIGDY nie zatwierdza. Niezależnie od
  tego lista przypina na początku auto-CV z `needs_review: true` (`origin:
  "auto"`, `stage_id`; także z parametrem `?stage_id=`), a karta tablicy niesie
  `auto_cv_ready` (jedno zapytanie na tablicę). „Wymaga przeglądu" ma JEDNĄ
  definicję (`services/cv_auto_review.py`): brak zatwierdzonej wersji z tej
  generacji i brak etapu, który ma ją jako `finalized`.
- **Awarie automatów: rekruter bez dzwonka, admin po serii**
  (`services/automation_failures.py`). Awaria = wpis z polskim powodem w „Pracy
  w tle" (`auto_full_review_failed`, `auto_match_failed`,
  `cv_auto_generate_failed`) + `logger.error` (→ Sentry). TEN SAM automat 3 razy
  z rzędu (licznik w `app_settings['automation_failure_streaks']`, pod `FOR
  UPDATE`, zerowany pierwszym sukcesem) = JEDNO powiadomienie
  `automation_failing` na serię, tylko dla adminów (`ADMIN_ONLY_NOTIFICATION_TYPES`).
  Pominięcia (reguła klienta, brak CV) NIE są awariami. Sukces bez otwartej
  serii nie dotyka bazy (`_known_clean`) — auto-match księguje go przy każdym CV.
- **Obserwowalność dysku:** `GET /api/admin/index-coverage` → `candidate_search`
  niesie `auto_runs`, `auto_runs_rows` i `auto_runs_estimated_bytes` (szacunek
  proporcjonalny do migawek populacji — dokładny pomiar wymagałby skanu).
- **D. `GET /api/pipeline/stages/{id}/screening` → `suggestions`** z gotowego
  `_notes_insights` (zero wywołań modelu, ZERO zapisów). `rate` tylko dla ról
  z `user_can_edit_rates`; pozostałe dostają `rate_redacted: true`.
  `source_note_id` jest dziś zawsze `null` — `_notes_insights` to agregat ze
  wszystkich notatek i nie pamięta źródła.
- **Front automatów (21.09.2026):** zdania „Pracy w tle" składa JEDEN moduł
  `frontend/src/lib/job-background-events.ts` (serwer daje polski `message`
  tylko przy awariach; kody pominięcia auto-CV → `autoCvSkipReason`). Ten sam
  klucz zapytania (`jobBackgroundEventsQueryKey(jobId, 30)`) czyta zakładka
  w `HistoryChatSlideOver` i `AutoCvSkipNotice` w sekcji CV panelu — nowy kod
  pominięcia dopisz do `SKIP_REASON_PL`, inaczej wyjdzie „powód: <kod>".
  Endpoint nie stronicuje: „Pokaż więcej" podnosi `limit` (sufit 100).
  Podpowiedzi screeningu (`ScreeningSuggestionChips`): stawka WYŁĄCZNIE
  wypełnia stan doku (idzie przy ruchu na „Zweryfikowany"); waluta inna niż
  PLN albo nieznana jednostka = chip bez „Użyj". **Dostępność NIGDY nie trafia
  do „Notatek rekrutera"** — to pole widzi KLIENT w share portalu, a podpowiedź
  pochodzi z wewnętrznych notatek. „Użyj" to jawny zapis w PROFILU
  (`PATCH /api/candidates/{id}` z `availability_date`, bramka `candidate.write`
  — bez niej przycisku nie ma; toast + unieważnienie kanbana i kluczy
  kandydata). Mapowanie ma JEDNO miejsce, `availabilityProfilePatch`: data ISO
  albo jednoznaczne „od razu" (= dziś); `availability_status` to postawa wobec
  ofert, nie termin — nie ustawiamy go. Reszta („za 2 tygodnie", okres
  wypowiedzenia) = chip bez „Użyj" z linkiem „uzupełnij w profilu".

## NEXUS bez limitów AI (decyzja Artura, 17.09.2026)

Nie ma już głównego wyłącznika AI, przełączników per funkcja ani miesięcznych
sufitów. Jedyną ochroną budżetu jest **alarm wydatków** (`app/tasks/ai_spend_alerts.py`),
który informuje administratorów i niczego nie zatrzymuje.

- **`ai_quota.check_and_increment` nigdy nie rzuca.** Zostaje, bo zapisuje
  `AIOperation` — na nim stoją liczniki w Ustawieniach → AI i alarm. Kontekst
  `ai_feature()` MUSI zostać przy każdym wywołaniu modelu (telemetria kosztów,
  `_assert_declared`). Pilnują tego `test_ai_quota_monthly_limit.py`
  (stare kolumny nie blokują, zużycie rośnie) i `test_ai_quota_provider_gate.py`.
- **Kolumny `ai_features.enabled` / `monthly_limit` i wiersz `ai_master_toggle` są
  martwe.** Nic ich nie czyta jako bramki, a trasy `PATCH /api/settings/ai/master`
  i `/features/{feature}` zniknęły. Nie przywracaj bramki czytającej te kolumny:
  panel nie pozwala ich zmienić, więc stara wartość z bazy blokowałaby po cichu.
- **`AIQuotaExceeded` zostaje jako klasa** — importuje ją kilkanaście modułów,
  a ich gałęzie `except` są martwym, nieszkodliwym kodem. Do sprzątnięcia przy okazji.
- **Czat publicznego interaktywnego CV** zależy wyłącznie od polityki klienta
  (`cv_interactive_enabled`) i dziennego limitu per link
  (`CV_INTERACTIVE_CHAT_DAILY_LIMIT`, obrona przed nadużyciem publicznego linku).
- **`EXPERIENCE_DATES_ON_DEMAND_ENABLED` domyślnie `True`** (wyłącznik awaryjny).
- Ustawienia → AI to raport: model, tokeny, koszt per funkcja, suma miesiąca, alarm.

## Modele AI per funkcja — decyzja z badania na danych produkcyjnych (16.09.2026)

Badanie siedmiu modeli na WSZYSTKICH funkcjach AI (raport poza repo:
`outputs/model-matrix-2026-09-15/RAPORT-KONCOWY.md`, identyfikatory F1–F17)
zakończyło się decyzją Artura wdrożoną w rejestrze `services/ai_models.py`:

| ID | funkcja | model | ID | funkcja | model |
|---|---|---|---|---|---|
| F1 | scoring | Sonnet 5 | F9 | cv_parser | Sonnet 5 |
| F2 | champion_profile_parse | Sonnet 5 (z Haiku) | F10 | cv_backfill, cv_name_backfill | Sonnet 5 (z Haiku) |
| F3 | cv_requirement_map | Sonnet 5 | F11 | notes_extraction | DeepSeek V4 Pro (z Haiku) |
| F4 | cv_generator | Sonnet 5 (z 4.6) | F12 | candidate_summary | DeepSeek V4 Pro |
| F5 | cv_interactive_chat | GPT Luna (z Haiku) | F13 | champion_draft | Sonnet 5 |
| F6 | job_description_generator | Sonnet 5 | F14 | cv_rule_lint | Sonnet 5 (z Haiku) |
| F7 | order_parser | **Sonnet 5** (od 21.09) | F15 | mindy_chat | GPT Luna |
| F8 | uop_check | GPT Luna | F16/F17 | `VOYAGE_MODEL` / `RERANKER_ENABLED` | voyage-3 / wyłączony |
| F18 | cv_factual_verification | GPT Luna (z Sonnet 5) | | | |

- **F7 wrócił na Sonneta 5 (decyzja Artura, 21.09.2026).** GPT Luna czytała
  zamówienia poprawnie, ale oznaczała odczyt jako `uncertain` bez konkretnego
  powodu („oznaczony przez model jako niepewny", echo instrukcji promptu), a
  bramka poczty traktuje każdą niepewność jako powód do kolejki — Nordea po
  16.09: 2 z 6 poprawnych zamówień do ręcznego sprawdzenia. Badanie 16.09 i tak
  zalecało zostawić odczyt na Sonnecie. `order_pdf_parser._MODEL` liczy się przy
  imporcie, więc zmiana `ORDER_PARSER_MODEL` w Coolify wymaga restartu.
- **Rejestr jest JEDYNYM miejscem „funkcja → model".** Dostawca wynika z NAZWY
  modelu (`llm_providers.provider_of`: `claude-*` → Anthropic, `gpt-*` →
  OpenAI, `deepseek*` → DeepSeek). Nie dokładaj literałów modeli ani osobnych
  klientów w serwisach — `test_ai_models_registry.py` przypina decyzję per ID.
- **Dostawcy spoza Anthropic idą przez TĘ SAMĄ granicę `claude_client.call_claude`**
  (`services/llm_providers.py`): ten sam kształt odpowiedzi (`ProviderMessage`
  = bloki tekstowe, `stop_reason`, `usage`), te same ponowienia, deadline,
  fallback i telemetria (`ai_metering` z własnym cennikiem i polem `provider`).
  Błędy są zgłaszane WYJĄTKAMI SDK Anthropic (`RateLimitError`, `APITimeoutError`,
  `AuthenticationError`…) z prawdziwym `httpx.Response` — na nich stoi
  klasyfikacja ponowień i mapowanie błędów kilkunastu wołających. Nie zamieniaj
  tego na osobną hierarchię wyjątków „bo czystsza": zepsuje `except anthropic.*`.
- **Nieobsługiwane u GPT/DeepSeek: streaming, `tools`, bloki inne niż tekst
  (obraz, dokument PDF)** — `ValueError` (nieponawialny), nie ciche pominięcie.
  OpenAI dostaje `reasoning_effort=none`, `store=false`, bez `temperature`
  (modele rozumujące odrzucają parametr); DeepSeek `thinking=disabled` — czyli
  konfiguracje, w których model wygrał badanie.
- **Funkcje na GPT/DeepSeek mają fallback na Sonneta 5** (429/5xx/przeciążenie).
  **Brak klucza dostawcy = 401 NIEPONAWIALNE, bez kaskady na Claude** — błąd
  konfiguracji ma być widoczny: `/api/health` → `checks.openai` /
  `checks.deepseek` (`unconfigured` | `configured` | `degraded` | `unhealthy`).
  Sondy „brak klucza" u wołających pytają `api_key_configured(model)`, nie o
  klucz Anthropic. Klucze `OPENAI_API_KEY` i `DEEPSEEK_API_KEY` są w Coolify
  od badania (16.09.2026).
- **`settings_attr` wygrywa z `default` rejestru**, więc domyślne wartości
  legacy pól w `config.py` (`CLAUDE_MODEL_CV`, `CLAUDE_MODEL_CV_BULK`,
  `ORDER_PARSER_MODEL`) MUSZĄ być tym samym modelem co w rejestrze — pilnuje
  `test_legacy_settings_defaults_agree_with_the_registry`. Tak Haiku siedziałby
  w backfillu mimo decyzji. MINDY nie honoruje już legacy `CLAUDE_MODEL_CV`.
- **F4: Sonnet 5 z `CV_B2B_THINKING=disabled`** (domyślne). Rewert #628 mierzył
  Sonneta 5 z wymuszonym thinking; badanie z thinking wyłączonym: wymyślone fakty
  0.20 vs 0.41 u 4.6. Nie przywracaj pinu 4.6 bez ponownego pomiaru.
- **F2: zmiana modelu parsera Championa zmienia WYNIKI parsowania** — przy
  kolejnej edycji promptu bump `PARSER_VERSION`; klucz cache nie zawiera nazwy
  modelu.
- **F16/F17:** `VOYAGE_MODEL` w kodzie = `voyage-3` (do 16.09 kod mówił
  `voyage-3-large`, prod `voyage-3` — rozjazd wysyłał eval na ścieżkę
  referencyjną); `RERANKER_ENABLED=False` — na ścieżce produkcyjnej był no-opem
  (pula = wynik, `canonical_fit` i tak sortuje), dosypka 500→rerank-3→200
  n.s. Kod rerankera zostaje; włączenie = env w Coolify.
- **Dokładając nowy model:** wpis w `ai_models._REGISTRY` z uzasadnieniem
  (ID + liczba z badania), cena w `ai_metering._PRICES` (dwójka = Anthropic,
  trójka = dostawca z własną stawką za odczyt cache), przy nowym dostawcy —
  gałąź w `llm_providers.build_request/parse_response` i etykieta w
  `HEALTH_LABEL`.

## NUL w żądaniach i `detail` błędów API w UI (odbiór #1549, 15.09.2026)

Schemathesis znalazł 500 dla NUL (`%00`) w `q`; odbiór na produkcji pokazał, że
poprawne 422 wywracało listę kandydatów ekranem „Coś poszło nie tak" (React #31),
a testy na PostgreSQL — że `location`, `q_all`, `q_any`, `q_none` miały ten sam
500 (`asyncpg CharacterNotInRepertoireError`).

- **NUL odrzuca JEDNO middleware** (`app/core/null_character_guard.py`): query
  string, zdekodowana ścieżka i ciała JSON (także bez Content-Type) na
  POST/PUT/PATCH/DELETE → 422 `{type: "null_character", loc, msg, input}`.
  Nie obejmuje formularzy multipart/urlencoded, nagłówków ani WebSocketów.
  **Kolejność w `main.py` jest load-bearing:** guard tuż nad
  `UnhandledErrorMiddleware` (ta zostaje najgłębiej), pod korelacją i CORS —
  odrzucenie bez nagłówków CORS przeglądarka pokazuje jako „Network Error".
  Pilnuje `test_nul_guard_sits_inside_cors_and_outside_the_unhandled_error_net`.
  Nie dokładaj `pattern=` NUL do kolejnych parametrów; ten przy `q` zostaje, bo
  opisuje kontrakt w OpenAPI, z którego generator Schemathesis bierze wartości.
- **Publiczny formularz aplikacyjny stawia odmowę PRZY POLU** (18.09.2026):
  `lib/apply-form-errors.ts` mapuje `loc: ["body", <pole>]` na komunikat obok
  inputa, a `status` wraca do `idle` — kandydat poprawia i wysyła ponownie
  z tym samym CV. Wcześniej `body.detail` szło wprost do JSX: dla błędu
  walidacji `Form(...)` to TABLICA obiektów → React #31 → granica błędu zjadała
  całą stronę razem z wypełnionym formularzem i załączonym plikiem, a kandydat
  nie dowiadywał się, że chodziło o e-mail (zod 4 przyjmuje `jan@firma-.pl`,
  `EmailStr` odrzuca — ta rozbieżność ZOSTAJE, dlatego komunikat musi być
  konkretny). Strażnik `api-error-detail-guard.test.ts` nie wymaga już nazwy
  `data` (to ona przepuściła `body.detail`); świadomy wyjątek dla własnego
  endpointu z `detail: string` znaczy się markerem `// api-detail-ok: <powód>`.
- **Harness `/preview/*` ma zasiany KAŻDY stały klucz react-query**
  (`app/preview/__tests__/harness-seeds.test.ts`). Klucz, który się rozjechał
  z komponentem, uruchamia `queryFn` → 401 → przerzut na `/login`, czyli
  harness przestaje pokazywać cokolwiek — tak przestał działać
  `/preview/contracts-consolidation`, gdy `AddProjectDialog` dołożył do klucza
  klientów drugi element. Strażnik pomija `invalidateQueries` (nie pobiera) i
  klucze z parametrami (zależą od stanu), a komentarze wycina przed
  porównaniem — inaczej klucz wymieniony w komentarzu uciszałby go sam.
- **`detail` z FastAPI nigdy nie jest „na pewno stringiem"** — bywa obiektem
  albo tablicą walidacji. Tekst błędu do stanu, toasta lub alertu budujesz
  wyłącznie przez `apiErrorMessage(error, fallback)` z `@/lib/api-error`
  (czysty moduł: bez axios, więc bezpieczny dla stron publicznych i nie ginie
  pod mockiem `@/lib/api` w testach komponentów). `extractErrorMsg` stoi na tej
  samej funkcji. Test `api-error-detail-guard.test.ts` czyta źródła i odrzuca
  `data?.detail ??`/`||` oraz rzutowania `data?: { detail?: string }` — na
  `origin/main` sprzed zmiany znajdował 117 takich miejsc w 48 plikach.
  Odczyty strukturalne (`detail?: unknown` + sprawdzenie typu, np.
  `{missing}`/`{blockers}`) są w porządku.

## Narzędzia rekrutera — reguły po audycie 17.09.2026

Audyt `docs/recruiter-tools-audit-2026-09-17.md`, raport z poprawek
`docs/recruiter-tools-fixes-completion-report.md`. Decyzje Artura, które łatwo
cofnąć „przy okazji”:

- **Bramka „Pending” USUNIĘTA** (wyłączona 17.09.2026, kod skasowany 18.09.2026
  — szczegóły w sekcji „Kanban bez bramek”). Ruch na „Zweryfikowany” ze stawką
  ponad budżet przechodzi jako `active`, a przekroczenie jedzie na kartę jako
  informacja (`budget_exceeded`, odznaka „ponad budżet”). Trasy akceptacji /
  odrzucenia i `/pending-verifications` nie istnieją, UI kolejki usunięte
  (`/pending-verifications` → 308 na `/jobs`, bo stare powiadomienia w bazie
  nadal tam linkują). Stare wiersze `pending` zalicza jednorazowo
  `pending_verification_promotion.py` (blok w `entrypoint.sh`, znacznik
  `pending_verification_promotion_2026_09_17`): status `active`
  + `record_accepted_verification`, `approved_by` puste.
- **Head of Recruitment = parytet z rekruterem.** HoR jest w `RecruiterPlus`,
  `CANDIDATE_WRITE_ROLES` i zbiorach `recruitment_access` (ruchy, notatki,
  przypisania, pliki, kalendarz). Front bramkuje zapis na profilu capability
  `candidate.write` (lustro `CandidateWriteAccess`), nie samą sekcją. HoR nadpisuje
  cudze werdykty HM i feedback z rozmów (jak DL). W kalendarzu HoR edytuje cudze
  wydarzenia, ale **odwołać/usunąć** (także PATCH `status=cancelled`) może tylko
  właściciel albo admin — `user_can_remove_event`, flaga `can_remove` w odpowiedzi.
- **Stawka do klienta** (`PATCH …/client-rate`): role admin/HoR/DL/TCM/TAC/finance
  z członkostwem w rekrutacji ALBO właściciel/twórca rekrutacji niezależnie od
  roli. Jedna funkcja `resolve_client_rate_write` zasila bramkę i
  `can_write_client_rate` w `GET /api/jobs/{id}`; tablica i warsztat CV pytają
  o stawkę tylko przy `true`.
- **Wyszukiwarka, tryb semantyczny:** sort i chipy „podbijające ranking” działają
  też w hybrydzie (`_resort_hybrid_pool`: soft-ranki → sort → pozycja RRF). Bez
  chipów i przy „Trafność” kolejność RRF zostaje nietknięta.
- **Werdykt HM z karty rekrutacji zapisuje WYŁĄCZNIE wiersz bez wydarzenia.**
  Wiersz przypięty do rozmowy opisuje tę rozmowę, a FK ma `ON DELETE CASCADE`
  — nadpisanie go gubiło notatkę rundy 1 i kasowało werdykt z karty razem ze
  spotkaniem. Lista pokazuje ostatnio zmieniony wiersz pary (`updated_at`).
- **Kalendarz:** wydarzenia z Outlooka się ODWOŁUJE (`POST …/cancel`, Graph
  cancel → fallback DELETE), a `DELETE` na nich daje 409; `isAllDay`/iCal `DATE`
  → `all_day` (poza kolizjami, przypomnieniami i pasami siatki); przypomnienie
  czyta `reminder_minutes` i linkuje `/calendar?event=`. Picker rekrutacji
  w kalendarzu auto-wybiera i udostępnia tylko rekrutacje z `can_schedule`
  (członkostwo) — cudza podstawiona sama kończyła zapis 403.
- **Powiadomienia:** `stage_stuck_7d` tylko opublikowane rekrutacje, etap 7–30 dni,
  raz na tydzień per etap, z nazwiskiem i etykietą; resurface porównuje dobę
  Warsaw jak `ix_notif_dedup_daily` i zapisuje w savepoincie; `own_unread_count`
  steruje „Oznacz wszystko” (oznacza tylko własne); odświeżenia dzwonka po
  wiadomościach czatu są zlewane (`CHAT_REFRESH_COALESCE_MS`).
- **Powiadomienie z triggera ma JEDNĄ bramkę odbiorcy i JEDEN helper
  rekrutacji (od 18.09.2026).** `emit()` w `notification_triggers.py` pyta
  `notification_recipient_has_access` (`is_active` + polityka sekcji) — to
  jedyne wąskie gardło wszystkich producentów, więc nowy trigger nie ma jak go
  obejść; sprawdzanie per trigger rozjeżdża się przy pierwszym dopisanym.
  Mierzone przed zmianą: 10,5% powiadomień z 90 dni szło na konta NIEAKTYWNE
  (`stage_stuck_7d` w 30 dni: 1 701 do 4 kont nieaktywnych vs 903 do 3
  aktywnych), a konta dezaktywowane odtwarza nocny sync Traffita i nadal bywają
  właścicielami rekrutacji, więc to się nie naprawiało samo. Konsekwencja:
  **typ spoza `NOTIFICATION_SECTION_BY_TYPE` jest teraz odrzucany przy ZAPISIE**
  (dotąd zapisywał się i był niewidoczny dopiero przy odczycie) — pilnuje tego
  kontrakt w `test_notification_fanout.py`. Rekrutacje czyta wyłącznie
  `_open_jobs_by_id` (`status == published`); nieprzefiltrowany `_jobs_by_id`
  USUNIĘTY, bo to rozwidlenie było przyczyną: poprawka z 17.09 objęła jedną
  z dwóch gałęzi i `dl_stage_stale_6h` uzbierał 52 263 powiadomienia, z tego
  59,3% o rekrutacjach ZAMKNIĘTYCH, przeczytane: 1.
- **`GET /api/cv-generator/clients/{id}/rule-for-generation`** (bramka
  `CandidateWriteAccess`) zwraca notatkę i instrukcje DL tylko przy
  `can_view_knowledge` klienta — reszta roli dostaje same wymogi formularza.
- **Etykiety dostępności w wyszukiwarce** idą z `lib/search-availability.ts`
  („Otwarty na oferty”), nie z `lib/filter-options.ts` („Otwarty na projekty”).

## Jarvis — asystent-agent w shellu (0330, zastępuje MINDY)

Maskotka w prawym dolnym rogu każdego ekranu (⌘J, paleta ⌘K „Zapytaj Jarvisa”)
dla KAŻDEJ zalogowanej roli (decyzja Artura 21.09.2026). Odpowiada na pytania
o dane NEXUSA i przygotowuje zadania. Raport: `docs/jarvis-assistant-completion-report.md`.
Backend: `app/api/jarvis.py` + `app/services/jarvis/`; front: `components/jarvis/`,
`lib/jarvis/`; harness `/preview/jarvis`.

- **Jarvis nie ma własnych uprawnień.** Narzędzie = wywołanie ISTNIEJĄCEJ trasy
  in-process (`httpx.ASGITransport`) z tokenem z żądania (`transport.py`).
  Bramki sekcji, członkostwa, portfela DL i redakcja kwot działają same. Nie
  dokładaj narzędzia z własnym SQL-em ani wołaniem handlera wprost — snapshot
  sekcji dokleja tylko `get_authenticated_user`.
- **Trzy poziomy (`tools.py`):** `read` wykonywany od razu; `write` model tylko
  PROPONUJE (`jarvis_actions.status=proposed`, karta w UI), wykonanie dopiero
  po `POST /api/jarvis/actions/{id}/confirm` klikniętym przez człowieka — i to
  DOKŁADNIE z zapisanymi `args`, idempotentnie (`proposed → confirmed` warunkowym
  UPDATE, TTL 15 min); `link` (`open_screen`) — operacje krytyczne (usuwanie,
  wypowiedzenie, podpis, stawki, maile, generatory, admin) NIGDY nie są
  wykonywane, Jarvis daje przycisk do ekranu. Listę zakazaną i „read ⇒ trasa
  odczytu” pilnuje `test_jarvis_tool_registry_contract.py`.
- **`acknowledge_eligibility` nie jest w schemacie narzędzia** — ustawia go
  wyłącznie serwer po prawdziwym 409 `ELIGIBILITY_WARNING` (druga karta „mimo
  ostrzeżenia”). Kalendarz bez `attendees`/`teams_link` — Jarvis nie zaprasza ludzi.
- **Karta akcji jest budowana przez SERWER** z args + nazw doczytanych przez API
  (`_display_names`); `sanitize_args` wycina klucze spoza schematu (model nie
  wstrzyknie `_display`). Etap przy przesunięciu idzie z tablicy, nie ze słów modelu.
- **Tylko Anthropic** (`AIFeatureKey.jarvis` → Sonnet 5, fallback Haiku) —
  `llm_providers` odrzuca `tools` dla GPT/DeepSeek. Cała tura = jedna operacja
  `ai_feature(jarvis)`. `claude_client` liczy koszt narzędzi KLIENCKICH zwykłym
  cennikiem (`_has_server_tools`); do 0330 każde `tools` = „unpriced”.
- **Prompt systemowy stały bajt w bajt** (cache); data, rola, ekran, imię
  nadane przez użytkownika idą blokiem `[Kontekst…]` w wiadomości użytkownika.
  Po tym znaczniku liczy się też miękki licznik dzienny (`JARVIS_DAILY_SOFT_LIMIT`,
  informuje, nie blokuje).
- **Pętla nie trzyma połączenia DB** podczas modelu i narzędzi (`store.py` —
  krótkie sesje). Jedna tura na osobę (`busy_until`, 409). Historia jest
  naprawiana przed wysłaniem (`repair_history`): `tool_use` bez wyniku (deploy
  uciął turę) dostaje syntetyczne „przerwane”. SSE z heartbeatem 10 s; rozłączenie
  klienta nie przerywa tury.
- **Tag `via: jarvis`** w `activities.details` bez dotykania 241 miejsc
  `Activity(`: nagłówek `X-Jarvis-Internal` z sekretem PROCESU → `stamp_via`
  w `deps.get_authenticated_user` → listener `before_flush` (`via_tag.py`).
  Nagłówek z przeglądarki nic nie daje.
- **RODO:** rozmowy wiążą kandydatów w `jarvis_conversation_entities` (args,
  `candidate_id` w wynikach, `/candidates/{id}`, wiersze narzędzi kandydackich,
  ekran). `DELETE /api/candidates/{id}` kasuje całe powiązane rozmowy
  (`jarvis/erasure.py`, licznik w audycie). Retencja 30 dni (`jarvis_retention`,
  biegnie niezależnie od `JARVIS_ENABLED`).
- **Tryb „podgląd jako” = Jarvis niedostępny** (403 na trasach, front chowa).
- **Kill-switch `JARVIS_ENABLED` domyślnie `false`**; włączenie przez workflow
  „Coolify set env”. Wyłączony: brak maskotki (poza trybem kids), trasy 503.
- **Jedna maskotka:** `KidsMascot` usunięta, jej zachowania (slogany, konami,
  `celebrate`) żyją w `useKidsChatter`; `kidsBuddy` zdjęty ze store'u motywu (v8).
  Postaci to gotowe ilustracje SVG na klasach `j-*` (`globals.css`), lista =
  `prefs.py` `JarvisCharacter` (test w `jarvis-lib.test.ts`); `robot_gold`/`trophy`
  odblokowuje `competition_winners` (rank 1 / ≤3), PATCH odrzuca zablokowaną 403.
- **⌘J = Jarvis, ⌘⇧J = nowa rekrutacja** (goły `j` bez zmian).
- **Endpointy MINDY (`/api/dynareporter/mindy/*`) usunięte** (21.09.2026) —
  wraz z ich zwolnieniem z blokady `DYNAREPORTER_MODE=read_only`. Wartość enuma
  `mindy_chat` ZOSTAJE (Postgres nie ma `DROP VALUE`, historia kosztów ją
  niesie), razem z wpisem w rejestrze modeli. Strona `/dynareporter/mindy`
  i przekierowania `/mindy`, `/chat` prowadzą do informacji o Jarvisie.
  Powrót routera łapie `test_mindy_endpoints_are_gone`.
- **Internet = przełącznik 🌐 na JEDNĄ wiadomość** (`web: true`, 21.09.2026,
  `services/jarvis/web.py`). Zasada: internet ALBO baza, nigdy oba. Tura z
  internetem dostaje wyszukiwarkę Anthropic (`web_search_20250305`,
  `JARVIS_WEB_MAX_SEARCHES_PER_TURN`) i WYŁĄCZNIE narzędzia z `WEB_SAFE_TOOLS`
  (Pomoc + link); nie dostaje historii rozmowy ani ID rekordu z ekranu — dane
  z NEXUSA nie mają jak trafić do zapytania na zewnątrz (RODO, wstrzyknięcie
  z CV). Twardy limit `JARVIS_WEB_DAILY_LIMIT` (429), wyłącznik
  `JARVIS_WEB_ENABLED`, domeny `JARVIS_WEB_ALLOWED_DOMAINS`/`_BLOCKED_DOMAINS`.
  Źródła (tylko http(s), z wyników wyszukiwarki, nie z tekstu modelu) idą
  zdarzeniem `sources` i blokiem `x_sources`, który `repair_history` odfiltrowuje
  przed wysłaniem do API. `pause_turn` jest kontynuowany surowymi blokami.
  Koszt: `ai_metering` dolicza 0,01 USD za wyszukiwanie
  (`usage.server_tool_use.web_search_requests`); `web_search_*` NIE jest już
  „unpriced”. Dokładając narzędzie do `WEB_SAFE_TOOLS` — tylko takie, które nie
  czyta danych osobowych ani biznesowych.
- **Dodając narzędzie:** wpis w `tools.py` (opis PL, `label`, `section`, `shape`
  przycinający wynik; zapis: `preview` + `done` + `invalidates`), test kontraktowy
  przechodzi sam, jeśli trasa istnieje i poziom się zgadza. Dokładając trasę
  pod `/api/jarvis/*` — wpis w `_BARE_BASELINE` i `_SECTIONLESS_ALLOWLIST`.

## „Moi ludzie" — lista rekrutera, dzwonek przy nowej rekrutacji, postać w rogu (21.09.2026)

Rekruter wysyła tych samych ludzi do klientów raz za razem, aż któryś projekt
się zamknie. „Moi ludzie" to ta lista: buduje się sama, jest pod ręką z każdego
ekranu (przycisk w topbarze, skrót `m`, postać w rogu), a publikacja rekrutacji
od razu mówi, kto z listy pasuje. Migracja `0334_my_people` (+ lustro
w `entrypoint.sh`, sondy w `/api/health/deep`). Raport:
`docs/my-people-completion-report.md`.

- **Właściciel osoby = PIERWSZY weryfikator** pary (kandydat, rekrutacja), która
  potem doszła do `cv_sent` — ktokolwiek wysłał CV (decyzja Artura 21.09).
  Para bez żadnej weryfikacji (import Traffita pomija etap) → autor pierwszego
  `cv_sent`. Para bez `cv_sent` nie tworzy listy. **Bez limitu czasu** —
  porządek robi ręczne „Uśpij". Liczone WPROST z `candidate_stages`
  (`services/my_people.py`, indeks `ix_candidate_stages_moved_by_stage`),
  **nie** przez `VERIFIER_ANCHORED_CTE` — tamto płaci nagrody i nie wolno go
  ruszać przy okazji.
- **Nazwa w UI to „Moi ludzie", nie „ławka"** — `EmploymentState.on_bench`
  znaczy już „konsultant bez projektu", a „shortlista" to `JobShortlist`.
- **Grupy:** aktywni po primary CC (`candidate_competence_categories`, fallback
  `competence_category_id`, reszta „Pozostałe"); **„Pracują"** = żywa umowa
  (`current_employment`) — osoba nie znika, ale nie ma przycisku „Dodaj";
  **„Uśpieni"** (`my_people_overrides.kind='snoozed'`, powód obowiązkowy —
  CHECK). „Przypnij" (`kind='pinned'`) dokłada osobę spoza wyliczenia; jeden
  wiersz na (użytkownik, kandydat), nowsza decyzja nadpisuje. Globalna
  blacklista wyklucza zawsze.
- **Dzwonek `my_people_match`** (`services/my_people_matching.run_for_job`)
  jedzie na kolejce auto-matcha: `tasks/candidate_auto_match._run_my_people`
  po `run_job_event`, w savepoincie — zwykły błąd nie cofa auto-matcha,
  `AutoMatchUnavailable` (Qdrant) PRZECHODZI dalej, żeby zdarzenie się
  powtórzyło. Działa niezależnie od `AUTO_MATCH_DRY_RUN` (niczego nie dodaje),
  ale przy `AUTO_MATCH_ENABLED=false` stoi (nie ma zdarzeń). Wyłącznik
  `MY_PEOPLE_MATCH_ENABLED`; próg `MY_PEOPLE_MATCH_MIN_SCORE` (70), sufit
  `MY_PEOPLE_MATCH_MAX_PER_USER` (10), pula `MY_PEOPLE_MATCH_POOL` (200).
  Jeden dzwonek na (odbiorca, rekrutacja), link `/jobs/{id}?people=1`, i tylko
  przy NOWYCH wierszach `my_people_job_matches` (UNIQUE na trójce) — istotna
  zmiana rekrutacji nie budzi drugi raz tymi samymi nazwiskami.
- **Liczba to kanoniczny fit** (`canonical_fit.score_candidates`), ta sama co
  na ekranach C2 — NIE `rank_candidates_for_job`. Niezmierzony = `None`, nigdy
  0 i nigdy w dzwonku. `hidden` (blacklista, duplikat) odpada, ostrzeżenia
  (konflikt klienta, weto HM) jadą jako plakietka; weto HM blokuje „Dodaj".
  Dzwonek liczy profilem wag klienta (`user_id=None`), zakładka panelu
  profilem patrzącego — przy profilach per użytkownik liczby mogą się różnić.
- **Zakładka „Do tej rekrutacji"** (`GET /api/my-people/for-job/{id}`, bramka
  `_authorized_job` jak `/scores`, limit 20/min) liczy na żądanie do
  `MY_PEOPLE_PANEL_POOL` (60) najbliższych wektorowo; awaria Qdranta =
  `degraded: true` i komunikat „nie znaczy, że nikt nie pasuje", nigdy pusta
  lista. Obejrzenie zakładki zeruje dopasowania tej rekrutacji w liczniku
  (`POST /matches/seen` — GET zostaje tylko do odczytu).
- **Front:** panel to NIEMODALNY `<aside>` z-40 (`components/v2/my-people/`),
  kontekst z `usePathname()`; widoki prezentacyjne w `MyPeopleViews.tsx`
  (harness `/preview/my-people`, zero zapytań). Capability `nav.my_people` =
  lustro `nav.candidates` (`CandidateSearchAccess`). Dodanie idzie przez
  `proposals/bulk` ze źródłem **`my_people`** (lustra: `BulkAddSource`
  w `proposals_bulk.py` i `candidate-search-api.ts`, `PIPELINE_ADD_SOURCES`
  w telemetrii). WS `pipeline_changed` unieważnia listę i zakładkę rekrutacji,
  ale NIE podsumowanie (liczy całą listę); WS `notification` typu
  `my_people_match` unieważnia wszystko.
- **Postać w rogu** mówi wyłącznie zdaniami z szablonów
  (`lib/my-people-summary.summarySentences`, zero AI), raz na sesję dla tej
  samej treści (`sessionStorage`), pulsuje tylko licznik. **Ustępuje maskotce
  Jarvisa** (ten sam róg; `useJarvisOwnsCorner` = lustro `showMascot`
  z `JarvisRoot`, te same klucze zapytań — także w trybie Kids), chowa się na
  `/jobs/{id}` (róg zajmuje dok kanbanu),
  przy otwartym panelu i po „Ukryj postać" (`useUiStore.hideMyPeopleBuddy`,
  przywracane checkboxem w stopce panelu). Główne, dostępne wejście to
  przycisk w topbarze.
- **Jarvis przypomina o przepinaniu** (21.09.2026): narzędzia odczytu
  `my_people` i `my_people_for_job` (tylko osoby do przepięcia; brak wyniku =
  `"niepoliczony"`, weto HM = `nie_mozna_dodac`), sekcja „PRZEPINANIE" w
  prompcie, poranny skrót dnia dostaje `briefFragments` (nowe dopasowania,
  czekający > 30 dni), a dzwonek `my_people_match` → zdarzenie okna
  `nexus:my-people-match` (z `useNotifications`) → dymek Jarvisa, którego
  kliknięcie wysyła `reassignPrompt(jobId)` i kończy się kartą
  `add_candidates_to_job` do potwierdzenia. Świadomie tylko DWA momenty
  (poranek + nowa rekrutacja) — częstsze przypomnienia uczą ignorowania.
  Działa dopiero przy `JARVIS_ENABLED=true`.
- **Poza zakresem świadomie:** widok HoR „czyja lista leży", zmiana atrybucji
  wyścigów.

## Kalendarz = „Rozmowy u klienta” (0338, 22.09.2026)

`/calendar` był kopią Outlooka trzech osób: 10 wydarzeń założonych w NEXUSIE
w całej historii, 0 w ostatnich 90 dniach, 0 feedbacków. Zespół nie umawia
w NEXUSIE screeningów ani rozmów. Planuje prep i drugi prep oraz musi znać
termin rozmowy kandydata U KLIENTA, żeby zadzwonić ≤30 min po niej. Ekran
prowadzi teraz jeden cykl per para (kandydat, rekrutacja):
`Terminy od klienta (DL) → Wybór terminu (rekruter) → Prep → Prep 2 →
Rozmowa u klienta → Telefon ≤30 min → Debrief`. Raport:
`docs/calendar-client-interview-cycle-completion-report.md`.

- **Trzy widoki tych samych danych** (`?view=agenda|week|board`, domyślnie
  agenda): Agenda („Do zrobienia” + dziś/jutro + karta kandydata z 7 krokami
  i pytaniami klienta), Tydzień (dawna siatka, `components/calendar/WeekCalendar.tsx`,
  zachowanie `?event=`/`action=feedback` bez zmian) i Tablica (7 kolumn).
  `?event=` zawsze otwiera Tydzień. Zakres `?scope=mine|jobs|all`: DL/TAC
  domyślnie `jobs`, reszta `mine`, `all` tylko admin/HoR (403).
- **Kroki i zadania liczy SERWER** (`services/interview_cycle.py`, czyste
  `compute_steps`/`compute_todos` + hurtowe `load_overview`, stała liczba
  zapytań). Front (`lib/interview-cycle.ts`) tylko prezentuje. Para jest „w cyklu”,
  gdy ma otwarty wniosek o terminy, prep/rozmowę u klienta w oknie −14/+30 dni
  albo najnowszy etap „Rozmowa z klientem” z ostatnich 30 dni.
- **Terminy od klienta = `client_interview_slot_requests`** (`services/interview_slots.py`):
  `awaiting_recruiter → awaiting_dl → confirmed | cancelled`, przejścia pod
  `FOR UPDATE`, jeden OTWARTY wniosek na parę (częściowy UNIQUE → 409). Dodaje
  i potwierdza WYŁĄCZNIE admin/HoR/DL/TAC z członkostwem w rekrutacji; wybiera
  rekruter wniosku (domyślnie: właściciel procesu → pierwszy weryfikator →
  `job.recruiter_id`) albo członek zespołu. Potwierdzenie zakłada wydarzenie
  `EventType.client_interview` z `operational_owner_id` = rekruter i opcjonalnie
  blokadę w JEGO Outlooku bez uczestników (kandydata zaprasza klient; awaria
  Grapha nie blokuje potwierdzenia: `outlook="failed"`).
- **Telefon po rozmowie = istniejące wyzwalacze `post_interview_*`**, poszerzone
  o `client_interview` (`_POST_INTERVIEW_EVENT_TYPES`). Dla rozmowy u klienta:
  strona KANDYDATA (dzwoni rekruter, nie zbiera feedbacku klienta), odbiorca =
  właściciel wydarzenia, link `/calendar?cycle=c-j&debrief=<id>` (ekran otwiera
  okno debriefu). `calendar_auto_complete` też kończy `client_interview`.
  Okno na agendzie: `POST_INTERVIEW_CALL_WINDOW_MINUTES` (30).
- **Debrief = `InterviewFeedback(candidate_side)` pod wydarzeniem rozmowy**
  (`PUT /api/interview-cycle/events/{id}/debrief`, upsert): jak poszło
  (`overall_impression` 5/3/1), komentarz (`concerns`), pytania klienta
  (`client_questions` + bank `InterviewQuestion(source=client_debrief, client_id)`
  + pin `JobQuestion`), `offer_acceptance` (yes/likely/no/unknown) i
  `acceptance_condition` (nowe kolumny). Pytanie bez klienta NIE trafia do
  banku — globalny bank wyciekłby do prepów innych klientów.
- **Prep-kit ma warstwę `client_debrief`** (zaraz po przypiętych, filtrowana
  `_fits_job`) — pytania tego klienta z poprzednich rozmów. Prep z ekranu to
  `ScheduleInterviewModal` z `defaultEventType="prep_call"`; `prep_call`
  domyślnie dostaje Teams (lustro `_TEAMS_DEFAULT_EVENT_TYPES` ↔ `TEAMS_DEFAULT_FOR`).
- **„Oba kierunki” z Outlookiem:** PATCH terminu/tytułu/miejsca/opisu wydarzenia
  z Outlooka idzie NAJPIERW do Grapha organizatora (`update_graph_event`,
  czas w `BUSINESS_TZ` bez przesunięcia — `_graph_datetime`), dopiero potem do
  bazy. Brak połączenia twórcy / 400/403/404 = 409 i ZERO zmian lokalnie
  (zapis tylko w NEXUSIE sync by cofnął). Uczestnicy, cały dzień i link Teams
  zostają Outlookowi. Synchronizacja działa tylko dla osób z połączonym M365.
- Harness `/preview/calendar-cycle` (`?as=dl`) — dane fikcyjne, zero zapytań
  (dane agendy przez `dataOverride`, reszta zasiana w cache).

## Dwa silniki wyszukiwania — jedna semantyka filtrów (09.2026)

NEXUS ma DWA silniki wyszukiwania kandydatów, które UI połączy w jeden ekran
„Kandydaci": **L** = `GET /api/candidates` (lista, ⌘K, eksport, alerty
zapisanych wyszukiwań) i **S** = `POST /api/search/candidates` (+ `/diagnostics`;
`/candidates/search` i ręczne szukanie w rekrutacji). Do 09.2026 rozjeżdżały się
w 11 miejscach (`docs/sesja-2026-07-28-completion-report.md`). Filtry wspólne
buduje WYŁĄCZNIE `app/services/candidate_search_predicates.py` — oba endpointy
czytają je stamtąd (także warianty legacy), prywatne kopie są zakazane
(`test_candidate_search_predicates.py` czyta źródła). Sortowanie, stronicowanie,
retrieval hybrydowy i diagnostyka zostają przy endpointach.

- **`semantics_version` rozstrzyga WSZYSTKO. Brak pola = v1 = DOKŁADNIE
  dotychczasowe wyniki każdego endpointu, łącznie z rozjazdami** (lista wycina
  osoby bez stawki/lokalizacji/stażu i czyta samą kolumnę `location`;
  wyszukiwarka dopasowuje tag podłańcuchem, liczy tylko kategorię główną, łączy
  „Otwarty na" koniunkcją, nie czyta koszyka Traffita i nie przełącza `q`
  wyglądającego na osobę). Całe nowe zachowanie jest opt-in: `semantics_version: 2`
  (pole w S, parametr w L) — wtedy oba silniki odpowiadają identycznie.
  Dowody: `test_saved_search_legacy_replay.py` (31 ładunków legacy; ten sam plik
  przechodzi na `origin/main` sprzed zmiany i po niej) oraz
  `test_search_engines_contract.py` (każda decyzja w v2: ten sam zbiór id z L i S).
  **Nie zmieniaj zachowania v1 „przy okazji" — na nim stoją alerty.**

Semantyka v2 (decyzje właściciela produktu, wiążące dla OBU endpointów):

| Filtr | Reguła v2 |
|---|---|
| Umiejętności | trzy kubełki: „Musi mieć" = TWARDO · „Mile widziane" = tylko ranking (także na liście — prowadzi każde sortowanie) · „Wyklucz" = TWARDO; bez kubełka → „Musi mieć". Jawne pola: `skills_required[]`, `skills_required_any_groups` (S: lista list; L: powtarzany parametr `a\|b`), `skills_preferred[]`, `skills_excluded[]`. `a\|b` = grupa LUB w KAŻDYM polu. Tag „java" nadal spełnia umiejętność „Java" (tagi są częścią zrzutu). |
| Tekst `q` | `text_mode: auto\|literal\|semantic`. Auto: e-mail, telefon, 2–3 wyrazy wyglądające na osobę → dopasowanie DOSŁOWNE (to samo w L i S: `literal_text_clause`); JEDNO słowo dosłownie TYLKO, gdy istnieje kandydat o takim imieniu, nazwisku albo członie nazwiska dwuczłonowego („Kowalska" → „Nowak-Kowalska") (`person_token_exists`: jedno `LIMIT 1` po indeksie trigramowym `search_doc_unaccented`, pamięć 60 s); reszta → tryb wybrany przez rekrutera. `interpretation.rule` mówi, która reguła zadziałała. W v1 auto działa tylko przy jawnym `text_mode`. |
| Brak danych | osoba BEZ lokalizacji / stażu / stawki ZOSTAJE i jest oznaczona w `unknown_fields: ["location","experience","rate"]` (tylko dla AKTYWNYCH filtrów); `hide_unknown: true` ją ukrywa. Stawka w walucie innej niż PLN = nieznana. |
| „Otwarty na" | LUB; `open_to_*: false` zostaje osobnym, twardym warunkiem |
| Kategoria kompetencji | główna LUB poboczna (M2M) LUB legacy FK |
| Lata doświadczenia | jedna reguła przedziału: dokładna liczba, a gdy jej brak — koszyk Traffita |
| Tagi | cały tag (token JSON, bez wielkości liter), nie podłańcuch |
| Lokalizacja | `city` LUB `location`, `%`/`_` dosłownie, bez polskich znaków; kilka miast (`location_cities`) i kraj w obu |
| `q_all`/`q_any`/`q_none` | jeden parser (`parse_q_groups`; grupa jako lista albo `a\|b`) |
| status / dostępność | zgodne w obu wersjach — przypięte testem |

- **Pola legacy umiejętności znaczą w L i S co innego — w OBU wersjach.** L:
  `skills` (+`skill_combine`), `skills_any`, `skills_none` są TWARDE. S:
  `skills_must` + `skills_any` to „Mile widziane" (SEARCH-P0-03), twarde jest
  tylko `skills_none`. Zgodne są dopiero pola jawne.
- **Lista nie ma retrievalu wektorowego** (do połączenia ekranów): przyjmuje
  `text_mode`, ale zawsze dopasowuje dosłownie i mówi to w `text_mode_applied`.
- **Diagnostyka zna twarde kubełki**: grupa `skills_required` („Musi mieć") obok
  `skills` („Wyklucz"); nowa grupa filtrów = wpis w `NULL_POLICY`.
- **Parser wyrażenia umiejętności ma port w Pythonie** (`parse_skill_expression`)
  i WSPÓLNY plik przypadków `frontend/src/lib/__fixtures__/skill-expression-cases.json`.
- **Nowy wspólny filtr:** builder w `candidate_search_predicates` (z wariantem
  v1, jeśli filtr już istniał), wpięcie w OBU endpointach, przypadek w obu
  plikach testów. Kanoniczny fit (`canonical_fit`, `scoring_service`) NIE jest
  tą zmianą dotykany.

### Zapisane wyszukiwania: format v3 i migracja na wspólną semantykę

- **Jeden format zapisu** (`version: 3`, `semantics_version: 2`, `origin`,
  `request`, `qs` z `sv=2`, `legacy`, `migration`) i adapter czytający OBA
  formaty legacy: `app/services/saved_search_payload.py` ↔
  `frontend/src/lib/saved-search-unified.ts`, wspólny plik przypadków
  `__fixtures__/saved-search-unified-cases.json`. `request` ma kształt wspólny
  + `list_only` / `search_only` dla filtrów jednego silnika. Najstarszy format
  listy `{qs}` bez `api` jest nieczytelny po stronie Pythona — zostaje nietknięty.
- **Migracja (`services/saved_search_migration.py`)** porównuje wynik v1 i v2
  przez PRAWDZIWE endpointy (token właściciela, do 500 id + `total`).
  **Zapis z LISTY migruje z flagami neutralizującymi** (`neutralise_list_request`:
  `hide_unknown: true` + `location_scope: "location_only"`), więc zwraca
  DOKŁADNIE to, co dotąd, i alerty się nie poszerzają; zapis z WYSZUKIWARKI
  zostawia osoby bez danych widoczne (tak działał zawsze). Nowo tworzone zapisy
  biorą zwykłe domyślne v2. Identyczny wynik → po cichu; inny (to, czego flaga
  nie wyrazi: `%`/`_` w lokalizacji, cały tag, kategoria poboczna, „Otwarty na"
  = LUB, koszyk Traffita, `q`-osoba) → `requires_reapproval=true`, alert
  WSTRZYMANY (`filters.migration.alert_was_on`), `diff` z samych LICZB + kody
  reguł `diff.rules` (`saved_search_payload.RULE_*`; statyczne „reguły, które
  dotyczą tego zapisu", nie atrybucja per osoba) i JEDNO powiadomienie
  `saved_search_reapproval` (migracja `0336_saved_search_reapproval_notif` +
  lustro w `entrypoint.sh`). Idempotentna (v3 i zapisy przypięte do v1 są
  pomijane). Tryb hybrydowy z `q` nie jest odtwarzany (embeddingi). Nieaktywny
  właściciel → do akceptacji bez powiadomienia. Najstarsze `{qs}` bez `api` są
  tylko liczone (`unreadable_ids`).
- **Decyzja właściciela zapisu = istniejące `confirm_reapproval`**
  (`PATCH /api/saved-searches/{id}`) + `reapproval_choice`: `accept`
  („Zatwierdź nowe wyniki") wznawia alert i ZERUJE linię bazową
  (`last_scanned_at`) — pierwszy przebieg skanera zasiewa dziennik nowym zbiorem
  bez alertu, zero burzy `saved_search_match`; `keep_legacy` („Zostaw po
  staremu") przywraca ORYGINALNY ładunek z `filters.legacy` ze znacznikiem
  `keep_legacy_semantics` — zapis zostaje przy v1 (jedyny sposób na te same
  wyniki, gdy różnicy nie wyraża żadna flaga), linia bazowa zostaje, a kolejne
  przebiegi migracji go omijają (`pinned`). UI: panel w `SavedSearchesMenu`
  („Zmieniły się zasady wyszukiwania", liczby przed/po, kody przetłumaczone
  w `lib/saved-search-reapproval.ts`) — osobny od plakietki po wycofaniu
  stawek miesięcznych (tamten zapis nie ma `filters.migration`).
- **Uruchomienie:** `POST /api/saved-searches/migrate-semantics[?dry_run=true]`
  (admin; odpowiedź = liczniki + id) albo przy starcie skanera alertów, gdy
  `SAVED_SEARCH_SEMANTICS_MIGRATION_AUTORUN=true` (domyślnie OFF — migracja
  wstrzymuje alerty i powiadamia ludzi, moment wybiera człowiek). Paragon:
  `app_settings['saved_search_semantics_migration_v3']`.
- **Skaner alertów** (`alert_list_params`): v3 → ścieżka wspólna
  (`unified_to_list_params`, `semantics_version=2`), legacy → `filters.api` bez
  zmian. Zapis v3 z filtrami, których lista nie zna (`list_engine_gaps`: języki,
  źródła…), NIE jest odtwarzany — alert byłby szerszy niż zapis.
- **UI do połączenia ekranów:** lista czyta `sv=2` z querystringu zapisu
  (`CandidateFilters.semanticsVersion` → `semantics_version=2`), widok
  wyszukiwarki otwiera v3 przez `savedSearchToSearchViewRequest`. Stary ekran
  nadal ZAPISUJE formaty legacy (v1) — kolejny przebieg migracji je podniesie.
## Własny pulpit startowy (0337, 21.09.2026)

`/dashboard` to od 21.09.2026 pulpit, który każdy układa sam z kafelków
(decyzje Artura: start od PUSTEGO pulpitu z poleceniami dla roli, katalog
gotowych kafelków + kreator własnej metryki, siatka 12 kolumn z przeciąganiem
i zmianą rozmiaru, JEDEN pulpit na osobę, stare presety ról usunięte od razu,
finanse w kreatorze od razu). Raport: `docs/custom-dashboard-completion-report.md`.

- **Układ = `user_dashboards` (0337)**, jeden wiersz na osobę, `layout` JSONB +
  `version`. `GET/PUT /api/users/me/dashboard`; PUT wymaga `expected_version`
  (409 `DASHBOARD_VERSION_CONFLICT` = inna karta zapisała wcześniej). Kształt
  pilnuje `services/dashboard_tiles.py` — ściśle przy zapisie (422 po polsku),
  łagodnie przy odczycie (nieznany typ odpada do `dropped_tiles`, pulpit się
  otwiera). Linki w notatce: tylko `https://` i ścieżki `/…` (XSS).
- **Nowy kafelek = cztery miejsca:** `TileType` (backend), `TILE_TYPES`
  (`lib/api/userDashboard.ts`), definicja w `lib/dashboard-tiles/catalog.ts`
  i `case` w `components/v2/dashboard/custom/TileContent.tsx`. Pierwsze dwa
  pilnuje `test_dashboard_tile_types_mirror.py`.
- **Gotowe kafelki to widżety ze starego pulpitu ról OPAKOWANE, nie przepisane**
  (każdy sam pobiera dane i ma swoje bramki). Dostępność w katalogu jest lustrem
  dawnych bramek `RoleDashboard` (sekcja, nie sama rola). `PriorityWorkIsMounted`
  pilnuje, że Priority Work ma wejście z katalogu.
- **Kreator metryki: `POST /api/dashboard-metrics/evaluate`** (POST tylko do
  odczytu — w `READ_ONLY_POST_ROUTE_TEMPLATES`; limit 60/min per użytkownik;
  katalog źródeł `GET /catalog`). Definicja deklaratywna
  (`services/custom_metrics/definition.py`) — zamknięte słowniki miar,
  podziałów i filtrów per źródło, zero SQL od użytkownika. **Uprawnienia liczone
  przy KAŻDYM zapytaniu** (`engine.py`): sekcja źródła
  (`section_access_for_user`), „czyje dane” z `resolve_dashboard_scope`
  (self → tylko „moje”, recruitment_org → + zespół, delivery_clients/organization
  → + cała firma). Za szeroka prośba = 403 `metric_scope_denied` ze zdaniem —
  kafelek mówi „Brak dostępu”, nigdy nie pokazuje zera.
- **Ruchy w pipeline liczą WYŁĄCZNIE kamienie milowe z
  `analytics_first_milestones`** (reguła D2, jak Insights) — inne etapy świadomie
  poza kreatorem, bo surowe `candidate_stages` dubluje powroty na etap.
- **Kwoty = `insights_board_money.fold_money`** (ta sama funkcja co kafle Rady),
  kontrakty z `RATE_SCHEDULE_LOADS`. Redakcja całościowa: Finanse/admin — wszyscy
  klienci; Delivery Lead — wyłącznie klienci z
  `resolve_delivery_lead_finance_client_ids`; klient spoza portfela w filtrze =
  odmowa całości, nie częściowa suma. Wynik niesie notę o młodszej ewidencji
  kontraktów.
- **Zapis na froncie:** menu kafelka i dodanie z katalogu zapisują od razu;
  przeciąganie/rozmiar pracują na szkicu z „Cofnij” i idą jednym PUT po
  „Zapisz układ”. Na telefonie (< 768 px) lista w kolejności wiersz→kolumna,
  bez edycji układu.
- **`/dashboard#nadzor-kontaktu`** (link alertów SLA z `dashboard_v2.py`)
  pokazuje panel nadzoru tymczasowo, gdy ktoś nie ma tego kafelka, z „Dodaj na
  stałe”. `?preset=` jest ignorowane; `dashboardHref()` zawsze zwraca `/dashboard`.
- Harness: `/preview/custom-dashboard` (pusty i pełny pulpit, zero zapytań).


## Jeden ekran „Kandydaci" — trzy tryby zamiast trzech pozycji menu (21.09.2026)

Decyzja Artura 21.09.2026: Wyszukiwarka i Talent Radar były osobnymi wejściami
do tej samej bazy obok listy kandydatów. Teraz to TRYBY jednego ekranu
`/candidates` (`components/v2/candidates/CandidatesWorkspace.tsx`, parametr
`?mode=` — czysty moduł `lib/candidates-mode.ts`):

| Tryb | Adres | Punkt startu | Komponent |
|---|---|---|---|
| Baza | `/candidates` | filtry | `CandidatesListV2` |
| Wyszukiwanie | `/candidates?mode=search` | nazwisko / słowa / opis (auto-rozpoznanie) | `CandidateSearchView` (`hideHeader`, `persistUrlParams`) |
| Z treści requestu | `/candidates?mode=request` | wklejony request albo profil Championa | `TalentRadarWorkspace` (`embedded`) |

- **Stare adresy działają**: `/candidates/search` przekierowuje serwerowo
  z zachowaniem `?s=` i `?job=`; `/talent-radar` przekierowuje role z
  `nav.candidates`, a rola BEZ niej (middleware nie wpuszcza jej na
  `/candidates`) dostaje radar na miejscu — decyzja z 19.08 („radar dla każdej
  zalogowanej roli") zostaje. Linki `/talent-radar` zapisane w powiadomieniach
  (`candidate_search_worker`, `notification_access`) nie wymagają migracji.
- **Tryb czyta się z WARTOŚCI parametru przy każdym renderze** — miękka
  nawigacja przełącza widok (reguła z `useClientTab`).
- **„Szukaj jak z requestu"**: długi wpis w wyszukiwarce (≥ 300 znaków albo
  ≥ 3 nowe linie) proponuje przejście do trybu requestu; tekst jedzie STANEM
  (`requestSeed` + `key` remontujący radar), nigdy adresem — to bywa pełna
  treść requestu klienta. Radar z `initialText` czyści kryteria poprzedniego
  wyszukiwania i nie przełącza się na zapamiętaną „Zapisaną rekrutację".
- **Wyszukiwanie w rekrutacji** („Propozycje z bazy", „Szukaj ręcznie") zostaje
  w rekrutacji — to ten sam `CandidateSearchView` z `addToJob`.
