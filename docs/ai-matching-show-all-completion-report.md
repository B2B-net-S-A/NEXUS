# AI Matching — „pokaż wszystkich pasujących kandydatów" (zamiast top‑10)

**Data:** 2026-05-29 · **PR:** [#367](https://github.com/artur-t-96/Nexus/pull/367) · **Commit na main:** `77aeac0` · **Status:** zdeployowane + zweryfikowane na prod.

## Cel

Na `/jobs/{id}` → zakładka **AI Matching** oba silniki zwracały sztywno **top‑10 najlepszych** kandydatów. Zmiana: zwracają **wszystkich kandydatów, którzy pasują** (score ≥ próg dopasowania), posortowanych malejąco. Próg — nie arbitralny top‑K — decyduje, kto się pokazuje.

Dotyczy obu sekcji zakładki:
- **Rekomendowani kandydaci** — hybrydowy scorer 0‑100 (snapshot + live fallback).
- **Klasyczne AI Matching (legacy)** — `/ai-matches` (semantic Qdrant + Voyage rerank + tag fallback).

## Kalibracja progów (zmierzona na żywym rozkładzie joba 15 — Scrum Master, PRZED wyborem progu)

- **legacy rerank** (Voyage rerank‑2.5, 0‑1): klaster **0.61‑0.87** — czysty sygnał trafności.
- **hybrydowy composite** (0‑100): 2 wyróżniki (58.9, 53.8) + długi płaski ogon **24‑34** (kandydaci dociągnięci semantycznie, ale composite zaniżony bo salary/location/availability często nieznane → punkty częściowe). To sygnał **rankingowy**, nie skalibrowane 0‑100.
  - ≥25 → **48** · ≥30 → 6 · ≥50 → 2 (stąd próg 25, nie 50).

## Ustawienia (runtime‑tunable przez Coolify env, `is_runtime` — bez rebuildu)

| Setting | Default | Skala | Silnik |
|---|---|---|---|
| `AI_MATCH_MIN_SCORE` | `0.5` | 0‑1 | legacy `/ai-matches` |
| `RECOMMENDATION_MIN_SCORE` | `25.0` | 0‑100 | hybrydowe `/recommendations` + proposals |
| `AI_MATCH_POOL_SIZE` | `100` | — | pula retrieval legacy (koszt rerank ~liniowy) |
| `MATCH_MAX_RESULTS` | `200` | — | twardy bezpiecznik rozmiaru payloadu (oba) |

Strojenie: jeśli wyników za dużo/za mało → zmień próg w Coolify env vault + restart kontenera (nie wymaga rebuildu). Patrz `~/.claude/rules/deployment-runbook.md §3`.

## Zmienione pliki

**Backend (6)**
- `app/core/config.py` — 4 nowe ustawienia + notatka kalibracyjna.
- `app/api/matching.py` — `get_ai_matches`: poszerzona pula (`AI_MATCH_POOL_SIZE`), rerank **całej** puli (`top_k=len(docs)`), filtr `match_score ≥ próg` zamiast trim top‑10; fallback tag‑based też po progu. Sygnatura: `top_k` → `min_score`/`limit` (query overrides). `min_score` w odpowiedzi.
- `app/api/recommendations.py` — `recommend_candidates_for_job`: filtr `total ≥ próg` przed capem; `top_k` default 20→200 (rola: bezpiecznik), `le` 100→200; `min_score` query override + w odpowiedzi.
- `app/tasks/compute_proposals.py` — snapshot: filtr `total ≥ RECOMMENDATION_MIN_SCORE` przed capem; default `top_k` → `MATCH_MAX_RESULTS`.
- `app/api/jobs.py` — auto‑snapshot na create: `top_k` 20 → `MATCH_MAX_RESULTS`.
- `app/api/proposals.py` — regenerate: `top_k` default/le → `MATCH_MAX_RESULTS`.

**Frontend (3)**
- `components/SuggestedCandidatesWidget.tsx` — usunięty selektor „Top N" (jego jedyny cel to cap, sprzeczny z „pokaż wszystkich"); pokazuje wszystkich pasujących; `topK` = stała 200 (bezpiecznik).
- `app/jobs/[id]/page.tsx` — legacy `getMatches(jobId, 10)` → `getMatches(jobId)`.
- `lib/api.ts` — `matchingApi.getMatches(jobId, opts?)` bez sztywnego `top_k=10`.

## Brak nowych migracji / endpointów

Bez zmian DB. Bez nowych endpointów — zmiana zachowania istniejących `GET /api/jobs/{id}/ai-matches`, `GET /api/jobs/{id}/recommendations`, `POST /api/jobs/{id}/proposals/regenerate`.

## Wpływ na jakość matchingu

Zmiana **nie rusza** funkcji scoringu ani kolejności rankingu — tylko zdejmuje cap i dodaje filtr progu **po** rankingu. Metryki `eval_matching.py` (P@5/Recall@20/MRR/nDCG@10, liczone na uporządkowanej liście) pozostają **bez zmian**. Re‑run eval niepotrzebny.

## Weryfikacja (prod, 2026-05-29)

- CI green: gitleaks, ruff (check+format), pytest (BE), Trivy/hadolint, ESLint+tsc+build (FE), Claude review.
- `/api/health` → `healthy`, `version=77aeac0…`.
- **API** (job 15, login claude‑admin):
  - `/ai-matches` → `min_score=0.5`, **n=100** (było 10), wyniki 0.56‑0.87.
  - `/recommendations` → `min_score=25.0`, **n=47** (było 10), dół = 25.0.
  - `/proposals/regenerate` → snapshot `ready`, **n=39**, `top_k=200`, dół 25.0 (39 < 47 bo snapshot wyklucza kandydatów już w pipeline).
- **UI (Chrome)**:
  - „Klasyczne AI Matching (legacy)": **„Znaleziono 100 pasujących kandydatów"**, lista renderuje do #100 (score 56%).
  - „Rekomendowani kandydaci **(39)**": „AI zaproponowało 39 kandydatów", lista renderuje; selektor „Top N" **usunięty**.

## Znane ograniczenia / uwagi

- **legacy zwraca pełną pulę 100 dla popularnych ról** (np. Scrum Master), bo reranker ocenia wszystkich 100 retrieved jako ≥0.56. To poprawne („wszyscy pasują"), ale dla ról niszowych przejdzie mniej. Większe pokrycie = ↑ `AI_MATCH_POOL_SIZE` (rośnie koszt rerank Voyage ~liniowo).
- **snapshot ≠ live** w liczbie: snapshot wyklucza kandydatów już w pipeline joba (świadome — to nie „propozycje"); live `/recommendations?exclude_in_pipeline=false` ich uwzględnia.
- Progi to sygnały jakości danego silnika (rerank 0‑1 vs composite 0‑100), różne skale — nieporównywalne 1:1; oba tunowalne niezależnie.
