# CV audit remediation — 2026-09-09

Scope: both audits, CV-01 through CV-20, baseline main
`5f0d30a1f1e682e286250720b1733f8253d4f1f5`.
A local regression fix is not a completed delivery. Completion requires required
CI, merge, expected deployment revision and relevant production verification.

| Finding | Acceptance criteria | Status |
|---|---|---|
| CV-01 | Consent reset on candidate switch; server rejects asset bound to another subject | Signed upload receipt binds owner, candidate/stage/client or uploaded CV bytes/client. UI resets and ignores late responses. Local regressions pass; CI/deploy/production proof pending |
| CV-02 | Standalone and pipeline share an immutable selected version across edit, approval, export and share; legacy links preserved | Pending |
| CV-03 | Atomic save/finalize, version conflict detection, recoverable failed autosave, new revision after approval | Atomic current-content approval, draft OCC, immutable versions and pinned legacy links implemented; hosted DB races, CI and production interaction pending |
| CV-04 | Share result survives stage move and queue depletion; action labels distinguish link creation from sending | Implemented with 23 component regressions; CI and production interaction pending |
| CV-05 | Explicit upload candidate/job association; server-filtered paginated history | Implemented with explicit process selection and server cursor history; local tests pass, hosted DB >60-document regression and production proof pending |
| CV-06 | Common client resolver respects upload client in public CV, chat and export | Implemented locally; CI and production verification pending |
| CV-07 | Job resource authorization on generation, listing, download and share; authorized Finance reads preserved | Shared read/write guards and SQL filtering implemented; 163 local regressions pass, hosted database and production checks pending |
| CV-08 | Mode/client-specific readiness; frozen explicit source selection; invalid required inputs block generation | Pending |
| CV-09 | Durable inputs/jobs, retry/idempotency/progress; validate before charging quota | Pending |
| CV-10 | Evidence-based review gate; source/rule/model/prompt/template metadata; stable approved artifact bytes/hash | Pending |
| CV-11 | Full/scoped tenure distinguished; month formats, gaps, overlap, partial dates and career changes handled without inflated claims | In progress: conservative arithmetic and scoped-claim regressions; source-linked tenure still pending |
| CV-12 | Complete facts extracted independently of display limits/omitted sections | Pending |
| CV-13 | Claims bound to source subject, polarity, unit and role; unsupported claims removed or approval blocked | Pending |
| CV-14 | Typed independent highlighting; identical verified spans in DOCX, HTML and public view | Implemented locally with typed policy, shared matcher and public text runs; CI and production artifact verification pending |
| CV-15 | Distinct concise fact-based summaries; meaningful rewriting instead of mechanical truncation | Pending |
| CV-16 | Typed language aliases cannot alter technologies, certification or seniority; final factual validation | Typed reviewed role translations implemented, arbitrary legacy substitutions skipped with warnings, unsafe publication blocked. CI, deployment and final factual review acceptance pending |
| CV-17 | Independent draft/published recipes incl. flags; atomic versioned publish, concurrency, rollback | Implemented with migration and local regressions; hosted API/migration tests and production verification pending |
| CV-18 | Snapshot-based preview uses production contract and actual DOCX; applied/skipped/conflicting rule feedback | Recipe snapshot, language check and draft cap implemented; source snapshot, DOCX and complete validation still pending |
| CV-19 | Validate client naming patterns and mappings; review exact recipes and evidence before operational publication | Filename validation implemented locally; configuration review/publication and production verification pending |
| CV-20 | Shared deterministic policies and versioned source corpus; primary/fallback evaluations and DL acceptance evidence | Pending |

## Verification ledger

Initial package targets the deterministic CV-11 defects. Existing tests that
assigned the total career to an unproven role/industry were corrected to assert
an explicitly generic total or preservation of the scoped claim. This does not
establish whether a model-produced claim is true; source-linked facts and final
verification remain required by CV-11/CV-13.


## Draft/publication package

The API keeps published columns and live client flags unchanged on draft save.
Every mutation checks `expected_revision` while holding the client row lock;
missing or stale revisions return 409. Version restoration creates a draft.
The migration snapshots currently active recipes without activating seeds.
Older publications without a historical snapshot are not invented from diffs.
Preview jobs capture the complete recipe and flags before enqueue; freezing
candidate inputs and exporting the exact preview artifact remain CV-18 work.

Hosted acceptance includes publish → draft → stale edit rejection → publish →
restore → publish and two competing initial saves. Local unit tests verify
mutation isolation and immutable snapshot contents; they do not replace DB
transaction or migration verification.


## Consent subject binding

New consent uploads receive an eight-hour signed receipt, with a separate signing
purpose. Candidate mode binds the DB candidate and stage plus the server-derived
client; manual upload binds the exact SHA-256 of CV bytes and client. Generation
verifies operator and context before charging quota. Bare historic storage keys
cannot attach images to newly generated documents; already generated artifacts
retain their original images. An older open frontend needs refresh/re-upload.
The signature records the association, not an assessment of the screenshot text.

Switching CV/candidate/stage/client clears the attachment. Late responses for a
previous subject are ignored. Upload success also clears the candidate picker.
The regression generates A with consent, then B without carrying A's receipt.


## Highlighting package

Highlight policy is independent of narrative mode: candidate technologies,
MUST, MUST+NICE, explicit technology list, or none. Selection checks lexical
presence in the source and the technology taxonomy. It is not semantic proof of
competence or claim truth; CV-13 remains responsible for that gate.
DOCX, downloadable HTML and public text runs use the same matcher. Public runs
are derived after privacy projection and are not added to AI input payloads.
Ambiguous Polish uses of Jest are excluded unless a testing context is present.
Keyword formatting leaves structural heading styles intact.

## Draft persistence and approved versions


Approval sends the editor's current HTML and expected revision as one command.
All saves, approvals, revision creation and token creation serialize on the
stage-CV row. Conflicts return 409 before mutation. Approved HTML and metadata
are kept in `cv_document_versions`; creating a new draft pins legacy unbound
tokens first, so previous links keep their approved content. No tokens are
revoked and no historical bulk migration is performed.

The editor serializes autosave and approval, retains typing during a save,
keeps failed edits for retry and flushes pending changes before closing or
printing. A new version starts from the last approved content. This is the
versioning foundation: selecting generator output as the pipeline's canonical
document and sharing by explicit selected-version ID remain CV-02 work.

Host checks: 8 version unit tests plus 2 selected Finance/read regressions,
6 frontend persistence/component tests, TypeScript, Ruff and shell syntax.
The former audit reproduction for immediate approval now passes. PostgreSQL
concurrency, old/new token pinning and migration tests are required in hosted
CI. A local attempt at 6 DB model tests returned connection-refused against the
deliberately unavailable test DB; it provides no DB acceptance evidence. No
local Docker was used. Production validation remains outstanding.

## Generator recruitment resource scope

Job-associated generator documents use the existing pipeline resource guards.
Readiness and document history are SQL-filtered before returning results or
applying the history limit. Generation checks the stage/candidate pair and job
membership before client rules, source reads or quota. Pending rows, including
the automatic second language, carry job_id before background work finishes.
DOCX/HTML, sharing, share history, revocation and deletion use one scoped loader.
Finance keeps organization-wide read access; that read bypass does not grant
job commands. Existing unassociated uploads remain globally available under
the candidate role/section guard. Legacy null-job records cannot be assigned to
a recruitment without evidence; no guessed backfill is performed.

163 focused host tests pass (including 14 new scope cases). A separate hosted
PostgreSQL test covers real membership, scope before LIMIT and Finance readiness
reads. No local database or Docker was used. Operational production authorization
checks and hosted CI remain required.
## Handoff result package

One-time share links are retained with the candidate/job context immediately
after creation, independently of the selected stage. They remain visible after
the candidate leaves the queue, after moving to another candidate and after the
queue becomes empty. Copy and mail-draft actions use the captured context.
No email is sent by stage movement; labels explicitly describe link creation and
status changes. Tokens are held only in this mounted screen, not local storage;
full-page reload or navigation recovery is not claimed.

23 focused component tests pass, including the original queue-depletion audit
regression, two consecutive candidates and existing partial-failure behavior.
TypeScript passes. Production interaction and hosted CI remain required.

## Safe language aliases package

The glossary now accepts reviewed `role_translation` pairs for whole position
fields, with a fixed source/target language. Runtime never substitutes inside
skills, certificates, summaries or responsibilities and never strips seniority
from compound titles. Only catalog entries matching the generated document's
language reach the editorial prompt or deterministic translation.

Legacy arbitrary pairs remain visible in drafts/history, are ignored with a
generation warning, and block publication until replaced or removed. The editor
selects from the server catalog instead of free text. No client recipe is
operationally edited by the deployment. The initial catalog has five PL/EN role
pairs; additional equivalents require explicit review. This closes arbitrary
glossary rewriting, not hallucinations originating in free-form instructions or
model output, which remain the final factual gate's responsibility.

Verification: 65 focused backend tests, 9 editor tests and TypeScript checks;
hosted CI and production interaction still pending. No local Docker.

## CV-02 — explicit generated document selection (partial delivery)

A recruitment draft can now explicitly select a completed generated document for
that exact candidate and job. Selection checks the draft revision under the stage
row lock, preserves an earlier approval and its links, and imports the same
client-safe body used by HTML export, including technology emphasis. The selected
source ID is captured on approval. Template/language changes cannot silently
replace a selected document with a fresh rendering of the candidate profile;
users generate and choose a replacement instead. Deleting the source does not
remove this protection.

Validation: 28 focused backend tests and 38 frontend tests pass; TypeScript,
Ruff and one Alembic head pass. Hosted API lifecycle test covers selection,
immediate approval of current edited content, reselection and the original
public link. PostgreSQL lifecycle/migration execution and production interaction
remain required.

This is not completion of CV-02/CV-10: DOCX export after manual editing, immutable
approved DOCX bytes, standalone approval and one version across standalone
interactive links still require implementation. Imported HTML uses the existing
HTML export presentation, not the original DOCX letterhead/consent image layout.


## Upload association and complete history

Upload requests optionally carry candidate/stage IDs. The server validates their
relationship and recruitment membership, derives the client, and refuses stale
client assertions before quota or background work. Finalization and the optional
second-language document preserve that association. No name-based matching or
legacy reassignment is performed. Embedded upload binds to its current process;
standalone upload offers an explicit process or a candidate-only/unassigned file.

The history API applies candidate/job filters before LIMIT and provides a stable
id cursor. The UI loads older pages with the same context and polls processing
rows on loaded pages. Context switches reset pending source attachments.
40 local backend and 14 component tests pass; the hosted PostgreSQL regression
inserts more than 60 unrelated documents and checks filtered cursor traversal.
CI, deployment and actual production flow remain required.

## Upload association and complete history

Upload requests optionally carry candidate/stage IDs. The server validates their
relationship and recruitment membership, derives the client, and refuses stale
client assertions before quota or background work. Finalization and the optional
second-language document preserve that association. No name-based matching or
legacy reassignment is performed. Embedded upload binds to its current process;
standalone upload offers an explicit process or a candidate-only/unassigned file.

The history API applies candidate/job filters before LIMIT and provides a stable
id cursor. The UI loads older pages with the same context and polls processing
rows on loaded pages. Context switches reset pending source attachments.
40 local backend and 14 component tests pass; the hosted PostgreSQL regression
inserts more than 60 unrelated documents and checks filtered cursor traversal.
CI, deployment and actual production flow remain required.

## Multipage letterhead regression (synthetic production CV)

The actual production fixture split the word "Tworzenie" around background
artwork on page 2. The renderer now reserves the artwork band and removes tight
wrapping, preserving image bytes and native page coordinates. Negative column
coordinates were rejected after rendered inspection showed disappearing headers
on continuation pages. The standalone browser preview corrects its own missing
page-origin and centered-inline wrapper behavior.

Verification: two rendered pages inspected using bundled LibreOffice; local
Chrome rendered the actual synthetic DOCX with the production docx-preview
library and the new helper. Header is complete. 17 focused backend regressions,
preview DOM regression and type-check pass. Hosted CI/deployment/production
browser proof remain pending. This fixes letterhead layout, not unsupported
AI claims, font availability or complete Word/browser pagination parity.

### CV-09 / required Champion admission — partial delivery

Upload now reads at most the existing 50 MB limit plus one byte and validates both files before charging quota or creating a generation row. It rejects unsupported/empty/corrupt DOCX and PDF documents, empty DOCX text, blank PDF pages and oversized DOCX expansion. A client-required Champion must have recognized content or explicit manual requirements; a filename alone is insufficient. Optional unrecognized profiles retain the existing warning behavior.

The preflight runs without AI or OCR. Image PDFs remain eligible for the existing worker OCR, so unreadable scans and later OCR failures still need durable worker/quota accounting; this package does not claim to solve those cases or restart/retry persistence. 35 host-only tests pass, including real PDF/DOCX parsing and six HTTP cases proving no quota, pending row or worker call on invalid uploads. Production and hosted acceptance remain open. Depends on the explicit upload/history package #1450.
