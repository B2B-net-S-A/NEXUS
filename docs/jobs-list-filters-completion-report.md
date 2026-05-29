# Jobs list filters — completion report

**Date:** 2026-05-29
**Branch → main:** `cec83a9` (feature `85742c2` + ruff-format fixup)
**Scope:** Add 6 missing filters to the recruitments list (`/jobs`).

## What was asked

`https://nexus.dynaminds.pl/jobs` was missing filters for: **Potrzebny search**,
**Aktywni w searchu**, **Competence Category**, **Klient**, **Osoba
odpowiedzialna**, **Deadline**. Goal: make recruitments filterable by each.

## Filter → backend mapping

| UI control | Param on `GET /api/jobs` | Semantics |
|---|---|---|
| Potrzebny search (toggle) | `needs_sourcing=true` | `Job.needs_sourcing IS TRUE` (DL onboarding flag) |
| Aktywni w searchu (toggle) | `active_in_search=true` | job has ≥1 `job_collaborators` row with `removed_from_auto_cc=false` |
| Competence Category (multi dropdown) | `competence_category_id=<id…>` | primary `Job.competence_category_id IN (…)` |
| Klient (multi dropdown) | `client_id=<id…>` | `Job.client_id IN (…)` — param widened to a list (single-value back-compat) |
| Osoba odpowiedzialna (multi dropdown) | `responsible_id=<id…>` | matches `recruiter_id` **OR** `tac_id` (delivery lead is **not** counted as responsible) |
| Deadline (preset select) | `deadline_from` / `deadline_to` / `has_deadline` | po terminie / 7 dni / 30 dni / z / bez terminu |

### Product decision

"Osoba odpowiedzialna" **replaces** the previous narrow "Rekruter" picker (which
only matched `recruiter_id`). Per product clarification (2026-05-29), the
responsible person is the **recruiter or the TAC** — a delivery lead is *not*
counted. So `responsible_id` matches `recruiter_id OR tac_id`. The legacy
`owner_id` param is retained on the backend for compatibility but is no longer
used by the jobs page.

## Files changed

- `backend/app/api/jobs.py` — 7 new query params + `client_id` widened to list; WHERE clauses.
- `frontend/src/components/v2/pages/JobsListV2.tsx` — states, query params, filter-bar controls, `FilterToggle` + `deadlineParams` helpers.
- `frontend/src/components/v2/filters/CompetenceCategoryMultiSelect.tsx` — new (wraps `MultiSelectFilter`, loads CCs from `/api/competence-categories`).
- `backend/tests/test_jobs_filters_multi.py` — 7 new tests (client multi + single back-compat, CC, responsible across 3 roles, needs_sourcing, active_in_search incl. soft-removed collaborator, deadline range/has_deadline).

## Verification

- **Local:** `ruff check` + `ruff format --check` clean; frontend `tsc` ✓, ESLint 0 errors ✓, `next build` ✓.
- **CI (run on `cec83a9`):** success — backend pytest (incl. the 7 new tests) green against Postgres.
- **Deploy:** Coolify auto-deploy; `/api/health` healthy on `cec83a9`.
- **Chrome smoke test on prod**, cross-checked against the production DB:

  | Filter | UI result | DB truth | match |
  |---|---|---|---|
  | baseline | 3876 | 3876 | ✓ |
  | `needs_sourcing=true` | 0 | 0 | ✓ |
  | `competence_category_id=2` | 0 | 0 (no jobs have any CC assigned — all legacy Traffit imports) | ✓ |
  | `active_in_search=true` | 1 (Security Analyst) | 1 | ✓ |
  | deadline "Najbliższe 7 dni" → `deadline_from=2026-05-29&deadline_to=2026-06-05` | 3 | 3 | ✓ |

  All new params return HTTP 200 (no 422). Deadline date math uses local-date
  components (no UTC off-by-one).

## Known limitations / notes

- `needs_sourcing` and Competence Category currently match **0** prod jobs — a
  data fact (DL sourcing flag unset; legacy jobs have NULL CC), not a filter bug.
  Both will populate as DLs flag jobs / CC auto-assignment runs on new jobs.
- `ClientMultiSelect` loads up to 100 clients (existing shared component limit).
- Deadline filter is preset-based (not an arbitrary custom range) — covers the
  common recruiter cases; backend params support arbitrary ranges if needed later.
