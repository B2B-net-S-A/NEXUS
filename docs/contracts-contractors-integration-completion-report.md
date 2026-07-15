# Contracts ↔ Contractors integration — completion report

> Merges the `/contractors` roster into the `/contracts` workspace as a second
> mode, plus three decoupled correctness fixes surfaced during the analysis.
> Branch `claude/contracts-contractors-integration-420fe1`, 2026-07-15.

## Context

`/contracts` and `/contractors` were two sidebar entries over **one** data model
— a "contractor" is not a separate entity, it's a `Candidate` with a `Contract`
in status `draft|active|ending` (see `backend/app/api/contractors.py`). They were
separate lenses (finance/register vs delivery/operations) with different RBAC,
not separate datasets. This work folds them into one module while keeping both
lenses, and fixes real defects found along the way.

## What changed

### 1. Pagination on the contractor roster (live bug)
`ContractorsListV2` fetched only the backend's default first page (50) and had no
controls, so the "Aktywni" tab showed 50 of ~415. The backend was already fully
paginated (`page`/`page_size`, `total`) — the FE just never used it. Wired the FE
to it (page state + prev/next, mirroring `ContractsListV2`), reset page on tab
change.

### 2. One "ending soon" definition (count consistency)
The register used a **date window** (`expiring_in_days`), the contractor
list/stats used the **stored `status=ending`** — they diverged (cron lag under-
counts freshly-crossed contracts; expired-not-yet-demoted over-counts). Added a
single source of truth in `contract_service.py`:
`is_ending_soon` / `ending_soon_clause` / `live_not_ending_clause` — a LIVE
contract whose `end_date` is within the next 30 days. The contractor list + stats
now use it, so tab counts match the register. Locked by pure unit tests in
`tests/test_contracts_expiring.py`.

### 3. Currency in the contractor payload
`ContractorListItem` lacked `currency`, so the roster hardcoded PLN. Added it
(financial payload only — currency without rates is meaningless) in the schema +
`_to_item`; the FE now formats rates/margin in the contract's currency.

### 4. IA merge — one `/contracts`, two modes
- Sidebar: removed the standalone "Kontraktorzy" item.
- `/contracts` is now a workspace with a mode toggle:
  **Obsługa kontraktorów** (the roster) and **Rejestr kontraktów** (the register).
- Operations mode is role-gated on the FE to the same roles the old "Kontraktorzy"
  nav item used (`admin, delivery_lead, tac, head_of_recruitment`), so viewers see
  only the register. **Security is not the toggle** — the backend
  `_require_contractor_access` independently 403s viewers (restored here; see the
  security note). Locked by a unit test in `tests/test_contracts_expiring.py`.
- `/contractors` is kept as a **redirect** to `/contracts?view=operations`,
  preserving the `?tab=` deep-link so old links/bookmarks keep working.
- Contract detail stays at `/contracts/{id}` (completing a draft is a
  contract-level action). No "Contractor 360" person-grouping (one person can
  have multiple/parallel contracts).

### 5. Workspace state in the URL
`view` and `client` persist via the History API (deep-link + back/forward);
`ContractorsListV2` writes the active `tab` too. Read after mount (no
`useSearchParams`) to avoid the Next 15 streaming-SSR Suspense boundary.

## Files

**Backend**
- `app/services/contract_service.py` — shared ending-soon helpers.
- `app/api/contractors.py` — list/stats use the date-window buckets.
- `app/schemas/contract.py` — `currency` on `ContractorListItem`.
- `tests/test_contracts_expiring.py` — unit tests for the shared predicate.

**Frontend**
- `src/app/contracts/page.tsx` — two-mode workspace shell + URL state.
- `src/app/contractors/page.tsx` — redirect to `/contracts?view=operations`.
- `src/components/v2/pages/ContractorsListV2.tsx` — pagination, currency, tab-in-URL.
- `src/components/v2/shell/SidebarV2.tsx` — removed the "Kontraktorzy" item.
- `src/lib/api.ts` — `currency` on the `ContractorListItem` type.

## Verification

- FE: `tsc --noEmit` clean (0 errors); ESLint clean on touched files (one
  pre-existing `BarChart3` unused-import warning in the sidebar, unrelated).
- BE: `py_compile` + `ruff` clean on all changed files. DB-touching pytest runs
  in CI (`Backend (ruff + pytest)`); the new pure unit tests run there too.
- Post-merge: Chrome UI smoke on the prod frontend (toggle switches modes;
  `/contractors` redirects; "Aktywni" paginates past 50).

## Security note — needs a decision (found during rebase)

Rebasing onto current `main` surfaced that `backend/app/api/contractors.py` has
diverged from the branch base: the `_require_contractor_access` gate was removed
and `UserRole.user` was added to `_FULL_VISIBILITY_ROLES`. The code comment frames
it as intentional ("user (read-only viewer) → sees everyone, but UI should gate
the widget", "QC / client").

**Consequence:** on `main`, any authenticated account — including a read-only
viewer — could `GET /api/contractors` and receive the full roster: candidate names
+ emails (PII) and rates + margins. This contradicted the P0 hardening this work
was scoped around (don't rely on UI hiding).

**Resolution (per decision):** the backend gate is restored — `UserRole.user` is
removed from `_FULL_VISIBILITY_ROLES` and `_require_contractor_access` refuses any
account without an operational role (`admin, head_of_recruitment, delivery_lead,
tac, recruiter, sourcer`), returning 403. `recruiter`/`sourcer` keep their view
scoped to their own candidates; the read-only viewer gets no access. Locked by
`test_contract*_access_*` in `tests/test_contracts_expiring.py`.

## Known limitations / deferred

- Per-list intra-state beyond the tab (register search text, page number) is not
  URL-persisted — deferred to avoid destabilizing the two complex list
  components; the workspace-level state (`view`, `client`, operations `tab`) is.
- Operations and register still format spacing slightly differently (the roster
  brings its own `p-6`); cosmetic, left as-is.
