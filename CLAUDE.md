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
  - `docker-compose.yml` — base z `build:` block (no port bindings, Coolify Traefik routuje przez `expose:`). **Limity pamięci (mem_limit) są TUTAJ** — Coolify czyta wyłącznie ten plik (docker_compose_location), więc limity trzymane w overlayu nigdy nie obowiązywały na prodzie (Memory=0, wykryte i naprawione 2026-08-12).
  - `docker-compose.override.yml` — dev (re-adds host port bindings, auto-loaded przez `docker compose up`).
  - `docker-compose.prod.yml` — prod overlay (ports/env/healthchecks — referencja do ręcznej symulacji prod; BEZ limitów zasobów).
- **Auto-deploy:** ✅ **TAK** — `git push origin main` → `.github/workflows/deploy.yml` (unified template, PR #68 merged 2026-05-04) → Coolify webhook → build + restart → smoke test.
- **Trigger:** push `main` → `.github/workflows/deploy.yml`.
- **Rollback:** Coolify panel `https://coolify-nexus.dynaminds.pl` → Resources → nexus → Deployments → poprzedni → Redeploy.
- **Standardy + procedury:** patrz `~/.claude/rules/deployment.md` + `~/.claude/rules/deployment-runbook.md`.

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
- **Codecov flags:** `backend` + `frontend` — separate uploads.
- **Lint warnings cap:** `next lint --max-warnings=300` — historyczny dług, nie failować na obecnych warningach.
- **`npm ci --legacy-peer-deps`** w FE (React 19 + niektóre pakiety jeszcze RC).
- **40+ feature branches w remote** — przy `git checkout` weryfikuj że `main` pociągnięty (`git fetch && git log origin/main..HEAD`).
- **Wiele PR-ów naraz = merge train, nie ręczne klikanie.** Branch protection `strict=true` + ~22-min CI → każdy merge flipuje resztę PR-ów w `BEHIND`, a auto-merge NIE aktualizuje gałęzi sam; GitHub merge queue niedostępny (repo prywatne na koncie osobistym). Użyj `scripts/merge-train.sh <pr> <pr>...` (lokalnie — update z PAT-a triggeruje CI, z GITHUB_TOKEN by nie triggerował): uzbraja auto-merge i aktualizuje JEDEN PR na raz, sekwencyjnie. NIE zdejmuj `strict` — squash stalej gałęzi cicho cofa cudze merge'e (incydent 27.07: -6 merge'y na prodzie). Deploye z burstu koalesują się same: deploy job skipuje rebuild, gdy prod serwuje już TARGET_SHA/potomka (deploy.yml 2026-08-07) — to gasi dawne zapychanie kolejki Coolify (429).

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

Zobacz `~/.claude/rules/observability.md` dla pełnego standardu (Sentry + Grafana Cloud + Cloudflare). Per-NEXUS odstępstwa:

- **Sentry projekty:** `nexus-be` (FastAPI 0.115 + Python 3.12) + `nexus-fe` (Next.js 15 + React 19) — osobne projekty bo dwa stacki w jednym monorepo.
- **Backend SDK:** `sentry-sdk[fastapi]>=2.20.0` z `AsyncioIntegration` (dla 14 background tasks w lifespan: calendar reminder, match TTL, slack SLA, contract alerts, competition autofreeze, cc centroid sync, ...) + `LoggingIntegration` (auto-bridge `logger.error` → Sentry breadcrumb/event) + `FastApiIntegration(transaction_style="endpoint")`. JSON logger już skonfigurowany przez `python-json-logger` w `app/core/logging_config.py`.
- **Frontend SDK:** `@sentry/nextjs ^9` (nie ^8 jak Compass — Next 15 + React 19 wymaga nowszej wersji). `error.tsx` dodany w PR #109 (App Router error boundary, dotąd brak).
- **Replay privacy:** `maskAllText: true, blockAllMedia: true` — NEXUS trzyma dane kandydatów (RODO ATS).
- **Compose `logging:`** — `json-file 10MB×5 + tag` na 4 services (postgres, qdrant, backend, frontend) przez YAML anchor (`x-logging`).
- **Alloy sidecar:** profile-gated (`profiles: [observability]`). Bez `COMPOSE_PROFILES=observability` w Coolify nie startuje. Po dodaniu Grafana creds → `{app="nexus"}` zwraca logi z 4 services + structured fields (FastAPI JSON logging od PR #108).
- **Cloudflare:** `api.nexus.dynaminds.pl` — proxy ON, Full strict TLS, OWASP CRS PL2, rate limit `/api/auth/*` 10 req/min/IP. Backend ma już `slowapi` rate limiter — Cloudflare to pierwsza linia, slowapi druga.

## Generator Umów B2B — trzy zakładki cyklu życia umowy

Rejestr rozbity na trzy zakładki odpowiadające fazom życia umowy (migracja
`0226_b2b_generated_contract_suspended`, na bazie 0203/0224):
**„Umowy aktywne i w trakcie podpisu"** (`active` + `in_progress`) ·
**„Umowy bez projektu"** (`suspended`) · **„Zakończone umowy"** (`closed`).
Wszystko w `components/v2/pages/B2BContractGeneratorV2.tsx`.

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

## Klienci → Profil: tabela konsultantów + stawki z harmonogramu

Sekcja „Konsultanci" (`app/clients/[id]/ProfileTab.tsx`) renderuje **tabelę**
(`components/client-profile/ConsultantsTable.tsx`), nie karty. Kolumny: `Konsultant`
(nazwisko / tag CC / **rekrutacja**) · `Start date` · `Stawka kosztowa` ·
`Stawka przychodowa` · `Marża` (+ `End date` tylko w Archiwum, + `Akcje` w obu).

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
  użyty) — master toggle → feature toggle → miesięczny limit. Oba endpointy za
  `OperationalUser`. Model override: env `CANDIDATE_SUMMARY_MODEL`.
- Wyjście plaintext (nie JSON) + `thinking={"type": "disabled"}` (trap truncacji
  Sonnet 5). Tabela ma lustro DDL w entrypoint.sh (jak każda zmiana schematu).

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
- **Health:** `/api/health.checks.traffit` = `unconfigured` (off) / `misconfigured` (brak secretów) / `degraded` (włączony, brak świeżego runu / errors) / `healthy` (ostatni `__daily__` < 36h, status ok). **To sonda ŚWIEŻOŚCI, nie kompletności** — `healthy` nie znaczy, że dane się zgadzają z Traffitem (tak właśnie luka w plikach/CV żyła miesiącami przy zielonym healthu).
- **DB:** `traffit_sync_state` (PK `phase` + markery `__daily__`/`__full__`) — migracja `0136_traffit_sync_state` (na bazie `0135`).

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
- **Role**: `require_candidate_write` (admin, delivery_lead, tac, recruiter,
  sourcer — **bez** head_of_recruitment). Ta sama piątka w czterech miejscach:
  sidebar, paleta ⌘K, `CAPABILITY_ROLES` i `ROLE_ROUTES` w middleware. Bez wpisu
  w middleware viewer wchodzi na stronę i dostaje 403 z API wyrenderowane jako
  pusta lista.
- **Pułapka przy dokładaniu endpointów**: moduł z `@limiter.limit` nie może mieć
  `from __future__ import annotations` (PEP 563 + slowapi #579 → body ląduje jako
  parametr Query). Pilnuje tego test czytający AST, nie treść pliku — docstring
  wspomina ten import, żeby przed nim ostrzec, więc szukanie stringu wywalało
  się na własnym ostrzeżeniu.

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
