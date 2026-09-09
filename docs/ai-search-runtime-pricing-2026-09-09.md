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
