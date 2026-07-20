# Audyt wydajności systemu NEXUS — 2026-07-17

**Baza:** `main` @ `bdf5a75` · **Skala referencyjna:** ~49 000 kandydatów, ~158 000 wierszy `candidate_stages`, 205 migracji, 20 pętli background w lifespan
**Środowisko prod:** 1× Hetzner CAX21 ARM (4 rdzenie / 8 GB) — postgres + qdrant + backend + frontend (+ alloy) na jednej maszynie, **single replica**, bez Redisa

## Metodologia

Audyt wieloagentowy: **10 równoległych znalazców** (każdy inny wymiar: N+1, indeksy, blokowanie event loopu, pętle background, payloady API, frontend, matching/Qdrant, pooling/config, infra/compose, trace gorących endpointów) → **98 surowych znalezisk** (~75 unikalnych po deduplikacji między wymiarami) → **adwersaryjna weryfikacja**: każde znalezisko dostało sceptyka z nastawieniem „obal to" (dla P0/P1 drugi niezależny głos). Limit sesji przerwał weryfikację 5 wymiarów — te znaleziska (wszystkie kluczowe P0/P1 + większość P2) doweryfikowałem ręcznie, czytając kod linia po linii. Statusy:

- **[P]** potwierdzone przez sceptyka (37 szt.) lub ręcznie (~18 szt.) — z cytatem kodu
- **[NW]** niezweryfikowane (tylko P2/P3 o mniejszym ciężarze) — traktować jako hipotezy
- **[O]** obalone (4 szt.) — wypisane osobno, żeby nikt do nich nie wracał

Severity po korektach weryfikatorów (kilka P0 zeszło na P1 po znalezieniu mitygacji, kilka P1 na P2/P3):
**P1 = 13** · **P2 = ~35** · **P3 = ~15**. Zero potwierdzonych P0 (nic nie grozi natychmiastową awarią), ale filar 1 w praktyce degraduje całą aplikację przy jednym otwartym dashboardzie menedżera.

## TL;DR — co boli najbardziej

| # | Problem | Gdzie | Sev. |
|---|---------|-------|------|
| 1 | `GET /api/pipeline/overview` ładuje **całą tabelę `candidate_stages` (~158k wierszy) jako obiekty ORM** i deduplikuje w Pythonie — a frontend menedżera odpytuje go **co 30 s** | [pipeline.py:1230](backend/app/api/pipeline.py:1230) + [manager/page.tsx:82](frontend/src/app/manager/page.tsx:82) | P1 |
| 2 | Lista kandydatów z `include_match_stats` (kafelki + **każdy widok mobilny**) robi ~**1 000–2 000 sekwencyjnych zapytań** na stronę (2 zapytania × kandydat × job, do 50 jobów) + ~1 000 linii logów INFO | [candidates.py:1517](backend/app/api/candidates.py:1517) | P1 |
| 3 | Pętla triggerów powtarza pełny skan `candidate_stages` **2–6× co 5 minut**, a `check_stage_stuck_7d` ponawia INSERT dla każdego „stuck" etapu w każdym ticku | [notification_triggers.py:129](backend/app/services/notification_triggers.py:129), [:486](backend/app/services/notification_triggers.py:486) | P1 |
| 4 | Rerank hybrydowy jest **domyślnie włączony** (`RERANKER_ENABLED=True`) — każde zapytanie hybrydowe ładuje ~200 pełnych encji Candidate i wysyła ~800 KB do Voyage | [config.py:39](backend/app/core/config.py:39) + [hybrid_search.py:147](backend/app/services/hybrid_search.py:147) | P1 |
| 5 | Cały API + 20 pętli background = **1 worker uvicorna, 1 proces, 1 rdzeń** z 4 dostępnych; Postgres na **fabrycznych defaultach** (shared_buffers 128 MB) przy limicie 1 G | [entrypoint.sh:1841](backend/entrypoint.sh:1841), [docker-compose.yml:23](docker-compose.yml:23) | P1 |
| 6 | Eksporty ładują 10–50k **pełnych** encji (z `raw_cv_text`!) do RAM i budują XLSX na event loopie | [import_export.py:271](backend/app/api/import_export.py:271), [candidates.py:1912](backend/app/api/candidates.py:1912) | P1 |
| 7 | Synchronjczny `smtplib` (timeout do 10 s) inline w async endpointach auth | [auth.py:482](backend/app/api/auth.py:482) | P1 |

Wspólny mianownik filarów 1–2: **wzorzec „pełny skan `candidate_stages` + dedupe w Pythonie" został już raz naprawiony** w `/overview-sla` ([phase3.py:123](backend/app/api/phase3.py:123): „dawniej pełen scan 158k rows + Python loop … wisiało >15s") — pozostałe miejsca wciąż używają starego wzorca. Fix jest znany i zmierzony we własnym repo.

---

## Filar 1 — pełne skany `candidate_stages` (~158k wierszy)

### 1.1 [P] `GET /api/pipeline/overview` — pełny skan + dedupe w Pythonie (P1)
[pipeline.py:1230](backend/app/api/pipeline.py:1230) — `select(CandidateStage)` **bez WHERE i bez LIMIT**, posortowane po (candidate_id, job_id, moved_at desc), materializacja wszystkich ~158k wierszy do ORM, potem pętla „latest per (candidate, job)" w Pythonie. Własny pomiar tego samego wzorca (komentarz w phase3.py): **>15 s**. Do tego [manager/page.tsx:82](frontend/src/app/manager/page.tsx:82) robi `refetchInterval: 30s` — **jeden otwarty dashboard menedżera to ciągły młot na DB i RAM backendu** (setki MB przejściowych obiektów Pythona na 1G-limitowanym kontenerze).
**Fix:** `SELECT DISTINCT ON (candidate_id, job_id) …` z 5 kolumnami (wzór już jest w `/overview-sla`) albo istniejący widok `analytics_current_pipeline` (używany przez dashboard.py) + cache TTL 60 s. Po stronie FE: interval 30 s → 3–5 min.

### 1.2 [P] Pętla triggerów — ten sam skan 2–6× co 5 minut (P1)
[notification_triggers.py:129](backend/app/services/notification_triggers.py:129) — kilka triggerów w jednym ticku niezależnie ładuje pełną tabelę stages do ORM. Do tego [triggers_loop.py:42](backend/app/tasks/triggers_loop.py:42) [P]: wszystkie 8 triggerów w **jednej transakcji**, która zaczyna się od UPDATE i wysyła WebSockety w trakcie (długo trzymany lock + połączenie).
**Fix:** jeden wspólny snapshot „latest stage per pair" na tick (DISTINCT ON, 5 kolumn, bez ORM), przekazywany do wszystkich triggerów; commit per trigger.

### 1.3 [P] `check_stage_stuck_7d` — burza INSERT-ów co 5 minut (P1)
[notification_triggers.py:486](backend/app/services/notification_triggers.py:486) — dla każdego etapu „stuck >7 dni" (mogą być ich setki/tysiące) w **każdym ticku** ponawiana jest próba INSERT-u notyfikacji (dedup łapie duplikat dopiero na poziomie zapytania/konfliktu).
**Fix:** marker „już notyfikowane" (kolumna/tabela stanu) filtrowany w SELECT, nie po stronie INSERT-ów.

### 1.4 [P] `slack_sla_alerts` — duplikat tego samego skanu co 30 min (P2)
[slack_sla_alerts.py:37](backend/app/tasks/slack_sla_alerts.py:37) — osobna pętla, ten sam pełny skan. Po 1.2 powinna konsumować ten sam snapshot.

### 1.5 [P] Profil klienta — agregacja całej tabeli stages ×2 na wejście (P2)
[clients.py:197](backend/app/api/clients.py:197) — subquery liczące kandydatów agreguje **całą** `candidate_stages` dwukrotnie przy każdym otwarciu profilu klienta.

### 1.6 [NW] „Moje KPI" — funkcja okienkowa po całej tabeli na każdą wizytę (P2)
[kpis.py:164](backend/app/api/kpis.py:164) — panel KPI rekrutera przelicza window-function view po całych stages bez cache (endpoint `/dashboard/kpis` MA cache, panel „Moje KPI" wg znalazcy nie).

---

## Filar 2 — lista kandydatów, szerokie encje, eksporty

### 2.1 [P] `include_match_stats` — O(strona × 50 jobów) sekwencyjnych zapytań (P1)
[candidates.py:1517](backend/app/api/candidates.py:1517) → `rank_jobs_for_candidate` → [scoring_service.py:1003-1004](backend/app/services/scoring_service.py:1003): `_score_champion_fit` (SELECT na candidate_stages) + `_check_penalties` (SELECT na candidate_conflicts) **per para (kandydat×job), sekwencyjnie** + `logger.info` per para. Domyślny desktop tego nie włącza (kolumna „match" poza HARD_DEFAULT_COLUMNS), ale **kafelki i KAŻDY widok mobilny** ([candidate-list-query.ts:55](frontend/src/components/v2/pages/candidate-list-query.ts:55), wymuszenie tiles na mobile w CandidatesListV2) — realnie ~1–3 s latencji + ~1 000 linii logu do Loki na każde wejście z telefonu. `match_score_cache` istnieje, ale ta ścieżka go **nie używa**.
**Fix:** 2 zapytania setowe przed pętlą (DISTINCT ON stages dla par + konflikty dla klientów), scoring czysto w pamięci; log → DEBUG.

### 2.2 [P] Szerokie encje wszędzie: `raw_cv_text` niedeferowane + snapshoty LinkedIn + pełna historia etapów (P2×3)
- [candidate.py (model)](backend/app/models/candidate.py) — `raw_cv_text` (największa kolumna, ~171 MB w tabeli wg pomiaru z PR #432) **nie jest `deferred()`** — każdy `select(Candidate)` detoastuje pełny tekst CV, którego lista nigdy nie zwraca.
- [candidates.py:321](backend/app/api/candidates.py:321) — lista eager-loaduje **wszystkie** snapshoty LinkedIn (pełne JSONB Proxycurl) per wiersz.
- [candidates.py:308](backend/app/api/candidates.py:308) — lista eager-loaduje **pełną** historię etapów (z Job+Client) tylko po to, żeby pokazać bieżący etap.
**Fix (jeden PR):** `deferred(raw_cv_text)` (+ jawny `undefer` w 3–4 miejscach, które go naprawdę czytają: parsowanie CV, search po cv, eksport), slim query dla listy (tylko kolumny widoku), bieżący etap z DISTINCT ON zamiast pełnej historii.

### 2.3 [P] Brakujące indeksy pod realne filtry (P1+P2)
- **P1** [dashboard.py:140](backend/app/api/dashboard.py:140) — globalny feed aktywności sortuje **całą** tabelę audit-logu; `activities.created_at` bez indeksu.
- **P1** [candidates.py:758](backend/app/api/candidates.py:758) — filtr skills robi `LIKE` po `lower(JSONB::text)` na 3 kolumnach — nieindeksowalne, pełny skan z pełnym parsowaniem JSONB.
- **P2** [candidates.py:1022](backend/app/api/candidates.py:1022) — domyślne sortowanie listy `ORDER BY created_at DESC` bez indeksu (sort 49k szerokich wierszy per stronę; dotyka też badge w sidebarze — patrz 6.2).
- **P2** [candidates.py:2597](backend/app/api/candidates.py:2597) — `lower(email)` equality bez indeksu funkcyjnego (Outlook add-in, per sprawdzenie).
- **P2** [candidates.py:397](backend/app/api/candidates.py:397) — filtry current_company/title unnest-ują JSONB `experience` per wiersz (indeks trigramowy z 0044 nie obejmuje tej ścieżki).
- **P2** [dedup_service.py:108](backend/app/services/dedup_service.py:108) — dedupe = OR nieindeksowalnych predykatów, gwarantowany full scan (wołane przy tworzeniu kandydata).
- **P3** [calls.py:361](backend/app/api/calls.py:361) — matching telefonów `regexp_replace` po całej tabeli (CloudTalk dormant → niska waga dziś).

### 2.4 [P] Eksporty — dziesiątki tysięcy pełnych encji w RAM + XLSX na event loopie (P1)
- [import_export.py:271](backend/app/api/import_export.py:271) — `GET /api/export/candidates` ładuje **wszystkie 49k** kandydatów jako pełne ORM bez limitu.
- [candidates.py:1912](backend/app/api/candidates.py:1912) — `GET /api/candidates/export`: `limit` domyślnie 10 000, max **50 000**, pełne encje (z raw_cv_text → gigabajty detoastu), openpyxl buduje workbook **na event loopie** ([P] także werdykt async-blocking dla :1963).
- [candidates.py:4054](backend/app/api/candidates.py:4054) — bulk-cv-download: ZIP do 200 CV budowany w całości w BytesIO (częściowa mitygacja: odczyty przez aiofiles/to_thread — potwierdzone).
**Fix:** kolumnowy SELECT tylko pól eksportu + streaming CSV; XLSX w `asyncio.to_thread`; twardszy cap.

### 2.5 [P] Autocomplete firm/stanowisk — lateral scan całego JSONB per zapytanie (P2)
[candidates.py:1772](backend/app/api/candidates.py:1772) — `jsonb_array_elements` po `experience` **wszystkich** kandydatów przy każdym odpytaniu autocomplete (filtr firmy/tytułu). Fix: zmaterializowana tabelka sugestii odświeżana w tle (albo indeks GIN + LIMIT po prefiksie).

### 2.6 [P] Advanced search — ten sam ciężki filtr wykonywany 3× na request (P2)
[search.py:318-364](backend/app/api/search.py:318) — count (1×), strona wyników (2×), facety CC (3×) — wszystkie z tym samym `where_clause` (UNION-of-ids z trigramami z PR #432 — szybki, ale ×3). Fix: policzyć id-slice raz (CTE/temp), reszta z niego.

### 2.7 [P] Global search (pasek górny) — omija istniejący indeks trigramowy (P2)
[search.py:472-481](backend/app/api/search.py:472) — ILIKE po **osobnych** kolumnach `name/lastname/email`, a indeks z migracji 0013 (`ix_candidates_identity_trgm`) jest na **wyrażeniu** `name||' '||lastname||' '||email` → planner go nie użyje, seq scan 49k per wpisany znak (po debounce). Do tego [P] [search.py:506](backend/app/api/search.py:506) — N+1: osobny SELECT klienta per znaleziony job (max 5 — P3).
**Fix:** predykat na tym samym wyrażeniu co indeks (albo `search_doc ILIKE`), klient przez selectinload/JOIN.

### 2.8 [P] Kalendarz — N+1 do 3 zapytań per event, bez LIMIT (P1)
[calendar.py:130](backend/app/api/calendar.py:130) — lista eventów bez deduplikacji i bez limitu, do 3 osobnych SELECT-ów na event.

---

## Filar 3 — blokowanie event loopu (1 worker!)

- **P1 [P]** [auth.py:482](backend/app/api/auth.py:482) — synchroniczny `smtplib` (socket timeout do 10 s) inline w async endpointach (reset hasła, weryfikacja, admin) — **każdy** request w tym czasie stoi. Fix: `asyncio.to_thread` (60 sekund pracy).
- **P2 [P]** [auth.py:121](backend/app/api/auth.py:121) — bcrypt hash/verify na event loopie (~100–300 ms per login przy koszcie 12).
- **P2 [P]** [contracts.py:718](backend/app/api/contracts.py:718) — eksport kontraktów: openpyxl+zip na loopie.
- **P2 [P]** [cv_parser.py:274](backend/app/services/cv_parser.py:274) — `anthropic.Anthropic` z **600-sekundowym** default timeoutem w threadpoolu — długie zawieszenia wątków przy problemach API.
- **P2 [P]** [embedding_service.py:125](backend/app/services/embedding_service.py:125) — nowy `httpx.AsyncClient` (pełny TCP+TLS handshake) **na każde** wywołanie Voyage (embed i rerank); analogicznie [P] QdrantClient budowany od zera przy każdej operacji ([embedding_service.py:473](backend/app/services/embedding_service.py:473), [:52](backend/app/services/embedding_service.py:52)). Fix: moduł-singletony.
- **P3 [P]** [storage_service.py:56](backend/app/services/storage_service.py:56) — synchroniczne chunki na dysk w async upload.

---

## Filar 4 — matching / Qdrant / Voyage

- **P1 [P]** `score_candidate_job` = 2 sekwencyjne zapytania per parę ([scoring_service.py:889](backend/app/services/scoring_service.py:889), [:944](backend/app/services/scoring_service.py:944)) — systemowa przyczyna 2.1; na zimnym `/recommendations` 400+ szeregowych round-tripów.
- **P1 [P]** Rerank **domyślnie ON** ([config.py:39](backend/app/core/config.py:39): `RERANKER_ENABLED: bool = True`) — każde hybrydowe wyszukiwanie: pełne encje dla ~100–200 id + `_build_candidate_text[:4000]` × 200 → ~800 KB do Voyage ([hybrid_search.py:147-155](backend/app/services/hybrid_search.py:147)). Fix: zmierzyć wartość rerank przez `scripts/eval_matching.py`; jeśli zostaje — kolumnowy select + mniejszy pool.
- **P1 [P]** Outbox indeksowania embeduje **1 encję na call Voyage**, mimo że `_voyage_embed_batch` (do 128 tekstów) już istnieje ([index_outbox_service.py:209-220](backend/app/services/index_outbox_service.py:209)) — przy burstach Traffit sync = tysiące osobnych calli z osobnym TLS.
- **P2 [P]** Query-embeddingi **celowo omijają cache** ([embedding_service.py:209-216](backend/app/services/embedding_service.py:209): „Queries skip the cache") — słuszne dla zapytań usera, ale recommendations/proposals/marketplace embedują **ten sam tekst joba** przy każdym wywołaniu → zbędny call Voyage per request. Fix: cache po hashu dla query-embeddingów jobów.
- **P2 [P]** Centroidy CC/pool ściągają **wszystkie** wektory członków do list Pythona i uśredniają w Pythonie ([cc_centroid_service.py:131](backend/app/services/cc_centroid_service.py:131)) — po backfillu CC największa kategoria to kilkanaście tys. × 1024 float — ~100+ MB przejściowo na 1G kontenerze. Fix: uśrednianie strumieniowe/batched.
- **P2 [P]** Marketplace sweeper re-scoruje cały pool przeciw każdemu zmienionemu jobowi do 4× w 30-minutowym cyklu ([marketplace_service.py:767](backend/app/services/marketplace_service.py:767)).
- **P2 [P]** Cache embeddingów robi UPDATE+COMMIT na **każdym trafieniu** (last_used) — write amplification na gorącej ścieżce ([embedding_cache.py:79](backend/app/services/embedding_cache.py:79)). Fix: update batched/okresowy.
- **P2 [NW]** Historical boost przeliczany na każdy `/recommendations` (2 calle Qdrant + agregacja SQL) ([similar_job_candidates.py:258](backend/app/services/similar_job_candidates.py:258)).
- **P2 [P]** Regex ekstrakcji skills z Champion/JD liczony od nowa dla **każdego kandydata** w przebiegu scoringu, choć zależy tylko od joba ([scoring_service.py:652-655](backend/app/services/scoring_service.py:652)) — czysty CPU na event loopie ×200. Fix: memo per job (lru_cache po job.id+hash tekstu).

---

## Filar 5 — infra / konfiguracja

- **P1 [P]** **1 worker uvicorna** ([entrypoint.sh:1841](backend/entrypoint.sh:1841): `exec uvicorn app.main:app` bez `--workers`) — API + 20 pętli + scoring + parsery dzielą 1 proces/1 rdzeń z 4. **Uwaga:** więcej workerów NIE jest prostym fixem — in-memory cache (`core/cache.py`), slowapi, WebSocket manager i pętle zakładają 1 proces (świadoma decyzja z audytu modułu 6). Właściwy kierunek: patrz „Decyzje" niżej.
- **P1 [P]** Postgres na fabrycznych defaultach ([docker-compose.yml:23](docker-compose.yml:23) — brak `command:`/config): shared_buffers 128 MB, work_mem 4 MB, random_page_cost 4.0 — przy limicie 1 G ([docker-compose.prod.yml:8-19](docker-compose.prod.yml:8)) i najcięższej roli na tej maszynie. Fix (tani, duży zysk): `command: postgres -c shared_buffers=256MB -c effective_cache_size=768MB -c work_mem=16MB -c maintenance_work_mem=128MB -c random_page_cost=1.1` (+ `shm_size: 256mb`).
- **P2 [P]** Brak kompresji odpowiedzi w aplikacji (grep: zero GZip w main.py) — duże JSON-y listy/analityki lecą nieskompresowane, chyba że Traefik ma compress (niepotwierdzone). Fix: `GZipMiddleware(minimum_size=2048)` albo potwierdzić compress na Traefiku.
- **P2 [P]** Pool SQLAlchemy 20+40=60 połączeń ([database.py:29-36](backend/app/core/database.py:29)) vs nietunowany PG z limitem 1 G (default max_connections=100; 60 z aplikacji + pętle = presja na RAM PG). Po tuningu PG ograniczyć overflow.
- **P2 [P-kontekst]** Entrypoint = **1841 linii** wykonywanych przy **każdym** starcie kontenera (alembic + ~200 idempotentnych DDL + skany UPDATE + seed + 6 spawnów Pythona) — to bezpośrednio wydłuża okno niedostępności deployu przy single replica (znany kontekst: prod-alembic orphaned, safety-net celowy). Kierunek: flaga „skip safety-net gdy brak zmian schematu" / hash-marker ostatnio zaaplikowanego zestawu.
- **P3 [NW]** Healthcheck frontendu SSR-uje `/` co 15 s ([frontend/Dockerfile:45](frontend/Dockerfile:45)); backend-image bez fallbacku HEALTHCHECK.
- **[DO SPRAWDZENIA W PANELU COOLIFY]** Czy prod overlay (`docker-compose.prod.yml` — limity pamięci + healthcheck backendu) jest w ogóle ładowany przez Coolify (`docker_compose_location`). Jeśli nie — limity i healthcheck **nie obowiązują na prod**, a to zmienia priorytet tuningu PG/limitów.

---

## Filar 6 — frontend

- **P2 [P]** TipTap/ProseMirror importowany **statycznie** w CandidateDetailV2 ([CandidateDetailV2.tsx:8-9](frontend/src/components/v2/pages/CandidateDetailV2.tsx:8)) — najcięższa strona aplikacji ładuje edytor zawsze, nawet gdy nikt nie pisze notatki (pomiar znalazcy: ~539 kB gz route JS). Fix: `next/dynamic` dla edytora i ciężkich modali.
- **P2 [P]** Badge w sidebarze: co 5 min ([SidebarV2.tsx:413](frontend/src/components/v2/shell/SidebarV2.tsx:413)) **każda otwarta karta** strzela w `/api/candidates?page_size=1&created_after=…` (count po nieindeksowanym `created_at` — patrz 2.3), `/api/jobs?page_size=1` i **niepaginowane** `/api/pipeline/pending-verifications`. Fix: 1 dedykowany, tani endpoint badge (3 COUNT-y z indeksami) albo push przez istniejący WS.
- **P2 [P]** Polling mimo WebSocketów: notyfikacje co 30 s ([NotificationsDropdown.tsx:210](frontend/src/components/NotificationsDropdown.tsx:210)), KPI co 60 s, pending-verifications co 60 s pod dwoma różnymi query-keys — per karta.
- **P3 [P]** Manager dashboard `refetchInterval: 30 s` na pipeline/overview ([manager/page.tsx:82](frontend/src/app/manager/page.tsx:82)) — mnożnik problemu 1.1; po fixie 1.1 i tak podnieść do 3–5 min.
- **P2 [NW]** recharts (~101 kB gz) eager na dashboardzie DL dla warunkowego wykresu ([DlTrendChart.tsx:5](frontend/src/app/dashboard/delivery-lead/_components/DlTrendChart.tsx:5)).
- **P3 [NW]** ImportTab poll co 5 s bez warunku ([ImportTab.tsx:41](frontend/src/components/settings/admin/ImportTab.tsx:41)); dnd eager w route jobów ([KanbanBoardV2.tsx:12](frontend/src/components/v2/pages/KanbanBoardV2.tsx:12)).
- **[O-częściowo]** „QuickActionsV2 (2053 linie) w bundlu każdej strony przez AppShell" — import w AppShellV2 jest **type-only** ([AppShellV2.tsx:15](frontend/src/components/v2/shell/AppShellV2.tsx:15)), więc sam w sobie nie bundluje modułu; wymaga sprawdzenia realnego miejsca montowania zanim ktoś to „naprawi".

---

## Obalone — nie wracać do tych tematów

1. **„match_score_cache bez indeksu po job_id"** — indeks JEST, w migracji `0014_match_score_cache` (znalazca czytał tylko model ORM; indeksy tej tabeli żyją w alembicu).
2. **„Marketplace membership reconcile ładuje wszystko do Pythona"** — skala i częstotliwość czynią koszt pomijalnym (id-sety, nie encje).
3. **„Saved-search alerts co 30 min przez pełny stack HTTP"** — mechanika prawdziwa, ale `ix_candidates_updated_at` (migracja `0131`) powstał **celowo** pod tę pętlę i neutralizuje koszt.
4. **(częściowo)** „QuickActionsV2 w bundlu layoutu" — patrz filar 6.

## Czyste obszary (potwierdzone pozytywy — nie ruszać)

- `dashboard_metrics` / lista kontraktów (selectinload + batched latest-order) / lista jobów (batched county) / kanban (bulk-load nazw) / `analytics_v1` (SQL-metryki + cache kopert) / `hybrid_search` faza retrieval (gather + RRF) — **bez N+1**.
- Wyszukiwanie kandydatów `?q=` — po PR #432 (UNION-of-ids na indeksach GIN pg_trgm) — nie dotykać predykatów bez EXPLAIN.
- Uwaga-niuans: `/api/dashboard/stats` nie ma N+1, ale też **nie ma cache** (docstring sugeruje współdzielenie z cache'owanym `/api/admin/snapshot`, ale sam endpoint liczy ~8 COUNT-ów na każde wejście na dashboard) — tani fix: ten sam cache 30 s co snapshot.

---

## Plan naprawczy — proponowane fale

**Fala A — quick wins (1 tydzień, każdy punkt = mały PR, zysk natychmiastowy):**
1. `pipeline/overview` → DISTINCT ON / widok `analytics_current_pipeline` + cache 60 s (wzór z phase3.py) + FE interval 30 s → 5 min. *(zabija największy pojedynczy koszt)*
2. Triggers: wspólny snapshot latest-stage 1×/tick + marker dla stuck-7d; slack_sla na tym samym snapshocie.
3. `include_match_stats` → 2 zapytania setowe + scoring in-memory + log DEBUG.
4. `smtplib` → `asyncio.to_thread`; bcrypt → `to_thread`.
5. Global search → predykat zgodny z indeksem 0013; klient jobów bez N+1.
6. Indeksy: `activities(created_at)`, `candidates(created_at)`, `lower(email)` — **pamiętać o mirrorze w entrypoint safety-net!**
7. `GZipMiddleware` (po sprawdzeniu Traefik compress) + cache 30 s na `/dashboard/stats`.
8. Postgres `command:` tuning + `shm_size` (walidacja: czy Coolify ładuje prod overlay).

**Fala B — DB/ORM (1–2 tygodnie):**
`deferred(raw_cv_text)` + slim list query + bieżący etap bez pełnej historii; eksporty: kolumnowy select + streaming CSV + XLSX w to_thread + realny cap; autocomplete firm/tytułów z materializowanej tabelki; advanced search 3×→1× filtr; kalendarz batched.

**Fala C — matching/Voyage/Qdrant (wymaga eval_matching.py przed/po!):**
Outbox batch-embed (128/call); cache query-embeddingów jobów; singletony httpx/Qdrant; memo skills-per-job; centroidy strumieniowo; decyzja o rerank (pomiar wartości vs 800 KB/query); embedding_cache last_used batched.

**Fala D — frontend:**
dynamic() dla TipTap/recharts/dnd; 1 tani endpoint badge + konsolidacja pollingu z WS; przegląd intervalów (30 s/60 s → eventy).

**Decyzje wymagane (nie robić bez uzgodnienia):**
- **Wydzielenie 20 pętli do osobnego kontenera „worker"** — właściwy fix na „1 rdzeń z 4", ale wymaga rozwiązania WS-broadcastów i in-memory stanu (single-replica założenie z audytu modułu 6). Alternatywa minimalna: zostawić 1 worker API, przenieść tylko pętle ciężkie CPU/DB (triggers, sweeper, sync) — one nie trzymają stanu w pamięci procesu API poza WS.
- Zwiększenie `--workers` uvicorna — **NIE** bez powyższej architektury (rozjedzie cache/slowapi/WS/pętle uruchomione ×N).
- `RERANKER_ENABLED` — pozostawić/wyłączyć po pomiarze.

## Metryki audytu

128 agentów (10 znalazców, ~110 weryfikatorów w 2 przebiegach + wznowienia), ~6,6 mln tokenów, 550 wywołań narzędzi; 98 surowych znalezisk → ~75 unikalnych → 55 potwierdzonych (37 sceptyk + ~18 ręcznie), 4 obalone, reszta [NW] (P2/P3). Weryfikacja 5 wymiarów przerwana limitem sesji — wszystkie P0/P1 z tych wymiarów doweryfikowane ręcznie w kodzie; [NW] zostały tylko pozycje niższej wagi.
