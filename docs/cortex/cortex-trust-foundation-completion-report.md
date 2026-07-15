# Cortex Trust Foundation — completion report (2026-07-13)

Realizacja **Etapu 0** planu remediacji ([audyt](./cortex-audit-2026-07-13.md), zweryfikowany 34/35 twierdzeń). Cel: liczby Cortexa mają być **deterministyczne, aktualne i audytowalne** — zanim będą używane biznesowo. Jeden PR „Cortex Trust Foundation".

## Co naprawiono (P0/P1/P2 audytu)

### P0 — blokery jakości danych
- **Dedup taksonomii** (migracja `0160_cortex_trust_foundation`): scala 37 par case-insensitive (`python`/`Python`) + 5 par semantycznych (`kafka`→`Apache Kafka`, `express`→`Express.js`, `node`→`Node.js`, `rest`→`REST API`, `vue`→`Vue.js`). Repin aliasów + `cortex_skill_facts` na survivora (Title-Case, potem #aliasów, potem `MIN(id)`), scalenie kolizji faktów, canonical loser → alias. Guard: funkcyjne unique `lower(canonical_name)` / `lower(alias)`. `seed_skill_aliases.py` lookup teraz case-insensitive (nie odtworzy duplikatów). `load_taxonomy` deterministyczny (`order_by(id)` + głośny log na kolizji zamiast last-wins). **Korekta z weryfikacji:** scoring był już case-insensitive — dedup naprawia tech-map split + niedeterministyczny `skill_id`, NIE scoring.
- **Reconcile faktów** (`fact_store.normalize_and_upsert(reconcile=True)`): skill usunięty ze źródła znika z fact store (`DELETE ... skill_id NOT IN seen`). Per-kandydat **savepoint** (`begin_nested`) — zatruta transakcja jednego nie ubija runu.
- **Idempotentny unmatched** (`cortex_unmatched_observations`, UNIQUE `term+candidate+source`): `occurrences` liczy UNIKALNYCH kandydatów; rerun na niezmienionych danych NIE zawyża licznika (dawny `+1` per przebieg). Test `test:113` zmieniony na `== first_occurrences`.

### P1
- **Trwałe runy** (`cortex_extraction_runs`): zastępują in-memory `_TRAFFIT_JOB`. Single-flight atomowy przez **partial unique** `(source) WHERE status='running'` (koniec TOCTOU) — nie advisory lock (ten nie przeżyłby wymiany połączenia z puli między commitami). Status endpoint czyta trwały wiersz (przeżywa restart). **Orphan reaper** sprząta porzucone runy.
- **Daily sync**: faza `cortex` po `candidates` w `traffit_sync._phase_plan` — delta (tylko kandydaci dotknięci w runie) + tygodniowy full reconcile. Kill-switch `CORTEX_SYNC_ENABLED` (default True, gated też przez `TRAFFIT_SYNC_ENABLED`).
- **Deep health**: 4 tabele Cortex w `/api/health/deep` `core_checks`. `checks.cortex` (świeżość ostatniego runu) w `/api/health` — overall status pozostaje DB-only (nie psuje smoke-testu).
- **Heatmapa/KPI** (`tech_map.py` + `TechMapHeatmap.tsx`): prawdziwe `skill_totals` (Σ bez `min_count`); `candidates_covered` overlap-aware headline; `sources` jako rozbicie (nie sumować); mianownik respektuje kohort; globalna skala koloru + legenda; token `hsl(var(--primary)/α)` zamiast hardcoded rgba; `<caption>` + `<th scope="row">`. `data_as_of` w obu raportach.
- **Frontend error-states**: `TechMapPanel`/`CoveragePanel` obsługują `isError` (retry zamiast wiecznego spinnera); invalidacja `cortex-coverage` + `cortex-tech-map` po zakończeniu backfillu.
- **Multi-role RBAC**: JWT niesie claim `roles` (unia primary+secondary), `middleware.ts` sprawdza unię (fallback na `role` dla starych tokenów). Koniec `/403` dla usera z rolą secondary.

### P2
- DB CHECK dla `source`/`level`/`years`/`confidence`/`status`; provenance na faktach (`extractor_version`, `run_id`, `content_hash`, `source_ref`); indeks `cortex_unmatched_terms(status)`; freshness token map w `CoverageView`.

## Pliki
- **Nowe:** `alembic/versions/0160_cortex_trust_foundation.py`, `app/services/cortex/runs.py`, ten raport.
- **Backend:** `models/cortex.py` (+3 modele, provenance, CHECK), `services/cortex/{fact_store,extractor_traffit,tech_map,coverage}.py`, `api/cortex.py`, `tasks/traffit_sync.py`, `main.py`, `core/{config,security}.py`, `api/{auth,auth_microsoft}.py`, `scripts/seed_skill_aliases.py`, `entrypoint.sh`.
- **Frontend:** `components/cortex/{TechMapPanel,CoveragePanel,TechMapHeatmap,CoverageView}.tsx`, `lib/api.ts`, `middleware.ts`, `app/preview/cortex/page.tsx`.
- **Testy:** `tests/test_cortex_{api,traffit_extract}.py` (idempotencja + reconcile + DB single-flight guard).

## Weryfikacja
- ✅ ruff check + ruff format (`app/`), tsc `--noEmit`, ESLint — zielone lokalnie.
- ⏳ Backend integracyjne (Postgres) + `alembic upgrade heads` + import smoke — walidowane w CI (brak lokalnego Postgresa/venv).
- **Reguła entrypoint 3-place** dopełniona: każda nowa tabela/kolumna/indeks mirrorowana w `entrypoint.sh` `_COLUMN_STATEMENTS`.

## Znane ograniczenia / operacyjne
- **Przed migracją na prod:** read-only SQL audyt realnego stanu duplikatów taksonomii (kryterium wejścia audytu). Migracja jest idempotentna + guarded, ale scalanie danych jest nieodwracalne (downgrade zdejmuje tylko schemat).
- **Fully-cleared candidate:** jeśli kandydat wyczyści CAŁE `traffit_technologie`, filtr „niepuste" pomija go → jego stare fakty nie są reconcilowane (rzadki edge; token usunięty z NIEpustego pola jest obsłużony). Do rozważenia w Etapie 1.
- **content_hash** populowany, ale skip-unchanged jeszcze nie używa go (świadomy defer — Etap 0 = poprawność, nie perf).
- **Unmatched reconcile-on-removal** nie zaimplementowany (kandydat porzucający unmatched term → drobny overcount; kolejka kuracji, nie metryka precyzyjna).
- **Aktywacja daily sync:** wymaga `TRAFFIT_SYNC_ENABLED=true` (+ secrety Traffit) na prod.

## Etap 1 — Action Layer (zrobione, commit `615bf1b`)
Backend (`app/services/cortex/{drill_down,client_stack,curation}.py`, endpointy `app/api/cortex.py`, migracja `0161_cortex_curation_audit`):
- **drill-down** `GET /skill/{id}/candidates` — kandydaci z evidence/confidence/świeżość/seniority/zatrudnienie (RODO gate); `GET /skills` — pełna, przeszukiwalna, paginowana lista (koniec top-40).
- **client × stack** `GET /client-stack` (contract ∪ hired→job→client); **następcy** `GET /successors` (kontrakty kończące się w N dni + dostępni ze wspólnym stackiem).
- **kuracja** (admin, audyt `curated_by/at`): `POST unmatched-terms/{id}/map|ignore`, `POST skills`, `POST skills/{id}/aliases` + odświeżenie `ALIAS_MAP`.
- `tech-map` zwraca `skill_ids` (drill-down z komórki); unmatched/coverage zwracają `id`.
Frontend: nowe zakładki `CortexView` (Technologie, Klienci, Następcy, Kuracja) + `SkillCandidatesDrawer` (klikalne komórki), filtry heatmapy w URL.
PR0: plik audytu zwersjonowany + korekty (atrybucja a11y, staleness, „scoring już case-insensitive").

## Etap 2 — Intelligence Layer (zrobione + świadome bramki)
Zbudowane (`app/services/cortex/{extractor_cv_llm,resolved,supply_demand}.py`, endpointy, `scripts/eval_cortex_extraction.py`):
- **CV/LLM extractor** (`source=cv_llm`, `parse_cv` na `raw_cv_text`) — gated `CORTEX_CV_LLM_ENABLED` (default OFF), **nigdy auto**, tylko admin endpoint `POST /admin/backfill-cv-llm`, przez `cortex_extraction_runs`, `only_active` first, `limit` dla kontrolowanej populacji.
- **resolved facts** — jeden fakt per (kandydat, skill): precedencja `screening>cv_llm>traffit` × freshness-decay; `GET /candidate/{id}/resolved-skills`; helper `resolved_canonical_names` pod scoring.
- **podaż vs popyt** `GET /supply-demand` (rozwiązane fakty vs skille otwartych jobów, luki); **normalizacja tytułu** `GET /normalize-title` (heurystyka, bez LLM).
- **harness** precision/recall ekstrakcji (gold-set) — gotowy do użycia po oznaczeniu ~30-50 kandydatów.
Frontend: zakładka „Podaż/Popyt", karta CV-LLM backfill (admin), rozwiązane kompetencje w drawerze.

**Świadome bramki (NIE wpięte domyślnie — wymagają walidacji, której nie da się zrobić autonomicznie):**
- **Integracja resolved facts ze scoringiem/Qdrant** — flaga `CORTEX_FACTS_IN_SCORING` (default OFF, zero zmiany zachowania). Włączenie zmienia matching → **wymaga `scripts/eval_matching.py`** (reguła autonomous-verification §4) na danych prod-like. Building block gotowy (`resolved_canonical_names`), wpięcie w hot-path scoringu odłożone do walidacji.
- **Wymuszone procesy zbierania** (`close_reason`/`termination_reason`/availability/expected_rate/verified_tech) — duża zmiana produktowa (formularze + walidacja w wielu ekranach), część danych już istnieje na modelach; poza zakresem generacji kodu bez decyzji produktowych.

## Bramka wdrożeniowa (bez zmian)
Merge Etapu 0→2 na `main` **uruchamia nieodwracalną migrację dedup `0160` na prodzie**. Wymaga **read-only SQL audytu** realnych duplikatów przed merge (brak dostępu do prod-DB w tej sesji → nie mergowane autonomicznie).
