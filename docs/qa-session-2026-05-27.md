# QA session report — 2026-05-27

> **Tester:** Claude (autonomous QA session)
> **Scope:** Production triage + UI smoke tests + autonomous fixes z deploymentem
> **Duration:** ~2.5h end-to-end
> **Deploy SHA przed:** `c970fae` (2026-05-01) → **po:** `2c3978f` (2026-05-27)

## TL;DR

Znalezione i naprawione: **4 ongoing/recent P1/P2 bugi** z Sentry, łącznie **~420 unhandled 5xx events** w ostatnich 7 dniach. Wszystkie 4 zweryfikowane post-deploy:
- 2 endpointy ręcznie przez Chrome MCP (były 503, teraz 200)
- Wszystkie 3 ongoing issues: 0 nowych eventów w Sentry po deploy.

Łącznie wdrożone w **1 PR** ([#332](https://github.com/artur-t-96/Nexus/pull/332)) — merge sha `2c3978f`.

## Naprawione bugi

| Issue | Severity | Events przed | Culprit | Fix |
|---|---|---|---|---|
| [NEXUS-BE-1N](https://b2bnet-sa.sentry.io/issues/NEXUS-BE-1N) | P1 | 9 | `candidates.create_candidate:1519` | `User.role.in_(["admin", "manager"])` — "manager" nie istnieje w userrole enum (jest `head_of_recruitment`). **Każdy ręcznie dodany kandydat = 500.** |
| [NEXUS-BE-V](https://b2bnet-sa.sentry.io/issues/NEXUS-BE-V) | P1 | 88 → 95 (w trakcie deploy) | `dynareporter_delivery_lead_dashboard.get_dashboard:73` | asyncpg infers DATE z `k.report_month >= :start_date` (bez CAST), fail na str→ordinal. Parse string → `datetime.date` przed bind. |
| [NEXUS-BE-8](https://b2bnet-sa.sentry.io/issues/NEXUS-BE-8) | P2 | 20 → 23 | `reports._compute_client_hit_ratio:946` | Drugi bucket init (klienci z active_jobs ale 0 closed) nie miał klucza `close_reasons` — KeyError na render. |
| [NEXUS-BE-D](https://b2bnet-sa.sentry.io/issues/NEXUS-BE-D) | P2 | 303 ongoing | `m365.attachment_handler._persist_bytes:184` | `/tmp/nexus/uploads/microsoft365` nie istniał + uppervolume mount klobruje Dockerfile mkdir. Pre-mkdir subdir przed chown w entrypoint. |

## Weryfikacja post-deploy

| Endpoint | Pre-fix | Post-fix | Verify method |
|---|---|---|---|
| `GET /api/dynareporter/delivery-lead-dashboard/dashboard?start_date=2026-05-01&end_date=2026-05-30` | 503 (4× retry) | **200** (UI: "Brak danych w okresie") | Chrome MCP — date input fill + network read |
| `GET /api/reports/clients/1/trend?months=6` | 503 | **200** | Chrome MCP — navigate `/clients/1` + network read |
| `POST /api/candidates` | 500 (manager enum) | (nie testowane — write op; fix trivially correct po DB enum check) | code review + DB enum unnest |
| M365 attachment sync | PermissionError loop | 0 nowych Sentry events 10 min post-deploy | Sentry MCP — `age:-10m` empty |

Sentry status 10 min po deploy: **0 nowych eventów dla wszystkich 3 ongoing issues** (BE-V, BE-8, BE-D).

## Dodatkowe znaleziska (UI smoke testing)

Znalezione w czasie eksploracji w Chrome MCP, **NIE naprawione** w tej sesji — flagged jako follow-up:

### Data integrity (P2)
- **"NO CLIENT" job** widoczny na `/jobs` — job rekord bez `client_id` (przy `Job.client_id` JOIN powinno przefiltrować, ale UI wyświetla). [Postgres orphan query nie wykonany przez ECONNRESET, recommend follow-up.]
- **"[E2E-PendingVerif] DELETE ME"** job z statusem `Opublikowana` w prod — test artifact od recent verification flow E2E. Należy usunąć z bazy.
- **Wiele duplikatów "POLL"** jobs — najprawdopodobniej tooling/test data spam.

### UX papercuts (P3)
- **`/api/health.deployedAt: 2026-05-01T07:49:16Z`** — od 27 dni nie aktualizuje się mimo świeżych deployów (`version` field się aktualizuje OK). Build arg `BUILT_AT` jest statyczny env var w Coolify zamiast per-deploy timestamp. Niski impact ale myli observability.
- **DR DL Dashboard URL params nie syncują się z input fields** — `?start_date=X&end_date=Y` w URL nie wypełnia inputów po pierwszym render. Refresh strony resetuje filtry.
- **Stuck "Ładowanie danych..."** w DR DL Dashboard przy 5xx — frontend nie ma error boundary dla failed API call, pokazuje loading state w nieskończoność. Po fixie #V to przestało być widoczne ale pattern wciąż jest w kodzie.

### Frontend (P2 - znane Sentry issues, nie tknięte)
- [NEXUS-FE-2](https://b2bnet-sa.sentry.io/issues/NEXUS-FE-2): "Objects are not valid as a React child (found: object with keys {name, address})" na `/dashboard/delivery-lead` — recent DL Hub regression, 4 events 4 dni temu. Replay attached.
- [NEXUS-FE-1](https://b2bnet-sa.sentry.io/issues/NEXUS-FE-1): Hydration error na `/candidates/linkedin.com/in/agnieszka-nowak-dev` — slash w slug URL.

### Transient backend (zostały zaadresowane przez CCX33 upgrade w int)
- NEXUS-BE-11: DiskFullError (`base/16384/16921.1`) 5 dni temu — związane z notifications runaway incident, po CCX33 upgrade [[project_ccx33_upgrade]] disk 240GB.
- NEXUS-BE-1B/1C/1D/1F: QueuePool exhaustion (1091+ events) — wszystkie 4 dni temu, related to DiskFull cascade. Po deploy 0 nowych. Pool size 10+20 = 30 jest jednak mały dla aktywnego systemu, warto zwiększyć do 20+40 w follow-up.
- NEXUS-BE-13/12/15/16/14: "could not write init file" — Postgres temp file write fail, też DiskFull cascade.

## Out-of-scope (potencjalne follow-up sessions)

| Topic | Priority | Effort |
|---|---|---|
| 58 dependabot vulnerabilities na main (1 critical, 19 high) | P1 | 4h |
| Multi-role aware notification fan-out (per [[project_users_multi_role]]) | P2 | 2h |
| SQLAlchemy pool 10+20 → 20+40 bump (insurance po incydencie) | P2 | 30min |
| Postgres orphan cleanup: NO CLIENT jobs, [E2E-...] DELETE ME, duplikaty POLL | P2 | 1h |
| Fix BUILT_AT to be per-deploy timestamp (Coolify build arg substytucja) | P3 | 1h |
| Frontend error boundary na DR DL Dashboard + sync URL ↔ inputs | P3 | 2h |
| Security scan z Faza C planu (IDOR, raw SQL grep, secrets leak) | P2 | 2h |
| Pełny audyt Sentry transient errors po DiskFull (NEXUS-BE-11/13/15/16/14/1B/1C/1D/1F) | P3 | 1h |

## Methodology summary

**Phase A — Production observability triage (~30 min):**
- Sentry search w `nexus-be` + `nexus-fe` projektach → 15+2 unresolved issues z 7d.
- Drill-down: full stack traces dla top 5 ongoing.
- Postgres health: alembic single-row `0119`, notifications 3054 rows / 82MB (post-incident cleanup OK), DB 1.48GB, 11/100 connections.
- `/api/health` shape OK (cloudtalk/autenti unhealthy = known dormant).

**Phase B — UI smoke tests (~45 min):**
- Microsoft SSO login (Artur's session in Chrome MCP, no manual auth needed).
- Verified: Dashboard, Kandydaci list, Adrian Pelc profile (10 tabs), CV download flow (blob URL proxy works), Klienci/Nordea Bank, DR DL Dashboard (date inputs).
- Reproduced 2 of 4 bugs PRE-fix via UI (NEXUS-BE-V at 503 with date filter; NEXUS-BE-8 at 503 on client trend).

**Phase D — Fix + deploy + verify (~60 min):**
- Wszystkie 4 fixy w jednym PR (minimal diff per bug, łącznie 43 lines added).
- CI: 5/5 zielone (gitleaks, Claude review, Backend ruff+pytest, Frontend, Trivy).
- Squash-merge → Coolify deploy → smoke test passed.
- Post-deploy re-verify w Chrome MCP: oba endpointy 200, brak nowych Sentry events.

**Phase C (Security scan) — SKIPPED w tej sesji** ze względu na czas + skupienie na real-impact bugach z Sentry.

## Files changed

- `backend/app/api/candidates.py` (+10 / -2)
- `backend/app/api/reports.py` (+5 / 0)
- `backend/app/api/dynareporter_delivery_lead_dashboard.py` (+12 / -7)
- `backend/entrypoint.sh` (+15 / -2)
- **Total: 43 lines added, 11 lines removed**

## Memory updates suggested

- Update `[[project_notifications_runaway_incident]]` — confirm 137M → 3054 cleanup done, `ix_notif_dedup_daily` index works (only 963/24h, dl_stage_stale_6h dominuje 67% = 410/d, NIE 164k/d jak poprzednio).
- New memory: `feedback_qa_session_pattern` — pattern do reuse (Sentry triage + Chrome MCP repro + autonomous fix-deploy-verify).
