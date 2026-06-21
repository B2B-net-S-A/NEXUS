# AI scoring ring na kartach pipeline — completion report

> Data: 2026-06-19/21 · Feature: koliste odznaki AI match score (0-100) na kartach
> kandydatów w kanbanie `/jobs/[id]` (jak referencja Traffit). Zweryfikowane na
> prodzie przez Chrome MCP na `/jobs/177165`.

## Co dostarczono

Każda karta kandydata w pipeline'ie pokazuje **ring z hybrydowym AI score (0-100)**
— kolorowy łuk + liczba w środku, jak w referencji ("88" zielony / "28"
pomarańczowy). Kolory są stałe (niezależne od palety motywu): emerald ≥75,
sky ≥50, amber ≥25, rose <25.

## Architektura

- **Backend** — `GET /api/jobs/{job_id}/pipeline-scores` (w `app/api/recommendations.py`)
  → `{candidate_id: 0-100}` (hybrydowy wynik, ten sam silnik co `/recommendations`:
  semantic + skills + salary + location + availability + champion_fit).
  - **Cache-first**: czyta świeże `CandidateJobMatchScore` (per aktywny profil);
    ciepły pipeline = zero wywołań AI (embedding/Qdrant pominięte).
  - **Pełne pokrycie bez deflacji**: dla niezcache'owanych liczy similarity
    przez `embedding_service.similarity_for_candidate_ids` — **filtrowany po id
    (`HasIdCondition`) search w Qdrant**, czyli dokładny cosinus dla KAŻDEGO
    zaembedowanego kandydata niezależnie od globalnego rankingu (nie top-K pula).
    Warstwa semantyczna nigdy nie jest zerowana → brak zaniżonych wyników w cache
    współdzielonym z `/recommendations`. Pomijani tylko kandydaci bez embeddingu.
  - `@limiter.limit("30/minute")`, cap 200 kandydatów, profil aktywny (cache-key
    alignment). Helper nie dotyka okna AI-health (lookup, nie user-facing search).
- **Frontend** — `matchingApi.pipelineScores(jobId)` dociągany równolegle do
  kanbana (gated na tab „pipeline", `staleTime` 5 min). `scoreMap`
  (keyed by `candidate_id`, **przeżywa** optimistic-move i rebuild „verified") +
  `scoresLoading` przekazywane przez `KanbanBoardV2` → kolumna → `CandidateKanbanCard`.
  Nowy `ScoreRing` (SVG): kolory stałe, placeholder (pulsujący) w trakcie liczenia,
  ring pomijany na kartach `pending` (kolizja z badge'em). Inwalidacja
  `["pipeline-scores"]` po dodaniu kandydata (AI matching + manual search).

## Pliki

- `backend/app/api/recommendations.py` — endpoint `pipeline_match_scores`
- `backend/app/services/embedding_service.py` — helper `similarity_for_candidate_ids`
- `frontend/src/lib/api.ts` — `matchingApi.pipelineScores`
- `frontend/src/app/jobs/[id]/page.tsx` — query + `scoreMap`/`scoresLoading` + inwalidacja
- `frontend/src/components/v2/pages/KanbanBoardV2.tsx` — `ScoreRing` + przepięcie propów

## Proces

Eksploracja (4 agenty) → implementacja → **adwersaryjny review wieloagentowy**
(12 agentów: backend/frontend/UX, każdy finding zweryfikowany) → fix 9
potwierdzonych issues → deploy → **weryfikacja przez Chrome MCP**, która wyłapała
runtime bug niewidoczny statycznie (patrz niżej).

## Gotchas (na przyszłość)

- **`@limiter.limit` + bare `CurrentUser` alias = 422.** Bare
  `current_user: CurrentUser` (`Annotated[User, Depends(...)]`) gubi metadane
  `Depends` pod dekoratorem slowapi → FastAPI traktuje `current_user` jako
  wymagany **query param** → 422 na każde wywołanie. Rate-limitowane endpointy
  MUSZĄ używać jawnego `current_user: User = Depends(get_current_user)`. (Złapane
  dopiero na prodzie przez Chrome — statyczny review tego nie widzi.)
- In-pipeline kandydaci **nie są** pre-warmowani przez `/recommendations` ani
  proposals (oba `exclude_in_pipeline=True`), więc pierwsze otwarcie pipeline'a
  liczy score'y na żywo; kolejne z cache.

## Deploy

3 PR-y zmergowane do `main`: #555 (feature), #556 (fix 422), #557 (pełne pokrycie).
Prod healthy, `/api/jobs/177165/pipeline-scores` → 200, **10/10** kart w pipelinie
ma ring (zweryfikowane wizualnie).

## Znane ograniczenia / out-of-scope

- Liczba na ringu (hybrydowy 0-100) różni się skalą od paska % w zakładce
  „AI Matching" (semantyczny cosinus ×100) — świadomie zostawione, inne taby,
  inny (bogatszy) sygnał. Tooltip ringa: „Dopasowanie AI: X/100".
- `MatchScoreBar`/`SuggestedCandidatesWidget` (istniejące komponenty) nie ruszane.
