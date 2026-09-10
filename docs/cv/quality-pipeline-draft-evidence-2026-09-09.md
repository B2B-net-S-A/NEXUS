# Inactive quality pipeline — delivery evidence

## Responsibility limits without substring truncation (draft)

The factual pipeline rewrites only retained responsibility bullets exceeding the client limit, in one bounded provider call. It validates complete path coverage and lengths before applying changes; empty/overlong/ellipsis responses block the document. Final factual verification sees the rewritten text and original sources, with explicit preservation of training/academic/assisted-work qualifications. Forty focused tests pass, including a rejected training-to-production rewrite before DOCX. Actual-model success, false rejections and added latency/cost remain unmeasured; this package is not active in production.

### Recovered verifier smoke result and diagnostic categories

Receipt `34365301060-1` (runtime d511b13d, prompt fingerprint 74dc405a)
completed four primary-model cases: two English cases passed, both Polish cases
returned `invalid_review`. All four provider calls were metered; estimated cost
was USD 0.013698. This is a negative smoke result, not a full CV benchmark or
proof that the current prompt detects hallucinations. Recovery task cleanup was
confirmed. The inactive quality branch now distinguishes invalid JSON, schema,
and claim coverage using fixed codes only; no raw response is logged. These
protocol failures never count as successful semantic rejections. 44 focused gate
and transport tests pass. No live activation or further model run is implied.

### CV-18: one extracted ledger in the inactive quality pipeline

The quality branch now prepares CV text, complete source facts and dated tenure
once for a rule preview, then supplies the same immutable JSON ledger to both
variants. Each variant deserializes its own copy and retains final factual review.
CV-byte and notes hashes reject accidental reuse with another source. One
regression runs both pipelines, mutates the first result's fact list, checks the
second remains complete, and proves only one text/source extraction occurred.
67 focused gate/editorial/snapshot/publication/runtime tests pass. This remains
inactive pending actual-model quality acceptance and does not add durable jobs.

## Exact derived durations

The advisory numeric guard no longer admits a computed year count plus or minus one. Individual jobs use the same month-precision validation and inclusive completed-year calculation as the career headline. Year-only or incomplete dates cannot authorize a duration by assuming missing months. Five regression cases cover an extra year, an incomplete year, missing precision and overlapping full-source history. 53 focused numeric/factual tests pass. This remains an advisory numeric check; coincidence of source numbers and role/tool attribution still require the final semantic verifier and real-model acceptance.
