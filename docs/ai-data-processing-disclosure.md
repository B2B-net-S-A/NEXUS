# AI data processing disclosure

The active provider, model, route version and sent-data categories are exposed
read-only in Settings → AI. Administrators may change only feature enablement,
monthly calls and monthly budget; routing activation is a separate audited API.

Anthropic is the primary generative provider. Voyage is used for anonymised
embedding/reranking text. OpenAI is an inactive parser challenger and receives
no candidate data unless all of the following are true: production use, DPA,
ZDR and subprocessors are approved; the transfer basis is `eea` or `scc_tia`;
the feature is enabled; budget/quota are available; and both the provider API
key and AES-256-GCM evaluation vault key are configured. Responses API storage
is always disabled (`store=false`); Batch API is prohibited for candidate data.

Evaluation cases store references to source records, not copied CVs. Temporary
model outputs are encrypted with AES-256-GCM and removed after 14 days. The
13-month call ledger stores hashes, route/model identity, token/cost/latency and
status metadata, never prompts or responses. Candidate identifiers and contact
data are excluded from embedding text; pay, location and availability remain
structured filters.

Ollama is development/offline-only and is never a silent production fallback.
Fable is disabled. No model autonomously rejects a candidate, and generated
match explanations cannot alter deterministic scoring.
