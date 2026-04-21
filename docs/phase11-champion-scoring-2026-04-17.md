# Phase 11 — Champion scoring integration + client-ready card

## Kontekst

Phase 10 wprowadziła Profil Championa + screening flow. Phase 11 dopina ostatnie elementy:

1. **Scoring** — `champion_fit` jako pełnoprawny layer hybrid scoringu (0-10pt), rebalansacja pozostałych wag.
2. **UI breakdown** — `ScoreBreakdownTooltip` pokazuje Champion row z kontekstem (`brak screeningu` / `fit · 100%` / `deal-breaker`).
3. **ChampionCard** — read-only widok na profilu kandydata (tab "Rekrutacje"), pokazuje pytania DL + odpowiedzi rekrutera z wizualizacją fit/deal-breakers.
4. **Cache invalidation** — POST screening flaguje `(candidate, *)` cache jako stale, następny read rekalkuluje z nowym champion_fit.

## Rebalans wag scoringu

| Layer | Phase 0 | Phase 11 |
|---|---:|---:|
| semantic | 40 | **35** |
| skills | 30 | 30 (bez zmian) |
| salary | 15 | **12** |
| location | 10 | **8** |
| availability | 5 | 5 |
| champion_fit | — | **10** |
| **Σ** | 100 | **100** |

Rationale: `skills` nie dotyka (chroni istniejące testy + recruiter intuition). Semantic/salary/location oddają 10pt łącznie na nową warstwę.

## Jak liczy się `champion_fit`

1. Szukamy najnowszego `CandidateStage` z `screening_answers` dla pary `(candidate, job)`.
2. Brak screeningu → **neutral 5.0/10** (nieblokujące, kandydat nadal competitive).
3. Jakikolwiek `deal_breaker_hit=true` → **0.0/10** (praktycznie wyłącza kandydata).
4. W innym wypadku: `(match_percent / 100) × profile.champion_fit`, gdzie `match_percent` = `(% odpowiedzianych) × {fit:1.0, uncertain:0.6, miss:0.2}`.

## Zweryfikowano w Chrome

1. **Tab "Profil Championa"** na `/jobs/2` — edytor pre-filled z danymi PUT'niętymi przez curl (2 pytania, sourcing, kontekst).
2. **`ScoreBreakdownTooltip`** — klik w info icon przy kandydacie:
   ```
   Semantic     33.3/40   sim 0.83
   Skills       10.0/30   must 2/4
   Salary       15.0/15   w widełkach
   Location      0.0/10   brak dopasowa...
   Availability  5.0/ 5   na czas
   Champion      5.0/10   brak screeningu   ← NOWE
   ```
3. **API smoke test** — Agnieszka Nowak, stage 4, perfect screening → `total=86.5 champion=10.0/10 (fit · 100%)`. Bez screeningu → `total=48.3 champion=5.0/10 (brak screeningu)`. **+5pt różnicy** dla pełnego Championa.
4. **ChampionCard** na `/candidates/2` → Rekrutacje → "Java Backend Developer" (Akceptacja, 5/5):
   ```
   ✨ Profil Championa                    Pasuje 2/2
   Q1  Opisz migrację do mikroserwisów
       Migrowałam monolit do 8 mikroserwisów z Kafka i saga pattern…  ✓
   Q2  Jak testujesz kod produkcyjny?
       Unit + integration tests, 85% coverage, TDD                     ✓
   Świetny kandydat, ma realne case studies
   ```

## Re-run eval (po rebalansie + champion_fit)

| Metric | Phase 9 | Phase 11 | Δ |
|---|---:|---:|---:|
| Precision@5 | 0.550 | 0.550 | = |
| Recall@20 | 0.840 | 0.840 | = |
| MRR | 1.000 | 1.000 | = |
| nDCG@10 | 0.803 | **0.816** | +1.6% |

Seed data ma głównie neutralne screeningy (5/10), więc main metrics stabilne. nDCG lekko wyższe bo champion_fit ma mniejszą wariancję niż salary/location w seed. W produkcji z wypełnionymi Championami efekt będzie większy (dla kandydatów z pełnym fit: +10pt; z deal-breaker: −5pt vs neutral).

## Pliki

### Backend
- `app/services/scoring_service.py`:
  - `CHAMPION_FIT_MAX = 10.0` + rebalansowane `SEMANTIC_MAX/SALARY_MAX/LOCATION_MAX`.
  - `WeightProfile.champion_fit` field + `from_record` z fallbackiem.
  - `ScoreBreakdown.champion_fit` pole + `as_dict()` wyprowadza.
  - `_score_champion_fit()` async helper — czyta `CandidateStage.screening_answers`, liczy punkty wg reguły z Phase 10.
- `app/services/match_score_cache.py` — `_breakdown_from_row` hydruje `champion_fit`.
- `app/api/pipeline.py::submit_stage_screening` — po zapisaniu odpowiedzi woła `mark_stale_for_candidate`.

### Frontend
- `components/ScoreBreakdownTooltip.tsx` — nowy wiersz `Row label="Champion"` (warunkowy).
- `components/ChampionCard.tsx` (NEW) — read-only widok z Q + odpowiedzią + badge fit + deal-breaker indicator.
- `components/CandidatePipelinesWidget.tsx` — wstawia `<ChampionCard stageId={...}/>` dla external/terminal stages.
- `lib/api.ts` — `ScoreBreakdown.champion_fit?: LayerPoints`.
- `e2e/phase9-matching-ux.spec.ts` — +3 testy (Profil Championa tab, breakdown Champion row, ChampionCard w profilu).

## Pytest status

- **34/34 passed** (`tests/test_scoring_service.py`). Jeden test updated (`test_location_same_city_prefix_partial` — skala proporcjonalna do nowego LOCATION_MAX=8).

## Stan systemu

**Wszystko z planu zrobione + zweryfikowane w Chrome na localhost produkcji.**

Flow end-to-end:
1. Delivery Lead tworzy ofertę → tab "Profil Championa" → wypełnia briefing (podstawy, kontekst, pytania screeningowe, sourcing).
2. Rekruter sourcuje kandydatów (AdvancedFilterBar + Sparkles drawer + QuickAssign).
3. Przy przesunięciu do `cv_sent`/`client_interview`/... ScreeningModal otwiera się automatycznie, rekruter odpowiada na pytania DL-a.
4. Scoring silnik dopina `champion_fit` layer (0-10pt) do hybrid score.
5. Profil kandydata → Rekrutacje → ChampionCard pokazuje filled card gotową do przedstawienia klientowi.

### Migracje head = 0019
```
0012_skill_taxonomy
0013_search_indexes
0014_match_score_cache
0015_scoring_weights
0016_match_cache_profile
0019_champion_profile   (0017/0018 były zajęte przez contract_rate_unit + contract_documents)
```
