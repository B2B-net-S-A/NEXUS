# Matching M3 — containment PR A + PR B: raport ukończenia

> Data: 2026-07-16 (Europe/Warsaw)
> Plan źródłowy: `docs/matching-scoring-recommendations-module-audit-and-claude-implementation-plan-2026-07-16.md` (Codex, 18 PR-ów)
> Zakres tej iteracji: **weryfikacja audytu + PR 1 planu + fragment PR 2 + frontendowe quick winy zaufania** (decyzja: containment-first)

## 1. Weryfikacja audytu Codex (przed implementacją)

Wszystkie sprawdzone twierdzenia P0 potwierdzone w kodzie `origin/main` (78aab28):

| Ustalenie | Werdykt | Dowód |
|---|---|---|
| M3-API-01 recompute-scores zepsuty | ✅ potwierdzony, gorszy niż opisano | route→route call bez `request` (slowapi TypeError) + sentinele `Query(...)` jako wartości `profile_id`/`min_score` |
| M3-COST-01 nieograniczony koszt /ai-matches | ✅ | `effective_pool = max(pool, limit)` przy `location` → nieograniczony Qdrant fetch + rerank Voyage z raw CV |
| M3-SEC-01 RBAC | ✅ częściowo | `POST /assign-to-job` na CurrentUser = read-only viewer mógł mutować pipeline; viewer mógł triggerować płatne generacje Claude; odczyt PII przez viewer = baseline całej appki (nie osobliwość matchingu) |
| M3-VEC-01 Ollama miesza przestrzeń | ✅ | cache embeddingów chroniony (tylko Voyage), ale Qdrant NIE — fallback vector trafiał do kolekcji Voyage |
| M3-TX-01 serwisy commitują cudzą sesję | ✅ | match_score_cache, telemetry, outbox `_commit_enqueue` |
| M3-CACHE-01 degraded → cache fresh | ✅ | fallback bez Qdranta liczy composite z neutralnym semantic i zapisywał do cache |
| M3-JOB-01 marketplace starvation | ✅ | top-30 Qdrant ze WSZYSTKICH statusów → filtr published po fakcie; payload Qdrant nie ma `status` |
| Ukryty historical boost (66.2 vs 61.2) | ✅ | backend zwraca `historical_boost` w breakdown; frontendowy typ go nie znał → tooltip nie renderował |
| `(TODO)` + „Pokaż wszystkie" w UI | ✅ | ContractorMatchCard.tsx:369 |
| 5 vs 6 warstw w /settings/scoring | ✅ + dodatkowy bug | edytor 5-warstwowy; **każdy zapis ustawiał champion_fit=0 (cicho wyłączona warstwa Champion)**; stare rekordy bez klucza dostają +10 ponad budżet 100 |
| `query.current_user: Field required` na prodzie | ✅ zlokalizowana klasa | `extractErrorMsg` renderował surowy `loc` z walidacji FastAPI |
| „38 przed 40" w candidate→jobs | ⚠️ celowy design | published > draft w sortowaniu (`_recommendation_rank_key`) — problem komunikacji, nie bug |

## 2. Decyzje produktowe (Artur, 2026-07-16)

1. **Zakres sesji:** PR A (backend containment) + PR B (frontend trust). PR 3-6 planu (RankingBundle, telemetry V2, ground truth, evaluator) — wstrzymane do osobnej decyzji.
2. **`SCORE_UNKNOWN_NEUTRAL_FRACTION=0.65` zostaje.** Codex M3-SCORE-02 (unknown bez punktów) odrzucony na teraz — sprzeczny z wcześniejszą świadomą decyzją („scoring za surowy"); zmiana semantyki rankingu wymaga evaluatora, którego jeszcze nie ma (sam plan tego wymaga).
3. **Legacy „Klasyczne AI Matching" ukryte dla nie-adminów** — tani krok przejściowy przed pełną migracją do jednej listy (PR 13 planu).

## 3. Krytyka planu — co odrzucone/odroczone i dlaczego

- **PR 3–6 (infra wersjonowania/telemetrii):** poprzedni 13-PR program AI matching zbudował już telemetry scaffold, outbox, manifest — wszystko flag-OFF i nieużywane na prodzie. Budowanie „V2" na niewłączonej „V1" = piętrowanie martwej infrastruktury. Najpierw decyzja o włączeniu istniejących flag (shadow), potem rozbudowa.
- **PR 7 (scoring V3):** zmiana znaczenia unknown przetasowałaby wszystkie rankingi bez narzędzia do zmierzenia skutku — dokładnie to, czego plan zakazuje („nie zmieniać wag na wyczucie").
- **PR 16–17 (experiment control plane, calibration registry, learned ranker):** enterprise ML-platform dla zespołu, którego nie ma; sam plan czyni PR 17 opcjonalnym.
- **M3-TX-01 pełny refactor transakcji:** wzorzec brzydki, ale przy read-only GET-ach dziś nieszkodliwy; dotknąć przy unifikacji silnika.
- **Draft joby z „Przypisz":** normalna praktyka sourcingu — kod robi to celowo; nie „naprawiano".

## 4. PR A — backend containment ([#776](https://github.com/artur-t-96/Nexus/pull/776))

- **M3-API-01:** `_recommend_candidates_core()` wydzielony z route'a; `recompute_scores` woła core (plain async, bez transportu FastAPI). Endpoint znowu działa.
- **M3-COST-01:** `GET /jobs/{id}/ai-matches` — `limit` 1..500, `min_score` 0..1, `location` ≤120.
- **M3-SEC-01:** powierzchnie matching z PII → `OperationalUser` (ai-matches, recommendations job+candidate, candidates-from-similar, seeking-contractors, marketplace GET×3, proposals GET×2, manual/scores/diagnostics/semantic search, scoring justification, cv-upload-preview). Mutacja `assign-to-job` → `RecruiterPlus`. Nav search (`GET /`, `/global`) zostawiony na CurrentUser (nawigacja dla viewera-QC).
- **M3-VEC-01:** `generate_embedding` — fallback do Ollamy TYLKO gdy Voyage nieskonfigurowany (tryb offline/dev); skonfigurowany-a-padnięty → `None` (degraded), bez mieszania przestrzeni w kolekcji Voyage.
- **M3-CACHE-01:** `bulk_get_or_compute(allow_cache_write=False)` na ścieżce degraded — `/recommendations` i `compute_proposals`. `pipeline-scores` już wcześniej odporne.
- **M3-JOB-01:** `JOB_SEMANTIC_POOL_SIZE=150` — szeroka pula przed filtrem statusu w marketplace scan, reverse recommendations i seeking-contractors. Właściwy fix (status w payloadzie Qdrant + backfill payloadów, bez re-embedu) — w dalszej części programu.
- **Testy:** `backend/tests/test_matching_containment.py` (bounds 422, recompute 200 e2e — przed fixem 500, viewer 403 read+mutacja, admin 200, degraded-no-cache-write, no-Ollama-mixing) — dopisane do selektywnego slice'u pytest w `ci.yml` (M3-CI-01).

## 5. PR B — frontend trust ([#778](https://github.com/artur-t-96/Nexus/pull/778))

- **M3-SCORE-01:** wiersz „Historia +X pkt" w `ScoreBreakdownTooltip` (+ typ `ScoreBreakdown.historical_boost/…_sources_count/fit_confidence`); suma widocznych warstw = total. Testy vitest.
- **5→6 warstw:** `/settings/scoring` edytuje `champion_fit` (default = built-in 35/30/12/8/5/10); edycja legacy-profilu pokazuje realną sumę (110) i wymusza rebalans do 100.
- **M3-UI-01:** legacy sekcja + „Przelicz scoring"/„Embed all jobs" tylko dla admina (widok diagnostyczny).
- **M3-UI-01 marketplace:** `(TODO)`/„Pokaż wszystkie" → uczciwy opis + realna kontrolka „Min. dopasowanie (0–100)" w filtrach.
- **M3-UI-02:** `extractErrorMsg` nie pokazuje surowego `loc` walidacji dla query/path/header (fix klasy `query.current_user: Field required`); pola `body` (input użytkownika) nadal actionable.

## 6. Weryfikacja delivery

- CI: <do uzupełnienia po merge>
- Merge: <SHA po merge>
- Deploy + `/api/health` version match: <po deployu>
- Chrome smoke (UI): <po deployu>

## 7. Znane ograniczenia / następne kroki (propozycja kolejności)

1. **Decyzja o włączeniu istniejących flag telemetrii/outboxu w shadow** (warunek sensowności PR 3-6 planu).
2. Status jobów w payloadzie Qdrant + backfill payloadów (`set_payload`, bez re-embedu) → filtry po stronie Qdranta zamiast overfetchu.
3. M3-ELIG-01: wspólna brama eligibility na read-surfaces (batch po retrieval).
4. M3-ACT-01: jeden `AddCandidateToJobCommand` (obecnie ścieżki mają różne side-effects; single-assign ma gate eligibility, inne różnie).
5. M3-SNAP-01: durable proposal generation (dziś FastAPI BackgroundTasks — deploy może zostawić `pending`).
6. Dopiero potem: unifikacja silnika (PR 12-14 planu) w shadow/canary.
