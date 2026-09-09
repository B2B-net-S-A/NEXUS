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
