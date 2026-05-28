# QA Process Runbook — NEXUS

> Standard pracy QA tester (lub Claude jako QA) na NEXUS ATS prod.
> Wypracowane w sesji 2026-05-27 (30 znalezionych bugów, 6 naprawionych,
> 3 false positives, 4 PR-y na prod). Cementuje pattern dla kolejnych
> sesji żeby unikać znanych pułapek metodologii.

## Filozofia: Sentry-first > UI clicking

**Reguła**: gdy ktoś prosi "znajdź bugi", **najpierw Sentry**, dopiero potem UI.

Powód: Sentry pokazuje co **WALI W PROD TERAZ** (real user impact, real
frequency, real stacktraces). UI clicking znajduje teoretyczne edge case'y
bez dowodu że ktokolwiek na nie wpada.

Sesja 2026-05-27: Sentry triage znalazł 4 ongoing bugi w 30 minut. UI clicking
przez 4h znalazł 14 dodatkowych (większość mock data / placeholder / drobny
UX). ROI Sentry-first = ~10x.

## Phase A — Observability triage (~30 min)

**Cel**: zidentyfikować real błędy w prod ZANIM zaczniemy ręczne testy.

### Tooling

- `mcp__sentry__search_issues` — `is:unresolved lastSeen:-7d`, sort `freq`
- `mcp__sentry__get_sentry_resource` — full stacktrace + lokalne zmienne + release tag
- `mcp__postgres-nexus__query` — sanity check tables (alembic_version, notifications growth, orphans)
- `mcp__grafana__query_loki_logs` — ostatnie ERROR/CRITICAL z app="nexus"
- `curl /api/health` — wszystkie checks healthy?

### Pattern

1. **Sentry projekty NEXUS**: `nexus-be` (FastAPI 0.115) + `nexus-fe` (Next.js 15)
2. Top 10 issues po `sort=freq` — drill-down każdy z `get_sentry_resource`
3. Patrz na `release` tag — czy bug jest w aktualnej wersji czy stary
4. Patrz na `lastSeen` — ongoing czy transient (cluster wokół incident date)
5. Patrz na `users` count — high user impact = priority

### Gotcha: 4 vs 5 dni temu = transient

Bugi z `lastSeen:-5d` często to **cascade** z większego incidentu (np.
2026-05-22 notifications runaway → DiskFull → QueuePool exhausted → BE-1B/1C/1D/1F + 13/12/15/16/14). Naprawienie **root cause** automatycznie eliminuje cluster.

## Phase B — UI smoke testing przez Chrome MCP (~90 min)

**Cel**: znaleźć functional bugi które Sentry nie łapie (UX, hardcoded mock,
broken navigation, niespójne data między widokami).

### Tooling

- `mcp__Claude_in_Chrome__*` — Artur ma zalogowaną sesję (SSO MS, 2FA push)
- `browser_batch` zamiast pojedynczych klików (10x szybciej)
- `read_network_requests` po każdej navigacji — wykrywa 4xx/5xx/pending
- `javascript_tool` z `localStorage.getItem('access_token')` dla auth fetch w console

### Gotcha #1: NIE testuj z `credentials: 'include'`

Backend (FastAPI HTTPBearer) wymaga `Authorization: Bearer ${token}` w header,
NIE cookie. Test bez tokena zwraca 401/403 dla każdego endpoint → fałszywy
"RBAC broken" bug. Zawsze:

```js
const tok = localStorage.getItem('access_token');
const r = await fetch(url, { headers: { Authorization: `Bearer ${tok}` } });
```

### Gotcha #2: Sesja MS SSO wygasa ~30 min

Po długiej sesji JWT expires. Sympomy: wszystkie endpointy zaczynają 403,
sidebar pokazuje broken state. Recovery: `localStorage.clear()` + `navigate('/login')` + Artur zatwierdza 2FA.

### Gotcha #3: "no available server" = infrastructure, NIE kod

`/sourcing/marketplace?tab=seeking` lub `/cv-generator` białe strony z "no available server" to **Traefik 502/503** gdy Next.js standalone container freezuje (mem_limit 512M). NIE jest to bug w `page.tsx` (oba `"use client"`, nie SSR). Skip do osobnej infra session.

### Coverage matrix

| Sekcja | Routes | Recommended depth |
|---|---|---|
| Sourcing | Dashboard, Kandydaci+filtry, Generator CV, Talenty, Targ | Filtry stage/company/talent_pool ZAWSZE; CV download flow ZAWSZE |
| Pipeline | Oferty list+detail+8 tabów, Kalendarz | Tab AI Matching SKIP (sessio expiry trap); Profil Championa silently fails |
| Delivery | Klienci (158)+7 tabów, Moi/relacje, Kontrakty, Kontraktorzy | Sample 1 klient (Nordea) wszystkie taby |
| Candidate profile | 10+ tabów per kandydat | Sample Adrian Pelc tabs Profil/Notatki/Pliki; reszta empty dla nowych |
| Insights | 3 taby (Rekrutacja/Klienci/Zarząd) | URL `?tab=` pattern działa; date filtry mogą crashować (BUG #V tu znaleziony) |
| Settings | 7 tabów role-gated | Sub-routing `/settings/profile` 404, `?tab=profile` działa |
| DR | 11 modułów | Slug NIE jest spójny — `/dynareporter/liga` 404, `/dynareporter/admin` redirects do `/admin-dashboard` |
| RBAC | 5 ról × matrix | Seed accounts (olaf@b2bnet.pl) NIE istnieją na prod (SSO only) — test ograniczony |

## Phase C — Security & data integrity quick scan (~30 min)

### Pattern

```bash
# Raw SQL f-string risk (SQLi)
grep -rnE 'execute\(\s*(text\()?f["\'"][^"]*\{' backend/app/ --include="*.py" | grep -v test

# Hardcoded secrets
grep -rnE '(api_key|secret|password|token)\s*=\s*"[A-Za-z0-9]{15,}"' backend/app/ --include="*.py"

# Debug statements
grep -rn "print(" backend/app/ --include="*.py" | grep -vE "test|window.print|scripts|cli"
```

### IDOR test ZAWSZE z Bearer token (per Gotcha #1)

```js
const tok = localStorage.getItem('access_token');
const hdr = { Authorization: `Bearer ${tok}` };
const tests = [['GET','/api/users'],['PATCH','/api/users/1'],['DELETE','/api/jobs/1']];
for (const [m, p] of tests) {
  const r = await fetch(`https://api.nexus.dynaminds.pl${p}`, {method: m, headers: hdr});
  console.log(`${m} ${p} → ${r.status}`);
}
```

Expect:
- Admin user: 200/204 dla wszystkich
- Recruiter: 403 dla `/api/admin/users`, `/api/contracts` (DeliveryLeadPlus required)
- Viewer (`user` role): 403 dla większości write/admin endpoints

## Phase D — Fixes + deploy + verify (~45 min per PR)

### Per-PR workflow (autonomous mode per `[[feedback_autonomy]]`)

1. Branch `fix/qa-<area>-<short-desc>` z `main`
2. Minimal diff per bug (Karpathy surgical changes)
3. `ruff check` + `ruff format --check` (apply if needed)
4. `gh pr create` z bug description + Test plan + ID Sentry
5. `gh pr merge --squash --admin` (CI auto-checked)
6. Background poll `until /api/health.version startswith new SHA`
7. Chrome MCP verify konkretny broken flow
8. Sentry watch 10 min — `lastSeen:-10m` empty oznacza fix działa

### Priority

- 🔴 P0: security (auth bypass, IDOR, secret leak) → fix natychmiast, branch z main
- 🟠 P1: data integrity (orphans growing, JWT broken, RBAC misconfig) → fix w sesji
- 🟡 P2: critical user flow broken (login, CV download, contract finalize) → fix w sesji
- 🟢 P3: UX papercut (typo, label, icon, hardcoded mock) → batch jako 1 PR

## Anti-patterns (uniknij)

### ❌ Anti-pattern #1: Pełne UI clicking jako pierwszy krok

Sesja 2026-05-27 → pierwsze 30 min Sentry znalazło 4 ongoing P1 bugi. UI clicking
przez 90 min znalazł 14 dodatkowych ALE większość mock data lub placeholders (low impact). ROI Sentry-first ~10x. Zawsze Sentry najpierw.

### ❌ Anti-pattern #2: Test API bez Bearer token

`credentials: 'include'` = tylko cookies, NIE Authorization header. Backend
zwraca 403 dla każdego endpoint → fałszywy "RBAC broken admin" bug.

### ❌ Anti-pattern #3: Direct URL test = bug

Mój test `/manager-panel` → 404, ale sidebar link wskazuje `/dashboard/delivery-lead`
poprawnie. Direct URL guess ≠ sidebar nav.

### ❌ Anti-pattern #4: Pominięcie reklasyfikacji false positives

3 z 30 "bugów" w sesji 2026-05-27 to były **errors metodologii**, nie real bugi.
Po każdej sesji: reality-check top bugów z świeżymi danymi (np. test z Bearer
token gdy pierwotnie bez).

### ❌ Anti-pattern #5: Fix bez verify post-deploy

Sentry events mają ~5 min delay. Po merge + deploy: poczekaj 10 min,
sprawdź `lastSeen:-10m` dla issue. Empty = fix działa.

### ❌ Anti-pattern #6: Sesja >4h bez przerwy

JWT expires ~30 min, Postgres MCP może padać ECONNRESET, Coolify container może być cold-started. Sesja >4h = degraded quality. Po 4h: zamknij, spawn follow-up chips.

## End-of-session checklist

- [ ] Wszystkie PR-y zmergowane + zweryfikowane post-deploy
- [ ] `docs/qa-session-YYYY-MM-DD.md` z listą bugów (znalezione/naprawione/false positive/sflagowane)
- [ ] Memory updated — `[[feedback_qa_*]]` jeśli nowy pattern
- [ ] Spawn task chips dla follow-up (nie wisz w kontekście kolejnej sesji)
- [ ] Regression tests Playwright dla naprawionych bugów (`frontend/e2e/qa-regression-<date>.spec.ts`)
- [ ] Sentry alert rules per `docs/sentry-alerts-runbook.md` (jednorazowy 15 min setup, nie per sesja)
- [ ] Final summary message: ile bugów, ile naprawione, gdzie raport, ile chips

## Reference: artefakty z poprzednich sesji

- `docs/qa-session-2026-05-27.md` — pełen log + 30 bugów + reality-check
- `docs/sentry-alerts-runbook.md` — 6 alert rules (15 min setup)
- `frontend/e2e/qa-regression-2026-05-27.spec.ts` — 5 regression specs

## E2E coverage status

> Source of truth: `frontend/e2e/` (Playwright). Auth setup w `auth.setup.ts`,
> helpers w `helpers/test-entities.ts` (EntityTracker + cleanup po każdym spec).
>
> Cel: 100% pokrycie 30 critical flows. Postęp incrementalny po ~5 stubs/sesja.

**Coverage: 9/30 flows (30%)**

Implemented specs (Playwright):
- `flow-create-candidate.spec.ts` — manual create + duplicate email guard
- `flow-stage-transition.spec.ts` — assign → screening → interview → reject
- `flow-write-note-mention.spec.ts` — Tiptap mention round-trip
- `flow-contract-draft.spec.ts` — P0 draft → render → finalize + Autenti 503 (sesja 2026-05-28)
- `flow-job-create.spec.ts` — P1 auto-assign TAC+DL + bulk proposals (sesja 2026-05-28)
- `flow-calendar-event.spec.ts` — P1 interview event (sesja 2026-05-28)

Pending (21 stubs w `flow-stubs-todo.spec.ts`):
- Candidate ops (5): CSV import, CV PDF parse, bulk CV download, searchbar, marketplace TTL
- Job ops (3): edit job, close job, AI job posting
- Communication (2): M365 email, file upload PDF
- Talent (2): talent pool add, marketplace match
- Client mgmt (4): create client, contact, MSA, SOW
- Integrations (2): M365 OAuth, Teams notifications
- DL Hub (2): pending verification, DL assignment
- Interview (1): post-interview feedback
- `~/.claude/projects/-Users-arturtwardowski-NEXUS--ATS-/memory/feedback_qa_sentry_first_pattern.md` — pattern memory
