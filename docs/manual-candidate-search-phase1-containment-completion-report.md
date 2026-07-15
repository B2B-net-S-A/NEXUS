# Manual candidate search — Phase 1 containment (completion report)

> Date: 2026-07-15 · PR: [#727](https://github.com/artur-t-96/Nexus/pull/727)
> · Branch: `claude/codex-candidate-search-audit-4cea59`
> Parent plan: [manual-candidate-search-audit-and-implementation-plan-2026-07-15.md](./manual-candidate-search-audit-and-implementation-plan-2026-07-15.md)

## Scope

PR #1 of the program — **Phase 1 correctness containment** only. No data
migration, no engine rebuild. Every finding was verified against live code
before fixing.

## Findings addressed

| ID | Fix |
|---|---|
| SEARCH-P0-01 | Hourly job rate no longer compared against monthly `salary_expectation`. New additive `rate_hourly_min/max` on `CandidateSearchRequest`, wired to the existing `Candidate.expected_rate_hourly`; **missing rate = included** (user decision). Job prefill sends `rate_hourly_*`, not monthly `salary_*`. Global-list monthly filter untouched. |
| SEARCH-P0-02 | `Job.location` parsed into real cities (work-mode tokens dropped) instead of passed whole. Job-editor `remote_policy` options changed from `on_site`/`flexible` (422 on backend enum) to canonical `onsite`/`hybrid`/`remote`. |
| SEARCH-P1-01 | Reference number (e.g. `(ZOB-2846)`) stripped from free-text query. `nice_skills` no longer sent as a hard `skills_any` "≥1" gate. |
| SEARCH-P2-01 | Stale-response race fixed (cancel flag hoisted to effect scope). Selection cleared on filter/sort/saved-search change; kept across pagination. |

## Files

- `backend/app/schemas/candidate_search.py` — `rate_hourly_min/max` fields.
- `backend/app/services/structured_candidate_search.py` — hourly clause (NULL-inclusive).
- `backend/tests/test_structured_candidate_search.py` — 4 hourly-rate cases.
- `frontend/src/lib/job-search-prefill.ts` — new pure prefill helper.
- `frontend/src/lib/__tests__/job-search-prefill.test.ts` — 19 cases.
- `frontend/src/lib/candidate-search-api.ts` — `rate_hourly_*` on the request type.
- `frontend/src/app/jobs/[id]/page.tsx` — uses the helper.
- `frontend/src/components/v2/pages/CandidateSearchView.tsx` — race + selection.
- `frontend/src/components/AppShell.tsx` — canonical remote-policy options.

## Verification

- Frontend: `vitest` 19/19 green; `type-check` clean; `eslint` 0 errors (pre-existing warnings only).
- Backend: hourly clause SQL shape verified standalone; full `pytest` runs in CI (local Python is 3.9, app needs 3.12).
- Pending: CI green on PR #727, then exact-SHA `/api/health` smoke + Chrome smoke on a real hourly-rate + `"City / Remote"` job.

## Explicitly deferred

- **SEARCH-P0-03** (skills substring → exact-token): own PR with the Cortex resolver + golden eval — a naive exact-token change risks recall regression on `C++`/`.NET`/`React.js`.
- Phases 2–5: DSL (`CandidateSearchQueryV3`), eligibility service, saved-search unification, canonical facts + Qdrant lifecycle, shortlist/compare. Each is its own PR per the plan's sequence.
