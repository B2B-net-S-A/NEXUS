# AI Scoring recalibration — completion report (2026-06-23)

## Problem

Recruiters reported that the AI match score (the 0-100 ring on kanban cards and in
`/recommendations`) **systematically underrates candidates** — genuinely strong
people landed ~18-37. The deflation was already documented in
`config.py` ("composite zaniżony bo salary/location/availability często nieznane →
punkty częściowe … nie skalibrowane 0-100").

### Root causes (confirmed)

1. **Uncalibrated semantic layer (35 pt).** It was raw Voyage cosine × 35. For
   genuinely relevant candidates the cosine (voyage-3-large) clusters ~0.4-0.65,
   so a linear mapping awarded only ~14-23 of 35 even for good matches.
2. **Unknown metadata hard-zeroed.** `salary` (12 pt) returned 0 when no rate was
   known (~99% of imported Traffit candidates) and `location` (8 pt) returned 0
   when the job had no location (~99.6% of imported jobs) — even though
   `availability` (no date → 0.5×) and `champion_fit` (no screening → 0.5×) already
   used a **neutral-half** convention for "no signal". The inconsistency dragged the
   whole imported pool down.

A typical strong-but-imported candidate therefore capped around 35-37.

## Changes

All gated behind runtime-tunable env (Coolify, `is_runtime`), so the exact legacy
behaviour is one flip away (`gamma=1.0` + `neutral=0.0`).

| Area | File | Change |
|---|---|---|
| Semantic calibration | `app/services/scoring_service.py` `score_semantic` | `cosine ** SEMANTIC_CALIBRATION_GAMMA` (default **0.6**). Strictly increasing → per-candidate ranking preserved; lifts the deflated middle (0.5 → 0.66 of budget) without saturating the top. `gamma=1.0` = legacy linear. |
| Salary neutral-fill | `_score_salary` | Missing rate/range → `SALARY_MAX * SCORE_UNKNOWN_NEUTRAL_FRACTION` (default **0.5** → 6 pt), not 0. In-range = full and out-of-range decay **unchanged** (a real mismatch still decays below neutral). |
| Location neutral-fill | `_score_location` | City half: when the job **has** a location but the candidate's is unknown (one-sided) → neutral half. The 99.6%-no-job-location case stays a **hard no-op (0)** — no mass inflation. Remote half unchanged. |
| Config knobs | `app/core/config.py` | `SEMANTIC_CALIBRATION_GAMMA=0.6`, `SCORE_UNKNOWN_NEUTRAL_FRACTION=0.5`. |
| Threshold retune | `app/core/config.py` | `RECOMMENDATION_MIN_SCORE` 25 → **40** (covers `/recommendations` + `compute_proposals`, both read the setting). `MARKETPLACE_SCORE_THRESHOLD` 70 → **80** (prevent alert flood on the lifted scale). |
| Cache invalidation | `alembic/versions/0143_invalidate_match_score_cache.py` | Marks all `candidate_job_match_scores` rows `stale=true` so the read-through cache recomputes with the new engine. Data-only, `to_regclass`-guarded, chained off head `0142`. |

### Expected effect

A genuinely good candidate moves from ~30-37 to ~55-70 (ring shifts amber → sky/
emerald). Pure noise stays low. Neutral baseline for the fully-unknown-metadata
cohort = salary 6 + availability 2.5 + champion 5 = 13.5 (location stays 0 for the
no-job-location majority).

## Verification

- **Unit tests:** `backend/tests/test_scoring_service.py` — **65 passed** (run in a
  `python:3.12-slim` container; local machine only has Python 3.9, which can't
  import the app). Modified the semantic/salary/location assertions to the new
  behaviour and added 7 lock-in tests:
  - gamma curve sample points + monotonicity + pinned endpoints
  - salary missing-data → neutral; salary in-range > unknown > far-out-of-range
  - location one-sided city-neutral; empty-job-location stays no-op
  - **ranking preserved within a same-unknown cohort** (composite Δ == semantic Δ)
  - **legacy reproduced** with `gamma=1.0` + `neutral=0.0`
- **Adjacent tests** (`test_cv_upload_preview.py`, `test_seeking_contractors.py`):
  reviewed — they assert ordering / explicit `?threshold=80` / rollups, not absolute
  scores tied to the changed defaults (cv-preview default threshold is `0.0`). No
  change needed; full validation runs in CI (real postgres).
- **ruff:** clean on all changed files.
- Design was de-risked first via a 4-lens adversarial review (ranking regression,
  consumer blast-radius, test-contract deltas, before/after math).

## Known limitations / follow-ups (IMPORTANT)

1. **Eval harness not run locally.** `scripts/eval_matching.py` needs the prod
   DB + Qdrant + Voyage, unreachable from the dev worktree. Per the team rule,
   **run it in the deployed/staging env before relying on the new thresholds** and
   accept ≤2% regression on Precision@5 / Recall@20 / MRR / nDCG@10; if a metric
   drops more, back off `gamma`→0.65 or `neutral`→0.4 via env (no redeploy). The
   semantic change is monotonic and neutral-fill is a constant shift for the
   dominant cohort, so ranking is expected to hold — but this must be confirmed.
2. **Marketplace notification volume.** `MARKETPLACE_SCORE_THRESHOLD` 70→80 guards
   against a flood now that 70 is reachable by a much larger cohort. Monitor
   `marketplace_scan` alert counts the first week; tune via env if needed.
3. **Thresholds are anchored to one documented job's distribution** (job 15). All
   four scoring constants are runtime env — tune live without rebuild.
4. **Cache transition.** Until each cached row is re-read post-deploy, a card may
   briefly show its old (deflated) total. Self-heals on read (the migration flips
   `stale`). Verify via Chrome MCP after deploy.

## Rollback

Set in Coolify env (no redeploy): `SEMANTIC_CALIBRATION_GAMMA=1.0`,
`SCORE_UNKNOWN_NEUTRAL_FRACTION=0.0`, `RECOMMENDATION_MIN_SCORE=25`,
`MARKETPLACE_SCORE_THRESHOLD=70` → exact legacy behaviour.
