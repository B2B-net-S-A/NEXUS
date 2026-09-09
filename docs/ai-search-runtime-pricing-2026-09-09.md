# Search cost estimates: production acceptance follow-up

Runtime diagnostic `34380867562-1` confirmed production uses `voyage-3`, but its
tariff was missing. Two of six archived searches and the synthetic provider probe
therefore correctly reported unknown monetary cost. Four searches recorded no
provider calls and correctly reported zero incremental provider cost.

The default model-price map now contains the official public list prices verified
on 2026-09-09 at <https://docs.voyageai.com/docs/pricing>: `voyage-3` costs $0.06
per million tokens; the application default `voyage-3-large` costs $0.18.
These are estimates from observed token usage, not invoices or total indexing
cost. Negotiated account rates can replace the map through the existing
`AI_SEARCH_EMBEDDING_PRICES` environment JSON. An explicit `{}` disables pricing;
unknown models and missing usage remain unknown. Archived runs are not repriced.

Acceptance requires a new production diagnostic after deployment: the runtime
must report the actual model tariff, and a successful synthetic call with known
token usage must report the corresponding non-null estimated cost. A model
switch or another indexing repair is not required by this change.

Other acceptance remains open: the diagnostic saw 44,514 pending indexing tasks
and no dead tasks. The latest two comparable runs covered 59,964 candidates and
had identical raw scores for all 7,949 pairs with valid measurements in both
runs, but their full rankings were incomplete. Six partial searches yielded an
observed p95 of 439,010.002 ms; this small sample does not prove a latency target
or ranking quality. Recruiter-labelled quality evaluation is still required.

## Healthy backlog pacing

The subsequent audit `34384473176-1` found 16,850 current profiles and 43,114
wrong/unknown-model profiles in the unchanged 59,964-record population. The
worker previously paused for 30 seconds after every 50-record batch, even when
the backlog remained large. It now uses `AI_INDEX_WORKER_BUSY_INTERVAL_SECONDS`
(default 1, minimum 1) only after a full committed batch of successful events.
Idle/partial batches, failed/dead events and database exceptions retain the
normal pause. Processing, claims and provider retries remain sequential and
unchanged; no additional repair is enqueued. Set both intervals equally to
restore fixed pacing. Measure actual coverage growth and failures after deploy
before revising the completion estimate.

Pricing and pacing are delivered together in PR #1470; PR #1471 is superseded.
All remaining code changes for this audit must stay in the same open PR per
the user's instruction. Native combined validation: 31 focused tests passed.
