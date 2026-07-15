# Canonical CI/CD and delivery contract

Przeczytaj przed pierwszą zmianą. Te zasady mają pierwszeństwo przed starszymi opisami workflow.

## CI and deploy are separate tracks

1. **CI** (`.github/workflows/ci.yml`) is the required gate for every PR and push to `main`: gitleaks → lint → typecheck → tests → build. Merge only when it is green.
2. **Deploy** (`.github/workflows/deploy.yml`) starts after merge to `main`. GitHub Actions only calls the Coolify webhook; Coolify clones the repository, builds from `build:` in compose, restarts services, and waits for Docker healthchecks.
3. Production proof is the smoke test: `GET /api/health` must return `status != "unhealthy"` and a `version` starting with the deployed commit's seven-character SHA. HTTP 200 alone is insufficient.
4. The health contract is stable: `{status, version, deployedAt, checks: {database}}`; return 200 for healthy/degraded and 503 for unhealthy. Do not change its shape without updating its consumers.
5. GitHub runners are behind Cloudflare's threat-score rule. Every production smoke-test curl must send `User-Agent: dynaminds-smoke-test/1.0`; without it, 403 is expected.

## Definition of Done

- Complete the requested scope; state conscious out-of-scope work explicitly.
- Run the documented relevant checks and include their real result.
- Leave a clean working tree with committed changes.
- Verify UI changes through real browser interaction and a screenshot; verify backend-only changes with curl and parsed JSON.

## Working rules

- Work autonomously. Warn only before `DROP TABLE`, `git push --force`, removing a public endpoint, or deleting production data.
- Before coding run `git fetch origin && git log origin/main..HEAD`; also check whether the feature already exists.
- Use focused `feat/...`, `fix/...`, or `chore/...` branches, conventional commits, a PR, green CI, then squash-merge. Never use `--no-verify` or force-push `main`.
- Keep the scope tight: every changed line must come from the task; do not add adjacent refactors or speculative abstractions.
- Never commit secrets, Dockerfile ARG defaults containing secrets, or repository `.env` files. Use GitHub secrets and the Coolify vault; rotate an exposed secret.
- Never hardcode UI colours: use semantic tokens. Never run a build concurrently with dev because it corrupts `.next` or `dist`.
- Local Docker remains forbidden by the global Codex policy. Use host-native checks and hosted CI.

## NEXUS additions

Stack: `backend/` FastAPI 0.115/Python 3.12/async SQLAlchemy/Alembic + `frontend/` Next.js 15/React 19/TS 5.7; Postgres 16 + Qdrant; production `api.nexus.dynaminds.pl`.

Relevant verification:
```bash
cd backend && ruff check app/ && ruff format --check app/
alembic -c alembic/alembic.ini upgrade heads  # plural 'heads'
pytest tests/test_<obszar>.py -v
cd frontend && npm ci --legacy-peer-deps
npm run lint && npm run type-check && npm run test && npm run build
```

**Migration trap:** production has multiple Alembic heads. Every new column or table must be mirrored idempotently in `backend/entrypoint.sh` → `_COLUMN_STATEMENTS`; a migration alone can leave a green deploy with a 503 endpoint.
Other traps: Axios `Network Error` can be a CORS-hidden 500—reproduce with curl; protected files need authenticated fetch → `blob:` URL; pay rates are `NUMERIC`/`Decimal`, never `int`; normalize surname search with `unicodedata.normalize('NFC', q)`; never run `npx shadcn add`, use `frontend/scripts/add-block.sh`.

---

# AGENTS.md — NEXUS (ATS)

> Per-app deviations od globalnego standardu w `~/.Codex/rules/deployment.md`.
> Plik ładowany automatycznie przy każdej sesji Codex'a w tym repo.

## Stack & ports

- **Backend:** FastAPI 0.115 + SQLAlchemy 2.0 (async, asyncpg) + Alembic — `backend/`, port 8000.
- **Frontend:** Next.js 15.1 (App Router, React 19, TypeScript 5.7) — `frontend/`, port 3000.
- **Database:** Postgres 16-alpine (compose service) + Qdrant (vector DB, embeddings przez Voyage AI).
- **Auth:** JWT + RBAC.
- **Local AI:** Ollama (llama3.2) — opcjonalnie, dla offline pracy.
- **Test:** pytest + pytest-asyncio (BE) + Vitest + Playwright (FE).
- **Sentry:** `sentry-sdk[fastapi]` w `backend/requirements.txt` (status w prod do potwierdzenia).

**Specyfika:** **monorepo** z dwoma podkatalogami `backend/` + `frontend/`, każdy ze swoim Dockerfile i package mgr.

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

- **Hosting:** Coolify v4 self-hosted on Hetzner CAX21 ARM (91.99.199.112).
- **Coolify panel:** `https://coolify-nexus.dynaminds.pl` (HTTPS+LE, public via Traefik route — od 2026-05-04).
- **App UUID (Coolify):** `ocgkwcbovpve9wvf9smxl0kx`.
- **Registry:** **brak GHCR** — Coolify buduje obrazy lokalnie z compose `build:` block (jednolite z Compass + LeadGen).
- **Compose orkiestracja:**
  - `docker-compose.yml` — base z `build:` block (no port bindings, Coolify Traefik routuje przez `expose:`).
  - `docker-compose.override.yml` — dev (re-adds host port bindings, auto-loaded przez `docker compose up`).
  - `docker-compose.prod.yml` — prod overlay (resource limits, healthchecks).
- **Auto-deploy:** ✅ **TAK** — `git push origin main` → `.github/workflows/deploy.yml` (unified template, PR #68 merged 2026-05-04) → Coolify webhook → build + restart → smoke test.
- **Trigger:** push `main` → `.github/workflows/deploy.yml`.
- **Rollback:** Coolify panel `https://coolify-nexus.dynaminds.pl` → Resources → nexus → Deployments → poprzedni → Redeploy.
- **Standardy + procedury:** patrz `~/.Codex/rules/deployment.md` + `~/.Codex/rules/deployment-runbook.md`.

## Healthcheck endpoint

- **Standard URL:** `/api/health` z full shape `{status, version, deployedAt, checks: {database}}` (Faza 1.B done 2026-04-29, PR #61).
- **Legacy URL:** `/health` zachowane jako alias (uptime-probe.yml legacy compat).
- **Implementation:** `app/main.py` (`/api/health` z DB ping z 2s timeout).
- **Compose healthcheck:** backend `curl /api/health` (docker-compose.prod.yml).
- **Uptime probe:** `.github/workflows/uptime-probe.yml` — cron na `/api/health` z `jq -e '.status != "unhealthy"'`.
- **GIT_SHA / BUILT_AT:** Coolify env vars (substytutowane przez `$SOURCE_COMMIT` + statyczny timestamp), patch via Coolify API (PR #62).

## Env vars (build-time vs runtime)

**Build args (FE):**
- `NEXT_PUBLIC_API_URL` (default `http://localhost:8000` w `docker-compose.yml`).
- `GIT_SHA`, `BUILT_AT` (po Fazie 1).

**Runtime env (BE — przez `.env` na serwerze, mapowany do compose `env_file:`):**
- `DATABASE_URL` (postgresql+asyncpg://...)
- `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` (na serwerze override DATABASE_URL przez compose service names)
- `SECRET_KEY` (JWT signing, min 48 chars)
- `QDRANT_HOST`, `QDRANT_PORT`
- `VOYAGE_API_KEY` (embeddings)
- `SENTRY_DSN` (opcjonalnie)
- inne per feature

**Walka z surprise:** compose `env_file: .env` — wszystkie sekrety w jednym pliku na serwerze (Coolify env vault).

## CI gotchas

- **Najsilniejsze CI w stacku** (gitleaks + ruff + alembic + pytest + ESLint + tsc + Vitest + Codecov).
- **`needs: secret-scan`** — gitleaks musi przejść przed innymi jobami (świadomy guard).
- **Pytest selective:** wskazane konkretne pliki testów (5 plików), nie `pytest .` — bo cały suite ma live-server tests które są skipowane (`RUN_LIVE_TESTS=0`).
- **Codecov flags:** `backend` + `frontend` — separate uploads.
- **Lint warnings cap:** `next lint --max-warnings=300` — historyczny dług, nie failować na obecnych warningach.
- **`npm ci --legacy-peer-deps`** w FE (React 19 + niektóre pakiety jeszcze RC).
- **40+ feature branches w remote** — przy `git checkout` weryfikuj że `main` pociągnięty (`git fetch && git log origin/main..HEAD`).

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
- **E2E:** Playwright lokalnie + osobny workflow `e2e.yml`.
- **40+ feature branches:** historyczne, niektóre stale. Przed merge nowej feature branchy — sprawdź czy nie ma duplikatów.

## Po Fazie 1

Update tej sekcji:
- `/health` zachować, `/api/health` standard shape.
- Update `uptime-probe.yml` na `/api/health` + nowy jq query.
- Dodać `pytest tests/test_health_v2.py` do `backend-lint-test` job.

## Observability

Zobacz `~/.Codex/rules/observability.md` dla pełnego standardu (Sentry + Grafana Cloud + Cloudflare). Per-NEXUS odstępstwa:

- **Sentry projekty:** `nexus-be` (FastAPI 0.115 + Python 3.12) + `nexus-fe` (Next.js 15 + React 19) — osobne projekty bo dwa stacki w jednym monorepo.
- **Backend SDK:** `sentry-sdk[fastapi]>=2.20.0` z `AsyncioIntegration` (dla 14 background tasks w lifespan: calendar reminder, match TTL, slack SLA, contract alerts, competition autofreeze, cc centroid sync, ...) + `LoggingIntegration` (auto-bridge `logger.error` → Sentry breadcrumb/event) + `FastApiIntegration(transaction_style="endpoint")`. JSON logger już skonfigurowany przez `python-json-logger` w `app/core/logging_config.py`.
- **Frontend SDK:** `@sentry/nextjs ^9` (nie ^8 jak Compass — Next 15 + React 19 wymaga nowszej wersji). `error.tsx` dodany w PR #109 (App Router error boundary, dotąd brak).
- **Replay privacy:** `maskAllText: true, blockAllMedia: true` — NEXUS trzyma dane kandydatów (RODO ATS).
- **Compose `logging:`** — `json-file 10MB×5 + tag` na 4 services (postgres, qdrant, backend, frontend) przez YAML anchor (`x-logging`).
- **Alloy sidecar:** profile-gated (`profiles: [observability]`). Bez `COMPOSE_PROFILES=observability` w Coolify nie startuje. Po dodaniu Grafana creds → `{app="nexus"}` zwraca logi z 4 services + structured fields (FastAPI JSON logging od PR #108).
- **Cloudflare:** `api.nexus.dynaminds.pl` — proxy ON, Full strict TLS, OWASP CRS PL2, rate limit `/api/auth/*` 10 req/min/IP. Backend ma już `slowapi` rate limiter — Cloudflare to pierwsza linia, slowapi druga.

## CloudTalk (telefonia)

5-fazowa integracja zdeployowana w PR #157 (Fazy 1-5 razem). Dormant na prod do momentu provisioning secret + flipnięcia killswitcha.

- **Kill-switch:** `CLOUDTALK_ENABLED=false` default. Wszystkie `/api/cloudtalk/*` zwracają 503, webhook stoi w DRY-RUN, background loop `cloudtalk_sync` exit immediate, `/api/health.checks.cloudtalk = "unconfigured"`.
- **Aktywacja:**
  1. CloudTalk panel → Settings → API Keys → generate pair → secret pokazany RAZ
  2. `openssl rand -hex 32` → webhook signing secret
  3. Coolify env vault → `CLOUDTALK_API_KEY_ID`, `CLOUDTALK_API_KEY_SECRET`, `CLOUDTALK_WEBHOOK_SECRET` (runtime), na koniec `CLOUDTALK_ENABLED=true`
  4. CloudTalk panel → Integrations → Webhooks → URL `https://api.nexus.dynaminds.pl/api/calls/webhook`, secret = ten sam co `CLOUDTALK_WEBHOOK_SECRET`, events: `call-ended`, `transcript-ready`, `recording-ready`
  5. Settings → Integracje → CloudTalk → **Synchronizuj** żeby zmapować agentów do userów (auto-match po email; ręcznie dropdown gdy email się różni)
- **Inbound flow:** webhook → HMAC verify (`X-CloudTalk-Signature`) → kandydat lookup po phone (last-9-digits z `dedup_service._normalize_phone`) → upsert `Call` po `cloudtalk_call_id` → jeśli `agent.id` mapowany → `Call.user_id` → jeśli transkrypt + active stage → Champion enrichment via `champion_draft_service.enrich_from_call`.
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
  - **full** (tygodniowo `TRAFFIT_SYNC_FULL_WEEKDAY`=6 niedz.): full-scan reconcile, safety net.
- **Delta filtr:** `TraffitClient.get_paginated(..., filter_=...)` → nagłówek `X-Request-Filter` (day-granular). Jeśli tenant odrzuci (HTTP 400) → fallback na full scan (upserty są idempotentne, więc bezpieczne).
- **Notatki (kluczowe — „no notatka missing"):** importer NIE pisał do `notes` (jednorazowo zrobiła to migracja `0077`). `TraffitImporter.promote_notes(since)` powtarza logikę `0077` na każdym syncu — promuje `activities` (`traffit:Notatka/Email/Reply/Rozmowa telefoniczna/Spotkanie`) → `notes` (dedup `NOT EXISTS (candidate_id, created_at)`, stamp `source_ref='traffit:activity:<id>'`). Wołane wewnątrz `import_candidate_activities`.
- **Pliki/CV (delta):** scope = kandydaci **dotknięci w tym runie** (faza candidates upsertuje Traffit-zmienionych → Nexus `updated_at >= run_start`), NIE 45-dniowe okno danych (bo edycje w samym Nexusie bumpują `updated_at` wszystkich 49k → 2.7h zbędnych calli `/files`). Per kandydat pobiera tylko `file_id` których jeszcze nie ma (po `external_id="<emp>-<file>"`) → nowe/podmienione CV bez re-downloadu. (full reconcile: brama „kandydaci bez plików".)
- **Enrich names (faza `candidates_enrich_names`):** Traffit rekordy bez imienia i bez użytecznego emaila lądowały jako `name="?"` / `lastname="?"` (importer pobierał CV do object storage, ale go NIE parsował). Ta faza (po `candidate_files`) czyta zapisane CV → `cv_text_extractor` → `parse_cv` (Codex→Ollama→regex) → `_apply_cv_enrichment`, fallback na imię z **nazwy pliku CV** (`name_from_filename`, konserwatywny — zgaduje tylko gdy 2 czyste tokeny / camelCase). Delta: scope `since=files_since` (świeże „?"); full reconcile: wszystkie pozostałe „?". **Idempotentny + bezpieczny** — wypełnia tylko puste/placeholder pola (`?`/`Nieznane` traktowane jako blank), nigdy nie nadpisuje realnej wartości. Logika współdzielona: `app/services/cv_backfill.py` + helpery `app/services/cv_enrichment.py` (wyniesione z `candidates.py`, re-eksport zachowany). **Backfill istniejących:** `POST /api/admin/candidates/backfill-names?limit=&prefer_llm=` (background, admin) + `GET .../backfill-names/status`.
- **Aktywacja:** Coolify env vault (secrety `TRAFFIT_TENANT/CLIENT_ID/CLIENT_SECRET` już ustawione z migracji) → `TRAFFIT_SYNC_ENABLED=true` → `POST /api/admin/traffit/sync?mode=delta` (admin) żeby odpalić pierwszy run; `GET /api/admin/traffit/sync/status` pokazuje watermark + per-phase stats.
- **Health:** `/api/health.checks.traffit` = `unconfigured` (off) / `misconfigured` (brak secretów) / `degraded` (włączony, brak świeżego runu / errors) / `healthy` (ostatni `__daily__` < 36h, status ok).
- **DB:** `traffit_sync_state` (PK `phase` + markery `__daily__`/`__full__`) — migracja `0136_traffit_sync_state` (na bazie `0135`).

## Self-service registration (email/password — alternatywa dla Microsoft SSO)

Rejestracja bez logowania przez Microsoft, ograniczona do domen z whitelisty
`SSO_ALLOWED_DOMAINS` (te same co SSO, np. `b2bnetwork.pl`). Nowe konta są
**read-only viewer** (`UserRole.user`), niezweryfikowane do kliknięcia linku
aktywacyjnego; admin podnosi rolę w panelu (Settings → Admin → Users — flow
istniał wcześniej). PR 2026-06-23. Pełny opis: `docs/self-registration-completion-report.md`.

- **Kill-switch:** `SELF_REGISTRATION_ENABLED` (default `false`). Off → `POST /api/auth/register` zwraca 503, strona `/register` pokazuje "rejestracja wyłączona".
- **Endpoint `POST /api/auth/register`** (`app/api/auth.py`): gate → domain whitelist (fail-closed, pusta lista = reject-all) → rola **wymuszona `user`** server-side (`SelfRegisterRequest` NIE ma pola `role` — zamyka starą dziurę gdzie `role` był z body i każdy mógł zrobić sobie `admin`) → `email_verified=False` → token + mail. **Anti-enumeration:** zawsze generyczne `201` (nigdy `409`), bcrypt liczony na obu ścieżkach (no timing leak); duplikat na niezweryfikowanym koncie re-wysyła link, na zweryfikowanym — cicho no-op.
- **`POST /api/auth/verify-email`** — jednorazowy 64-hex token (SHA-256 hash, TTL 24 h) → `email_verified=True`. **`POST /api/auth/resend-verification`** — anti-enum (zawsze 200).
- **Login gate:** `login` blokuje konta z `email_verified=False` (czytelny komunikat PL). Istniejący userzy email/hasło + SSO mają `email_verified=True` (backfill migracji + SSO ustawia), więc **nie są dotknięci**.
- **Frontend:** `/register` (formularz) + `/register/verify` (auto-verify on mount) + link na `/login`; `/register` w `PUBLIC_PATHS` (`middleware.ts`).
- **DB:** `users.email_verified` (BOOLEAN NOT NULL DEFAULT true) + tabela `email_verification_tokens` (bliźniacza do `password_reset_tokens`) — migracja `0139_email_verification` (na bazie `0138_candidate_expected_hourly_rate`; aplikowana przez `alembic upgrade heads`).
- **Aktywacja na prod:** Coolify → `SSO_ALLOWED_DOMAINS` zawiera `b2bnetwork.pl` (już z SSO) + `SMTP_ENABLED=true` (+ SMTP creds, żeby mail aktywacyjny wyszedł) + `SELF_REGISTRATION_ENABLED=true`.
