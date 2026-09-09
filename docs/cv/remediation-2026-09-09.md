# CV audit remediation — 2026-09-09

Scope: both audits, CV-01 through CV-20, baseline main
`5f0d30a1f1e682e286250720b1733f8253d4f1f5`.
A local regression fix is not a completed delivery. Completion requires required
CI, merge, expected deployment revision and relevant production verification.

| Finding | Acceptance criteria | Status |
|---|---|---|
| CV-01 | Consent reset on candidate switch; server rejects asset bound to another subject | Pending |
| CV-02 | Standalone and pipeline share an immutable selected version across edit, approval, export and share; legacy links preserved | Pending |
| CV-03 | Atomic save/finalize, version conflict detection, recoverable failed autosave, new revision after approval | Pending |
| CV-04 | Share result survives stage move and queue depletion; action labels distinguish link creation from sending | Pending |
| CV-05 | Explicit upload candidate/job association; server-filtered paginated history | Pending |
| CV-06 | Common client resolver respects upload client in public CV, chat and export | Implemented locally; CI and production verification pending |
| CV-07 | Job resource authorization on generation, listing, download and share; authorized Finance reads preserved | Pending |
| CV-08 | Mode/client-specific readiness; frozen explicit source selection; invalid required inputs block generation | Pending |
| CV-09 | Durable inputs/jobs, retry/idempotency/progress; validate before charging quota | Pending |
| CV-10 | Evidence-based review gate; source/rule/model/prompt/template metadata; stable approved artifact bytes/hash | Pending |
| CV-11 | Full/scoped tenure distinguished; month formats, gaps, overlap, partial dates and career changes handled without inflated claims | In progress: conservative arithmetic and scoped-claim regressions; source-linked tenure still pending |
| CV-12 | Complete facts extracted independently of display limits/omitted sections | Pending |
| CV-13 | Claims bound to source subject, polarity, unit and role; unsupported claims removed or approval blocked | Pending |
| CV-14 | Typed independent highlighting; identical verified spans in DOCX, HTML and public view | Pending |
| CV-15 | Distinct concise fact-based summaries; meaningful rewriting instead of mechanical truncation | Pending |
| CV-16 | Typed language aliases cannot alter technologies, certification or seniority; final factual validation | Pending |
| CV-17 | Independent draft/published recipes incl. flags; atomic versioned publish, concurrency, rollback | Pending |
| CV-18 | Snapshot-based preview uses production contract and actual DOCX; applied/skipped/conflicting rule feedback | Pending |
| CV-19 | Validate client naming patterns and mappings; review exact recipes and evidence before operational publication | Filename validation implemented locally; configuration review/publication and production verification pending |
| CV-20 | Shared deterministic policies and versioned source corpus; primary/fallback evaluations and DL acceptance evidence | Pending |

## Verification ledger

Initial package targets the deterministic CV-11 defects. Existing tests that
assigned the total career to an unproven role/industry were corrected to assert
an explicitly generic total or preservation of the scoped claim. This does not
establish whether a model-produced claim is true; source-linked facts and final
verification remain required by CV-11/CV-13.
