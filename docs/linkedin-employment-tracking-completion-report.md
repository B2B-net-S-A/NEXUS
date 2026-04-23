# LinkedIn Employment Tracking — Completion Report

Status: **MVP + v1 delivered end-to-end**, verified via tests + Chrome MCP.
Date: 2026-04-23
Branch: `main` (uncommitted — awaiting user review before push)

## What shipped

Nexus now detects and surfaces when a candidate has changed jobs (based on
their LinkedIn profile via Proxycurl). Recruiters see a badge on the list,
can filter by recent-job-change window (1/2/3 months), and see full sync
status + change history on the candidate detail view.

## Scope (confirmed with user before build)

- Provider: **Proxycurl API** (~$0.01 cached / $0.04 live per lookup)
- Full MVP + v1: migracja, service layer, background sync, API, frontend
- Only **new employer** triggers "job change" (awans = osobny sygnał, v1.1)
- CV parser auto-extracts LinkedIn URL (LLM primary, regex fallback)

## Migration

`backend/alembic/versions/0049_linkedin_employment.py` — applied, DB head.

- Added 7 columns on `candidates`:
  - `linkedin_current_company` (indexed), `linkedin_current_title`,
    `linkedin_current_started_at`
  - `linkedin_employment_changed_at` (indexed — filter path)
  - `linkedin_synced_at` (indexed — stale query)
  - `linkedin_sync_status` (enum, default `disabled`, NOT NULL)
  - `linkedin_sync_error`
- Added table `candidate_linkedin_snapshots` with FK CASCADE and composite
  index `(candidate_id, fetched_at DESC)`.
- Enums created: `linkedinsyncstatus`, `linkedinchangekind`.

## New files

**Backend**
- `backend/app/models/linkedin_snapshot.py` — `CandidateLinkedinSnapshot`
  model + 2 enums.
- `backend/app/services/proxycurl/client.py` — `ProxycurlClient` (retry,
  Retry-After, 404 → `ProfileNotFound`), `normalize_linkedin_url`.
- `backend/app/services/proxycurl/diff.py` — pure change-detection with
  `rapidfuzz` fuzzy company matching.
- `backend/app/services/proxycurl/sync.py` — orchestration:
  `sync_candidate_linkedin`, `prune_old_snapshots`.
- `backend/app/services/proxycurl/__init__.py` — public exports.
- `backend/app/tasks/linkedin_sync.py` — asyncio loop (disabled while
  `PROXYCURL_API_KEY` empty).
- `backend/alembic/versions/0049_linkedin_employment.py`
- `backend/tests/test_proxycurl_diff.py` — 10 tests
- `backend/tests/test_proxycurl_client.py` — 6 tests
- `backend/tests/test_cv_parser_linkedin_extraction.py` — 10 tests
- `backend/tests/test_candidates_api_recent_job_change.py` — 5 tests

**Frontend**
- `frontend/src/components/v2/LinkedinSyncPanel.tsx` — detail-view section
  with current employer, change history, refresh button (POST sync).

## Modified files

**Backend**
- `backend/app/models/candidate.py` — 7 columns, relationship to snapshots.
- `backend/app/models/__init__.py` — export new model + enums.
- `backend/app/core/config.py` — `PROXYCURL_*` block (enabled, api key,
  interval 1h, stale 7d, batch 50, fuzz threshold 90).
- `backend/app/main.py` — register `linkedin_sync_loop` in lifespan.
- `backend/app/api/candidates.py` — filter `recently_changed_jobs` (1/2/3),
  `POST /{id}/sync-linkedin`, eager-load snapshots in
  `_candidate_list_options` (stripped from list response).
- `backend/app/schemas/candidate.py` — new fields on `CandidateResponse`,
  `LinkedinSnapshotSummary`, `CandidateLinkedinSyncResponse`.
- `backend/app/services/cv_parser.py` — regex fallback + LLM backfill for
  `linkedin_url`.
- `backend/app/services/llm_prompts.py` — `CV_ENRICHMENT` v3: adds
  `linkedin_url` field.
- `backend/requirements.txt` — `rapidfuzz==3.10.1`.

**Frontend**
- `frontend/src/components/v2/CandidateHighlights.tsx` — "Nowa praca X"
  badge with 30/60/90-day tier (warning / info / neutral).
- `frontend/src/components/v2/pages/CandidatesListV2.tsx` — `recently_changed_jobs`
  state + URL param `?rcj=` + "Niedawno zmienił pracę" radio section in the
  advanced filters popover.
- `frontend/src/components/v2/pages/CandidateDetailV2.tsx` — mounts
  `LinkedinSyncPanel` in ProfilTab, above "Doświadczenie zawodowe".

## Tests

**31 new tests, all green.** Run:
```
docker exec nexusats-backend-1 python -m pytest \
  tests/test_proxycurl_diff.py \
  tests/test_proxycurl_client.py \
  tests/test_cv_parser_linkedin_extraction.py \
  tests/test_candidates_api_recent_job_change.py -v
```

Existing candidate-related tests (`test_candidates.py`,
`test_candidates_position_filters.py`) still pass — 13 regression-green
confirming no break in the list/filter path.

Pre-existing failure in `test_candidates_filters.py::test_create_candidate_sets_created_by`
is **unrelated** (`userrole='manager'` enum not in DB) — untouched by this
change.

## Chrome MCP verification (end-to-end UI smoke)

Verified on `http://localhost:3001` after rebuilding the frontend image:
- Badge `🔄 Nowa praca 1 tyg` (warning variant) renders in the candidate
  list row (STATUS column) and detail-view header.
- Advanced filter popover shows `NIEDAWNO ZMIENIŁ PRACĘ (LINKEDIN)`
  section with radio buttons Wszyscy / 1 mies. / 2 mies. / 3 mies.
- Selecting `1 mies.` reduces the list to 1 matching candidate, sets URL
  `?rcj=1`, and lights up the filter counter badge.
- Candidate detail view renders the full `LinkedinSyncPanel` including:
  status pill, last sync timestamp, current LinkedIn company/title/start
  date, detected change date, and snapshot history ordered by fetched_at.

## Key configuration

Add to `.env` to activate Proxycurl sync:
```
PROXYCURL_API_KEY=<get from https://nubela.co/proxycurl>
PROXYCURL_ENABLED=true
PROXYCURL_SYNC_INTERVAL_SECONDS=3600
PROXYCURL_CANDIDATE_STALE_DAYS=7
PROXYCURL_BATCH_SIZE=50
PROXYCURL_COMPANY_FUZZ_THRESHOLD=90
```

Until the API key is set, `linkedin_sync_loop` exits with a
`disabled: PROXYCURL_API_KEY empty` log line and the manual
`POST /api/candidates/{id}/sync-linkedin` endpoint returns 503.

## Cost estimate

Worst case active pool (50 candidates/tick × 24 ticks/day × 30 days) =
36 000 lookups/month × $0.01 cached = **~$360/month**. Adjustable via
`PROXYCURL_BATCH_SIZE` and `PROXYCURL_CANDIDATE_STALE_DAYS`.

## Rollout notes

1. Deploy backend — the migration 0049 runs automatically via `entrypoint.sh`.
2. Set `PROXYCURL_API_KEY` in production env.
3. Frontend deploys the new UI — no migration step.
4. Task loop starts on next app boot; first tick after 45s grace.

## Known limitations / follow-ups (v1.1 — deferred)

- **Bulk admin resync endpoint**: `POST /api/admin/candidates/resync-linkedin`
  — not built; scheduled loop will pick up all stale candidates on its own.
- **Mismatch alert** (LinkedIn company ≠ `experience[0]` from CV) — foundation
  is in place (`linkedin_current_company` + `experience` both present); UI
  warning badge not implemented yet.
- **Promotion badge** (`new_title_same_company`): recorded in snapshots
  but not surfaced as a separate visual cue — currently only visible in
  change history if Proxycurl detected it.
- **rapidfuzz token_set_ratio threshold 90** may miss some edge cases
  (e.g. "Allegro" vs "Allegro Pay" same parent). Revisit after observing
  real-world false-positive rate.

## Operational verification steps

```sql
-- Tables exist
\dt candidate_linkedin_snapshots
\d+ candidates   -- grep linkedin_

-- Enum types
SELECT enumlabel FROM pg_enum
WHERE enumtypid IN (
  SELECT oid FROM pg_type
  WHERE typname IN ('linkedinsyncstatus', 'linkedinchangekind')
);

-- Candidates eligible for next sync tick
SELECT id, linkedin, linkedin_synced_at
FROM candidates
WHERE status='active'
  AND linkedin IS NOT NULL
  AND (linkedin_synced_at IS NULL OR linkedin_synced_at < now()-'7 days'::interval)
LIMIT 10;
```

```bash
# API surface
curl -sS -H "Authorization: Bearer <token>" \
  "http://localhost:8000/api/candidates?recently_changed_jobs=1"
curl -sS -H "Authorization: Bearer <token>" \
  "http://localhost:8000/api/candidates/42"
curl -sS -o /dev/null -w "HTTP %{http_code}\n" \
  -X POST -H "Authorization: Bearer <token>" \
  "http://localhost:8000/api/candidates/42/sync-linkedin"
# expect 202 (with API key) or 503 (without)
```
