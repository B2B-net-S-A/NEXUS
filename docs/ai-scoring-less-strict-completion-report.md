# AI scoring — „mniej surowo, adekwatnie do oferty" (2026-06-30)

> Zgłoszenie: na ofercie **Ferryt Developer** (`/jobs/240915`) AI scoring kandydatów
> w pipeline (pierścienie na kartach Kanban) jest **dalej zbyt surowy**. Ma oceniać
> kandydatów adekwatnie do oferty, mniej surowo.

## Diagnoza (na żywych danych prod)

Pierścienie na Kanbanie pochodzą z `GET /api/jobs/{id}/pipeline-scores` →
`scoring_service.score_candidate_job` (hybrydowy composite 0-100), **nie** z zakładki
„AI Matching" (`/ai-matches`, surowy cosinus 0-1 — osobna powierzchnia, nietknięta).

Oferta 240915 to typowy import z Traffitu: **brak lokalizacji, brak deadline'u, brak
widełek, brak `must_skills`, brak Championa**, `remote_policy=hybrid`. Realny rozkład
score'ów w pipeline: **27–57**. Rozbicie najlepszego kandydata (sim 0.45, skille 1/1):

| warstwa | pkt | max | powód |
|---|---|---|---|
| semantic | 21.6 | 35 | sim 0.45 (gamma 0.6) |
| skills | 20 | 30 | must 1/1 (z opisu) |
| salary | 6 | 12 | brak danych → neutralnie (½) |
| **location** | **0** | 8 | **twarde zero** — brak lokalizacji oferty + brak preferencji remote |
| availability | 2.5 | 5 | brak daty → ½ (hardcode) |
| champion | 5 | 10 | brak screeningu → ½ (hardcode) |
| **razem** | **55.1** | 100 | |

**Sedno:** dla importów z Traffitu (norma ~99%) **35 ze 100 pkt żyje w warstwach
metadanych, które przy braku danych mogą przyznać tylko swój neutralny ułamek** — a
`location` przyznawała **0**, łamiąc własną konwencję silnika „brak sygnału = połowa
budżetu" (salary/availability/champion). Nawet idealny trafny kandydat dobijał ~55.

To **nie był bug, tylko świadoma decyzja** (test `test_location_empty_job_location_stays_noop`
z uzasadnieniem *„żeby nie zawyżać dominującej kohorty o stałą… chronić metryki eval"*).
Silnik trzymał score'y zaniżone celowo. Użytkownik chce odwrotnie — realnych liczb.

## Zmiana

Jeden spójny mechanizm „benefit of the doubt" dla **wszystkich czterech** warstw
metadanych, wszystko sterowane jedną gałką `SCORE_UNKNOWN_NEUTRAL_FRACTION`:

1. **`location` przestaje twardo-zerować przy braku sygnału** (brak lokalizacji oferty /
   brak preferencji remote kandydata) → neutralny ułamek, spójnie z salary/availability/
   champion. Znane niedopasowania (inne miasto, sprzeczne preferencje remote) dalej = 0.
2. **`availability` i `champion_fit`** — neutral przeniesiony z hardcode `0.5` na tę samą
   gałkę.
3. **Ułamek podniesiony `0.5 → 0.65`** (config) — nieznane = 65% budżetu, nie 50%.

**Efekt:** kohorta „wszystko nieznane" (dominująca) dostaje stały lift +~9 pkt:
- top trafny kandydat **55 → 64**,
- pierłcienie pipeline **27–57 → ~36–66**.

**Ranking zachowany → metryki eval (P@5, Recall@20, MRR, nDCG@10) niezmienione.** Lift
to **stały addytywny shift per-job** dla kohorty bez sygnału (potwierdza to istniejący
invariant `test_ranking_preserved_for_same_unknown_cohort`: `Δcomposite == Δsemantic`).
Zmiana jest **monotonicznie niemalejąca** dla każdego kandydata — nie potrafi obniżyć
żadnego score'a ani odwrócić kolejności w dominującej kohorcie.

**Reversible bez redeployu:** `SCORE_UNKNOWN_NEUTRAL_FRACTION=0.5` cofa ułamek; `=0.0` +
`SEMANTIC_CALIBRATION_GAMMA=1.0` to pełny escape hatch do zachowania sprzed 2026-06-23
(test `test_legacy_reproduced_with_gamma_1_and_neutral_0` to pilnuje).

## Pliki

| plik | zmiana |
|---|---|
| `backend/app/services/scoring_service.py` | `_score_location` (oba półbudżety neutralne przy braku sygnału), `_score_availability` + `_score_champion_fit` (neutral przez gałkę), default `ScoreBreakdown.champion_fit` |
| `backend/app/core/config.py` | `SCORE_UNKNOWN_NEUTRAL_FRACTION` 0.5 → 0.65 + komentarz |
| `backend/alembic/versions/0150_invalidate_match_cache_neutral065.py` | unieważnia cache `candidate_job_match_scores` (`stale=true`) → przeliczenie nowym silnikiem na pierwszym odczycie (jak `0143`) |
| `backend/tests/test_scoring_service.py` | 6 testów lokalizacji + availability + champion zaktualizowane; nowy `test_sparse_traffit_job_metadata_all_neutral` |

## Walidacja

- `ruff check app/` + `ruff format --check app/` — **pass** (lokalnie zweryfikowane).
- Cała arytmetyka testów zweryfikowana ręcznie; pełny pytest backendu leci w CI
  (`Backend (ruff + pytest)`) — środowisko dev jest Docker-only, brak lokalnego venv.
- **Cache:** migracja `0150` ustawia `stale=true`, więc po deployu pierwsze otwarcie
  pipeline przelicza score'y nowym silnikiem (pojedynczy `UPDATE` boolean — bez ryzyka
  timeoutu smoke-testu, w przeciwieństwie do ciężkiej migracji backfill).
- **Post-deploy:** weryfikacja `/jobs/240915/pipeline-scores` przez Chrome (score'y w górę).

## Zakres / poza zakresem

- **Tknięte:** hybrydowy composite (pierścienie Kanban + `/recommendations`).
- **Nietknięte:** zakładka „AI Matching" (`/ai-matches`) — to surowy cosinus/rerank 0-1,
  inna powierzchnia. Jeśli też uznana za zbyt surową → osobny lever (skalowanie cosinus→%).
- **Dalsze pokrętła** (gdyby `0.65` było za mało): `SCORE_UNKNOWN_NEUTRAL_FRACTION=0.7`
  (env) lub `SEMANTIC_CALIBRATION_GAMMA` 0.6→0.5 (podnosi warstwę semantyczną). Osobny
  follow-up: dla ofert z PUSTYM opisem (jak 240915) skille opierają się na 1 tokenie z
  tytułu → rozważyć „low-confidence skills = neutral" zamiast binarnego 0/20.
