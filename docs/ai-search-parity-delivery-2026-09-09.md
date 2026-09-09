# AI search parity delivery — 2026-09-09

Baseline: 2bc6b14ff48eaa4eaa012693efd80e8b4551bc3e.
Scope: all A01–A12 findings and acceptance criteria from the 2026-09-08 second audit, approved by the user. This ledger is not evidence of completion.

## Delivery checklist

- [ ] A01 shared base fit score across Radar, C2, recommendations, shortlist and pipeline; separate process readiness/history.
- [ ] A02 full eligible-population search in batches, missing-vector handling, stable pagination, coverage proof and index reconciliation dry run.
- [ ] A03 shared persisted reviewed requirements with AND/OR, PL/EN, negation, nice-to-have and intentional empty lists.
- [ ] A04 canonical full request text and explicit cache/index version invalidation.
- [ ] A05 rate amount/currency/unit preserved; backend comparability drives frontend filtering and labels.
- [ ] A06 independently supplied seniority, grounded drafting and explicit review of proposed changes; no salary autofill or fabricated facts on either generator route.
- [ ] A07 one resolved budget for filters, score and presentation, retaining hard ceiling.
- [ ] A08 unavailable measurements remain unknown, visible partial status, no misleading empty results or poisoned cache.
- [ ] A09 requirement evidence distinguishes met, confirmed failure and unknown; missing proof policy explicit.
- [ ] A10 saved job selection in Radar with shared client/HM/location/eligibility context; assignment guards retained.
- [ ] A11 consistent score units/counts and brief completeness, truthful population/search counters.
- [ ] A12 search-run metering of embedding, retrieval, rerank and generation; cost and p95 evidence.

## Acceptance evidence still required

- Same saved request and filters: same IDs/order, stable ties, score difference <=0.1.
- Request/profile/candidate updates invalidate appropriate results and snapshots; versions visible.
- Outside-initial-pool known positive found in full mode; entire population accounted for.
- PL/EN alternatives, long request, negation, nice-have and manually cleared requirements regressions.
- Foreign/unknown currency and unit never compared or relabeled as PLN/h.
- Partial provider/index failure preserves uncertainty and does not claim complete/no-match results.
- Pages and post-filter totals available.
- Empty brief visibly preliminary; both >=75 counters agree.
- Priority does not change seniority/pay; drafts do not assert unapproved facts.
- Frozen request evaluation with known positives and recruiter labels; recall/top20, cost and p95, not average score alone.
- Hosted required CI; merged SHA; normal deploy; exact health/deep/Alembic; Chrome proof for both entrances on same recruitment.

No production data repairs, index deletion or historical rate rewrites have been performed.

## First implementation increment (not deployed)

A05: matching response includes amount, original currency and hourly unit; both displays and the filter use authoritative comparability. Unlabeled currency is unknown at the dealbreaker gate. A11: header converts its 75-point threshold to the API 0–1 scale. A06: generator no longer derives seniority from priority or fills salary/requirements; editable draft requires an explicit apply action. Both server templates avoid fabricated facts and structured provider output cannot replace supplied criteria or introduce pay/benefits.

Validation: 32 focused writer/matching tests passed, 3 database integration cases deferred to hosted CI; 29 dealbreaker tests passed; 18 frontend tests passed including real form interaction; TypeScript and targeted Ruff passed. A first broader local test selection included 3 PostgreSQL fixtures and failed because no local server is running. No Docker was used.

Remaining: all unchecked scope above, especially full-population search and shared request/ranking, plus production delivery. The draft-description prompt and human review reduce fabrication risk but are not a quality evaluation of actual model output. Frozen request evaluation remains required.

## Budget and exhaustive scan increment (not deployed)

A07 now resolves the same explicit request budget (then Champion fallback) for both salary scoring and dealbreakers. Radar places its manually entered budget on the scored request. Unknown/foreign currency is not comparable in either layer. The scoring algorithm digest changes, invalidating old algorithm-version cache entries. Focused scoring and cache-contract suite: 90 passed. Additional Champion/budget/exhaustive-scan suite: 21 passed (overlapping budget tests).

A02/A08 foundation: `full_candidate_scan.py` evaluates every SQL population snapshot ID in bounded batches, checks source versions, preserves unmeasured candidates beyond score thresholds, reports excluded/evaluated/failed/unknown counts and distinguishes complete coverage from complete ranking. Stable pages break ties by ID. Tests cover a known positive beyond the first batch, failed middle batches, missing vectors, changed/deleted records and unknown scores. This is an internal execution component, not yet wired to product endpoints; durable storage, shared evaluation and UI integration remain required.

## Shared request and durable execution increment (not deployed)

- Additive migration 0282 adds persisted reviewed AND-of-OR criteria on jobs and durable search run/result tables. The store snapshots SQL IDs/versions, leases execution, commits progress batches and refuses completion with unaccounted records. Integration tests exercise ownership, leases, full counts and invalidation on PostgreSQL in CI.
- New shared `/candidate-search/runs` API accepts a saved job or ad-hoc request, checks search capability/job visibility and only exposes runs to their creator. A restart-safe queue worker performs full-batch evaluation. Pages recheck source versions and current eligibility; changed population or request/profile invalidates reuse.
- The common request context preserves full text, client/HM, office requirements, criteria and normalized base-fit weights. Screening and client conflict penalties are separate from base fit. Query chunks retain the tail of long text. Exact vector retrieval measures supplied IDs rather than ANN top-K.
- New index writes carry content hash/model provenance. Unknown old vector provenance is marked stale, not silently called current. **Existing index reconciliation/reindex is still required before a complete production ranking can be claimed.** No production index writes/repairs have been performed.
- Explicit and prose PL/EN alternatives now remain a single OR group; approved empty criteria are preserved. New full execution treats missing skill proof as reviewable unless an explicit criteria policy requests exclusion. Old UI paths remain to be replaced and fully harmonized.
- Verification: 153 focused unit/regression tests passed, 2 PostgreSQL cases excluded locally. Main app imports and OpenAPI exposes both new routes. Alembic reports one head, 0282. Durable store integration and migration execution await hosted CI.

Still required: UI integration/job picker/shared criteria editor, remaining pipeline/recommendation/shortlist consumers, durable cost/latency metrics and retention, index dry run/repair, full quality evaluation, all hosted checks, merge/deploy and Chrome parity proof. No item is marked complete merely because its backend foundation exists.

### Increment: shared UI transport and readable stale snapshots

- Added typed full-search transport, explicit-start/poll/page hook, and shared population/progress/incomplete-ranking status component. They are not yet wired into the two production screens; A01/A02/A10/A11 remain incomplete.
- Returning to an older completed scan no longer fails the entire response when one candidate changes. Changed rows lose their numeric score and previous positive skill evidence; the response marks the snapshot stale and requires a new scan for a current ranking. Deleted or newly hidden candidates are not exposed.
- Minimal Radar identity remains separate from opt-in candidate details; details require the existing candidate-read guard. Saved-job reads also retain the Pipeline section and Delivery Lead resource guards.
- Validation: two focused API regressions (detail access and stale positive evidence), four frontend regressions (duplicate-click/clear race, paging without a new scan, partial/stale status, active progress), and frontend typecheck. No production verification or completion claim.

### Increment: Talent Radar uses the full-population run

- Replaced the production Radar workspace's capped synchronous search with the shared start/poll/page API. It shows population progress, stable pages, partial/stale status, explicit unknown skill evidence, and null scores without converting them to zero.
- Kept Champion requirement preview/edit/clear behavior, visible retryable errors, candidate-profile permission checks and the Radar back link. Returning from a profile reloads an actor-scoped server run ID; old locally stored capped results are discarded, and candidate result payloads are no longer persisted by this workspace.
- Hosted CI on c03352c8 correctly rejected then-unreachable UI primitives. With the actual Radar integration, the same local reachability gate passes (0 new unreachable modules); no allowlist exception was added.
- Validation: 27 focused frontend tests and typecheck pass. Saved-job selection in Radar, C2 integration, other score consumers, index reconciliation/repair, telemetry/evaluation and production verification remain outstanding. This increment is not a production completion claim.

### Increment: C2 pipeline ranking and global result filters

- Replaced C2's capped ai-matches query with the same durable full-search API used by Radar. Starts are explicit; existing proposal/shortlist actions and read-only restrictions remain. Null scores are shown as incomplete, and missing skill evidence is labelled unconfirmed.
- Added server-side snapshot filters for skill, rate status and normalized location, plus job-scoped process membership. Filtering precedes count, ordering and pagination; changing filters/pages never starts a new AI scan. Candidate rate status is frozen using the shared budget resolver.
- Default minimum score is 0 in both entrances and C2 no longer implicitly turns the job's location into a hard filter. Global strong-match counts come from the full run; the shared job header does not claim a complete summary for partial/stale/unavailable rankings.
- Result schema is versioned to invalidate snapshots without filter evidence. C2 coverage chips use the same frozen requirement evidence as Radar.
- Validation: 9 focused native backend tests; frontend adapter, filter/page hook and Radar regression tests; typecheck, Ruff and reachability gate. Added a hosted PostgreSQL case proving skill/location filters find lower-ranked profiles beyond the first page, unknown scores survive thresholds, and process filters are scoped to the requested job. Its execution is pending hosted CI.
- Remaining: saved-job picker and reviewed criteria editing in Radar/C2; remaining legacy score consumers; index reconciliation/repair, operational telemetry/evaluation, and complete production delivery/Chrome verification. No completion claim.

### Increment: saved recruitment in Radar and shared reviewed criteria

- Added paginated, authorized saved-job selection in Radar. The saved mode starts by job_id, uses full server-side request/client/HM context and shares the same actor/job run reference as C2. Ad-hoc mode remains available and explicitly identifies missing saved-job/HM context.
- Added one reviewed-requirements editor to saved Radar and C2. AND groups retain OR alternatives (PL/EN), excluded/uncertain lists, manual empty lists, and an explicit missing-evidence review/exclude policy. Saves use the existing guarded job PATCH, including its audit/cache behavior; read-only users cannot edit. Worker and editor read the same effective contract.
- Source changes through job edits, Champion editing/generation endpoints and Champion ingestion clear obsolete reviewed criteria; budget-only edits retain them. Unchanged groups preserve provenance when reviewed.
- Session restoration stores only a minimal job reference and run IDs. Logout clears the new keys.
- Validation: 23 Radar/editor/criteria tests, 11 session/hook/editor tests (overlap), 20 backend requirement-update/Champion-ingestion tests, plus API/worker checks; typecheck, targeted ESLint, Ruff and reachability pass. Fixed the React Hooks lint error in the test wrapper reported by hosted CI on 23d25176.
- Still outstanding: remaining legacy score consumers and parity evaluations, index reconciliation/repair, full telemetry/quality assessment, hosted gates and production delivery/Chrome proof. All audit rows remain subject to the final completion audit.

### Increment: exact candidate-index reconciliation and reviewed repair scope

- Added `scripts.audit_candidate_index`: read-only full SQL ID/version snapshot plus bounded Qdrant scrolling, comparing text hashes, model provenance and vector validity. The private JSON manifest identifies missing, stale, wrong/unknown-model, invalid, unindexable and orphan entries, records database changes during the scan, and carries a fingerprint. Provider/index failure cannot turn into a fabricated missing count.
- Added explicit manifest-based repair enqueueing through the established outbox. It verifies fingerprint/configuration and locks/revalidates the approved candidate versions/content before queuing. It skips matching pending/retrying intents and never deletes orphan points. Queue completion is not proof that indexing completed; a fresh audit and ranking run are still required.
- Fixed mass reembedding to stamp the exact embedded content hash and Voyage model, matching single-record indexing. Offline/unknown-provider embeddings are no longer stamped as verified Voyage vectors. Invalid vector values now degrade the individual measurement instead of crashing a whole candidate batch.
- Fast `/admin/index-coverage` now exposes point counts separately and leaves unmeasured membership coverage/marker drift null; subtraction of aggregate counts is not reported as actual missing candidates.
- Validation: 22 focused audit/backfill/vector tests and Ruff/diff checks. Production dry-run/repair have NOT been executed. Obtain the concrete production manifest before any production repair; all remaining parity, telemetry, quality, delivery and browser proof remain required.
