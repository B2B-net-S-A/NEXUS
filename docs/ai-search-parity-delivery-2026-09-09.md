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

### Increment: profile signals no longer claim verified competence

- Requirement evidence explicitly identifies profile signals versus missing evidence, with verification date and usage context absent unless actually established. Candidate/profile update timestamps are not treated as competency verification dates. Radar labels matches as profile signals requiring verification instead of confirmed proficiency; changed-data responses clear those evidence claims too.
- Inspected notes insights: gaps may be AI paraphrases and extraction timestamps, without a separate human-confirmed decision. They are therefore not promoted to confirmed negative evidence. A regression protects this distinction.
- Thirteen native requirement-policy/API tests and three result-panel tests pass, alongside typecheck/ESLint/Ruff/diff checks. Remaining A09 work is a proper reviewed requirement verification record with date/context and an authorized write/read flow, then integration into shared eligibility/scoring without trusting arbitrary extracted JSON. This increment improves evidence honesty but does not claim that three-state verification is fully delivered. Other quality/index/CI/production requirements remain open.

### Increment: explicit reviewed requirement records and scoped API

- Added append-only `requirement_verifications` records (migration 0283 after 0282) carrying the job/candidate/group, server-bound reviewer, met/not_met/unknown decision, evidence, usage context, verification date and fingerprints of effective requirements and full candidate skill/CV source data. This is separate from arbitrary extracted JSON; unknown records can supersede earlier decisions without deleting history.
- Added scoped read/write endpoints under candidate-search jobs/candidates/verifications. Reads require candidate read and job read scope. Writes require candidate write, pipeline access and job membership; they lock and refresh the job/candidate, reject stale editor versions, and bind the actor on the server. Recording a review bumps the candidate version so existing search/proposal results cannot retain pre-review facts, while review-only version changes do not invalidate other source-identical verification groups.
- Native validation: 12 schema/provenance/write-scope/concurrency/auth-contract tests pass; Ruff/diff checks pass. Alembic reports one head, 0283_requirement_verifications (correct config: `-c alembic/alembic.ini`). Migration execution remains hosted-CI work, not a local Docker task. No production review records were created.
- Still required for this feature: the actual review form, batch-loading verified evidence in shared search/scoring/filtering, explicit OR/negative/revocation tests and rendered production proof. This is backend groundwork, not completion of A09 or the broader audit. Latest CI remains queued.

### Increment: reviewed evidence participates in canonical fit and shared filters

- Shared visibility gates and canonical batch scoring load the latest database-backed reviews for the exact job/candidate/group. Only matching effective-criteria and full skill-source fingerprints are attached; old transient state is cleared. Other jobs cannot reuse the verdict, and stale/latest-revoked evidence cannot revive an earlier record.
- The canonical skills layer uses reviewed met/not_met/unknown group decisions without modifying candidate skills or asserting every OR alternative. Full-search evidence carries the reviewed state/date/context. Explicit missing-proof exclusion honors these decisions; default review policy does not acquire a new silent exclusion rule. Version traces/snapshots are bumped to invalidate prior scoring semantics.
- Detailed evidence/context/verification identifiers are redacted from minimal search responses. Reviewed positive rows are labelled verified with their date; ordinary profile signals remain labelled for review.
- Validation: 38 focused native tests initially passed; 100 scoring/filter/API regressions also passed (overlap in API coverage). After completing all skill-source fingerprint fields, 13 verification/scoring tests passed again. Three result-panel tests, frontend typecheck/ESLint and Ruff/diff checks passed. Updated unit DB fixtures return no reviews explicitly instead of accidentally treating candidate rows as reviews.
- Still open: review form, hosted PostgreSQL/migration and end-to-end checks, legacy/lexical paths not yet using the shared scoped filter inputs, quality/index/telemetry/operational completion and deployment. Latest hosted CI for ff861077 failed; its job-start/result cause is being inspected and is not assumed to be a code failure or a pass.

### Hosted CI follow-up: recommendation filter-switch spies

- CI 34331758953 executed real jobs: frontend and backend shards 0/2/3 passed; shard 1 failed exactly two recommendation-rubric tests. Their spy patched the old module function instead of the shared gate's imported binding, so it observed no kwargs despite the real gate running.
- The hosted tests now spy on the common gate while delegating to the actual gate, preserving checks for default AUTO remote policy and explicit override switches. One native schema/default test passes; the two real PostgreSQL tests await hosted rerun. This is not a full-CI success claim.

### Increment: shared human requirement verification form

- Saved-request Radar and pipeline results now expose the same scoped verification dialog. It records met/not_met/unknown, evidence, usage context and date against the exact loaded candidate/criteria versions; explicit submit is required. It displays previous decisions and their current/stale status. Ad-hoc searches cannot attach decisions without a saved recruitment.
- UI capability mirrors the existing CandidateWriteAccess roles and requires sourcing/pipeline write access; impersonation disables mutation. Server membership checks remain authoritative. No access policy was expanded.
- Version conflicts preserve entered proof and require refreshed data plus a new requirement selection. Failed reads do not create an editable fabricated form; late reads from another candidate cannot overwrite the active editor. Successful saves refresh the displayed result and explain that a new search is needed to recompute ranking.
- Validation: 314 focused frontend tests pass (role/backend capability contract, form concurrency/explicit writes, result visibility and action gates), TypeScript and ESLint pass. No production verification records were written. Hosted CI, rendered production evidence and all remaining audit requirements are still open.

### Main synchronization and migration branches

- GitHub reported PR 1428 CONFLICTING; the current main is 4ddd5bef. Merged main into the isolated task branch and retained both independent section-access test groups. All 27 section-access tests pass; Ruff passes on the merged guard/tests.
- Main introduced a separate 0282 signature-permission migration. Added a no-op merge revision joining it with 0283 requirement verifications, preserving both existing migration histories and all parent operations. This requires hosted upgrade/downgrade validation; local Alembic topology verification is not proof of database migration execution.

### Increment: obsolete proposal context cannot expose current numeric fit

- Latest proposal reads now pass the current request/profile freshness decision into hydration. Stale context clears numeric fit and old requirement breakdowns, marks context_changed and degraded, and retains current eligibility annotations. Null rows use stable candidate ordering; archived database snapshots are untouched.
- Nine native proposal freshness/eligibility tests pass, including changed-context clearing with unchanged candidate versions and continued assignment blocking. Ruff and diff checks pass. Hosted CI 34337354217 and gate 34337354219 started for 42ecdf80 after resolving the PR merge conflict; no full-CI success or production deployment is claimed.

### Increment: legacy AI Matching uses the common missing-evidence policy

- The /ai-matches handler now builds its shared rubric inputs with search_dealbreaker_inputs, used by both semantic and fallback branches. Default review policy keeps candidates with missing proof; explicit saved exclusion still gates them. Inputs include the job and requirement fingerprint so current reviewed OR-group decisions can participate. This does not yet remove the legacy ranking flag or make its bounded retrieval a full-population scan.
- Thirteen native requirement contract tests pass, including real shared-gate filtering for review versus exclude with an OR alternative and an unknown candidate. Ruff and diff checks pass. Hosted CI for eb4247b4 was still queued; latest changes require their own hosted validation.

### Increment: incomplete eligibility cannot imply permission

- The common search gate now rejects missing/null decisions for any requested candidate before producing visible/assignable results. Previously a partial decision map let the omitted candidate through without an annotation. Full-search execution records the failed batch without fabricated evaluations; synchronous consumers receive an error.
- Eighteen native contract/worker tests pass. Coverage includes absent and null decisions plus worker persistence of a failed eligibility batch, failed-stage telemetry and sanitized error code. Ruff and diff checks pass. CI 34337354217 was verified still running; latest-head runs were queued. Production and full-audit completion remain unproven.

### Increment: bounded worker evaluation before lease expiry

- Query embedding and batch evaluation now have cooperative asyncio deadlines of 240s and 90s, below their 300s and 120s leases. This leaves a persistence margin instead of allowing an indefinitely awaited provider to consume the lease and trigger repeated work. Query timeout proceeds with unknown semantic measurement; batch timeout rolls back and saves an explicit failed batch, with no invented scores.
- Five worker tests pass, including actual cancellation of indefinitely awaiting coroutines in both stages, single invocation, failure telemetry and sanitized TimeoutError checkpoint. Ruff and diff checks pass. These cooperative limits cannot preempt blocking CPU code or guarantee database availability; production throughput/p95 and full completeness still require measurement. No production execution or completion is claimed.

### Hosted CI follow-up: toast timers outlive unmount

- Frontend job 102419760814 failed with an unhandled ReferenceError: window is not defined from Toast.tsx timeout after teardown. ToastProvider now tracks and cancels timers at unmount and explicit dismissal; naturally expired timers remove their handles. Existing notification timing and context identity remain unchanged.
- Five toast accessibility/lifecycle/context tests, TypeScript and ESLint pass. The new test covers three notification types, early dismissal, natural expiration and zero remaining timers at unmount. This fixes the observed CI cause; it is not yet proof of a green hosted suite.

### Increment: legacy retrieval keeps the full canonical request

- Removed the legacy 300-character description / 500-character requirement truncation and invented seniority hints from _build_job_query. The legacy endpoint now constructs its retrieval document with the same full request builder as Radar and canonical fit, including reviewed requirements. Weight selection remains the scorer's responsibility.
- Sixteen native requirement tests pass. The new regression checks both long-field tails, an approved OR group, nice-to-have and a new tail edit changing the query. Ruff and diff checks pass. This fixes the query context only; legacy ranking mode, full-pool quality, operational proof, hosted CI and production delivery still require completion.

### Increment: compatibility endpoint keeps explicit location semantics

- /ai-matches no longer uses job.location as an implicit hard filter. Omitted location keeps unknown-location candidates eligible for ranking; an explicit location still filters. Removed the shared-engine branch's second query-text assignment so retrieval receives the canonical full document already built for the request.
- Nineteen native location/endpoint tests pass, including the actual handler with a located request and known/unknown-location candidates, explicit filter behavior and verification of the full document sent to retrieval. Provider/gate/scorer are controlled in this transport regression, so it is not production scoring-quality evidence. Ruff/diff checks pass; hosted CI and delivery remain open.

### Increment: remove alternative scoring from compatibility AI Matching

- Removed the flag-controlled raw cosine/reranker score and fallback profile-completeness ranking branches. /ai-matches always calls the canonical fit adapter, including null measurement handling, in semantic and SQL fallback discovery. The old setting can no longer change score meaning. SQL fallback selection is stable by candidate ID; discovery remains bounded and is not full-population evidence.
- Twenty-five native tests pass (six PostgreSQL integration cases deferred). Handler regressions exercise both old flag values and both discovery branches with explicit/no-location filters. Updated the old flag-off hosted contract to require total_score and match_score = total_score / 100. Ruff and diff checks pass. Broader hosted compatibility regressions may need expectation updates for the intentionally changed contract; CI/quality/index/production acceptance is still required.

### Compatibility integration fixtures follow canonical semantics

- Updated hosted compatibility scenarios to widen the actual MATCH_POOL_SIZE and expect semantic+composite. Must-have exclusion and rubric-label fixtures now explicitly select reviewed exclusion, preserving their intended hard-filter assertions without reinstating silent default exclusion. Healthy-ranking fixture supplies a successful exact vector measurement as well as retrieval hits; a hit alone no longer proves measured fit.
- Twenty-six native row-label/handler tests pass (one DB integration case excluded in that selection); Ruff/diff checks pass. The edited DB scenarios await hosted execution. Earlier CI 34337354217 shard 0 completed successfully; other backend shards were still running. Full latest-head CI, production and all audit acceptance remain open.

### Increment: persist specific full-scan exclusion categories

- Dealbreaker results now carry candidate-to-primary-reason mappings while preserving the existing counters and precedence. The shared gate optionally returns those mappings plus the privacy-preserving eligibility_hidden category. Full scan rows persist the actual category instead of always recording eligibility_or_filter. Blocked/warn candidates remain visible under existing rules.
- Fifty-one native gate/filter/worker tests pass, including reconciliation of a budget exclusion and a hidden candidate without duplicate counting. Ruff/diff checks pass. Aggregated API/UI reason counters and validation on a full production run remain required. Earlier CI shards 0 and 2 passed; remaining hosted acceptance and deployment are not complete.

### Increment: shared exclusion counters in API and UI

- The existing aggregate SQL count query now counts allowlisted primary exclusion categories. Empty/legacy/unrecognized reasons are reconciled into unknown, so categories sum to excluded and never double-count a candidate. No candidate identity or private restriction reason is added to this aggregate response.
- Radar and pipeline share the same labelled counters, including explicit missing-proof exclusion and a separate missing-details category for old results. Zero categories are omitted visually.
- Nine frontend status/result tests, typecheck, ESLint and Ruff/diff checks pass. The PostgreSQL store scenario now checks primary-reason precedence and empty/legacy categories; execution is deferred to hosted CI. Earlier CI shards 0/2 passed, 1/3 were still running. Production counters/coverage, other audit acceptance and delivery remain open.

### Hosted CI follow-up: client profile unknown opening date

- Backend shard 1 job 102419761105 failed only test_profile_returns_expected_shape: get_client_profile called max(0, None) when duration_days correctly returned unknown for an absent opened_at. The response now preserves the already nullable duration result; duration_days itself clamps actual negative durations.
- Added deterministic PostgreSQL endpoint coverage with a 30-day-old creation timestamp and no opening date, expecting HTTP 200 and null days_open. Ruff/format/diff checks and collection of 15 profile tests pass; the database scenario has not been executed locally and awaits hosted CI. This addresses the concrete observed failure without substituting created_at or fabricated zero days. Other audit and deployment requirements remain open.

### Increment: changed eligibility invalidates displayed run freshness

- Result reads compare current eligibility annotations to stored annotations. Adding/removing a block on a returned candidate now marks data_changed and prevents claiming a complete current ranking, even when candidate.updated_at did not change. Current annotations remain authoritative; fit itself remains unchanged when only eligibility changes.
- Shared UI labels totals and post-threshold membership as the state at scan time. Seven API tests and nine frontend status/result tests pass, alongside typecheck and Ruff/diff checks. Cases cover both block directions with unchanged/changed candidate data and preservation of private evidence redaction.
- This detects eligibility drift for read rows, not every off-page policy dependency. Global policy versioning/re-evaluation and production proof remain open, alongside the rest of the audit.

### Increment: reject contradictory measurement contracts

- CandidateEvaluation rejects measured-without-score, unknown measurement states and boolean scores. This prevents an invalid evaluator response from being counted as a complete measured ranking. Real numeric zero remains a valid measured value; missing vectors remain nullable and unmeasured.
- Sixteen native scan/worker tests pass, including new invalid-state cases and preservation of zero versus unknown. Ruff/diff checks pass. Latest CI 34338923482 and gate 34338923456 were verified queued, with concrete job IDs; neither was restarted. Production quality/index/coverage and the remaining audit requirements are still open.

### Increment: generated draft output matches consumed contract

- AI writer requests only the description field it actually consumes, avoiding generated titles/requirements/pay/benefits that are discarded. Explicit user criteria and empty unapproved compensation/benefits remain server-controlled.
- Empty, non-object or non-text descriptions now fail instead of producing a successful blank draft; the existing route maps provider failures to an explicit unavailable response. Thirteen native writer tests pass, including malformed payloads, prompt output fields and preserved supplied criteria. Ruff/diff checks pass. This validates transport/grounding boundaries, not factual accuracy of actual model prose; live quality review remains required. Latest CI was still queued.

### CI queue prevention for subsequent revisions

- CI and CI Gate now use workflow/PR concurrency groups and cancel superseded PR runs. Non-PR runs use unique run IDs and never cancel one another, preserving independent main/deployment gates. Existing old runs without a group may still need completion/cancellation; this is not a claim the queue is drained.
- Parsed both YAML files and compared every job/trigger with HEAD: unchanged. Four existing CI coverage/encryption contract tests pass, one skipped. Diff check passes. Latest checks still require actual hosted execution; no test or protection was bypassed.

### Increment: no implicit score floor across request search surfaces

- Compatibility AI Matching and live recommendations now default to a zero threshold, matching full Radar/C2. Explicit caller thresholds keep their existing scale and effect. Proposal snapshots retain top-ranked canonical fits without the former hidden 40-point floor; policy v6 invalidates older floor-truncated snapshots. Payload/retrieval limits remain explicit and unchanged.
- Eighteen native endpoint/proposal contract tests pass (six integration scenarios deferred). The endpoint regression now uses a 5/100 result and omitted threshold across semantic/fallback branches and both obsolete-flag settings. Ruff/diff checks pass. This aligns default score filtering, not bounded discovery with exhaustive membership; latest CI, quality/index and production requirements remain outstanding.

### Full-population eligibility freshness

Search start records a hash of all effective client conflicts and manager veto candidate IDs. Completed reads compare it across the entire scope, so an off-page block addition/removal or time-based expiry invalidates ranking completeness. Candidate status/preferences remain covered by population version checks; displayed rows still receive live eligibility enforcement. Old runs without the fingerprint are marked changed. This is detection, not automatic recomputation, and concurrent changes after a read remain possible.

Validation: 15 native freshness/API tests passed, including unchanged visible candidates with changed off-page policy. Existing database manager-verdict scenarios now also compare full-scope and candidate-scoped results; execution is left to hosted CI. Ruff passed. Production verification remains pending.

### Production index audit transport

Added `Coolify Ops` action `candidate-index-audit`. After the expected backend revision is deployed, dispatch that action on main. It schedules only `python -m scripts.run_candidate_index_audit_once --run-identity RUN_ID-ATTEMPT`, with a 12-minute subprocess limit and once-only private directory. Actions waits up to 15 minutes, validates population accounting, saves an aggregate artifact for seven days and removes only its uniquely named task. The manifest stays at `/tmp/nexus-index-audit-RUN_ID-ATTEMPT/manifest.json` inside the backend (directory 0700, manifest 0600). It is ephemeral across container replacement; rerun audit if lost. No raw CV, candidate rows, provider logs or orphan ID list is exported.

This action is audit-only: it does not enqueue repairs or delete index points. A reviewed fingerprint and exact manifest remain necessary for the separate repair CLI. The audit fails if SQL membership/content changed during scanning; successful output is still a reconciliation observation, not proof that a later repair finished.

Validation: 18 host-native audit/transport tests passed. Covered successful report extraction, failed/timeout reports, duplicate cron ticks, command identity validation, population accounting, output redaction and owned-task cleanup on success/failure. Ruff passed. Production dispatch is pending deployment; no production audit was performed in this increment.

### Exact-manifest production repair transport

Added `Coolify Ops` action `candidate-index-repair` with `index_audit_identity=RUN_ID-ATTEMPT` and `index_fingerprint=SHA256`. These inputs identify the previously reviewed manifest; neither the workflow nor remote wrapper accepts a path or arbitrary command. The existing repair service verifies the manifest fingerprint, model/collection, complete audit and every targeted candidate version/content under locks before recording outbox intents. No orphan deletion or historical candidate rewrite occurs.

The once-only remote wrapper invokes the existing CLI, returns only enqueue counters and preserves timeout as an unknown transaction outcome. A missing manifest (for example after container replacement) requires a fresh audit. Successful output says `state=enqueued`, not indexed: verify the index worker is enabled, observe queue processing, then run a new coverage audit and full search. Never treat scheduling or enqueueing alone as completed repair. Coolify task cleanup uses the operation's unique run identity and does not touch other crons.

Validation: 26 host-native index audit/repair/transport tests passed; Ruff and diff checks passed. Tests cover command shape, exact manifest path, fingerprint receipt mismatch, once-only execution, missing manifest, timeout uncertainty, redaction and task cleanup for both operations on success/failure. No production dispatch or repair was performed. Hosted CI for the preceding SHA remained queued/pending at this checkpoint.

### Traffit source-update invalidation

The job importer uses raw PostgreSQL UPSERT rather than the API's requirement-source update helper. Its incoming title now clears `matching_requirements` and `requirements_reviewed` only when distinct from the saved title, matching the normal edit contract. Identical repeated syncs and metadata/status updates retain reviewed criteria, including an intentionally empty list. This closes the observed title-update bypass; Traffit's current mapper does not update description, requirements or Champion fields.

Validation: 6 native reviewed-requirement/import-contract tests passed, Ruff and diff checks passed. Two new PostgreSQL cases execute the actual `_UPSERT_JOB`, checking changed-title invalidation, unchanged-title preservation and request fingerprints; collected successfully, execution deferred to hosted CI. No production imports were invoked.

### Frozen recruiter quality evaluation for full-search snapshots

Added `scripts.eval_full_search_quality`, a read-only evaluator of durable full-search results. `--prepare-labels` exports the top 20 plus explicitly selected candidate IDs with blank reviewer/date and unknown verdicts. The review artifact freezes request business facts separately from algorithm/weight versions, plus each candidate version; changed request/candidate facts invalidate evaluation, while the same judgments can compare new algorithm versions. It never converts pipeline stages or AI scores into recruiter judgments.

After human review, `--labels` reports known-positive recall at 20 and across all results, known positives excluded/failed/outside the population, judged coverage of top 20 and precision among judged results. Overall top-20 precision is null until all returned top-20 positions are judged. Missing measurements and failed coverage prevent a complete quality-review claim. Reports include recorded search metrics and version trace, distinguish archived evaluation from live freshness, and are created with mode 0600 without overwrite. Top-20 precision uses the actual returned size (up to 20), reported alongside it.

Validation: 6 native evaluator tests passed, including an outside-top20 positive, ties, unknown judgments, filter losses, partial failures, changed facts and an unjudged review-sheet export. Ruff/diff checks passed. This is measurement tooling, not measured production quality. No production run or human labels have been supplied yet; representative request/candidate examples were requested from the user while implementation continues. Legacy `eval_matching` still measures a different bounded scorer and historical stage proxies, so its results must not be presented as acceptance of the new full-search path.

### Hosted compatibility test corrections

Hosted shard 3 (job 102424824444, revision 2200f426) exposed two outdated test assumptions still present at 7324f6d8. The reviewed-requirement fixture now asserts `reviewed_requirements` on both semantic and fallback branches. The canonical-order test spies on the actual reranker service export after removal of the obsolete matching-module import; stable IDs, exact fit, unknown preservation and non-use of reranking remain asserted.

Validation: six native canonical-fit tests passed; targeted Ruff/format/diff checks passed. The database row-label scenario remains assigned to hosted CI. CI Gate passed on 7324f6d8, including migration and import checks, but full CI and all production acceptance criteria remain pending.

The same older run subsequently completed shards 2 and 0 with one failure each. SQL fallback intentionally includes the shared test population, so its missing-must count must include the known excluded fixture (at least one), while the semantic branch retains the exact one-exclusion assertion against its two-ID pool. Candidate-ID removal and blocked-candidate visibility/assignment assertions remain unchanged. The flag-off score assertion now checks the exact four-decimal API rounding rather than an unrealistically narrow float tolerance. No application logic was changed.

Validation: one native compatibility guard test passed, 11 database cases collected/deferred; focused Ruff/format and diff checks passed. Hosted rerun is required for the changed database assertions.

### Current-main migration integration

Merged main revision cdc26a70 (CV publication and highlighting changes) without conflicts. Alembic initially reported two heads; schema-neutral merge revision `0285_merge_search_cv` joins `0284_merge_search_signature` and `0284_cv_highlight_policy`, preserving both branches. Import registration and health checks retain both full search and published CV models.

Validation: Alembic reports one head, targeted Ruff/format and staged/unstaged diff checks passed. 27 native CV publication/highlighting tests passed. An additionally selected startup-schema test requires PostgreSQL and could not connect to localhost:5432; it remains a hosted-CI check, not a local pass. No local Docker or production schema changes were run. Required CI must run on the merged revision.

### Traffit source invalidation versus column ownership

Hosted shard 2 on fcf03ba1 (job 102437701223) reported two ownership-contract failures: the earlier title-change invalidation touched `matching_requirements` and `requirements_reviewed`, which remain NEXUS-owned. The ownership declaration now separates ordinary sync writes from narrowly allowed source invalidation. These two fields remain outside `SYNC_WRITABLE`; the importer may reset them to NULL/false only on a changed title and must retain them otherwise. No Traffit-provided criteria may overwrite NEXUS criteria.

The contract tests still exhaustively classify every Job column and reject all other NEXUS-owned writes. Additional native tests execute the actual UPSERT CASE expressions with changed/unchanged titles, populated and intentionally empty criteria, empty state and opposing external values. Nineteen focused ownership/remote-policy tests passed. The full PostgreSQL UPSERT tests remain part of hosted CI. This increment changes the explicit ownership contract and its enforcement tests; the previously implemented conditional SQL behavior is unchanged. Other shards of the same run were kept running to collect complete failure evidence before the next push.

### Proposal fixture follows removal of implicit score floor

Hosted shard 1 on fcf03ba1 (job 102437701177) found one obsolete expectation: a measured 28/100 candidate was expected to disappear from proposal snapshots. The implementation intentionally removed that hidden threshold in 41446759. The regression now retains measured 0/28/48 and unknown measurements, always checks the exact base fit/null, zero historical boost and separately reported history count. Five database cases collect successfully; Ruff/format/diff checks pass. Execution remains assigned to hosted CI. No scoring logic changed in this correction.

### Full CI passes and production acceptance cases

Revision `3edaa5fbb222524c2546386b020c360cfc2ecb42` passed the complete hosted CI run `34345928234`: all four PostgreSQL backend shards, their aggregate gate, frontend lint/typecheck/tests/build and the report-only image checks. CI Gate `34345928347` also passed, including the real migration upgrade/rollback/retry probe. This validates the corrected ownership and low-score proposal contracts in the hosted suite.

Merged current main `aaae2102` (CV consent source/client binding, PR #1443) without conflicts. Thirteen native consent-binding backend tests and nineteen frontend consent/standalone-generator tests passed. The combined revision still requires its own hosted CI before merge; no production delivery is claimed by the earlier green run.

Authenticated production Chrome supplied three read-only acceptance cases: job 565252 has an empty brief; job 143767 has a populated AI-imported Champion, a 120 PLN/h budget and hybrid work but empty raw description/requirements; job 14 has a saved Security Analyst description and prose requirements including `SIEM (Splunk lub QRadar)`. Job-edit dialogs were cancelled without changing fields or saving records.

After C2 finished loading for job 14, it displayed five must skills (including Splunk), five nice skills (including QRadar), a default `Rzeszów / Kraków` location filter, zero ranked results and 199 exclusions for must-have. The initial zero must count was a transient loading state, not the final result. The loaded criteria differ from the raw prose alternative; underlying legacy field provenance was not established, so this observation does not authorize rewriting historical criteria. These cases support before/after UI and context-parity checks, not frozen recruiter relevance judgments. Index coverage/repair, deployed SHA/health, actual cost/latency and human quality review remain outstanding.

### Concurrent-main workflow and migration integration

GitHub could not start CI for `75a9c225` because main advanced to `76a2ffca` with an overlapping Coolify Ops action list (CV quality evaluation). The merge retains both candidate-index actions and `eval-cv-quality`, including their separate inputs and jobs. New order migration `0285_md_budget_mode` is joined to the search/CV history by schema-neutral `0286_merge_search_orders`; no parent migration is rewritten.

Validation: all 38 native index-audit/repair/CV-quality operational tests passed, the combined workflow parses and retains all three actions, Ruff/format/diff checks passed, and Alembic reports the single head `0286_merge_search_orders`. Hosted migration execution and full CI remain required on the resolved revision. No operational job or production repair was dispatched.

### Production delivery, exhaustive coverage and index repair

PR #1428 merged as `39fdc7ba98b2956c04bdaaa986074f5795cca07e` after full CI `34347730877` and CI Gate `34347730874` passed on `83229dfc`. Main CI `34362221709` and Gate `34362221719` also passed. Deploy `34362412872` completed successfully; API health/deep served descendant `ba05436f8f0ddbcaea6d7a551d0405b334e97ba7`, and Alembic database/code both reported the single head `0286_merge_search_orders`.

Authenticated Chrome exercised saved job 14 in both C2 and Radar. Each evaluated all 59,964 SQL population members, retaining 58,485 and excluding 1,479 (1,449 remote-only, 30 eligibility). Both preserved 58,485 incomplete evaluations, equal first-page name order and functional second pages. Radar page IDs were 1–20 then 21–40. C2 elapsed time was 280 s; Radar 439 s including its queue wait. Numeric-fit parity and matching quality are **not proven** by these unknown-score results. Radar displayed unknown cost; C2 displayed zero, which requires inspection of actual provider attempts rather than assuming successful free inference.

Exact index audit `34363016584-1` found all 59,964 records had wrong/unknown model provenance and 1,932 orphan points. The unchanged-database manifest fingerprint was `071b872d90bfcef5ea61d9fd718bfde54a72a37c598aeb405f8181cab0f787fa`. Authorized repair `34363925361-1` enqueued exactly 59,964, already pending 0, deleted 0; orphan points were reported only. Fresh audits found 100 current (`34364169078-1`), then 500 current and 59,464 still wrong/unknown (`34364556761-1`). This proves worker progress, not completed repair. No duplicate repair was submitted.

### Runtime diagnostics for acceptance evidence

Added fixed Coolify Ops action `candidate-search-diagnostics`: read-only queue/model/worker/tariff settings, a bounded projection of the latest ten search runs and measurement states, the existing 24-hour cost/p95 report, and one fixed synthetic query-vector probe. The probe never sends candidate or request text. A once-only directory prevents repeated provider calls by cron ticks. Reports omit credentials, candidate/user IDs, source text and exception messages; the transport independently projects and validates allowed aggregate fields. Index actions no longer schedule the unrelated empty queue-ops job.

Validation: 27 native diagnostic/audit/repair operational tests passed, including invalid numeric data rejection, private-field removal, once-only probing, failure redaction, observed token accounting and owned-task cleanup. Ruff/format/diff checks and workflow parsing passed. Hosted CI and deployed execution of this follow-up remain required. Original A01–A12 acceptance remains open, especially finished index reconciliation, numeric parity, frozen human quality labels, tariff and measured latency/cost.

### Live factual job-draft regression

Authenticated production Chrome exercised the global new-job generator with a synthetic Software Developer draft: maintenance of an existing API, remote work, Python or Java, Django explicitly not required, SQL optional, and unspecified experience, client, benefits and pay. Priority was Critical while draft seniority remained unspecified. The returned source was AI; its text preserved the alternative, negation and optional skill, left seniority/experience/pay/benefits unspecified, and was labelled a draft for review.

The description stayed unchanged until explicit apply. After applying within the unsaved form, requirements remained unchanged, both salary fields remained empty and seniority remained unspecified. The form was cancelled without creating a recruitment. Evidence: private `generator-factual-draft-prod-20260909.json`. This is one live A06 regression, not a comprehensive quality benchmark.

CI Gate on diagnostic revision `3cc7465e` flagged a synthetic all-a UUID fixture as a Fireflies key. The fixture now constructs a deterministic UUID from integer 1, preserving the same contract without suppressing the scanner. Nine diagnostic tests passed after the correction. Hosted checks must pass on the corrected revision before delivery.
