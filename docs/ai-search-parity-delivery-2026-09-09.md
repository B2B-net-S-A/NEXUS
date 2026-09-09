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

### Increment: durable full-search usage, latency and cost accounting

- Added task-local per-run telemetry with bounded stage histograms for query embedding, SQL loading, eligibility, exact vector retrieval, scoring and batches. Rerank/generation remain explicitly zero calls in the current full-search path; this is not an Anthropic-only total. Provider instrumentation records each actual Voyage attempt, observed response tokens, failures, duration and model-specific tariff provenance without storing request/candidate content.
- Checkpoints are saved under the same worker lease as results; a replaced worker cannot overwrite them. Resumption preserves recorded usage and marks possible lost accounting. Permanent query errors now produce unknown measurements for the population instead of repeatedly re-entering the same query after lease expiry.
- Added optional `AI_SEARCH_EMBEDDING_PRICES` JSON mapping model names to USD per million tokens. No tariff is guessed: unknown usage/pricing gives a null total plus a known subtotal. Current production tariff still needs verification/configuration before monetary completeness can be claimed. Values are estimates, not invoices.
- Both search entrances receive the same metrics and display elapsed time including queue/retries and estimated API cost or an explicit incomplete-cost message. `python -m scripts.report_candidate_search_metrics --hours 24 --limit 1000` provides a read-only, identity-free report: exact nearest-rank run p95, sample/truncation counts, partial runs, unknown billing counts and a mean over fully priced runs only. Stage histogram p95 is separately labelled an upper bound.
- Validation: 18 unique focused native backend tests across telemetry, worker, API, vector measurement and embedding correctness; 4 frontend status tests; typecheck, ESLint, Ruff and diff checks. Added hosted PostgreSQL assertions for durable metric checkpoints and rejection of a replaced worker. Hosted CI for the preceding commit was still running at this checkpoint.
- Remaining: legacy score-consumer parity, explicit negative skill evidence, frozen quality evaluation, production index reconciliation/repair, production tariff verification, final hosted gates/merge/deployment and authenticated Chrome proof. A12 production evidence and the full audit are not yet complete.

### Increment: canonical pipeline badges and independent process membership

- Replaced the pipeline badge endpoint's legacy composite cache and truncated job embedding with the same request context, exact vector measurement, eligibility/requirements policy and base-fit evaluator used by full search. Scores retain their decimal precision. Saved-job authorization now also follows the shared Delivery Lead scope guard.
- Removed the arbitrary 200-member cap; members are evaluated in batches of 256. Pipeline IDs are returned separately from available scores, so an unknown embedding no longer makes C2 treat a person already in the process as absent. Query/batch failures preserve unknown status and explicit failed coverage, and do not write legacy score caches.
- Excluded job bookkeeping timestamps and Champion verification/recommended-search workflow metadata from the canonical request fingerprint and brief classification. Real requirement changes still invalidate it; request schema is now request-full-v2.
- Validation: 14 native tests covering exact pair parity, the request tail, 601 members, unknown measurements, partial batch failure and old-cache freshness guards; frontend typecheck/ESLint and Ruff pass. The new badge path currently computes on read without legacy cache reuse: versioned reuse, production latency and durable telemetry for this consumer still require final verification/work before completion.
- Hosted CI on 917994cf exposed two earlier integration omissions: registered both new requirement columns as NEXUS-owned, and corrected the digest budget fixture to supply explicit PLN. Extended that PostgreSQL case to retain unknown/foreign currency without inventing conversion. Six native column-ownership tests pass; the digest integration assertion awaits hosted CI. At this checkpoint frontend and backend shard 0 passed on 917994cf, shards 1/2 failed for those findings, shard 3 was still running.
- The remaining recommendation/shortlist/digest score consumers, explicit negative evidence, quality evaluation, index repair, full gates and production/Chrome verification remain open. This increment is not a deployment or full-audit completion claim.

### Increment: process history no longer changes recommendation fit

- Removed additive historical-project bonuses from recommendations, the legacy shared C2 path and proposal generation. The common annotation retains the count of related recruitment processes, keeps fit unchanged and resolves equal-score ties by candidate ID. Historical participation cannot lift a candidate through the minimum-fit threshold or reorder different base scores.
- The score tooltip presents history as separate context. Old persisted payloads containing a positive bonus are explicitly labelled archival and require recomputation; they are not described as already following the new rule.
- Added a versioned proposal fingerprint. Ready snapshots from the previous policy are reported stale across latest/list/regenerate responses even when no job data was edited. Pending snapshots remain pending, not falsely obsolete. The stale notice now covers both changed request data and changed scoring rules.
- Validation: 10 unique native tests across history invariance, snapshot versioning and pipeline parity; 22 frontend tooltip/widget tests, typecheck/ESLint, Ruff and diff checks. Updated the hosted PostgreSQL proposal test to cover both a below-threshold candidate who must stay excluded and an above-threshold candidate whose score must remain unchanged. Hosted CI on 272abcf6 was still running at this checkpoint.
- This removes one cross-surface score mutation; the legacy recommendation/proposal cache and retrieval paths still need migration to the canonical full-request base-fit contract. All remaining evidence, quality, operational, index and production-delivery requirements remain open.

### Increment: one base-fit calculation for recommendations and proposal snapshots

- Extracted the actual pair calculation into `canonical_fit.score_pair`; the durable full-search worker (and therefore Radar, C2 and pipeline badges), recommendations and proposal generation now call it with the same full request context, normalized base profile and verified exact semantic measurement. Recommendation/proposal retrieval scores only choose their working pool and are not reused as fit measurements. Those two consumers no longer read or write the legacy composite cache.
- Recommendations and proposal generation now use the complete canonical request text. Proposal fingerprints include the full context/weights/version fingerprint, and the snapshot policy version was bumped so older composites cannot be labelled current. Removed proposal generation's unnecessary prerequisite of indexing the job document before candidate scoring.
- Null measurements survive recommendation/proposal thresholds and are ordered after measured scores. Snapshot serialization, response schema, hydration and frontend types retain null; the widget shows an incomplete evaluation and does not log it as a calibrated history score. Only actual BM25 responses use the BM25 label.
- Recommendation telemetry explicitly covers only the canonical-fit subtotal and marks total accounting incomplete: the preceding legacy retrieval/reranker is outside that scope. No claim of complete request billing is made.
- Validation: 21 native tests covering the real recommendation handler's remeasurement (retrieval 0.99 vs exact 0.1), pair/batch/full-worker/pipeline parity, null snapshot hydration and legacy-cache exclusion; 17 widget tests, frontend typecheck/ESLint, Ruff and diff checks. Hosted proposal tests/fixtures now target the canonical scorer and include missing-index results below the usual threshold. Full PostgreSQL/CI execution remains required.
- Still open: recommendation/proposal pool and default-filter parity, canonical score reuse and durable telemetry for these consumers, remaining legacy C2/digest/shortlist/justification score paths, explicit negative evidence, quality evaluation, index repair and full production delivery/Chrome proof. The complete audit has not been marked done.

### Increment: shared missing-proof defaults and explicit search authorization

- Full search, recommendations and proposal generation now resolve the same stored missing-evidence policy through one helper. Default review retains missing/empty skill evidence; an explicit exclusion policy covers both partially known and entirely empty skill profiles. AND/OR requirements stay intact, and other hard gates (including known PLN budget excess) remain active. A supplied recommendation filter can explicitly override the default for that query.
- Request location no longer silently becomes a hard recommendation filter. The widget leaves its filter empty and offers the request location as a placeholder suggestion. Added visible guidance that missing-proof policy is controlled by the shared request requirements; bumped search/snapshot policy versions.
- Hosted CI on 40c51f48 finished frontend and backend shards 0/2/3 successfully; shard 1 reported the route-authorization contract for three candidate-search endpoints. Their existing in-body section check is now also a real router-level dependency requiring read access to Sourcing OR Pipeline. Owner/job-scope/PII checks remain in place. No bare-route baseline exemption was added.
- Validation: 27 native policy/criteria/pair/worker/pipeline tests plus 54 route-auth, section, API and low-level filter tests; 18 widget tests; typecheck/ESLint, Ruff and diff checks. Hosted proposal gate fixtures now explicitly select exclusion instead of depending on the old silent default.
- External delivery blocker first observed on CI 34326070055 (9386f19e): GitHub did not start jobs because account payments failed or the spending limit needs increasing. Native work continued; billing settings were not changed. A new full CI pass is still required after Actions is unblocked. Remaining eligibility-warning/pool parity, score consumers/reuse, evidence, quality, index and production verification remain open; this is not completion.

### Increment: weekly digest uses canonical fit and recipient context

- Digest retrieval now receives the complete request and selects identities only. The canonical scorer remeasures those candidates, so retrieval scores/unknown flags cannot substitute for fit or poison the legacy cache. Shared saved missing-evidence policy is applied before scoring.
- Each recipient gets their user/client/global weight resolution. Unknown final measurements do not generate strong-match notifications; measured ties sort by candidate ID. Notification totals count a job once even with multiple recipients.
- Validation: six native schedule/digest tests cover full request tail, recipient/client profile selection, independent remeasurement after an unknown retrieval signal, unknown final score suppression, threshold/tie behavior and per-recipient dispatch using a mocked emitter. Four PostgreSQL gate tests retain real eligibility and rate filters with updated canonical scorer fixtures; hosted execution remains required. No production notifications were sent.
- Digest still uses a limited discovery pool; this increment does not prove exhaustive recall. Remaining pool/eligibility parity, cache/reuse, explicit negative evidence, quality evaluation, index and production verification stay open. GitHub Actions billing blockage previously prevented the required CI jobs from starting.

### Increment: legacy C2 shared-engine rows use canonical fit

- The compatibility `/ai-matches` shared-engine path now calls the same full-request canonical scorer as Radar/C2 and no longer reads/writes the legacy composite cache or reorders rows with a surface-specific reranker. Retrieval scores choose identities only. History remains separate, ties use candidate ID, and rows include context/version provenance.
- Missing verified measurements retain null on both 0–1 and 0–100 response scales, survive score thresholds, and have no fabricated breakdown. This applies both to semantic discovery and SQL fallback; the shared fallback no longer substitutes profile completeness for fit. Metadata reflects final missing measurements rather than the earlier retrieval flags.
- Validation: seven native canonical/handler/exception-boundary tests, including actual pair equality, full request tail, stable ordering despite history, exclusion of old cache/reranker, and null retention at a 100% threshold in both discovery branches. Hosted tests now supply exact measurement fixtures independently of retrieval, and the outage case avoids external provider calls. Ruff and diff checks pass.
- CI 34327444464 for prior commit 06d01325 started real backend/frontend jobs; CI Gate and Claude review passed, so the previous billing block did not prevent this run. Full CI remains pending at this checkpoint. The compatibility endpoint still retains a flagged legacy mode and bounded pool; remaining default/filter/pool parity, shortlist provenance, other score consumers, evidence/quality/index work and deployment proof are not complete.

### Increment: live recommendations share visible eligibility blocks

- Live canonical recommendations now use the same visibility/dealbreaker gate as full Radar/C2 search. Global hidden candidates stay hidden; visible assignment blocks retain their reason and are exempt from ordinary dealbreakers according to the established Radar policy. Explicit query filter switches pass through the common gate; hidden eligibility and dealbreaker counts remain distinct.
- Recommendation rows carry eligibility annotations. The suggestion widget renders the reason and disables both shortlist and assignment actions for a blocked row. Backend write-time eligibility checks remain authoritative.
- Validation: 20 native tests across canonical handlers, authorization placement, requirement policy and the actual shared gate; 19 widget tests including a visible block and attempted clicks on both disabled actions. Typecheck, ESLint, Ruff and diff checks passed. No production records or notifications were written.
- Prior CI 34327444464 has passed frontend and backend shards 0/3; shards 1/2 were still running at this checkpoint. The new branch revision still needs its own hosted CI. Persisted proposal generation/hydration, lexical fallback and other bounded discovery consumers still need the same visibility treatment; no claim of complete audit or production delivery is made.

### Increment: proposal snapshots preserve and refresh eligibility

- Proposal generation now uses the same visibility/dealbreaker gate as Radar/C2/live recommendations and records annotations with each canonical fit. Snapshot policy version v3 marks prior policy snapshots stale.
- Every latest-snapshot read reloads candidate visibility. Newly hidden/deleted candidates are omitted, visible assignment blocks carry their current reason, and removed blocks disappear without regenerating scores. Missing eligibility decisions fail closed; gate errors propagate. Historical annotations are not exposed as current through the breakdown.
- Hydrated response/types/widget preserve the current annotation, including disabled shortlist/assign controls for saved proposals.
- Validation: 11 native contract/canonical/current-visibility tests, 20 widget tests, typecheck, ESLint, Ruff and diff checks. Read tests change eligibility between consecutive reads of the same snapshot, verify hidden/missing decisions and confirm an exception cannot fall back to old authorization. Hosted generation/DB tests remain required; no production mutations were made.
- CI 34327444464 (06d01325) finished frontend and backend shards 0/1/3 successfully; shard 2 failed and its log is being inspected. Later queued revisions still need their own required CI. Remaining full-pool/default parity, live snapshot score freshness/profile provenance, explicit negative evidence, quality/index/operational work and production delivery remain open.

### CI follow-up: retired digest cache writer guard

- Shard 2 of CI 34327444464 failed only `test_every_cache_writer_reads_the_unknown_semantics_signal`: its textual guard still classified the migrated digest as a legacy cache writer. Updated the guard to inspect actual calls in all four migrated consumers, require canonical measurement and reject old cache APIs. The existing retrieval zero/unknown behavior tests remain intact.
- All five tests in the regression file pass natively. The preceding CI result does not validate later commits; a new full required CI pass is still necessary.

### Increment: snapshot freshness is checked against the viewer's context

- Latest proposal reads compare the stored full-context fingerprint with the current request and active user/client/global weight profile, rather than relying only on the stored stale flag/version prefix. A changed request tail or another viewer's different profile therefore marks the ranking stale even if no invalidation job ran. Pending and already-obsolete snapshots do not incur profile/context work.
- Seven native proposal contract/current-eligibility tests pass, including long-tail edits, changed viewer weights, scope arguments and unchanged-context freshness. Ruff and diff checks pass. This exposes stale score context; candidate-version freshness, canonical reuse and the rest of the audit remain open.

### Increment: changed candidate data invalidates stored proposal fit

- Proposal generation captures each candidate's SQL version before scoring and stores it with the result. Reads compare that version with the current profile: changed or unversioned candidates receive null fit and no old skill breakdown, ordered after current measured rows. The response marks the ranking stale/degraded when these rows occur; policy v4 invalidates old snapshots.
- Eight native proposal contract/current-data tests pass. The new regression reads a snapshot, updates a candidate version, reads again and checks loss of the old numeric/skill claims, retained current scores, stable null ordering and non-mutation of stored history. Ruff and diff checks pass. This is conservative version-based invalidation; it does not yet cover all non-candidate dependencies or repair/recompute the full ranking automatically. Full audit and deployment requirements remain open.

### Increment: shortlist separates current canonical fit from archived score

- Shortlist reads now calculate the same canonical pair fit with the full current request and viewer's active profile. Response fields distinguish nullable current fit, measurement state and context fingerprint from the original score snapshot. Empty lists do not call the scoring providers.
- The panel displays current fit on the 0–100 scale, shows incomplete measurements explicitly and labels the stored score archival. Process evaluation/outreach remain separate.
- Seven native canonical/shortlist tests and ten panel tests pass; typecheck, Ruff and diff checks pass. The handler regression compares its actual fit with the shared pair scorer, exercises a missing index and preserves the unrelated archived value. Full hosted shortlist/access regression still required. This read currently recomputes fit; reusable versioned results/latency/cost, remaining audit work and deployment proof remain open.

### Increment: bounded reuse of full-request query vectors

- All canonical consumers now share a process-local query-vector cache keyed by full text hash, embedding model and chunking algorithm version. Successful immutable vectors are reused for five minutes, with at most 128 entries; callers receive copies. The cache contains no plaintext request or composite score and does not bypass candidate/index provenance or eligibility checks.
- Failures are not cached, so provider recovery is retried. Model/text changes and expiry force recomputation; LRU eviction bounds memory. Concurrent cold misses may still make separate calls, and separate workers keep independent caches.
- Thirteen native measurement/canonical/shortlist tests pass, including full text preservation, model/text/TTL invalidation, defensive copies, failure recovery and eviction. Ruff and diff checks pass. This reduces repeated query-embedding work but does not claim durable composite reuse or measured production p95/cost improvement; these and remaining audit/delivery requirements stay open.
