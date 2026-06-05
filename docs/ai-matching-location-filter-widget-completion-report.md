# AI Matching — location filter for „Rekomendowani kandydaci" + `_score_location` blob fix

> Status: implemented & verified locally; pending adversarial review → commit → prod E2E.
> Follow-up to PR #424 (location filter on the legacy `/ai-matches` engine).

## Problem

Two related gaps in the hybrid matching path:

1. **`_score_location` was broken for real data.** The composite "city match" half
   (`scoring_service.py`) compared `candidate.location` against `job.location` by
   raw-string substring. But on prod (confirmed 2026-06-05):
   - `candidate.location` is a JSON blob (`{"locality":"Warszawa","region1":…}`) in
     **8242 / 8305** located rows (63 plaintext) — substring never matched a blob.
   - `job.location` is empty in **3879 / 3894** jobs (only 15 populated) → the city
     half contributed ~0 regardless.
2. **The „Rekomendowani kandydaci" widget had no location filter.** The more visible,
   hybrid engine (`/recommendations` + `SuggestedCandidatesWidget`) ignored location,
   so a recruiter on a Warsaw role still saw candidates from all of Poland.

## Change

### Backend
- **`app/services/location_utils.py` (new)** — shared blob/plaintext location helpers
  (`location_tokens`, `tokens_overlap`, `location_matches`), extracted verbatim from
  `matching.py` (PR #424) so the legacy engine, the hybrid engine and the composite
  scorer share one implementation.
- **`app/api/matching.py`** — now imports the shared helpers (thin `_location_tokens`/
  `_location_matches` aliases keep existing imports/tests green); removed the now-unused
  local copies + `json`/`re` imports.
- **`app/services/scoring_service.py` — `_score_location`** — the city half now parses
  BOTH sides via `location_tokens` (blob-aware). **Strict no-op when `job.location` is
  empty** (`job_tokens` empty → 0 city points → identical to before), so composite
  scores for ~99.6% of jobs are unchanged. Only the ~15 located jobs change, where a
  same-city blob candidate finally earns the city half it was silently denied.
- **`app/api/recommendations.py`** — `GET /api/jobs/{id}/recommendations` gains an
  optional `location` param (falls back to `job.location`). When active it widens the
  Qdrant retrieval pool (`RECOMMENDATION_LOCATION_POOL_SIZE`, since located candidates
  are sparse), **pre-filters candidates by location before scoring** (so only the
  matched subset bears scoring cost), and echoes `location_filter`. An `isinstance`
  guard keeps the in-process direct call from `recompute_scores` (which passes the
  `Query(...)` sentinel) from tripping.
- **`app/core/config.py`** — `RECOMMENDATION_LOCATION_POOL_SIZE = 500` (runtime-tunable).

### Frontend
- **`lib/api.ts`** — `recommendationsApi.forJob` accepts `location`; return type gains
  `location_filter`.
- **`SuggestedCandidatesWidget.tsx`** — adds a `LocationInput` (debounced 300 ms). When
  a city is typed it bypasses the precomputed snapshot and hits the live
  `/recommendations?location=…` (server-side filter + pool widening); cleared → snapshot
  as before. Also renders `formatCandidateLocation()` instead of raw `cand.location`
  (prevents JSON-blob leak now that located candidates surface). Pre-fills from the
  job's own location via a new `defaultLocation` prop.
- **`app/jobs/[id]/page.tsx`** — passes `defaultLocation={formatCandidateLocation(job?.location)}`.

## Verification

- **Data reality** confirmed on prod DB: 3894 jobs / 15 located; 47600 candidates /
  8305 located / 8242 blobs.
- **Unit tests** — 62 pass (`test_scoring_service.py` + `test_matching_location.py`),
  including new tests locking the *no-op-when-`job.location`-empty* invariant and
  blob-aware matching. `ruff check` + `ruff format --check` clean; app imports clean.
- **Frontend** — `tsc --noEmit` clean; `eslint` clean on changed files.
- **Matching eval (`scripts/eval_matching.py`, 15 jobs, prod data) — before vs after:**

  | Metric | Baseline (`main`) | After | Δ |
  |---|---|---|---|
  | Precision@5 | 0.2000 | 0.2000 | 0.0000 |
  | Recall@20 | 0.2083 | 0.2083 | 0.0000 |
  | MRR | 0.3419 | 0.3416 | −0.0003 |
  | nDCG@10 | 0.2392 | 0.2392 | 0.0000 |

  3/4 metrics identical; MRR within noise (a single-rank reshuffle on the 5 Warsaw
  seed jobs from a *correct* location signal). No meaningful regression → GO. (The
  after-run used the new code injected into a throwaway process in the prod backend
  container; the running app was untouched and the container is back on clean `main`.)
- **Prod E2E (Chrome MCP)** — _pending_.

## Known limitations / notes

- `job.location` is empty for 99.6% of imported jobs, so the composite city half still
  rarely fires; the **filter** (which reads `candidate.location` directly) is the
  user-facing win, not the composite tweak.
- The match-score cache (`CandidateJobMatchScore`) has no formula version, so already
  cached composite scores keep their old (0) location points until invalidated. Impact
  is negligible (≤4 pts on ≤15 jobs) and the location *filter* does not depend on cached
  scores. Not force-invalidated to avoid a recompute storm.
- `test_matching_location.py` is not in the CI pytest list (CI token lacks `workflow`
  scope to edit `ci.yml`); the no-op invariant is covered by `test_scoring_service.py`,
  which IS in CI.
